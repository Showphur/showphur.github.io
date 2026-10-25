"""Command line: run lineages, read their metrics, compare arms, dig up old artifacts."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import Config
from .eventlog import read_events
from .lineage import run_lineage
from .metrics import compare, format_table, life_metrics, run_metrics

SHOW_COLS = ["life", "made", "new", "frontier", "max_tier", "parity", "iur", "slates", "code", "runs", "derived",
             "program_actions", "tokens_out"]


def make_factory(args, out: Path):
    if args.agent == "wanderer":
        from .agents.scripted import WandererAgent
        return (lambda gen: WandererAgent()), None
    if args.agent == "scribe":
        from .agents.scripted import ScribeAgent
        return (lambda gen: ScribeAgent()), None
    import anthropic

    from .agents.claude import ClaudeAgent, make_think_fn
    client = anthropic.Anthropic(max_retries=8)
    fallbacks = {"auto": None, "on": True, "off": False}[args.fallbacks]
    factory = lambda gen: ClaudeAgent(client, model=args.model, effort=args.effort, fallbacks=fallbacks,  # noqa: E731
                                      transcript_dir=out / "transcripts")
    return factory, make_think_fn(client, args.model)


def load_rows(run: Path) -> tuple[list[dict], dict]:
    cfg = Config.from_dict(json.loads((run / "config.json").read_text()))
    events = read_events(run / "events.jsonl")
    return life_metrics(events, cfg.turns_per_life), run_metrics(events)


def print_life(run: Path):
    def hook(gen, world):
        rows, _ = load_rows(run)
        row = rows[-1] if rows else {}
        print(f"life {gen:3d}: " + "  ".join(f"{k}={row.get(k)}" for k in SHOW_COLS[1:]), flush=True)
    return hook


def cmd_run(args) -> None:
    out = Path(args.out)
    cfg = Config(seed=args.seed, stage=args.stage, arm=args.arm, turns_per_life=args.turns)
    for kv in args.set or []:
        k, v = kv.split("=", 1)
        cur = getattr(cfg, k)
        setattr(cfg, k, type(cur)(v))
    factory, think = make_factory(args, out)
    run_lineage(cfg, out, factory, args.lives, resume=args.resume, think_fn=think, on_life=print_life(out))
    cmd_metrics(argparse.Namespace(run=str(out)))


def cmd_eval(args) -> None:
    snap = json.loads(Path(args.snapshot).read_text())
    cfg = Config.from_dict(snap["config"])
    cfg.turns_per_life = args.turns or cfg.turns_per_life
    out = Path(args.out)
    factory, think = make_factory(args, out)
    run_lineage(cfg, out, factory, args.lives, transplant=snap, think_fn=think, on_life=print_life(out))
    cmd_metrics(argparse.Namespace(run=str(out)))


def cmd_metrics(args) -> None:
    rows, summary = load_rows(Path(args.run))
    print(format_table(rows, SHOW_COLS))
    print(json.dumps(summary))


def cmd_compare(args) -> None:
    a, sa = load_rows(Path(args.a))
    b, sb = load_rows(Path(args.b))
    print(f"A = {args.a}\nB = {args.b}")
    print(compare(a, b))
    print("A:", json.dumps(sa))
    print("B:", json.dumps(sb))


def cmd_show(args) -> None:
    run = Path(args.run)
    snap = Path(args.snapshot) if args.snapshot else sorted((run / "snapshots").glob("*.json"))[-1]
    state = json.loads(snap.read_text())
    print(f"# {snap.name}: the world before life {state['gen']}\n")
    for o in state["objects"]:
        if o["kind"] in ("stone", "slate") and o["text"]:
            where = f"in {o['in_slot']}" if o["in_slot"] else f"at ({o['pos'][0]:.1f}, {o['pos'][1]:.1f})"
            print(f"--- {o['kind']} {o['id']} {where}  written in life {o['written_gen']}, "
                  f"uses={o['uses']} integrity={o['integrity']}")
            print(o["text"])
            print()


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="machineplay")
    sub = p.add_subparsers(dest="cmd", required=True)

    def agent_opts(sp):
        sp.add_argument("--agent", choices=["claude", "scribe", "wanderer"], default="claude")
        sp.add_argument("--model", default="claude-opus-5-5")
        sp.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
        sp.add_argument("--fallbacks", default="auto", choices=["auto", "on", "off"])

    r = sub.add_parser("run", help="run a lineage of lives")
    r.add_argument("--out", required=True)
    r.add_argument("--lives", type=int, default=10)
    r.add_argument("--stage", type=int, default=1, choices=[0, 1, 2, 3])
    r.add_argument("--arm", default="inherit", choices=["inherit", "amnesia"])
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--turns", type=int, default=150)
    r.add_argument("--set", action="append", metavar="KEY=VALUE", help="override any Config field")
    r.add_argument("--resume", action="store_true")
    agent_opts(r)
    r.set_defaults(fn=cmd_run)

    e = sub.add_parser("eval", help="archaeology: fresh beings in fresh worlds carrying one snapshot's writing")
    e.add_argument("--snapshot", required=True)
    e.add_argument("--out", required=True)
    e.add_argument("--lives", type=int, default=3)
    e.add_argument("--turns", type=int, default=0)
    agent_opts(e)
    e.set_defaults(fn=cmd_eval)

    m = sub.add_parser("metrics", help="per-life ratchet metrics for a run")
    m.add_argument("run")
    m.set_defaults(fn=cmd_metrics)

    c = sub.add_parser("compare", help="compare two runs life by life (e.g. inherit vs amnesia)")
    c.add_argument("a")
    c.add_argument("b")
    c.set_defaults(fn=cmd_compare)

    s = sub.add_parser("show", help="print all writing in a snapshot")
    s.add_argument("run")
    s.add_argument("--snapshot")
    s.set_defaults(fn=cmd_show)

    args = p.parse_args(argv)
    try:
        args.fn(args)
    except FileExistsError as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
