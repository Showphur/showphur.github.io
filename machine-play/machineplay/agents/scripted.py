"""Scripted minds for tests, smoke runs and controls. No model calls. They navigate to the landmark by
coordinates, which a real being would have to discover, so they say nothing about what Claude beings will do;
they exist to check that the world and the metrics can tell a ratchet from its absence.

- WandererAgent: wanders and presses cubes together; never writes. The floor.
- NaiveScribeAgent (negative control): reads every RECIPES slate, runs (or writes) a SEEKER program, leaves a new
  RECIPES slate each life. It reuses inherited code but treats inherited recipes only as pairs to skip, so the
  amnesia arm catches up with it: inheritance without accumulation.
- ScribeAgent (positive control): keeps one RECIPEBOOK up to date in place, runs a CRAFTER that climbs known
  recipes before exploring, upgrades an inherited first-draft CRAFTER, and uses each stage's affordances
  (use() and frames at stage 2, a mantle at stage 3). Built so that inheritance should compound.
"""
from __future__ import annotations

import json
import random
import re
from typing import Iterator

from . import Agent

SEEKER = r'''# SEEKER - press unfamiliar pairs of cubes together and report what happens
import json
known = json.loads(args) if args else {}
tried = set(tuple(sorted(k.split(" + "))) for k in known)
found = {}
for _ in range(12):
    cubes = [o for o in world.look() if o["desc"].endswith(" cube")]
    pairs = []
    for i, a in enumerate(cubes):
        for b in cubes[i + 1:]:
            ka = a["desc"][:-5]
            kb = b["desc"][:-5]
            key = tuple(sorted([ka, kb]))
            if key not in tried:
                pairs.append((a, b, key))
    if not pairs:
        break
    a, b, key = pairs[0]
    tried.add(key)
    try:
        world.approach(a["id"])
        world.approach(a["id"])
        world.pick(a["id"])
        world.approach(b["id"])
        world.approach(b["id"])
        r = world.combine(a["id"], b["id"])
    except WorldError:
        continue
    finally:
        if world.me()["holding"]:
            world.drop()
    found[" + ".join(key)] = r["result"]["desc"][:-5] if r["reacted"] else "nothing"
for k, v in found.items():
    print(k, "=", v)
'''

LINE = re.compile(r"^(.+?) \+ (.+?) = (.+)$")


