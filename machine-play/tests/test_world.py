from conftest import place

from machineplay.chemistry import Chemistry
from machineplay.world import World


def ok(r):
    assert r["ok"], r
    return r["value"]


def test_chemistry_is_deterministic_and_layered():
    a, b = Chemistry(7), Chemistry(7)
    assert a.reactions == b.reactions
    assert Chemistry(8).reactions != a.reactions
    for (x, y), p in a.reactions.items():
        tp = a.substances[p].tier
        assert tp == max(a.substances[x].tier, a.substances[y].tier) + 1
    assert max(s.tier for s in a.substances.values()) >= 4


def test_pick_put_stack_and_reach(make_world):
    w, b = make_world(stage=1)
    cubes = [o for o in w.objects.values() if o.kind == "cube"][:2]
    r = w.dispatch(b, "pick", [cubes[0].id])
    if w.hdist(b.pos, cubes[0].pos) > w.cfg.reach:
        assert not r["ok"] and "out of reach" in r["error"]
    place(w, b, cubes[0].id)
    ok(w.dispatch(b, "pick", [cubes[0].id]))
    assert not w.dispatch(b, "pick", [cubes[1].id])["ok"]  # hands full
    place(w, b, cubes[1].id)
    w.objects[cubes[0].id].pos = list(b.pos)
    v = ok(w.dispatch(b, "put", [cubes[1].id]))
    assert v["pos"][2] == cubes[1].pos[2] + 0.5
    assert b.holding is None


def test_combine_reacts_or_reveals(make_world):
    w, b = make_world(stage=0)
    (x, y), product = next(iter(w.chem.reactions.items()))
    ca = w._spawn_cube(x, [5.0, 5.0])
    cb = w._spawn_cube(y, [5.3, 5.0])
    b.pos = [5.1, 5.0, 0.0]
    v = ok(w.dispatch(b, "combine", [ca.id, cb.id]))
    assert v["reacted"] and ca.id not in w.objects
    assert w.objects[v["result"]["id"]].substance == product
    # a non-reacting pair reveals traits that stay on the cubes
    elems = w.chem.elements()
    pair = next((p, q) for p in elems for q in elems if w.chem.react(p, q) is None)
    c1, c2 = w._spawn_cube(pair[0], [8.0, 8.0]), w._spawn_cube(pair[1], [8.2, 8.0])
    b.pos = [8.1, 8.0, 0.0]
    v = ok(w.dispatch(b, "combine", [c1.id, c2.id]))
    assert not v["reacted"] and c1.known and c2.known


def test_writing_limits(make_world):
    w, b = make_world(stage=1)
    place(w, b, "stone1")
    v = ok(w.dispatch(b, "write", ["stone1", "x" * 500]))
    assert v == {"written": 200, "truncated": True}
    place(w, b, "quarry")
    sid = ok(w.dispatch(b, "pick", ["quarry"]))["holding"]["id"]
    v = ok(w.dispatch(b, "write", [sid, "y" * 5000]))
    assert v["written"] == 4000


def test_quarry_is_limited_per_life(make_world):
    w, b = make_world(stage=1, blanks_per_life=1)
    place(w, b, "quarry")
    ok(w.dispatch(b, "pick", ["quarry"]))
    ok(w.dispatch(b, "drop"))
    assert not w.dispatch(b, "pick", ["quarry"])["ok"]
    w.end_life()
    assert w.blanks_left == 1


def test_inherited_use_wears_and_unused_slates_erode(make_world):
    w, b = make_world(stage=1, erosion_per_life=30, erosion_threshold=50, erosion_rate=0.5)
    place(w, b, "quarry")
    keep = ok(w.dispatch(b, "pick", ["quarry"]))["holding"]["id"]
    ok(w.dispatch(b, "write", [keep, "KEEP\nsome useful words here"]))
    ok(w.dispatch(b, "drop"))
    lose = ok(w.dispatch(b, "pick", ["quarry"]))["holding"]["id"]
    ok(w.dispatch(b, "write", [lose, "LOSE\nwords nobody will read again"]))
    ok(w.dispatch(b, "drop"))
    ok(w.dispatch(b, "read", [keep]))
    assert w.objects[keep].uses == 0  # reading your own writing leaves no wear
    w.kill(b)
    for _ in range(3):
        w.end_life()
        b = w.spawn_being()
        place(w, b, keep)
        ok(w.dispatch(b, "read", [keep]))
        w.kill(b)
    assert w.objects[keep].uses == 3 and w.objects[keep].integrity == 100
    assert w.objects[lose].integrity < 50 and "·" in w.objects[lose].text
    assert "worn" in w.desc(w.objects[keep])


def test_stage_gating(make_world):
    w, b = make_world(stage=0)
    assert "engine" not in w.objects
    assert not w.dispatch(b, "run", [""])["ok"]
    w, b = make_world(stage=3)
    assert not w.dispatch(b, "think", ["hi"])["ok"]  # programs only
    assert not w.dispatch(b, "nonexistent")["ok"]
    assert not w.dispatch(b, "_move", [1, 1])["ok"]


def test_snapshot_round_trip(make_world):
    w, b = make_world(stage=2)
    place(w, b, "stone2")
    ok(w.dispatch(b, "write", ["stone2", "hello"]))
    w.kill(b)
    w.end_life()
    w2 = World.from_dict(w.to_dict())
    assert w2.to_dict() == w.to_dict()


def test_transplant_marks_writing_as_inherited(make_world):
    w, b = make_world(stage=1)
    place(w, b, "stone1")
    ok(w.dispatch(b, "write", ["stone1", "an old note"]))
    snap = w.to_dict()
    fresh = World(w.cfg)
    fresh.transplant(snap)
    nb = fresh.spawn_being()
    place(fresh, nb, "stone1")
    assert ok(fresh.dispatch(nb, "read", ["stone1"])) == "an old note"
    assert fresh.objects["stone1"].uses == 1
