"""Host side of the engine: start the child process, serve its world calls, enforce every limit."""
from __future__ import annotations

import json
import os
import resource
import select
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..world import Body, World

CHILD = Path(__file__).with_name("child.py")
_unshare_ok: bool | None = None


@dataclass
class ProgramResult:
    output: str
    ok: bool
    calls: int
    error: str | None = None


def _isolation_prefix() -> list[str]:
    """Run without a network namespace when the kernel allows unprivileged user namespaces."""
    global _unshare_ok
    if os.environ.get("MACHINEPLAY_NO_UNSHARE"):
        return []
    if _unshare_ok is None:
        try:
            _unshare_ok = bool(shutil.which("unshare")) and subprocess.run(
                ["unshare", "-rn", "true"], capture_output=True, timeout=5).returncode == 0
        except (OSError, subprocess.SubprocessError):
            _unshare_ok = False
    return ["unshare", "-rn"] if _unshare_ok else []


def run_program(world: "World", body: "Body", code: str, args: str = "", entry: str | None = None,
                label: str = "slate", max_calls: int | None = None, author_gen: int = -1,
                kind: str = "engine") -> ProgramResult:
    """Run `code` as `body`. Every run is logged as one `program` event crediting the slate (and the life that
    wrote it) with its world calls and the reactions it caused."""
    reactions_before = world.reactions
    world._programs.append((label, author_gen))
    try:
        res = _run(world, body, code, args, entry, label, max_calls)
    finally:
        world._programs.pop()
    world.log.emit(ev="program", gen=world.gen, turn=world.turn, kind=kind, label=label,
                   slate=label.rsplit(":", 1)[-1], prog_gen=author_gen, actor=body.id, ok=res.ok, calls=res.calls,
                   reactions=world.reactions - reactions_before, error=res.error)
    return res


def _run(world: "World", body: "Body", code: str, args: str, entry: str | None, label: str,
         max_calls: int | None) -> ProgramResult:
    cfg = world.cfg
    max_calls = max_calls or cfg.run_max_calls
    mem = cfg.run_memory_mb * 1024 * 1024

    def limits() -> None:
        resource.setrlimit(resource.RLIMIT_CPU, (cfg.run_cpu_seconds, cfg.run_cpu_seconds + 1))
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
        resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))

    out: list[str] = []
    tail = ""  # how the program ended, if badly; never cut off by the output cap
    calls, ok, error = 0, True, None
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.Popen(_isolation_prefix() + [sys.executable, "-I", "-S", str(CHILD)],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                cwd=tmp, env={}, preexec_fn=limits)
        fd = proc.stdout.fileno()
        buf = b""

        def send(msg: dict) -> None:
            proc.stdin.write((json.dumps(msg) + "\n").encode())
            proc.stdin.flush()

        def recv() -> dict:
            nonlocal buf
            while b"\n" not in buf:
                ready, _, _ = select.select([fd], [], [], cfg.run_wall_seconds)
                if not ready:
                    raise TimeoutError
                chunk = os.read(fd, 65536)
                if not chunk:
                    raise EOFError
                buf += chunk
            line, buf = buf.split(b"\n", 1)
            return json.loads(line)

        try:
            send({"code": code, "args": args, "entry": entry, "label": label, "stage": cfg.stage,
                  "out_cap": cfg.run_output_chars, "max_depth": cfg.use_max_depth})
            while True:
                msg = recv()
                t = msg.get("t")
                if t == "print":
                    out.append(msg["s"])
                elif t == "call":
                    calls += 1
                    if calls > max_calls:
                        ok, error = False, "call limit"
                        tail = "[the engine shudders to a stop: too many motions]\n"
                        break
                    send(world.dispatch(body, str(msg["fn"]), msg.get("a") or [], msg.get("kw") or {},
                                        via=f"program:{label}"))
                elif t == "use":
                    calls += 1
                    send(_resolve_use(world, body, str(msg.get("title", ""))))
                elif t == "done":
                    break
                elif t == "error":
                    ok, error = False, msg["s"].splitlines()[-1][:200]
                    tail = msg["s"][-800:] + "\n"
                    break
        except TimeoutError:
            ok, error = False, "timeout"
            tail = "[the engine falls silent: it waited too long]\n"
        except (EOFError, BrokenPipeError):
            ok, error = False, "killed"
            tail = "[the engine overheats and stops]\n"
        finally:
            proc.kill()
            proc.wait()
            for f in (proc.stdin, proc.stdout):
                try:
                    f.close()
                except OSError:
                    pass

    text = "".join(out)
    if len(text) > cfg.run_output_chars:
        text = text[: cfg.run_output_chars] + "\n[...the rest is lost in the engine's noise]\n"
    return ProgramResult(text + tail, ok, calls, error)


def _resolve_use(world: "World", body: "Body", title: str) -> dict:
    if world.cfg.stage < 2:
        return {"ok": False, "error": "use() means nothing here"}
    slate = world.find_slate(body, title)
    world._extra = {}
    if slate is None:
        world.log.emit(ev="use", gen=world.gen, turn=world.turn, actor=body.id, title=title, found=False)
        return {"ok": False, "error": f"no legible slate titled {title!r} within sight"}
    world._touch(body, slate, "use")
    world.log.emit(ev="use", gen=world.gen, turn=world.turn, actor=body.id, title=title, found=True, **world._extra)
    return {"ok": True, "code": slate.text, "label": slate.id}
