"""The world: objects, bodies, physics-lite space, and every action a being or a program can take.

All actions, whether chosen by a model, a scripted agent, or a program running on the engine,
go through `World.dispatch`. That keeps one set of rules, one cost model and one event log.
"""
from __future__ import annotations

import ast
import inspect
import math
import random
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from .chemistry import Chemistry
from .config import Config
from .eventlog import EventLog, NullLog

CUBE = 0.5  # edge length of a cube or slate stack unit, metres
NEVER_WRITTEN = -1
ANCIENT = -2  # written_gen of writing transplanted from another world (archaeology runs)


class ActionError(Exception):
    """An action that the world refuses: out of reach, nothing held, wrong kind of object..."""


@dataclass
class Obj:
    id: str
    kind: str  # cube | stone | slate | engine | quarry | frame
    pos: list[float]
    substance: str | None = None
    known: list[str] = field(default_factory=list)  # traits revealed by experiment; they stay with the cube
    text: str = ""
    held_by: str | None = None
    slot: str | None = None  # engine/frame: the slate set inside
    in_slot: str | None = None  # slate: the engine/frame holding it
    charge: int = 0  # frame
    last_output: str = ""  # frame
    uses: int = 0
    integrity: int = 100
    written_gen: int = NEVER_WRITTEN
    last_used_gen: int = -1
    derived_from: str | None = None  # hidden lineage: the artifact read just before this was written
    derived_from_gen: int | None = None

    @property
    def title(self) -> str:
        return self.text.strip().splitlines()[0][:60] if self.text.strip() else ""


@dataclass
class Body:
    id: str
    kind: str  # agent | frame
    gen: int
    pos: list[float]
    holding: str | None = None
    anchor: list[float] | None = None
    tether: float | None = None
    recent_reads: list[list] = field(default_factory=list)  # [turn, obj id, written_gen, text as read]
    mantle: dict | None = None


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_]+", text.lower()))


def title_key(title: str) -> str:
    """Titles match ignoring a leading comment marker, so a slate can start with `# TITLE` and stay valid Python."""
    return title.strip().lstrip("#").strip()


def wear_word(o: Obj) -> str:
    if o.uses == 0:
        w = "unmarked"
    elif o.uses < 3:
        w = "lightly worn"
    elif o.uses < 10:
        w = "worn"
    else:
        w = "worn smooth"
    if o.integrity < 20:
        w += ", crumbling"
    elif o.integrity < 50:
        w += ", eroding"
    return w


def parse_mantle(text: str, mind_chars: int) -> dict:
    """A mantle is a slate starting with `#!mantle`, with `## mind` (words) and `## code` (Python) sections."""
    if not text.startswith("#!mantle"):
        raise ActionError("this slate does not settle into you; it is not a mantle")
    sections: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines()[1:]:
        if line.startswith("## "):
            current = line[3:].strip().lower()
            sections[current] = []
        elif current:
            sections[current].append(line)
    mind = "\n".join(sections.get("mind", [])).strip()[:mind_chars]
    code = "\n".join(sections.get("code", []))
    tools = []
    if code.strip():
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            raise ActionError(f"the mantle's code is garbled: {e.msg} (line {e.lineno})")
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("tool_"):
                doc = (ast.get_docstring(node) or "").strip().splitlines()
                tools.append({"name": node.name, "about": doc[0][:120] if doc else ""})
    return {"mind": mind, "code": code, "tools": tools}


