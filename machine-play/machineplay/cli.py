"""Command line: run lineages, read their metrics, compare arms, dig up old artifacts."""
from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path

from .config import Config
from .eventlog import read_events
from .lineage import run_lineage
from .chemistry import Chemistry
from .metrics import aggregate_verdict, compare, format_table, life_metrics, program_table, ratchet_verdict, run_metrics

SHOW_COLS = ["life", "made", "new", "frontier", "max_tier", "remade", "iur", "slates", "code", "derived", "runs",
             "frame_runs", "uses", "inh_calls", "prog_made", "inh_made", "tokens_out"]


def make_factory(args, out: Path):
    if args.agent == "wanderer":
        from .agents.scripted import WandererAgent
        return (lambda gen: WandererAgent()), None
    if args.agent == "scribe":
        from .agents.scripted import ScribeAgent
        return (lambda gen: ScribeAgent()), None
    if args.agent == "naive-scribe":
        from .agents.scripted import NaiveScribeAgent
        return (lambda gen: NaiveScribeAgent()), None
    import anthropic

    from .agents.claude import ClaudeAgent, make_think_fn
    client = anthropic.Anthropic(max_retries=8)
    fallbacks = {"auto": None, "on": True, "off": False}[args.fallbacks]
    factory = lambda gen: ClaudeAgent(client, model=args.model, effort=args.effort, fallbacks=fallbacks,  # noqa: E731
                                      transcript_dir=out / "transcripts")
    return factory, make_think_fn(client, args.model)


def load_cfg(run: Path) -> Config:
    return Config.from_dict(json.loads((run / "config.json").read_text()))


def possible(cfg: Config) -> int:
    """How many compounds exist in this run's chemistry: the frontier's ceiling."""
    chem = Chemistry(cfg.seed, cfg.n_elements, cfg.max_tier)
    return sum(1 for s in chem.substances.values() if s.tier > 0)


def load_rows(run: Path) -> tuple[list[dict], dict]:
    cfg = load_cfg(run)
    events = read_events(run / "events.jsonl")
    return life_metrics(events, cfg.turns_per_life), run_metrics(events)


def print_life(run: Path):
    def hook(gen, world):
        rows, _ = load_rows(run)
        row = rows[-1] if rows else {}
        print(f"life {gen:3d}: " + "  ".join(f"{k}={row.get(k)}" for k in SHOW_COLS[1:]), flush=True)
    return hook


def build_cfg(args, seed: int, arm: str) -> Config:
    cfg = Config(seed=seed, stage=args.stage, arm=arm, turns_per_life=args.turns)
    for kv in args.set or []:
        k, v = kv.split("=", 1)
        cur = getattr(cfg, k)
        setattr(cfg, k, type(cur)(v))
    return cfg


def cmd_run(args) -> None:
    out = Path(args.out)
    cfg = build_cfg(args, args.seed, args.arm)
    factory, think = make_factory(args, out)
    run_lineage(cfg, out, factory, args.lives, resume=args.resume, think_fn=think, on_life=print_life(out))
    cmd_metrics(argparse.Namespace(run=str(out), programs=False))


def cmd_eval(args) -> None:
    snap = json.loads(Path(args.snapshot).read_text())
    cfg = Config.from_dict(snap["config"])
    cfg.turns_per_life = args.turns or cfg.turns_per_life
    out = Path(args.out)
    factory, think = make_factory(args, out)
    run_lineage(cfg, out, factory, args.lives, transplant=snap, think_fn=think, on_life=print_life(out))
    cmd_metrics(argparse.Namespace(run=str(out), programs=False))


def cmd_metrics(args) -> None:
    rows, summary = load_rows(Path(args.run))
    print(format_table(rows, SHOW_COLS))
    print(json.dumps({**summary, "compounds_possible": possible(load_cfg(Path(args.run)))}))
    if args.programs:
        print("\nprograms (one row per slate version):")
        print(format_table(program_table(read_events(Path(args.run) / "events.jsonl")),
                           ["slate", "written", "runs", "ok_rate", "made_per_run", "lives"]))


def cmd_compare(args) -> None:
    a, sa = load_rows(Path(args.a))
    b, sb = load_rows(Path(args.b))
    print(f"A = {args.a}\nB = {args.b}")
    print(compare(a, b, possible=possible(load_cfg(Path(args.a)))))
    print("A:", json.dumps(sa))
    print("B:", json.dumps(sb))


def cmd_sweep(args) -> None:
    """Both arms over several seeds, then one verdict across seeds. Finished runs are reused, so a sweep resumes."""
    out = Path(args.out)
    pairs = []
    for seed in range(args.seed, args.seed + args.seeds):
        rows = []
        for arm in ("inherit", "amnesia"):
            run = out / f"seed{seed}_{arm}"
            done = len(list((run / "snapshots").glob("*.json"))) if run.exists() else 0
            if done < args.lives:
                factory, think = make_factory(args, run)
                run_lineage(build_cfg(args, seed, arm), run, factory, args.lives, resume=done > 0, think_fn=think)
            rows.append(load_rows(run)[0][: args.lives])
        pairs.append(tuple(rows))
        print(f"seed {seed}: " + ratchet_verdict(*rows).splitlines()[-1].replace("verdict: ", ""), flush=True)
    a, b = pairs[-1]
    print(aggregate_verdict(pairs) + ceiling_warning_for(out / f"seed{args.seed}_inherit", pairs))


def ceiling_warning_for(run: Path, pairs) -> str:
    from .metrics import ceiling_warning
    n = possible(load_cfg(run))
    return next((w for a, b in pairs if (w := ceiling_warning(a, b, n))), "")


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
        sp.add_argument("--agent", choices=["claude", "scribe", "naive-scribe", "wanderer"], default="claude")
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
    m.add_argument("--programs", action="store_true", help="also list every program version and how it performed")
    m.set_defaults(fn=cmd_metrics)

    c = sub.add_parser("compare", help="compare two runs life by life (e.g. inherit vs amnesia)")
    c.add_argument("a")
    c.add_argument("b")
    c.set_defaults(fn=cmd_compare)

    w = sub.add_parser("sweep", help="inherit and amnesia arms over several seeds, with one verdict across them")
    w.add_argument("--out", required=True)
    w.add_argument("--seeds", type=int, default=5)
    w.add_argument("--seed", type=int, default=1, help="first seed")
    w.add_argument("--lives", type=int, default=12)
    w.add_argument("--stage", type=int, default=1, choices=[0, 1, 2, 3])
    w.add_argument("--turns", type=int, default=150)
    w.add_argument("--set", action="append", metavar="KEY=VALUE", help="override any Config field")
    agent_opts(w)
    w.set_defaults(fn=cmd_sweep)

    s = sub.add_parser("show", help="print all writing in a snapshot")
    s.add_argument("run")
    s.add_argument("--snapshot")
    s.set_defaults(fn=cmd_show)

    args = p.parse_args(argv)
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # piping into head is fine
    try:
        args.fn(args)
    except FileExistsError as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
