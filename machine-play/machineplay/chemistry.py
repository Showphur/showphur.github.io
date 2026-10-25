"""Hidden chemistry: a seeded reaction DAG over substances.

Base elements (tier 0) spring up in the world. Pairs of substances may react into a product one
tier above the higher of the two. Agents only ever see appearances, masses and traits revealed by
experiment; the table itself is never shown to them. Deep products are reachable only through
chains of earlier products, which is what makes accumulated knowledge worth having.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

COLORS = ["red", "blue", "green", "yellow", "white", "black", "orange", "violet", "grey", "teal",
          "amber", "pink", "copper", "silver", "ochre", "indigo"]
TEXTURES = ["rough", "smooth", "chalky", "glassy", "porous", "waxy", "grainy", "polished"]
QUALITIES = ["glowing", "humming", "warm", "cold", "translucent", "crystalline", "pulsing", "fragrant",
             "magnetic", "faceted", "iridescent", "feather-light", "dense", "sparking", "singing", "shifting"]
TRAITS = ["warm to the touch", "faintly magnetic", "rings when tapped", "smells of rain", "sinks in sand",
          "casts a faint shadow", "tingles", "is oddly heavy", "is oddly light", "flickers at the edges",
          "hums softly", "is slightly sticky"]


@dataclass
class Substance:
    sid: str
    appearance: str
    tier: int
    mass: float
    trait: str
    parents: tuple[str, str] | None = None


@dataclass
class Chemistry:
    seed: int
    n_elements: int = 8
    max_tier: int = 6
    substances: dict[str, Substance] = field(default_factory=dict)
    reactions: dict[tuple[str, str], str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        rng = random.Random(f"chem:{self.seed}")
        used: set[str] = set()

        def appearance(tier: int) -> str:
            for _ in range(1000):
                if tier == 0:
                    a = f"{rng.choice(TEXTURES)} {rng.choice(COLORS)}"
                else:
                    a = f"{rng.choice(QUALITIES)} {rng.choice(COLORS)}"
                    if tier >= 3:
                        a = f"{rng.choice(QUALITIES)} {a}"
                if a not in used:
                    used.add(a)
                    return a
            raise RuntimeError("ran out of appearances")

        for i in range(self.n_elements):
            sid = f"e{i}"
            self.substances[sid] = Substance(sid, appearance(0), 0, round(rng.uniform(0.5, 2.0), 2), rng.choice(TRAITS))

        by_tier: dict[int, list[str]] = {0: list(self.substances)}
        n = 0
        for tier in range(1, self.max_tier + 1):
            count = max(1, round(self.n_elements * 0.8 ** (tier - 1)))
            prev = by_tier[tier - 1]
            lower = [s for t in range(tier) for s in by_tier[t]]
            by_tier[tier] = []
            for _ in range(count):
                for _attempt in range(200):
                    a, b = rng.choice(prev), rng.choice(lower)
                    key = self.key(a, b)
                    if key not in self.reactions:
                        break
                else:
                    continue
                sid = f"p{n}"
                n += 1
                pa, pb = self.substances[a], self.substances[b]
                self.substances[sid] = Substance(sid, appearance(tier), tier,
                                                 round(pa.mass * 0.5 + pb.mass * 0.5 + rng.uniform(0, 0.5), 2),
                                                 rng.choice(TRAITS), (a, b))
                self.reactions[key] = sid
                by_tier[tier].append(sid)

    @staticmethod
    def key(a: str, b: str) -> tuple[str, str]:
        return (a, b) if a <= b else (b, a)

    def react(self, a: str, b: str) -> str | None:
        return self.reactions.get(self.key(a, b))

    def elements(self) -> list[str]:
        return [s for s, v in self.substances.items() if v.tier == 0]
