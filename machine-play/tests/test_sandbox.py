from conftest import place

from machineplay.sandbox import run_program


def slate_on_engine(w, b, text):
    place(w, b, "quarry")
    sid = w.dispatch(b, "pick", ["quarry"])["value"]["holding"]["id"]
    w.dispatch(b, "write", [sid, text])
    place(w, b, "engine")
    assert w.dispatch(b, "put", ["engine"])["ok"]
    return sid


def test_engine_runs_slate_as_the_beings_body(make_world):
    w, b = make_world(stage=1)
    slate_on_engine(w, b, "# HELLO\nme = world.me()\nprint('at', me['pos'][0] > 0, args)")
    r = w.dispatch(b, "run", ["xyz"])
    assert r["ok"] and r["value"].strip() == "at True xyz"


def test_limits_hold(make_world):
    w, b = make_world(stage=1, run_cpu_seconds=1, run_max_calls=20, run_output_chars=50)
    assert run_program(w, b, "while True: pass").error == "killed"
    assert run_program(w, b, "while True: world.me()").error == "call limit"
    assert "ImportError" in run_program(w, b, "import os").output
    assert "not reachable" in run_program(w, b, "().__class__.__bases__").output
    assert "NameError" in run_program(w, b, "open('/etc/passwd')").output
    assert "NameError" in run_program(w, b, "eval('1')").output
    r = run_program(w, b, "print('x' * 500)")
    assert len(r.output) < 120
    r = run_program(w, b, "try:\n  world.pick('nope')\nexcept WorldError as e:\n  print('caught', e)")
    assert r.ok and r.output.startswith("caught")


def test_program_actions_are_logged_as_program(make_world):
    from machineplay.eventlog import EventLog
    w, b = make_world(stage=1)
    w.log = EventLog(keep=True)
    run_program(w, b, "world.look()", label="s9")
    assert w.log.events[-1]["via"] == "program:s9"


def test_use_resolves_nearest_legible_slate_within_sight(make_world):
    w, b = make_world(stage=2)
    place(w, b, "quarry")
    lib = w.dispatch(b, "pick", ["quarry"])["value"]["holding"]["id"]
    w.dispatch(b, "write", [lib, "# MATHS\ndef double(x):\n    return 2 * x\n"])
    w.dispatch(b, "drop")
    r = run_program(w, b, "m = use('MATHS')\nprint(m.double(21))")
    assert r.ok and r.output.strip() == "42"
    assert "no legible slate" in run_program(w, b, "use('MISSING')").output
    b.pos = [0.0, 0.0, 0.0]
    if w.hdist(b.pos, w.objects[lib].pos) > w.cfg.look_radius:
        assert not run_program(w, b, "use('MATHS')").ok


def test_use_absent_before_stage_2(make_world):
    w, b = make_world(stage=1)
    assert "NameError" in run_program(w, b, "use('X')").output


def test_think_is_budgeted(make_world):
    w, b = make_world(stage=3, think_tokens_per_life=15)
    assert run_program(w, b, "print(think('hello'))").output.strip() == "[silence]"
    w.think_fn = lambda prompt, n: (prompt.upper(), 10)
    assert run_program(w, b, "print(think('hello'))").output.strip() == "HELLO"
    run_program(w, b, "think('a')")
    assert run_program(w, b, "print(think('again'))").output.strip() == "[silence]"
