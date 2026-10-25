"""Is anything ratcheting? Everything here is computed from the event log after the fact; no being ever sees it.

Per life:
  made          distinct compound substances made in this life
  new           of those, how many no earlier life had made
  frontier      distinct compounds made by any life so far
  max_tier      deepest compound made in this life
  parity        turn by which this life had re-made everything the previous life made (None = never)
  iur           inheritance use rate: share of turns that touched writing left by an earlier life
  slates/code   slates written / slates written containing code
  runs          engine or mantle runs (ok / total)
  derived       writes made right after reading an earlier life's writing (edit-chain links)
Per run:
  reused_slates slates touched (read/run/use) by >= 3 distinct later lives
  longest_chain longest chain of writes each derived from an earlier life's writing
  improved_derivations  derived slates run at least twice whose runs succeed more often than their parent's
"""
from __future__ import annotations

from collections import defaultdict

TOUCH_FNS = {"read", "run", "attune", "invoke"}


def life_metrics(events: list[dict], turns_per_life: int) -> list[dict]:
    by_gen: dict[int, list[dict]] = defaultdict(list)
    for e in events:
        if "gen" in e:
            by_gen[e["gen"]].append(e)
    rows, seen_ever, prev_made = [], set(), None
    for g in sorted(by_gen):
        evs = by_gen[g]
        made_at: dict[str, int] = {}
        max_tier = 0
        touched_turns, slates, code, runs, runs_ok, derived = set(), 0, 0, 0, 0, 0
        agent_actions = program_actions = tokens_in = tokens_out = 0
        for e in evs:
            if e.get("ev") == "llm":
                tokens_in += e.get("input_tokens", 0) + (e.get("cache_read") or 0) + (e.get("cache_write") or 0)
                tokens_out += e.get("output_tokens", 0)
            if e.get("ev") == "use" and e.get("inherited"):
                touched_turns.add(e["turn"])
            if e.get("ev") != "act" or not e.get("ok"):
                continue
            via = e.get("via", "")
            if via == "agent":
                agent_actions += 1
            elif via.startswith("program"):
                program_actions += 1
            if e.get("reacted") and e.get("product"):
                made_at.setdefault(e["product"], e["turn"])
                max_tier = max(max_tier, e.get("tier", 0))
            if e.get("inherited") and (e["fn"] in TOUCH_FNS or via.startswith("program")):
                touched_turns.add(e["turn"])
            if e["fn"] == "write" and e.get("kind") == "slate":
                slates += 1
                code += bool(e.get("is_code"))
            if e["fn"] == "write" and e.get("derived_from_gen") is not None and e["derived_from_gen"] != -1 \
                    and e["derived_from_gen"] < g:
                derived += 1
            if e["fn"] in ("run", "invoke") and via == "agent":
                runs += 1
                runs_ok += bool(e.get("program_ok"))
        made = set(made_at)
        new = made - seen_ever
        seen_ever |= made
        parity = None
        if prev_made:
            if prev_made <= made:
                parity = max(made_at[s] for s in prev_made)
        elif prev_made is not None:
            parity = 0
        rows.append({"life": g, "made": len(made), "new": len(new), "frontier": len(seen_ever), "max_tier": max_tier,
                     "parity": parity, "iur": round(len(touched_turns) / max(1, turns_per_life), 3),
                     "actions": agent_actions, "program_actions": program_actions, "slates": slates, "code": code,
                     "runs": f"{runs_ok}/{runs}", "derived": derived,
                     "tokens_in": tokens_in, "tokens_out": tokens_out})
        prev_made = made
    return rows


def run_metrics(events: list[dict]) -> dict:
    touch_gens: dict[str, set[int]] = defaultdict(set)
    writes: dict[tuple[str, int], tuple[str, int] | None] = {}
    run_stats: dict[tuple[str, int], list[int]] = defaultdict(lambda: [0, 0])  # (slate, written in life) -> ok, total
    for e in events:
        if e.get("ev") == "act" and e.get("ok") and e.get("fn") == "run" and e.get("obj"):
            st = run_stats[(e["obj"], e["author_gen"])]
            st[0] += bool(e.get("program_ok"))
            st[1] += 1
        if e.get("ev") in ("act", "use") and e.get("ok", True) and e.get("inherited") and e.get("obj"):
            touch_gens[e["obj"]].add(e["gen"])
        if e.get("ev") == "act" and e.get("ok") and e.get("fn") == "write":
            src, sg = e.get("derived_from"), e.get("derived_from_gen")
            link = (src, sg) if src and sg is not None and sg != -1 and sg < e["gen"] else None
            writes[(e["obj"], e["gen"])] = link

    memo: dict[tuple[str, int], int] = {}

    def depth(node: tuple[str, int]) -> int:
        if node not in memo:
            memo[node] = 1  # guards against cycles
            link = writes.get(node)
            memo[node] = 1 + (depth(link) if link in writes else 1) if link else 1
        return memo[node]

    def rate(node):
        ok, total = run_stats.get(node, (0, 0))
        return ok / total if total else None

    improved = sum(1 for node, link in writes.items()
                   if link and run_stats.get(node, (0, 0))[1] >= 2 and rate(link) is not None and rate(node) > rate(link))

    return {"reused_slates": sum(1 for gens in touch_gens.values() if len(gens) >= 3),
            "improved_derivations": improved,
            "longest_chain": max((depth(n) for n in writes), default=0),
            "artifacts_touched_by_later_lives": len(touch_gens)}


def format_table(rows: list[dict], cols: list[str] | None = None) -> str:
    if not rows:
        return "(no lives yet)"
    cols = cols or list(rows[0])
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    lines = ["  ".join(c.rjust(widths[c]) for c in cols)]
    for r in rows:
        lines.append("  ".join(str(r.get(c, "") if r.get(c) is not None else "-").rjust(widths[c]) for c in cols))
    return "\n".join(lines)


def compare(a: list[dict], b: list[dict], keys=("frontier", "new", "max_tier", "parity", "iur")) -> str:
    rows = []
    for i in range(max(len(a), len(b))):
        r = {"life": i}
        for k in keys:
            r[f"A.{k}"] = a[i].get(k) if i < len(a) else ""
            r[f"B.{k}"] = b[i].get(k) if i < len(b) else ""
        rows.append(r)
    return format_table(rows)
