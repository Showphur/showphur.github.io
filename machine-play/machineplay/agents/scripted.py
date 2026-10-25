"""Scripted minds for tests, smoke runs and cheap baselines. No model calls.

- WandererAgent: wanders and presses cubes together; never writes. A floor for comparison.
- ScribeAgent: a caricature of a culture-maker. It reads any RECIPES slate it finds, runs (or writes) a SEEKER
  program on the engine, and leaves a new RECIPES slate. It exists to exercise every channel (stones, slates,
  engine, lineage links) end to end, so the measurement pipeline can be checked without spending tokens.
  It navigates to the landmark by coordinates, which a real being would have to discover.
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
    def begin(self, world, body):
        super().begin(world, body)
        self.rng = random.Random(f"{self.name}:{world.cfg.seed}:{world.gen}")
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


class ScribeAgent(_GeneratorAgent):
    name = "scribe"

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
