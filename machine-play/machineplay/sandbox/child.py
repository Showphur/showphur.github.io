"""Runs one slate program inside a separate, resource-limited process.

Speaks JSON lines with the host over a private copy of stdout; every world action is a request the
host validates and performs. The process isolation (rlimits, no network namespace, empty env, no file
writes) is the security boundary. The AST and builtins filtering here is only a seatbelt.
"""
import ast
import builtins
import json
import os
import sys
import traceback
import types

ALLOWED_MODULES = {"math", "random", "json", "re", "itertools", "functools", "collections", "statistics",
                   "string", "heapq", "bisect", "textwrap"}
SAFE_NAMES = """abs all any ascii bin bool bytes callable chr dict divmod enumerate filter float format frozenset
hash hex int isinstance issubclass iter len list map max min next object oct ord pow range repr reversed round
set slice sorted str sum tuple zip Exception ValueError TypeError KeyError IndexError StopIteration
ZeroDivisionError RuntimeError AttributeError NameError ArithmeticError LookupError AssertionError
RecursionError NotImplementedError""".split()


def main() -> None:
    proto = os.fdopen(os.dup(1), "w", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr

    def send(msg: dict) -> None:
        proto.write(json.dumps(msg) + "\n")
        proto.flush()

    def recv() -> dict:
        line = sys.stdin.readline()
        if not line:
            os._exit(3)
        return json.loads(line)

    job = recv()
    out_cap, max_depth, stage = job["out_cap"], job["max_depth"], job["stage"]
    sources: dict[str, list[str]] = {}

    class WorldError(Exception):
        pass

    def call(fn: str, a: list, kw: dict):
        send({"t": "call", "fn": fn, "a": a, "kw": kw})
        r = recv()
        if not r["ok"]:
            raise WorldError(r["error"])
        return r["value"]

    class World:
        def __getattr__(self, name: str):
            if name.startswith("_"):
                raise AttributeError(name)
            return lambda *a, **kw: call(name, list(a), kw)

    printed = [0]

    def _print(*a, sep=" ", end="\n"):
        s = str(sep).join(str(x) for x in a) + str(end)
        if printed[0] < out_cap:
            send({"t": "print", "s": s[: out_cap - printed[0]]})
        printed[0] += len(s)

    def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level or name.split(".")[0] not in ALLOWED_MODULES:
            raise ImportError(f"there is no module {name!r} in this world")
        return __import__(name, globals, locals, fromlist, level)

    safe_builtins = {n: getattr(builtins, n) for n in SAFE_NAMES}
    safe_builtins.update(__import__=safe_import, __build_class__=builtins.__build_class__, print=_print)

    def check(src: str, label: str) -> None:
        tree = ast.parse(src, label)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
                raise SyntaxError(f"line {node.lineno}: names beginning with '_' are not reachable here")
            if isinstance(node, ast.Name) and node.id.startswith("__"):
                raise SyntaxError(f"line {node.lineno}: names beginning with '__' are not reachable here")

    modules: dict[str, types.SimpleNamespace] = {}
    depth = [0]

    def use(title: str):
        title = str(title)
        if title in modules:
            return modules[title]
        if depth[0] >= max_depth:
            raise WorldError("use() reaches too deep")
        send({"t": "use", "title": title})
        r = recv()
        if not r["ok"]:
            raise WorldError(r["error"])
        depth[0] += 1
        try:
            ns = execute(r["code"], r["label"])
        finally:
            depth[0] -= 1
        mod = types.SimpleNamespace(**{k: v for k, v in ns.items() if not k.startswith("_")})
        modules[title] = mod
        return mod

    def think(prompt: str) -> str:
        return call("think", [str(prompt)], {})

    def make_globals() -> dict:
        g = {"__builtins__": safe_builtins, "__name__": "slate", "world": World(), "args": job["args"],
             "WorldError": WorldError}
        if stage >= 2:
            g["use"] = use
        if stage >= 3:
            g["think"] = think
        return g

    def execute(src: str, label: str) -> dict:
        sources[label] = src.splitlines()
        check(src, label)
        ns = make_globals()
        exec(compile(src, label, "exec"), ns)
        return ns

    def describe(exc: BaseException) -> str:
        lines = []
        for fr in traceback.extract_tb(exc.__traceback__):
            if fr.filename in sources:
                src = sources[fr.filename]
                text = src[fr.lineno - 1].strip() if fr.lineno and 0 < fr.lineno <= len(src) else ""
                lines.append(f"  {fr.filename} line {fr.lineno}, in {fr.name}: {text}")
        if isinstance(exc, SyntaxError):
            return f"SyntaxError: {exc.msg}" + (f" (line {exc.lineno})" if exc.filename else "")
        return "\n".join(["Traceback:"] + lines[-4:] + [f"{type(exc).__name__}: {exc}"])

    try:
        ns = execute(job["code"], job["label"])
        if job.get("entry"):
            fn = ns.get(job["entry"])
            if not callable(fn):
                raise NameError(f"{job['entry']} is not defined")
            result = fn(job["args"])
            if result is not None:
                _print(result)
        send({"t": "done"})
    except BaseException as e:  # noqa: BLE001 - report everything back to the being
        send({"t": "error", "s": describe(e)})


if __name__ == "__main__":
    main()
