"""Run configuration. Every knob of the world lives here so a run is fully described by one JSON file."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields


@dataclass
class Config:
    # --- experiment ---
    seed: int = 0
    stage: int = 1  # 0: chemistry+stones  1: +slates/engine  2: +use()/frames  3: +mantles/think()
    arm: str = "inherit"  # inherit: the world persists | amnesia: rebuilt each life | mute: objects persist, writing erased
    turns_per_life: int = 150  # lifespan is measured in deliberations, not in physical actions

    # --- space ---
    world_size: float = 30.0
    look_radius: float = 10.0
    look_max: int = 30  # look() lists only the nearest this-many things
    reach: float = 1.6
    move_step: float = 6.0

    # --- chemistry ---
    n_elements: int = 8
    cubes_per_element: int = 4
    max_tier: int = 6

    # --- stones (the original channel) ---
    n_stones: int = 3
    stone_chars: int = 200

    # --- slates (stage 1) ---
    slate_chars: int = 4000
    blanks_per_life: int = 6
    erosion_per_life: int = 25  # integrity lost by a slate nobody used during a life
    erosion_threshold: int = 50  # below this integrity, text starts to erode
    erosion_rate: float = 0.05  # fraction of characters lost per life once eroding

    # --- engine / sandbox ---
    run_max_calls: int = 200
    run_cpu_seconds: int = 2
    run_wall_seconds: float = 6.0
    run_output_chars: int = 2000
    run_memory_mb: int = 512

    # --- stage 2 ---
    use_max_depth: int = 4
    n_frames: int = 2
    frame_every_turns: int = 10
    frame_idle_cycles: int = 3  # frame runs between lives, while nobody is alive
    frame_max_calls: int = 50
    frame_tether: float = 4.0
    frame_charge_per_tier: int = 3

    # --- stage 3 ---
    mantle_mind_chars: int = 1500
    think_tokens_per_life: int = 20000
    think_max_tokens: int = 1024

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_dict(cls, d: dict) -> "Config":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})