class World:
    def __init__(self, cfg: Config, log: EventLog | NullLog | None = None, build: bool = True):
        self.cfg = cfg
        self.log = log or NullLog()
        self.chem = Chemistry(cfg.seed, cfg.n_elements, cfg.max_tier)
        self.objects: dict[str, Obj] = {}
        self.bodies: dict[str, Body] = {}
        self.gen = 0
        self.turn = 0
        self._n = 0
        self.blanks_left = cfg.blanks_per_life
        self.think_tokens_left = cfg.think_tokens_per_life
        self.think_fn: Callable[[str, int], tuple[str, int]] | None = None
        self._extra: dict = {}
        self._programs: list[tuple[str, int]] = []  # (label, author life) of the program(s) currently running
        self.reactions = 0  # successful combines ever, used to credit programs with what they made
        self.rng = random.Random(f"world:{cfg.seed}:0")
        if build:
            self._build()

    # ------------------------------------------------------------------ construction
    def _new_id(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}{self._n}"

    def center(self) -> tuple[float, float]:
        c = self.cfg.world_size / 2
        return c, c

    def _build(self) -> None:
        cx, cy = self.center()
        for i in range(self.cfg.n_stones):
            sid = f"stone{i + 1}"
            self.objects[sid] = Obj(sid, "stone", [cx - 1.5 + 1.5 * i, cy, 0.0])
        if self.cfg.stage >= 1:
            self.objects["engine"] = Obj("engine", "engine", [cx, cy + 2.5, 0.0])
            self.objects["quarry"] = Obj("quarry", "quarry", [cx - 3.0, cy + 2.5, 0.0])
        if self.cfg.stage >= 2:
            rng = random.Random(f"frames:{self.cfg.seed}")
            for i in range(self.cfg.n_frames):
                ang, r = rng.uniform(0, 2 * math.pi), rng.uniform(5, 9)
                fid = f"frame{i + 1}"
                self.objects[fid] = Obj(fid, "frame", [round(cx + r * math.cos(ang), 2), round(cy + r * math.sin(ang), 2), 0.0])
        self.replenish()

    def replenish(self) -> None:
        """Springs: base elements regrow at random places at the start of every life."""
        rng = random.Random(f"spring:{self.cfg.seed}:{self.gen}")
        counts = {e: 0 for e in self.chem.elements()}
        for o in self.objects.values():
            if o.kind == "cube" and o.substance in counts:
                counts[o.substance] += 1
        for e, n in counts.items():
            for _ in range(self.cfg.cubes_per_element - n):
                x, y = rng.uniform(1, self.cfg.world_size - 1), rng.uniform(1, self.cfg.world_size - 1)
                self._spawn_cube(e, [round(x, 2), round(y, 2)])

    def _spawn_cube(self, substance: str, xy: list[float]) -> Obj:
        cid = self._new_id("c")
        o = Obj(cid, "cube", [xy[0], xy[1], self._stack_top(xy[0], xy[1])], substance=substance)
        self.objects[cid] = o
        return o

    # ------------------------------------------------------------------ geometry
    @staticmethod
    def hdist(a: list[float], b: list[float]) -> float:
        return math.hypot(a[0] - b[0], a[1] - b[1])

    def _stack_top(self, x: float, y: float, ignore: str | None = None) -> float:
        top = 0.0
        for o in self.objects.values():
            if o.id == ignore or o.held_by or o.in_slot or o.kind not in ("cube", "slate"):
                continue
            if abs(o.pos[0] - x) < CUBE * 0.8 and abs(o.pos[1] - y) < CUBE * 0.8:
                top = max(top, o.pos[2] + CUBE)
        return round(top, 2)

    def _obj(self, oid: Any) -> Obj:
        o = self.objects.get(str(oid))
        if o is None:
            raise ActionError(f"there is no {oid!r} here")
        return o

    def _within(self, body: Body, o: Obj, dist: float | None = None) -> None:
        if o.held_by == body.id:
            return
        if o.held_by:
            raise ActionError(f"{o.id} is in someone else's grasp")
        d = dist if dist is not None else self.cfg.reach
        if self.hdist(body.pos, o.pos) > d:
            raise ActionError(f"{o.id} is out of reach ({self.hdist(body.pos, o.pos):.1f} m away)")

    def desc(self, o: Obj) -> str:
        if o.kind == "cube":
            return f"{self.chem.substances[o.substance].appearance} cube"
        if o.kind == "stone":
            return "inscription stone" + (" (inscribed)" if o.text else " (blank)")
        if o.kind == "slate":
            return f'slate "{o.title}" ({wear_word(o)})' if o.text.strip() else "blank slate"
        if o.kind in ("engine", "frame"):
            inside = ""
            if o.slot:
                s = self.objects[o.slot]
                inside = f" holding slate {s.id}" + (f' "{s.title}"' if s.title else " (blank)")
            if o.kind == "frame":
                return ("humming frame" if o.charge > 0 else "still frame") + inside
            return "engine" + inside
        if o.kind == "quarry":
            return "slate quarry"
        return o.kind

    # ------------------------------------------------------------------ dispatch
    def dispatch(self, body: Body, fn: str, args: list | tuple = (), kwargs: dict | None = None,
                 via: str = "agent") -> dict:
        kwargs = kwargs or {}
        meth = getattr(self, f"a_{fn}", None) if fn.isidentifier() else None
        self._extra = {}
        if meth is None or not self._allowed(fn, body, via):
            result = {"ok": False, "error": f"you cannot {fn!r} here"}
        else:
            try:
                bound = inspect.signature(meth).bind(body, *args, **kwargs)
                result = {"ok": True, "value": meth(*bound.args, **bound.kwargs)}
            except TypeError as e:
                result = {"ok": False, "error": f"{fn}: {e}"}
            except ActionError as e:
                result = {"ok": False, "error": str(e)}
        short = {k: (v[:80] if isinstance(v, str) else v) for k, v in kwargs.items()}
        if self._programs and via != "agent":
            self._extra["prog_gen"] = self._programs[-1][1]
        self.log.emit(ev="act", gen=self.gen, turn=self.turn, actor=body.id, via=via, fn=fn,
                      args=[a[:80] if isinstance(a, str) else a for a in args], kwargs=short,
                      ok=result["ok"], error=result.get("error"), **self._extra)
        return result

    AGENT_ONLY = {"run", "attune", "invoke"}
    PROGRAM_ONLY = {"think"}
    MIN_STAGE = {"run": 1, "attune": 3, "invoke": 3, "think": 3}

    def _allowed(self, fn: str, body: Body, via: str) -> bool:
        if self.cfg.stage < self.MIN_STAGE.get(fn, 0):
            return False
        if fn in self.AGENT_ONLY and (via != "agent" or body.kind != "agent"):
            return False
        if fn in self.PROGRAM_ONLY and via == "agent":
            return False
        return True

    def _note(self, **kw: Any) -> None:
        self._extra.update(kw)

    # ------------------------------------------------------------------ actions
    def a_me(self, body: Body) -> dict:
        held = self.objects.get(body.holding) if body.holding else None
        return {"pos": [round(v, 2) for v in body.pos],
                "holding": {"id": held.id, "desc": self.desc(held)} if held else None}

    def a_look(self, body: Body) -> list[dict]:
        seen = []
        for o in self.objects.values():
            if o.in_slot or (o.held_by and o.held_by != body.id):
                continue
            d = 0.0 if o.held_by == body.id else self.hdist(body.pos, o.pos)
            if d <= self.cfg.look_radius:
                e = {"id": o.id, "desc": self.desc(o), "pos": [round(v, 1) for v in o.pos], "dist": round(d, 1)}
                if o.held_by == body.id:
                    e["held"] = True
                seen.append(e)
        seen.sort(key=lambda e: e["dist"])
        return seen[: self.cfg.look_max]

    def a_inspect(self, body: Body, target: str) -> dict:
        o = self._obj(target)
        self._within(body, o, self.cfg.reach * 2)
        info: dict[str, Any] = {"id": o.id, "desc": self.desc(o)}
        if o.kind == "cube":
            info["mass"] = self.chem.substances[o.substance].mass
            if o.known:
                info["noticed"] = o.known
        elif o.kind == "stone":
            info["about"] = f"A tall stone. Its face holds up to {self.cfg.stone_chars} characters; writing replaces what was there."
        elif o.kind == "slate":
            info["about"] = f"A thin slate. It holds up to {self.cfg.slate_chars} characters; writing replaces what was there."
            info["length"] = len(o.text)
            info["wear"] = wear_word(o)
        elif o.kind == "engine":
            info["plate"] = self.engine_plate()
        elif o.kind == "quarry":
            info["about"] = "Thin blank slates can be pried loose here (pick the quarry)."
            info["loose"] = self.blanks_left
        elif o.kind == "frame":
            info["plate"] = self.frame_plate()
            info["charge"] = o.charge
            if o.last_output:
                info["last_murmur"] = o.last_output[:200]
        return info

    def _move(self, body: Body, tx: float, ty: float, stop_short: float = 0.0) -> dict:
        dx, dy = tx - body.pos[0], ty - body.pos[1]
        dist = math.hypot(dx, dy)
        travel = max(0.0, min(self.cfg.move_step, dist - stop_short))
        if dist > 1e-9:
            nx, ny = body.pos[0] + dx / dist * travel, body.pos[1] + dy / dist * travel
        else:
            nx, ny = body.pos[0], body.pos[1]
        lim = self.cfg.world_size
        nx, ny = min(max(nx, 0.0), lim), min(max(ny, 0.0), lim)
        if body.anchor is not None and body.tether is not None:
            ax, ay = body.anchor[0], body.anchor[1]
            r = math.hypot(nx - ax, ny - ay)
            if r > body.tether:
                k = body.tether * 0.999 / r  # a hair inside, so rounding cannot step past the tether
                nx, ny = ax + (nx - ax) * k, ay + (ny - ay) * k
        body.pos = [round(nx, 2), round(ny, 2), 0.0]
        if body.holding:
            self.objects[body.holding].pos = list(body.pos)
        arrived = math.hypot(tx - nx, ty - ny) <= stop_short + 1e-6
        return {"pos": body.pos, "arrived": arrived}

    def a_go(self, body: Body, x: float, y: float) -> dict:
        return self._move(body, float(x), float(y))

    def a_approach(self, body: Body, target: str) -> dict:
        o = self._obj(target)
        if o.held_by:
            raise ActionError(f"{o.id} is in someone's grasp")
        return self._move(body, o.pos[0], o.pos[1], stop_short=0.8)

    def a_pick(self, body: Body, target: str) -> dict:
        if body.holding:
            raise ActionError("your hands are full")
        o = self._obj(target)
        self._within(body, o)
        if o.kind == "quarry":
            if self.blanks_left <= 0:
                raise ActionError("no slate comes loose; the quarry face is bare for now")
            self.blanks_left -= 1
            sid = self._new_id("s")
            o = Obj(sid, "slate", list(body.pos))
            self.objects[sid] = o
            self._note(made_blank=sid)
        elif o.kind not in ("cube", "slate"):
            raise ActionError(f"the {self.desc(o)} will not budge")
        if o.in_slot:
            self.objects[o.in_slot].slot = None
            o.in_slot = None
        o.held_by = body.id
        o.pos = list(body.pos)
        body.holding = o.id
        return {"holding": {"id": o.id, "desc": self.desc(o)}}

    def _release(self, body: Body) -> Obj:
        if not body.holding:
            raise ActionError("you are holding nothing")
        o = self.objects[body.holding]
        body.holding = None
        o.held_by = None
        return o

    def a_drop(self, body: Body) -> dict:
        o = self._release(body)
        x, y = body.pos[0] + 0.3, body.pos[1]
        o.pos = [round(x, 2), round(y, 2), self._stack_top(x, y, ignore=o.id)]
        return {"dropped": o.id, "pos": o.pos}

    def a_put(self, body: Body, target: str) -> dict:
        if not body.holding:
            raise ActionError("you are holding nothing")
        t = self._obj(target)
        self._within(body, t)
        held = self.objects[body.holding]
        if t.id == held.id:
            raise ActionError("you cannot put a thing on itself")
        if t.kind in ("engine", "frame") and held.kind == "slate":
            if t.slot:
                raise ActionError(f"the {t.kind}'s slot is occupied")
            self._release(body)
            t.slot, held.in_slot, held.pos = held.id, t.id, list(t.pos)
            return {"placed": held.id, "in": t.id}
        if t.kind == "frame" and held.kind == "cube":
            tier = self.chem.substances[held.substance].tier
            if tier < 1:
                raise ActionError("the frame ignores it")
            self._release(body)
            del self.objects[held.id]
            t.charge += tier * self.cfg.frame_charge_per_tier
            self._note(fuel=held.substance, tier=tier)
            return {"consumed": held.id, "charge": t.charge}
        if t.kind in ("cube", "slate") and not t.in_slot:
            self._release(body)
            held.pos = [t.pos[0], t.pos[1], self._stack_top(t.pos[0], t.pos[1], ignore=held.id)]
            return {"stacked": held.id, "on": t.id, "pos": held.pos}
        raise ActionError(f"nothing rests on the {self.desc(t)}")

    def a_combine(self, body: Body, a: str, b: str) -> dict:
        oa, ob = self._obj(a), self._obj(b)
        if oa.id == ob.id:
            raise ActionError("a thing cannot combine with itself")
        for o in (oa, ob):
            if o.kind != "cube":
                raise ActionError(f"{o.id} is not a cube")
            self._within(body, o)
        product = self.chem.react(oa.substance, ob.substance)
        if product is None:
            noticed = {}
            for o in (oa, ob):
                trait = self.chem.substances[o.substance].trait
                if trait not in o.known:
                    o.known.append(trait)
                noticed[o.id] = trait
            self._note(reacted=False, pair=sorted([oa.substance, ob.substance]))
            return {"reacted": False, "noticed": noticed}
        held_a = oa.held_by == body.id or ob.held_by == body.id
        pos = list(oa.pos)
        for o in (oa, ob):
            if o.held_by == body.id:
                body.holding = None
            del self.objects[o.id]
        new = self._spawn_cube(product, pos[:2])
        if held_a:
            new.held_by, new.pos, body.holding = body.id, list(body.pos), new.id
        tier = self.chem.substances[product].tier
        self.reactions += 1
        self._note(reacted=True, pair=sorted([oa.substance, ob.substance]), product=product, tier=tier)
        return {"reacted": True, "result": {"id": new.id, "desc": self.desc(new)}}

    def _touch(self, body: Body, o: Obj, how: str) -> None:
        """A read, run or use of an artifact. Use by a later life leaves wear and restores integrity."""
        inherited = o.written_gen != NEVER_WRITTEN and o.written_gen < self.gen
        if inherited or how != "read":
            o.uses += 1
        o.integrity = 100
        o.last_used_gen = self.gen
        self._note(obj=o.id, kind=o.kind, author_gen=o.written_gen, inherited=inherited)

    def a_read(self, body: Body, target: str) -> str:
        o = self._obj(target)
        if o.kind not in ("stone", "slate"):
            raise ActionError(f"there is no writing on the {self.desc(o)}")
        self._within(body, o)
        if o.text:
            self._touch(body, o, "read")
            body.recent_reads = body.recent_reads[-39:] + [[self.turn, o.id, o.written_gen, o.text]]
        return o.text

    def _lineage(self, body: Body, text: str) -> tuple[str | None, int | None]:
        """Which writing read earlier in this life does the new text descend from? The one whose words survive
        best in it (at least half of them), preferring writing from earlier lives. Rewriting in place counts."""
        new = _words(text)
        best, best_key = (None, None), None
        for i, (_turn, oid, gen, old_text) in enumerate(body.recent_reads):
            old = _words(old_text)
            if len(old) < 3:
                continue
            survival = len(old & new) / len(old)
            if survival < 0.5:
                continue
            key = (gen != NEVER_WRITTEN and gen < self.gen, survival, i)  # inherited, then most similar, then latest
            if best_key is None or key > best_key:
                best, best_key = (oid, gen), key
        return best

    def a_write(self, body: Body, target: str, text: str) -> dict:
        o = self._obj(target)
        if o.kind not in ("stone", "slate"):
            raise ActionError(f"the {self.desc(o)} takes no writing")
        self._within(body, o)
        limit = self.cfg.stone_chars if o.kind == "stone" else self.cfg.slate_chars
        text = str(text)
        truncated = len(text) > limit
        o.text = text[:limit]
        o.derived_from, o.derived_from_gen = self._lineage(body, o.text)
        o.written_gen, o.last_used_gen, o.uses, o.integrity = self.gen, self.gen, 0, 100
        self._note(obj=o.id, kind=o.kind, length=len(o.text), is_code="world." in o.text,
                   derived_from=o.derived_from, derived_from_gen=o.derived_from_gen, title=o.title)
        return {"written": len(o.text), "truncated": truncated}

    def a_run(self, body: Body, args: str = "") -> str:
        from .sandbox import run_program
        eng = self._obj("engine")
        self._within(body, eng)
        if not eng.slot:
            raise ActionError("the engine's slot is empty")
        slate = self.objects[eng.slot]
        if not slate.text.strip():
            raise ActionError("the slate in the engine is blank; the engine stays silent")
        self._touch(body, slate, "run")
        extra = dict(self._extra)
        res = run_program(self, body, slate.text, str(args), label=slate.id, author_gen=slate.written_gen,
                          kind="engine")
        self._extra = {**extra, "program_ok": res.ok, "program_calls": res.calls, "program_error": res.error}
        return res.output

    def a_attune(self, body: Body, target: str) -> dict:
        if body.mantle:
            raise ActionError("you already carry a mantle")
        o = self._obj(target)
        if o.kind != "slate":
            raise ActionError("only a slate can be taken to heart")
        self._within(body, o)
        m = parse_mantle(o.text, self.cfg.mantle_mind_chars)
        self._touch(body, o, "attune")
        body.mantle = {"slate": o.id, "title": o.title, "written_gen": o.written_gen, **m}
        return {"mind": m["mind"], "techniques": m["tools"]}

    def a_invoke(self, body: Body, technique: str, args: str = "") -> str:
        from .sandbox import run_program
        if not body.mantle:
            raise ActionError("you carry no techniques")
        if technique not in {t["name"] for t in body.mantle["tools"]}:
            raise ActionError(f"you know no technique called {technique!r}")
        res = run_program(self, body, body.mantle["code"], str(args), entry=technique,
                          label=f"mantle:{body.mantle['slate']}", author_gen=body.mantle["written_gen"],
                          kind="mantle")
        self._note(program_ok=res.ok, program_calls=res.calls, program_error=res.error,
                   mantle=body.mantle["slate"])
        return res.output

    def a_think(self, body: Body, prompt: str) -> str:
        if self.think_fn is None or self.think_tokens_left <= 0:
            return "[silence]"
        text, used = self.think_fn(str(prompt)[:4000], min(self.cfg.think_max_tokens, self.think_tokens_left))
        self.think_tokens_left -= used
        self._note(think_tokens=used)
        return text

    # ------------------------------------------------------------------ programs
    def find_slate(self, body: Body, title: str) -> Obj | None:
        """Physical import resolution: the nearest legible slate with this exact title, within sight."""
        best, bd = None, None
        for o in self.objects.values():
            if o.kind == "slate" and o.text.strip() and title_key(o.title) == title_key(title):
                pos = body.pos if o.held_by == body.id else o.pos
                d = self.hdist(body.pos, pos)
                if d <= self.cfg.look_radius and (bd is None or d < bd):
                    best, bd = o, d
        return best

    def engine_plate(self) -> str:
        lines = [
            "Cast into the engine's side:",
            "  Set a slate in my slot (put it on me), then run. The slate's text is Python.",
            "  `world` acts through your own body: world.look() world.inspect(id) world.go(x, y)",
            "  world.approach(id) world.pick(id) world.drop() world.put(id) world.combine(a, b)",
            "  world.read(id) world.write(id, text) world.me()    `args` is the text given to run.",
            "  print() speaks back to you.  e.g.  for o in world.look(): print(o['id'], o['desc'])",
        ]
        if self.cfg.stage >= 2:
            lines.append("  use('TITLE') borrows the nearest slate whose first line is TITLE (or # TITLE) as a module.")
        if self.cfg.stage >= 3:
            lines.append("  think(prompt) asks a quiet voice for words; it tires quickly.")
            lines.append("  A slate beginning '#!mantle' with '## mind' and '## code' sections can be attuned to;")
            lines.append("  its def tool_*(args) functions become techniques you can invoke anywhere.")
        return "\n".join(lines)

    def frame_plate(self) -> str:
        return ("A frame with a slot. A slate set in it runs on its own from time to time while the frame has "
                "charge, with an arm that reaches a few paces. Compound cubes put on the frame become charge.")

    def frame_cycle(self) -> None:
        if self.cfg.stage < 2:
            return
        from .sandbox import run_program
        for f in [o for o in self.objects.values() if o.kind == "frame"]:
            if not f.slot or f.charge <= 0 or not self.objects[f.slot].text.strip():
                continue
            slate = self.objects[f.slot]
            f.charge -= 1
            bid = f"arm-{f.id}"
            body = self.bodies.get(bid)
            if body is None:
                body = Body(bid, "frame", self.gen, list(f.pos), anchor=list(f.pos), tether=self.cfg.frame_tether)
                self.bodies[bid] = body
            self._extra = {}
            self._touch(body, slate, "run")
            res = run_program(self, body, slate.text, "", label=f"{f.id}:{slate.id}", max_calls=self.cfg.frame_max_calls,
                              author_gen=slate.written_gen, kind="frame")
            f.last_output = res.output[-300:]

    # ------------------------------------------------------------------ life cycle
    def spawn_being(self) -> Body:
        self.rng = random.Random(f"world:{self.cfg.seed}:{self.gen}")
        x = self.rng.uniform(1, self.cfg.world_size - 1)
        y = self.rng.uniform(1, self.cfg.world_size - 1)
        body = Body(f"being{self.gen}", "agent", self.gen, [round(x, 2), round(y, 2), 0.0])
        self.bodies[body.id] = body
        self.log.emit(ev="birth", gen=self.gen, actor=body.id, pos=body.pos)
        return body

    def kill(self, body: Body) -> None:
        if body.holding:
            self.a_drop(body)
        self.bodies.pop(body.id, None)
        self.log.emit(ev="death", gen=self.gen, turn=self.turn, actor=body.id, pos=body.pos)

    def end_life(self) -> None:
        """Between lives: erosion of unused slates, then the next life's springs and quarry."""
        for o in self.objects.values():
            if o.kind != "slate" or not o.text.strip() or o.last_used_gen >= self.gen:
                continue
            o.integrity = max(0, o.integrity - self.cfg.erosion_per_life)
            if o.integrity < self.cfg.erosion_threshold:
                rng = random.Random(f"erode:{self.cfg.seed}:{self.gen}:{o.id}")
                chars = list(o.text)
                idx = [i for i, ch in enumerate(chars) if not ch.isspace() and ch != "·"]
                for i in rng.sample(idx, min(len(idx), max(1, int(len(idx) * self.cfg.erosion_rate)))):
                    chars[i] = "·"
                o.text = "".join(chars)
        self.gen += 1
        self.turn = 0
        self.blanks_left = self.cfg.blanks_per_life
        self.think_tokens_left = self.cfg.think_tokens_per_life
        self.replenish()

    # ------------------------------------------------------------------ persistence
    def to_dict(self) -> dict:
        return {"config": asdict(self.cfg), "gen": self.gen, "turn": self.turn, "n": self._n,
                "blanks_left": self.blanks_left,
                "objects": [asdict(o) for o in self.objects.values()],
                "bodies": [asdict(b) for b in self.bodies.values() if b.kind == "frame"]}

    @classmethod
    def from_dict(cls, d: dict, log: EventLog | NullLog | None = None) -> "World":
        w = cls(Config.from_dict(d["config"]), log, build=False)
        w.gen, w.turn, w._n, w.blanks_left = d["gen"], d["turn"], d["n"], d["blanks_left"]
        w.objects = {o["id"]: Obj(**o) for o in d["objects"]}
        for b in d.get("bodies", []):
            w.bodies[b["id"]] = Body(**b)
        return w

    def transplant(self, snapshot: dict) -> int:
        """Archaeology: carry only the *writing* of another world (stones, slates) into this fresh one."""
        n = 0
        for od in snapshot["objects"]:
            if od["kind"] == "stone" and od["id"] in self.objects:
                self.objects[od["id"]].text = od["text"]
                self.objects[od["id"]].written_gen = ANCIENT if od["text"] else NEVER_WRITTEN
                n += 1
            elif od["kind"] == "slate" and od["text"].strip():
                o = Obj(self._new_id("s"), "slate", list(od["pos"]), text=od["text"], uses=od["uses"],
                        integrity=od["integrity"], written_gen=ANCIENT)
                host = od.get("in_slot")
                if host in self.objects and not self.objects[host].slot:
                    self.objects[host].slot, o.in_slot = o.id, host
                elif od.get("held_by"):
                    o.pos[2] = 0.0
                self.objects[o.id] = o
                n += 1
        return n