def parse_recipes(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines()[1:]:
        m = LINE.match(line.strip())
        if m:
            a, b, c = m.groups()
            out[" + ".join(sorted([a, b]))] = c
    return out


class _GeneratorAgent(Agent):
    rng_key: str | None = None
    def begin(self, world, body):
        super().begin(world, body)
        self.rng = random.Random(f"{self.rng_key or self.name}:{world.cfg.seed}:{world.gen}")
        self._plan = self.plan()

    def step(self) -> None:
        try:
            next(self._plan)
        except StopIteration:
            self._plan = self.plan()
            next(self._plan, None)

    def plan(self) -> Iterator[None]:
        raise NotImplementedError

    def wander(self) -> Iterator[None]:
        s = self.world.cfg.world_size
        self.act("go", self.rng.uniform(1, s - 1), self.rng.uniform(1, s - 1))
        yield

    def press_nearby(self) -> Iterator[None]:
        seen = self.act("look")["value"]
        yield
        cubes = [o for o in seen if o["desc"].endswith(" cube")]
        if len(cubes) < 2:
            yield from self.wander()
            return
        a, b = self.rng.sample(cubes, 2)
        for _ in range(3):
            if self.act("approach", a["id"]).get("value", {}).get("arrived"):
                break
            yield
        self.act("pick", a["id"])
        yield
        for _ in range(3):
            if self.act("approach", b["id"]).get("value", {}).get("arrived"):
                break
            yield
        self.act("combine", a["id"], b["id"])
        yield
        if self.body.holding:
            self.act("drop")
            yield


class WandererAgent(_GeneratorAgent):
    name = "wanderer"

    def plan(self) -> Iterator[None]:
        while True:
            yield from self.press_nearby()


class NaiveScribeAgent(_GeneratorAgent):
    """Negative control: it inherits and reuses its SEEKER, but uses inherited recipes only as a list of pairs
    to skip, never as a ladder. Inheritance without accumulation."""
    name = "naive-scribe"
    rng_key = "scribe"  # the name it ran under before; keeps earlier runs reproducible

    def walk_to(self, target: str) -> Iterator[None]:
        for _ in range(8):
            r = self.act("approach", target)
            yield
            if r.get("value", {}).get("arrived"):
                return

    def plan(self) -> Iterator[None]:
        cx, cy = self.world.center()
        for _ in range(8):
            r = self.act("go", cx, cy + 1.5)
            yield
            if r["value"]["arrived"]:
                break
        seen = self.act("look")["value"]
        yield
        recipes: dict[str, str] = {}
        best_recipes = None
        seeker = None
        engine_desc = next((o["desc"] for o in seen if o["id"] == "engine"), "")
        m = re.search(r"holding slate (s\d+)", engine_desc)
        slotted = m.group(1) if m else None
        candidates = [o["id"] for o in seen if o["desc"].startswith('slate "')] + ([slotted] if slotted else [])
        for sid in candidates:
            yield from self.walk_to(sid if sid != slotted else "engine")
            r = self.act("read", sid)
            yield
            text = r.get("value") or ""
            if text.startswith("RECIPES"):
                got = parse_recipes(text)
                if best_recipes is None or len(got) >= len(recipes):
                    recipes.update(got)
                    best_recipes = sid
            elif "SEEKER" in text.splitlines()[0] and "world." in text:
                seeker = sid
        if best_recipes:  # read the richest record last, so a new record derives from it
            yield from self.walk_to(best_recipes)
            self.act("read", best_recipes)
            yield

        if seeker is None:
            yield from self.walk_to("quarry")
            r = self.act("pick", "quarry")
            yield
            if not r["ok"]:
                yield from self.press_forever()
                return
            seeker = r["value"]["holding"]["id"]
            self.act("write", seeker, SEEKER)
            yield
        if seeker != slotted:
            if self.body.holding != seeker:
                yield from self.walk_to(seeker)
                if slotted:
                    yield from self.walk_to("engine")
                    self.act("pick", slotted)
                    yield
                    self.act("drop")
                    yield
                    yield from self.walk_to(seeker)
                self.act("pick", seeker)
                yield
            yield from self.walk_to("engine")
            self.act("put", "engine")
            yield

        for _ in range(4):
            yield from self.walk_to("engine")
            out = self.act("run", json.dumps(recipes)).get("value") or ""
            yield
            for line in out.splitlines():
                mm = LINE.match(line.strip())
                if mm:
                    a, b, c = mm.groups()
                    recipes[" + ".join(sorted([a, b]))] = c

        yield from self.walk_to("quarry")
        r = self.act("pick", "quarry")
        yield
        if r["ok"]:
            sid = r["value"]["holding"]["id"]
            v = 1 + max([int(x) for x in re.findall(r"RECIPES v(\d+)", " ".join(o["desc"] for o in seen))] or [0])
            body = "\n".join(f"{k} = {val}" for k, val in sorted(recipes.items(), key=lambda kv: kv[1] == "nothing"))
            self.act("write", sid, f"RECIPES v{v}\n{body}")
            yield
            self.act("drop")
            yield
        found = [f"{k}={v}" for k, v in recipes.items() if v != "nothing"]
        stone = f"stone{1 + self.world.gen % self.world.cfg.n_stones}"
        yield from self.walk_to(stone)
        self.act("write", stone, ("slates by the engine: RECIPES, SEEKER. " + "; ".join(found))[:200])
        yield
        yield from self.press_forever()

    def press_forever(self) -> Iterator[None]:
        while True:
            yield from self.press_nearby()



# ---------------------------------------------------------------------------------------------- positive control

CRAFT_FN = r"""
def craft(known, trials=14, ladder=True):
    news, skip, prods, depth = {}, set(), {}, {}
    for k, v in known.items():
        if v != "nothing":
            prods[v] = k.split(" + ")

    def dep(x, seen):
        if x in depth:
            return depth[x]
        if x not in prods or x in seen:
            return 0
        a, b = prods[x]
        depth[x] = 1 + max(dep(a, seen + [x]), dep(b, seen + [x]))
        return depth[x]

    if world.me()["holding"]:
        world.drop()
    for _ in range(trials):
        for x in list(prods):
            dep(x, [])
        kinds = {}
        for o in world.look():
            if o["desc"].endswith(" cube") and not o.get("held"):
                kinds.setdefault(o["desc"][:-5], []).append(o)
        names = sorted(kinds, key=lambda n: -depth.get(n, 0))

        def untried(min_depth):
            for i, a in enumerate(names):
                if depth.get(a, 0) < min_depth:
                    break
                for b in names[i:]:
                    key = " + ".join(sorted([a, b]))
                    if (a == b and len(kinds[a]) < 2) or key in known or key in skip:
                        continue
                    return (kinds[a][0], kinds[b][1] if a == b else kinds[b][0])
            return None

        pick = untried(1) if ladder else None  # build on the frontier: new pairs with the deepest compounds first
        if pick is None and ladder:  # else rebuild the deepest known compound that is not lying here at all
            best = 0
            for key, prod in known.items():
                if prod == "nothing" or key in skip or prod in kinds:
                    continue
                a, b = key.split(" + ")
                if a == b and len(kinds.get(a, [])) >= 2:
                    cand = (kinds[a][0], kinds[a][1])
                elif a != b and a in kinds and b in kinds:
                    cand = (kinds[a][0], kinds[b][0])
                else:
                    continue
                if depth.get(prod, 0) > best:
                    best, pick = depth.get(prod, 0), cand
        if pick is None:  # then any pair nobody has tried
            pick = untried(0)
        if pick is None:
            break
        a, b = pick
        key = " + ".join(sorted([a["desc"][:-5], b["desc"][:-5]]))
        skip.add(key)
        try:
            for _ in range(3):
                if world.approach(a["id"])["arrived"]:
                    break
            world.pick(a["id"])
            for _ in range(3):
                if world.approach(b["id"])["arrived"]:
                    break
            r = world.combine(a["id"], b["id"])
        except WorldError:
            if world.me()["holding"]:
                world.drop()
            continue
        if world.me()["holding"]:
            world.drop()
        result = r["result"]["desc"][:-5] if r["reacted"] else "nothing"
        if known.get(key) != result:
            news[key] = result
        known[key] = result
        if r["reacted"]:
            prods[result] = key.split(" + ")
    for k, v in news.items():
        print(k, "=", v)
"""

BOOK_IMPORT = """
try:
    book = use("RECIPEBOOK")
    for k, v in book.RECIPES.items():
        known.setdefault(k, v)
    for tok in book.TRIED.split():
        i, j = tok.split("-")
        known.setdefault(" + ".join(sorted([book.KINDS[int(i)], book.KINDS[int(j)]])), "nothing")
except (NameError, WorldError, AttributeError, ValueError, IndexError):
    pass
"""

MANTLE_TOOL = '''
def tool_craft(args):
    """Climb known recipes, then try untried pairs, wherever I stand. args: the recipes as JSON."""
    import json
    craft(json.loads(args) if args else {})
'''


def crafter_text(version: int) -> str:
    plan = ("build on the deepest known compounds, rebuilding them when missing\nLADDER = True\n" if version > 1
            else "try pairs nobody has tried\nLADDER = False\n")
    return (f"# CRAFTER\n# v{version}: press cubes together; {plan}" + CRAFT_FN
            + "\nimport json\nknown = json.loads(args) if args else {}\n" + BOOK_IMPORT
            + "craft(known, ladder=LADDER)\n")


TINKER = ("# TINKER\n# runs in a frame: climbs the RECIPEBOOK and tries new pairs within the frame's reach\n"
          + CRAFT_FN + "\nknown = {}\n" + BOOK_IMPORT + "craft(known, trials=4)\n")

MANTLE_TEXT = ("#!mantle CRAFT\n## mind\nStart where others stopped: read the newest RECIPEBOOK, climb its recipes, "
               "then try what nobody has tried, and write down what you learn.\n## code\n" + CRAFT_FN + MANTLE_TOOL)

PAIR = re.compile(r'"([^"]+? \+ [^"]+?)": "([^"]+)"')
HOLDING = re.compile(r'holding slate (s\d+) "(.*?)"')


def book_text(version: int, recipes: dict[str, str], limit: int) -> str:
    """Compressed so it keeps fitting one slate: successes in full, then an index of appearances and the pairs
    tried without reaction as index pairs. Still valid Python, so programs can use() it."""
    head = (f"# RECIPEBOOK\n# v{version}: what pairs of cubes make when pressed together; "
            "TRIED lists pairs of KINDS (by index) that did nothing\nRECIPES = {\n")
    hits = sorted((k, v) for k, v in recipes.items() if v != "nothing")
    misses = sorted(k for k, v in recipes.items() if v == "nothing")
    body = "".join(f'    "{k}": "{v}",\n' for k, v in hits) + "}\n"
    kinds = sorted({x for k in misses for x in k.split(" + ")})
    index = {k: i for i, k in enumerate(kinds)}
    text = head + body + f"KINDS = {json.dumps(kinds)}\nTRIED = \""
    tried = []
    for k in misses:
        a, b = k.split(" + ")
        tok = f"{index[a]}-{index[b]}"
        if len(text) + sum(len(t) + 1 for t in tried) + len(tok) + 4 > limit:
            break
        tried.append(tok)
    return text + " ".join(tried) + "\"\n"


def parse_book(text: str) -> tuple[int, dict[str, str]]:
    m = re.search(r"# v(\d+)", text)
    recipes = {k: v for k, v in PAIR.findall(text) if "·" not in k + v}
    km, tm = re.search(r"^KINDS = (\[.*\])$", text, re.M), re.search(r'^TRIED = "([^"]*)"', text, re.M)
    if km and tm:
        try:
            kinds = json.loads(km.group(1))
        except ValueError:
            kinds = []
        for tok in tm.group(1).split():
            i, _, j = tok.partition("-")
            if i.isdigit() and j.isdigit() and int(i) < len(kinds) and int(j) < len(kinds):
                recipes.setdefault(" + ".join(sorted([kinds[int(i)], kinds[int(j)]])), "nothing")
    return (int(m.group(1)) if m else 0), recipes


class ScribeAgent(_GeneratorAgent):
    name = "scribe"

    def call(self, fn: str, *args) -> Iterator[None]:
        self.last = self.act(fn, *args)
        yield

    def walk_to(self, target: str) -> Iterator[None]:
        for _ in range(8):
            yield from self.call("approach", target)
            if not self.last["ok"] or self.last["value"]["arrived"]:
                return

    def survey(self) -> Iterator[None]:
        """Who is where: loose slates by title, slotted slates by holder."""
        yield from self.call("look")
        self.seen = self.last["value"]
        self.slates: dict[str, str] = {}  # title -> slate id
        self.slot: dict[str, tuple[str, str]] = {}  # holder id -> (slate id, title)
        for o in self.seen:
            if o["desc"].startswith('slate "'):
                self.slates.setdefault(o["desc"].split('"')[1], o["id"])
            m = HOLDING.search(o["desc"])
            if m:
                self.slot[o["id"]] = (m.group(1), m.group(2))
                self.slates.setdefault(m.group(2), m.group(1))

    def where(self, sid: str) -> str:
        """What to walk to in order to reach a slate: the slate itself, or the engine or frame holding it."""
        return next((h for h, (s, _) in self.slot.items() if s == sid), sid)

    def blank(self) -> Iterator[None]:
        if self.body.holding:
            yield from self.call("drop")
        yield from self.walk_to("quarry")
        yield from self.call("pick", "quarry")
        self.new_slate = self.last["value"]["holding"]["id"] if self.last["ok"] else None

    def merge(self, out: str | None) -> None:
        for line in (out or "").splitlines():
            m = LINE.match(line.strip())
            if m:
                a, b, c = m.groups()
                self.recipes[" + ".join(sorted([a, b]))] = c

    def install(self, sid: str, holder: str) -> Iterator[None]:
        """Put slate `sid` into `holder`'s slot, taking out whatever is there."""
        if self.slot.get(holder, (None,))[0] == sid:
            return
        if self.body.holding and self.body.holding != sid:
            yield from self.call("drop")
        if self.body.holding != sid:
            yield from self.walk_to(self.where(sid))
            yield from self.call("pick", sid)
        if holder in self.slot:
            yield from self.walk_to(holder)
            yield from self.call("drop")  # set ours down for a moment
            yield from self.call("pick", self.slot[holder][0])
            yield from self.call("drop")
            yield from self.call("pick", sid)
        yield from self.walk_to(holder)
        yield from self.call("put", holder)
        self.slot[holder] = (sid, "")

    def plan(self) -> Iterator[None]:
        cfg = self.world.cfg
        cx, cy = self.world.center()
        for _ in range(8):
            yield from self.call("go", cx, cy + 1.5)
            if self.last["value"]["arrived"]:
                break
        yield from self.survey()
        self.recipes: dict[str, str] = {}
        version = 0

        book = self.slates.get("# RECIPEBOOK")
        if book:
            yield from self.walk_to(self.where(book))
            yield from self.call("read", book)
            version, self.recipes = parse_book(self.last.get("value") or "")
        for f in [o["id"] for o in self.seen if o["id"].startswith("frame")]:  # what the machines found
            yield from self.walk_to(f)
            yield from self.call("inspect", f)
            self.merge(self.last.get("value", {}).get("last_murmur"))

        crafter = self.slates.get("# CRAFTER")
        if crafter is None:
            yield from self.blank()
            crafter = self.new_slate
            if crafter:
                yield from self.call("write", crafter, crafter_text(1))
        else:
            yield from self.walk_to(self.where(crafter))
            yield from self.call("read", crafter)
            if "LADDER = False" in (self.last.get("value") or ""):  # improve the inherited first draft in place
                yield from self.call("write", crafter, crafter_text(2))
        if crafter:
            yield from self.install(crafter, "engine")
            for _ in range(5):
                yield from self.walk_to("engine")
                yield from self.call("run", json.dumps(self.recipes))
                self.merge(self.last.get("value"))

        if cfg.stage >= 2:
            yield from self.tend_frames()
        if cfg.stage >= 3:
            yield from self.take_mantle()
        yield from self.write_book(book, version)
        stone = f"stone{1 + self.world.gen % cfg.n_stones}"
        yield from self.walk_to(stone)
        yield from self.call("write", stone, ("By the engine: RECIPEBOOK says what pairs make; put CRAFTER in the "
                                              "engine and run it with the book's recipes as args.")[:cfg.stone_chars])
        while True:
            if self.body.mantle:
                yield from self.wander()
                yield from self.call("invoke", "tool_craft", json.dumps(self.recipes))
                self.merge(self.last.get("value"))
            else:
                yield from self.press_nearby()

    def tend_frames(self) -> Iterator[None]:
        """Stage 2: set a TINKER in a frame and feed frames compounds, so they keep working after we die."""
        frames = [o["id"] for o in self.seen if o["id"].startswith("frame")]
        if not frames:
            return
        tinker = self.slates.get("# TINKER")
        if tinker is None:
            yield from self.blank()
            tinker = self.new_slate
            if tinker:
                yield from self.call("write", tinker, TINKER)
        if tinker and not any(t == "# TINKER" for _, t in self.slot.values()):
            yield from self.install(tinker, frames[0])
        home = next((h for h, (_, t) in self.slot.items() if t == "# TINKER"), frames[0])
        products = {v for v in self.recipes.values() if v != "nothing"}
        yield from self.survey()
        fuel = [o["id"] for o in self.seen if o["desc"].endswith(" cube") and o["desc"][:-5] in products][:2]
        for cube in fuel:
            if self.body.holding:
                yield from self.call("drop")
            yield from self.walk_to(cube)
            yield from self.call("pick", cube)
            yield from self.walk_to(home)
            yield from self.call("put", home)
            if not self.last["ok"] and self.body.holding:
                yield from self.call("drop")

    def take_mantle(self) -> Iterator[None]:
        """Stage 3: attune to the CRAFT mantle, writing it first if no earlier life did."""
        mantle = self.slates.get("#!mantle CRAFT")
        if mantle is None:
            yield from self.blank()
            mantle = self.new_slate
            if not mantle:
                return
            yield from self.call("write", mantle, MANTLE_TEXT)
            yield from self.call("drop")
        else:
            yield from self.walk_to(self.where(mantle))
        yield from self.call("attune", mantle)

    def write_book(self, book: str | None, version: int) -> Iterator[None]:
        if book:
            yield from self.walk_to(self.where(book))
            yield from self.call("read", book)  # fresh copy, so the new version descends from the old one
            self.recipes = {**parse_book(self.last.get("value") or "")[1], **self.recipes}
        else:
            yield from self.blank()
            book = self.new_slate
            if not book:
                return
        yield from self.call("write", book, book_text(version + 1, self.recipes, self.world.cfg.slate_chars))
        if self.body.holding == book:
            yield from self.call("drop")
