from machineplay.metrics import aggregate_verdict, ceiling_warning, life_metrics, program_table, ratchet_verdict, run_metrics


def act(gen, turn, fn, **kw):
    return {"ev": "act", "gen": gen, "turn": turn, "fn": fn, "via": "agent", "ok": True, **kw}


def prog(gen, slate, prog_gen, reactions=0, ok=True, kind="engine"):
    return {"ev": "program", "gen": gen, "turn": 0, "kind": kind, "slate": slate, "prog_gen": prog_gen,
            "reactions": reactions, "ok": ok, "calls": 5}


def test_frontier_new_remade_and_parity():
    ev = [act(0, 3, "combine", reacted=True, product="p1", tier=1),
          act(0, 9, "combine", reacted=True, product="p2", tier=2),
          act(1, 4, "combine", reacted=True, product="p2", tier=2),
          act(1, 8, "combine", reacted=True, product="p3", tier=3),
          act(1, 8, "read", obj="s1", inherited=True, author_gen=0),
          act(2, 2, "combine", reacted=True, product="p2", tier=2),
          act(2, 5, "combine", reacted=True, product="p3", tier=3)]
    rows = life_metrics(ev, turns_per_life=10)
    assert [r["frontier"] for r in rows] == [2, 3, 3]
    assert rows[1]["new"] == 1 and rows[1]["max_tier"] == 3
    assert rows[1]["remade"] == 0.5 and rows[1]["parity"] is None
    assert rows[2]["remade"] == 1.0 and rows[2]["parity"] == 5
    assert rows[1]["iur"] == 0.1


def test_inherited_code_is_credited():
    ev = [prog(1, "s1", 0, reactions=2),
          {**act(1, 3, "look"), "via": "program:s1", "prog_gen": 0},
          {**act(1, 4, "look"), "via": "program:s2", "prog_gen": 1},  # this life's own program
          prog(1, "s9", 0, reactions=1, kind="frame")]
    r = life_metrics(ev, 10)[0]
    assert r["inh_calls"] == 1 and r["inh_made"] == 3 and r["prog_made"] == 3
    assert r["frame_runs"] == 1 and r["runs"] == "1/1"
    assert r["iur"] == 0.1


def test_chains_reuse_and_improvement():
    ev = [act(0, 1, "write", obj="s1", kind="slate", is_code=True)]
    ev += [prog(1, "s1", 0, reactions=0), prog(1, "s1", 0, reactions=1)]
    ev += [act(1, 9, "write", obj="s1", kind="slate", is_code=True, derived_from="s1", derived_from_gen=0),
           act(1, 12, "write", obj="s1", kind="slate", is_code=True, derived_from="s1", derived_from_gen=1)]
    ev += [prog(g, "s1", 1, reactions=3) for g in (2, 3)]
    ev += [act(g, 1, "run", obj="s1", inherited=True, author_gen=1) for g in (2, 3, 4)]
    ev += [act(5, 1, "write", obj="s3", kind="slate", derived_from="s1", derived_from_gen=1)]
    m = run_metrics(ev)
    assert m["longest_chain"] == 3  # s1@0 -> s1@1 (the same-life rewrite keeps the link) -> s3@5
    assert m["improved_derivations"] == 1  # s1 as rewritten in life 1 makes 3 per run, up from 0.5
    assert m["reused_slates"] == 1
    table = {(r["slate"], r["written"]): r for r in program_table(ev)}
    assert table[("s1", 0)]["made_per_run"] == 0.5 and table[("s1", 1)]["lives"] == 2


def test_verdicts():
    rows = lambda xs: [{"frontier": x} for x in xs]  # noqa: E731
    assert "RATCHET SIGNAL" in ratchet_verdict(rows([1, 3, 6, 9]), rows([1, 2, 3, 4]))
    assert "no ratchet" in ratchet_verdict(rows([1, 3, 6, 9]), rows([1, 3, 6, 9]))
    widening = [(rows([1, 3, 6, 9]), rows([1, 2, 3, 4 + d])) for d in (0, 1, -1)]
    assert aggregate_verdict(widening).endswith("verdict: RATCHET")
    noise = [(rows([1, 3, 5, 5]), rows([1, 2, 5, 6])), (rows([1, 2, 5, 6]), rows([1, 3, 5, 5]))]
    assert aggregate_verdict(noise).endswith("verdict: NO RATCHET")
    assert "ceiling" in ceiling_warning(rows([20]), rows([21]), 25)
    assert ceiling_warning(rows([5]), rows([6]), 25) == ""
