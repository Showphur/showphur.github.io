"""Is anything ratcheting? Everything here is computed from the event log after the fact; no being ever sees it.

Per life:
  made, new         distinct compounds made in this life / of those, how many no earlier life had made
  frontier          distinct compounds made by any life so far
  max_tier          deepest compound made in this life
  remade            share of the previous life's compounds this life made again (catching up)
  parity            turn by which this life had re-made all of them (None = never)
  iur               inheritance use rate: share of turns that touched writing or code left by an earlier life
  slates, code      slates written / of those, containing code
  derived           writes descending from an earlier life's writing (content-matched edit-chain links)
  runs              runs the being started itself, engine or mantle (ok/total)
  frame_runs        runs made by frames on their own
  uses              use() imports of slates written by earlier lives
  inh_calls         world calls made by programs written in earlier lives: capability carried by code
  prog_made         reactions caused by programs (inherited programs' share in inh_made)
Per run:
  reused_slates          slates touched (read/run/use) by >= 3 distinct later lives
  longest_chain          longest chain of writes, each descending from an earlier life's writing
  improved_derivations   derived programs that make more per run, or fail less, than the version they came from
"""
from __future__ import annotations

from collections import defaultdict

TOUCH_FNS = {"read", "run", "attune", "invoke"}


def _inherited(gen_written, gen_now) -> bool:
    return gen_written is not None and gen_written != -1 and gen_written < gen_now


def life_metrics(events: list[dict], turns_per_life: int) -> list[dict]:
    by_gen: dict[int, list[dict]] = defaultdict(list)
    for e in events:
        if "gen" in e:
            by_gen[e["gen"]].append(e)
    rows, seen_ever, prev_made = [], set(), None
    for g in sorted(by_gen):
        made_at: dict[str, int] = {}
        r = defaultdict(int)
        touched_turns = set()
        for e in by_gen[g]:
            ev = e.get("ev")
            if ev == "llm":
                r["tokens_in"] += e.get("input_tokens", 0) + (e.get("cache_read") or 0) + (e.get("cache_write") or 0)
                r["tokens_out"] += e.get("output_tokens", 0)
            elif ev == "use" and e.get("inherited"):
                r["uses"] += 1
                touched_turns.add(e["turn"])
            elif ev == "program":
                r["prog_made"] += e.get("reactions", 0)
                if _inherited(e.get("prog_gen"), g):
                    r["inh_made"] += e.get("reactions", 0)
                if e.get("kind") == "frame":
                    r["frame_runs"] += 1
                else:
                    r["runs"] += 1
                    r["runs_ok"] += bool(e.get("ok"))
            if ev != "act" or not e.get("ok"):
                continue
            via = e.get("via", "")
            if via == "agent":
                r["actions"] += 1
            elif _inherited(e.get("prog_gen"), g):
                r["inh_calls"] += 1
                touched_turns.add(e["turn"])
            if e.get("reacted") and e.get("product"):
                made_at.setdefault(e["product"], e["turn"])
                r["max_tier"] = max(r["max_tier"], e.get("tier", 0))
            if e.get("inherited") and e["fn"] in TOUCH_FNS:
                touched_turns.add(e["turn"])
            if e["fn"] == "write":
                if e.get("kind") == "slate":
                    r["slates"] += 1
                    r["code"] += bool(e.get("is_code"))
                if _inherited(e.get("derived_from_gen"), g):
                    r["derived"] += 1
        made = set(made_at)
        new = made - seen_ever
        seen_ever |= made
        remade = parity = None
        if prev_made:
            remade = round(len(prev_made & made) / len(prev_made), 2)
            if prev_made <= made:
                parity = max(made_at[s] for s in prev_made)
        rows.append({"life": g, "made": len(made), "new": len(new), "frontier": len(seen_ever),
                     "max_tier": r["max_tier"], "remade": remade, "parity": parity,
                     "iur": round(len(touched_turns) / max(1, turns_per_life), 3),
                     "slates": r["slates"], "code": r["code"], "derived": r["derived"],
                     "runs": f"{r['runs_ok']}/{r['runs']}", "frame_runs": r["frame_runs"], "uses": r["uses"],
                     "inh_calls": r["inh_calls"], "prog_made": r["prog_made"], "inh_made": r["inh_made"],
                     "actions": r["actions"], "tokens_in": r["tokens_in"], "tokens_out": r["tokens_out"]})
        prev_made = made
    return rows


def program_table(events: list[dict]) -> list[dict]:
    """One row per program version: a slate as written in one life (rewriting it starts a new version)."""
    nodes: dict[tuple[str, int], dict] = {}
    for e in events:
        if e.get("ev") != "program":
            continue
        key = (e["slate"], e.get("prog_gen", -1))
        n = nodes.setdefault(key, {"slate": key[0], "written": key[1], "runs": 0, "ok": 0, "made": 0, "lives": set()})
        n["runs"] += 1
        n["ok"] += bool(e.get("ok"))
        n["made"] += e.get("reactions", 0)
        n["lives"].add(e["gen"])
    rows = []
    for n in sorted(nodes.values(), key=lambda n: (n["written"], n["slate"])):
        rows.append({**n, "lives": len(n["lives"]), "made_per_run": round(n["made"] / n["runs"], 2),
                     "ok_rate": round(n["ok"] / n["runs"], 2)})
    return rows


