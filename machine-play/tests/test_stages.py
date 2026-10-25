import pytest
from conftest import place

from machineplay.world import ActionError, parse_mantle

MANTLE = '''#!mantle WAYFINDER
## mind
Read the stones first. Keep notes on slates.
## code
def tool_where(args):
    """Say where I stand."""
    p = world.me()["pos"]
    return f"{p[0]:.0f},{p[1]:.0f} {args}"
'''


def test_frame_runs_on_charge_and_compounds_are_fuel(make_world):
    w, b = make_world(stage=2)
    fid = "frame1"
    place(w, b, "quarry")
    sid = w.dispatch(b, "pick", ["quarry"])["value"]["holding"]["id"]
    w.dispatch(b, "write", [sid, "# MARK\nprint(len(world.look()))"])
    place(w, b, fid)
    assert w.dispatch(b, "put", [fid])["ok"]
    w.frame_cycle()
    assert w.objects[fid].last_output == ""  # no charge yet
    (x, y), p = next((k, v) for k, v in w.chem.reactions.items() if w.chem.substances[v].tier == 1)
    cube = w._spawn_cube(p, b.pos[:2])
    assert w.dispatch(b, "pick", [cube.id])["ok"]
    r = w.dispatch(b, "put", [fid])
    assert r["ok"] and w.objects[fid].charge == w.cfg.frame_charge_per_tier
    w.frame_cycle()
    assert w.objects[fid].last_output.strip().isdigit()
    assert w.objects[fid].charge == w.cfg.frame_charge_per_tier - 1
    arm = w.bodies[f"arm-{fid}"]
    w._move(arm, 0.0, 0.0)
    assert w.hdist(arm.pos, w.objects[fid].pos) <= w.cfg.frame_tether + 1e-6


def test_parse_mantle():
    m = parse_mantle(MANTLE, 1500)
    assert m["mind"].startswith("Read the stones")
    assert m["tools"] == [{"name": "tool_where", "about": "Say where I stand."}]
    with pytest.raises(ActionError):
        parse_mantle("just words", 100)
    with pytest.raises(ActionError):
        parse_mantle("#!mantle\n## code\ndef tool_x(:\n", 100)


def test_attune_and_invoke(make_world):
    w, b = make_world(stage=3)
    place(w, b, "quarry")
    sid = w.dispatch(b, "pick", ["quarry"])["value"]["holding"]["id"]
    w.dispatch(b, "write", [sid, MANTLE])
    v = w.dispatch(b, "attune", [sid])["value"]
    assert v["techniques"][0]["name"] == "tool_where"
    w.objects[sid].text = "erased"  # what is taken to heart no longer depends on the slate
    r = w.dispatch(b, "invoke", ["tool_where", "ok"])
    assert r["ok"] and r["value"].strip().endswith("ok")
    assert not w.dispatch(b, "invoke", ["tool_nope", ""])["ok"]
    assert not w.dispatch(b, "attune", [sid])["ok"]  # one mantle per life
