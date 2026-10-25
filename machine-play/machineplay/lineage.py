"""The generation loop: birth, a life of N deliberations, death, erosion, next birth.

Lives never overlap. The only things that cross a death are the world's objects and writing.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .agents import Agent
from .config import Config
from .eventlog import EventLog
from .world import World

AgentFactory = Callable[[int], Agent]


def fresh_world(cfg: Config, log, gen: int, transplant: dict | None = None) -> World:
    w = World(cfg, log, build=False)
    w.gen = gen
    w._build()
    if transplant:
        w.transplant(transplant)
    return w


def latest_snapshot(out: Path) -> Path | None:
    snaps = sorted((out / "snapshots").glob("after_life_*.json"))
    return snaps[-1] if snaps else None


def live_one_life(world: World, agent: Agent) -> None:
    cfg = world.cfg
    world.turn = 0
    body = world.spawn_being()
    agent.begin(world, body)
    for t in range(cfg.turns_per_life):
        world.turn = t
        agent.step()
        if cfg.stage >= 2 and (t + 1) % cfg.frame_every_turns == 0:
            world.frame_cycle()
    world.turn = cfg.turns_per_life
    agent.end()
    world.kill(body)
    for _ in range(cfg.frame_idle_cycles if cfg.stage >= 2 else 0):
        world.frame_cycle()
    world.log.emit(ev="life_end", gen=world.gen)


def run_lineage(cfg: Config, out_dir: str | Path, make_agent: AgentFactory, lives: int, resume: bool = False,
                transplant: dict | None = None, think_fn=None,
                on_life: Callable[[int, World], None] | None = None) -> World:
    """Run until `lives` lives have been lived in total. `transplant` makes every life start in a fresh world
    carrying that snapshot's writing (archaeology); the amnesia arm makes every life start in a fresh world."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "snapshots").mkdir(exist_ok=True)
    events_path = out / "events.jsonl"
    snap = latest_snapshot(out) if resume else None
    if snap:
        state = json.loads(snap.read_text())
        _truncate_events(events_path, state["gen"])  # drop the half-lived life that was interrupted
    elif events_path.exists() and events_path.stat().st_size:
        raise FileExistsError(f"{out} already holds a run; pass resume=True or choose another directory")
    log = EventLog(events_path)
    if snap:
        world = World.from_dict(state, log)
        cfg = world.cfg
    else:
        (out / "config.json").write_text(cfg.to_json())
        world = fresh_world(cfg, log, 0, transplant)
    try:
        while world.gen < lives:
            world.think_fn = think_fn
            live_one_life(world, make_agent(world.gen))
            if on_life:
                on_life(world.gen, world)
            world.end_life()
            if transplant is not None or cfg.arm == "amnesia":
                world = fresh_world(cfg, log, world.gen, transplant)
            path = out / "snapshots" / f"after_life_{world.gen - 1:04d}.json"
            path.write_text(json.dumps(world.to_dict()))
    finally:
        log.close()
    return world


def _truncate_events(path: Path, gen: int) -> None:
    if not path.exists():
        return
    keep = [line for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and json.loads(line).get("gen", -1) < gen]
    path.write_text("".join(line + "\n" for line in keep), encoding="utf-8")