def run_metrics(events: list[dict]) -> dict:
    touch_gens: dict[str, set[int]] = defaultdict(set)
    writes: dict[tuple[str, int], tuple[str, int] | None] = {}
    for e in events:
        if e.get("ev") in ("act", "use") and e.get("ok", True) and e.get("inherited") and e.get("obj"):
            touch_gens[e["obj"]].add(e["gen"])
        if e.get("ev") == "act" and e.get("ok") and e.get("fn") == "write":
            src, sg = e.get("derived_from"), e.get("derived_from_gen")
            link = (src, sg) if src and _inherited(sg, e["gen"]) else None
            node = (e["obj"], e["gen"])
            if link or node not in writes:  # a later same-life rewrite never erases an inherited link
                writes[node] = link or writes.get(node)

    memo: dict[tuple[str, int], int] = {}

    def depth(node: tuple[str, int]) -> int:
        if node not in memo:
            memo[node] = 1  # guards against cycles
            link = writes.get(node)
            memo[node] = 1 + (depth(link) if link in writes else 1) if link else 1
        return memo[node]

    stats = {(p["slate"], p["written"]): p for p in program_table(events)}

    def better(child, parent) -> bool:
        return child["runs"] >= 2 and (child["made_per_run"] > parent["made_per_run"]
                                       or child["made_per_run"] == parent["made_per_run"]
                                       and child["ok_rate"] > parent["ok_rate"])

    improved = sum(1 for node, link in writes.items()
                   if link and node in stats and link in stats and better(stats[node], stats[link]))

    return {"reused_slates": sum(1 for gens in touch_gens.values() if len(gens) >= 3),
            "improved_derivations": improved,
            "longest_chain": max((depth(n) for n in writes), default=0),
            "artifacts_touched_by_later_lives": len(touch_gens)}


def format_table(rows: list[dict], cols: list[str] | None = None) -> str:
    if not rows:
        return "(nothing yet)"
    cols = cols or list(rows[0])
    cell = lambda r, c: "-" if r.get(c) is None else str(r.get(c, ""))  # noqa: E731
    widths = {c: max(len(c), *(len(cell(r, c)) for r in rows)) for c in cols}
    lines = ["  ".join(c.rjust(widths[c]) for c in cols)]
    lines += ["  ".join(cell(r, c).rjust(widths[c]) for c in cols) for r in rows]
    return "\n".join(lines)


def ratchet_verdict(a: list[dict], b: list[dict], key: str = "frontier") -> str:
    """A ratchet means A (inherit) pulls away from B (control): the gap is positive at the end and wider late
    than early. Needs at least 3 lives in both runs."""
    n = min(len(a), len(b))
    if n < 3:
        return "verdict: too few lives to judge (need >= 3 in both runs)"
    gaps = [a[i][key] - b[i][key] for i in range(n)]
    third = max(1, n // 3)
    early, late = sum(gaps[:third]) / third, sum(gaps[-third:]) / third
    trend = "widening" if late > early else "narrowing" if late < early else "flat"
    signal = "RATCHET SIGNAL" if gaps[-1] > 0 and late > early else "no ratchet signal"
    return (f"{key} gap A-B by life: {gaps}\n"
            f"verdict: {signal} (final gap {gaps[-1]:+d}, early mean {early:+.1f}, late mean {late:+.1f}, {trend})")


def ceiling_warning(a: list[dict], b: list[dict], possible: int | None) -> str:
    if not possible or not a or not b:
        return ""
    fa, fb = a[-1]["frontier"], b[-1]["frontier"]
    if min(fa, fb) >= 0.7 * possible:
        return (f"\nwarning: both arms are near the ceiling ({fa} and {fb} of {possible} compounds exist), so the "
                "control can catch up. Use a deeper chemistry, e.g. --set n_elements=12 --set max_tier=8")
    return ""


def aggregate_verdict(pairs: list[tuple[list[dict], list[dict]]], key: str = "frontier") -> str:
    """Across seeds: mean A-B gap per life with its standard error. A ratchet: the mean gap is wider late than
    early, and the final mean gap is more than two standard errors above zero."""
    n = min(min(len(a), len(b)) for a, b in pairs)
    if n < 3 or len(pairs) < 2:
        return "verdict: need >= 2 seeds and >= 3 lives"
    gaps = [[a[i][key] - b[i][key] for a, b in pairs] for i in range(n)]
    means = [sum(g) / len(g) for g in gaps]
    k = len(pairs)
    var = sum((x - means[-1]) ** 2 for x in gaps[-1]) / (k - 1)
    se = (var / k) ** 0.5
    third = max(1, n // 3)
    early, late = sum(means[:third]) / third, sum(means[-third:]) / third
    seeds_with_signal = sum(1 for a, b in pairs if ratchet_verdict(a, b, key).split("verdict: ")[1].startswith("RATCHET"))
    signal = "RATCHET" if late > early and means[-1] > 2 * se else "NO RATCHET"
    return (f"mean {key} gap A-B by life: {[round(m, 1) for m in means]}\n"
            f"final mean gap {means[-1]:+.2f} +/- {se:.2f} (s.e., {k} seeds); early {early:+.2f}, late {late:+.2f}; "
            f"seeds with a ratchet signal: {seeds_with_signal}/{k}\n"
            f"verdict: {signal}")


def compare(a: list[dict], b: list[dict],
            keys=("frontier", "new", "made", "max_tier", "remade", "iur", "inh_calls"),
            possible: int | None = None) -> str:
    rows = []
    for i in range(max(len(a), len(b))):
        r = {"life": i}
        for k in keys:
            r[f"A.{k}"] = a[i].get(k) if i < len(a) else ""
            r[f"B.{k}"] = b[i].get(k) if i < len(b) else ""
        rows.append(r)
    return format_table(rows) + "\n" + ratchet_verdict(a, b) + ceiling_warning(a, b, possible)
