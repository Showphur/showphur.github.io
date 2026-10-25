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
    assert all(r["code"] == 0 for r in rows)  # found the transplanted CRAFTER instead of writing one


def test_scribe_uses_each_stages_affordances(tmp_path):
    cfg = Config(seed=4, stage=3, turns_per_life=150)
    run_lineage(cfg, tmp_path, lambda g: ScribeAgent(), lives=3)
    ev = read_events(tmp_path / "events.jsonl")
    fns = {e["fn"] for e in ev if e.get("ev") == "act" and e.get("ok") and e.get("via") == "agent"}
    assert {"run", "attune", "invoke"} <= fns
    kinds = {e["kind"] for e in ev if e.get("ev") == "program"}
    assert {"engine", "frame", "mantle"} <= kinds
    assert any(e.get("ev") == "use" and e.get("found") for e in ev)
    rows, summary = metrics(tmp_path, cfg)
    assert rows[2]["inh_calls"] > 0 and summary["longest_chain"] >= 3


def test_naive_scribe_reproduces_its_earlier_runs(tmp_path):
    from machineplay.agents.scripted import NaiveScribeAgent
    cfg = Config(seed=7, stage=1)
    run_lineage(cfg, tmp_path, lambda g: NaiveScribeAgent(), lives=1)
    rows, _ = metrics(tmp_path, cfg)
    assert (rows[0]["made"], rows[0]["max_tier"]) == (4, 1)  # as recorded before the rename


def test_book_round_trips_and_stays_valid_python():
    import ast

    from machineplay.agents.scripted import book_text, parse_book
    recipes = {"a x + b y": "c z", "b y + d": "nothing", "a x + d": "nothing", "d + d": "nothing"}
    text = book_text(3, recipes, 4000)
    ast.parse(text)
    assert parse_book(text) == (3, recipes)
    huge = {f"k{i} + k{j}": "nothing" for i in range(60) for j in range(i, 60)}
    text = book_text(1, huge, 4000)
    assert len(text) <= 4000 and len(parse_book(text)[1]) > 500  # compressed: far more than ~80 plain lines


def test_sweep_command_runs_and_resumes(tmp_path, capsys):
    from machineplay.cli import main
    argv = ["sweep", "--agent", "naive-scribe", "--seeds", "2", "--lives", "3", "--turns", "40", "--out", str(tmp_path)]
    main(argv)
    first = capsys.readouterr().out
    assert first.count("seed ") >= 2 and "verdict:" in first
    main(argv)  # finished runs are reused, not rerun
    assert capsys.readouterr().out.splitlines()[-1] == first.splitlines()[-1]
