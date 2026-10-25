import json

import pytest

from machineplay.agents.scripted import ScribeAgent, WandererAgent
from machineplay.config import Config
from machineplay.eventlog import read_events
from machineplay.lineage import run_lineage
from machineplay.metrics import life_metrics, run_metrics


def metrics(out, cfg):
    ev = read_events(out / "events.jsonl")
    return life_metrics(ev, cfg.turns_per_life), run_metrics(ev)


def test_inherit_arm_carries_artifacts_amnesia_does_not(tmp_path):
    cfg = Config(seed=1, stage=1, turns_per_life=120)
    run_lineage(cfg, tmp_path / "a", lambda g: ScribeAgent(), lives=4)
    rows, summary = metrics(tmp_path / "a", cfg)
    assert len(rows) == 4
    assert rows[0]["code"] >= 1 and rows[0]["iur"] == 0
    assert all(r["iur"] > 0 for r in rows[1:])
    assert summary["longest_chain"] >= 3 and summary["reused_slates"] >= 1

    cfg_b = Config(seed=1, stage=1, turns_per_life=120, arm="amnesia")
    run_lineage(cfg_b, tmp_path / "b", lambda g: ScribeAgent(), lives=4)
    rows_b, summary_b = metrics(tmp_path / "b", cfg_b)
    assert all(r["iur"] == 0 for r in rows_b)
    assert summary_b["artifacts_touched_by_later_lives"] == 0


def test_resume_continues_and_drops_partial_life(tmp_path):
    cfg = Config(seed=2, stage=1, turns_per_life=30)
    run_lineage(cfg, tmp_path, lambda g: WandererAgent(), lives=2)
    with open(tmp_path / "events.jsonl", "a") as fh:  # a life that was interrupted mid-way
        fh.write(json.dumps({"ev": "birth", "gen": 2}) + "\n")
    with pytest.raises(FileExistsError):
        run_lineage(cfg, tmp_path, lambda g: WandererAgent(), lives=3)
    run_lineage(cfg, tmp_path, lambda g: WandererAgent(), lives=3, resume=True)
    births = [e for e in read_events(tmp_path / "events.jsonl") if e["ev"] == "birth"]
    assert [e["gen"] for e in births] == [0, 1, 2]


def test_archaeology_transplants_writing_into_fresh_worlds(tmp_path):
    cfg = Config(seed=3, stage=1, turns_per_life=120)
    run_lineage(cfg, tmp_path / "src", lambda g: ScribeAgent(), lives=2)
    snap = json.loads((tmp_path / "src" / "snapshots" / "after_life_0001.json").read_text())
    run_lineage(cfg, tmp_path / "dig", lambda g: ScribeAgent(), lives=2, transplant=snap)
    rows, summary = metrics(tmp_path / "dig", cfg)
    assert all(r["iur"] > 0 for r in rows)
    assert all(r["code"] == 0 for r in rows)  # found the transplanted SEEKER instead of writing one
