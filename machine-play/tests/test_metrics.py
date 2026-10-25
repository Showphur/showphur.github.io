from machineplay.metrics import life_metrics, run_metrics


def act(gen, turn, fn, **kw):
    return {"ev": "act", "gen": gen, "turn": turn, "fn": fn, "via": "agent", "ok": True, **kw}


def test_frontier_new_and_parity():
    ev = [act(0, 3, "combine", reacted=True, product="p1", tier=1),
          act(0, 9, "combine", reacted=True, product="p2", tier=2),
          act(1, 4, "combine", reacted=True, product="p2", tier=2),
          act(1, 7, "combine", reacted=True, product="p1", tier=1),
          act(1, 8, "combine", reacted=True, product="p3", tier=3),
          act(1, 8, "read", obj="s1", inherited=True, author_gen=0)]
    rows = life_metrics(ev, turns_per_life=10)
    assert [r["frontier"] for r in rows] == [2, 3]
    assert rows[1]["new"] == 1 and rows[1]["max_tier"] == 3
    assert rows[0]["parity"] is None and rows[1]["parity"] == 7
    assert rows[1]["iur"] == 0.1


def test_chains_reuse_and_improvement():
    ev = [act(0, 1, "write", obj="s1", kind="slate", is_code=True)]
    ev += [act(1, t, "run", obj="s1", author_gen=0, inherited=True, program_ok=False) for t in (1, 2)]
    ev += [act(1, 3, "write", obj="s2", kind="slate", is_code=True, derived_from="s1", derived_from_gen=0)]
    ev += [act(g, t, "run", obj="s2", author_gen=1, inherited=True, program_ok=True) for g in (2, 3, 4) for t in (1,)]
    ev += [act(5, 1, "write", obj="s3", kind="slate", derived_from="s2", derived_from_gen=1)]
    m = run_metrics(ev)
    assert m["longest_chain"] == 3
    assert m["improved_derivations"] == 1
    assert m["reused_slates"] == 1  # s2 was run in lives 2, 3 and 4
