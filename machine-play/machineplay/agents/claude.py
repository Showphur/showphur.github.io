"""A being whose mind is a Claude model. One API call per deliberation, at most one action per call.

The history is append-only (per-turn status rides in the user turn, mantle words arrive as an appended system
message), so thinking blocks stay valid and the prompt cache keeps hitting. Old tool results are trimmed
server-side by context editing rather than by rewriting history.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import Agent

SYSTEM_PROMPT = """You are a being in a three-dimensional world. Nobody has given you a task, and there is nothing you are required to do. Explore, experiment, make things, and follow your own curiosity wherever it leads.

You perceive and act only through your tools, one action per moment. Positions are in metres: x and y run along the ground, z is height."""

FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}


def _tool(name: str, description: str, **props: dict) -> dict:
    return {"name": name, "description": description, "strict": True,
            "input_schema": {"type": "object", "properties": props, "required": list(props),
                             "additionalProperties": False}}


STR = {"type": "string"}
NUM = {"type": "number"}


def tools_for_stage(stage: int) -> list[dict]:
    tools = [
        _tool("look", "Look around: everything within about 10 m, nearest first."),
        _tool("inspect", "Examine something within a few metres closely.", target=STR),
        _tool("go", "Walk toward a point on the ground (at most 6 m per moment).", x=NUM, y=NUM),
        _tool("approach", "Walk toward something you can see, stopping within reach (at most 6 m per moment).",
              target=STR),
        _tool("pick", "Pick up something within reach. You can hold one thing at a time.", target=STR),
        _tool("drop", "Set down what you are holding."),
        _tool("put", "Place what you are holding onto or into something within reach.", target=STR),
        _tool("combine", "Press two cubes together. Both must be within reach or in your hand.", a=STR, b=STR),
        _tool("read", "Read the writing on a stone or slate within reach.", target=STR),
        _tool("write", "Write on a stone or slate within reach, replacing whatever was written there.",
              target=STR, text=STR),
    ]
    if stage >= 1:
        tools.append(_tool("run", "Run the engine. You must be within reach of it. `args` is passed to what runs.",
                           args=STR))
    if stage >= 3:
        tools.append(_tool("attune", "Take a mantle slate within reach to heart.", target=STR))
        tools.append(_tool("invoke", "Use a technique from the mantle you carry.", technique=STR, args=STR))
    return tools


class ClaudeAgent(Agent):
    name = "claude"

    def __init__(self, client: Any, model: str = "claude-opus-5-5", effort: str = "medium",
                 max_tokens: int = 16000, fallbacks: bool | None = None, transcript_dir: str | Path | None = None):
        self.client, self.model, self.effort, self.max_tokens = client, model, effort, max_tokens
        self.fallbacks = model in FALLBACK_MODELS if fallbacks is None else fallbacks
        self.transcript_dir = Path(transcript_dir) if transcript_dir else None

    def begin(self, world, body):
        super().begin(world, body)
        self.tools = tools_for_stage(world.cfg.stage)
        self.messages: list[dict] = []
        self.pending_system: str | None = None
        look = json.dumps(world.dispatch(body, "look", via="agent")["value"])
        self.pending: list[dict] = [{"type": "text", "text": f"You become aware of yourself.\n{self.status()}\nAround you: {look}"}]
        self._tx = None
        if self.transcript_dir:
            self.transcript_dir.mkdir(parents=True, exist_ok=True)
            self._tx = (self.transcript_dir / f"life_{world.gen:04d}.jsonl").open("w", encoding="utf-8")

    def status(self) -> str:
        me = self.world.a_me(self.body)
        held = me["holding"]["desc"] + f" ({me['holding']['id']})" if me["holding"] else "nothing"
        return f"[you stand at ({me['pos'][0]:.1f}, {me['pos'][1]:.1f}); holding: {held}]"

    def request(self) -> dict:
        kw: dict[str, Any] = dict(
            model=self.model, max_tokens=self.max_tokens, system=SYSTEM_PROMPT, tools=self.tools,
            messages=self.messages, tool_choice={"type": "auto", "disable_parallel_tool_use": True},
            thinking={"type": "adaptive", "display": "summarized"}, output_config={"effort": self.effort},
            cache_control={"type": "ephemeral"},
            context_management={"edits": [{"type": "clear_tool_uses_20250919"}]},
            betas=["context-management-2025-06-27"],
        )
        if self.fallbacks:
            kw["fallbacks"] = "default"
            kw["betas"].append("server-side-fallback-2026-07-01")
        return kw

    def step(self) -> None:
        self.messages.append({"role": "user", "content": self.pending})
        if self.pending_system:
            self.messages.append({"role": "system", "content": self.pending_system})
            self.pending_system = None
        resp = self.client.beta.messages.create(**self.request())
        u = resp.usage
        self.world.log.emit(ev="llm", gen=self.world.gen, turn=self.world.turn, stop=resp.stop_reason,
                            input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                            cache_read=getattr(u, "cache_read_input_tokens", None),
                            cache_write=getattr(u, "cache_creation_input_tokens", None))
        content = list(resp.content) or [{"type": "text", "text": "(a moment passes)"}]
        self.messages.append({"role": "assistant", "content": content})

        results = []
        for i, block in enumerate(b for b in content if getattr(b, "type", None) == "tool_use"):
            if i == 0:
                r = self.world.dispatch(self.body, block.name, (), dict(block.input), via="agent")
            else:
                r = {"ok": False, "error": "only one action fits in a moment"}
            text = json.dumps(r["value"]) if r["ok"] and not isinstance(r["value"], str) else (
                r["value"] if r["ok"] else r["error"])
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": text or "(nothing)",
                            "is_error": not r["ok"]})
            if block.name == "attune" and r["ok"] and r["value"]["mind"]:
                self.pending_system = ("Words you have taken to heart, from the mantle slate you attuned to. "
                                       "They are now part of how you think:\n" + r["value"]["mind"])
        self.pending = results + [{"type": "text", "text": self.status()}]
        if self._tx:
            self._tx.write(json.dumps({"turn": self.world.turn, "stop": resp.stop_reason,
                                       "assistant": [_dump(b) for b in content],
                                       "results": results}) + "\n")
            self._tx.flush()

    def end(self) -> None:
        if self._tx:
            self._tx.close()
        self.messages = []  # the mind is wiped


def _dump(block: Any) -> Any:
    return block.model_dump(exclude_none=True) if hasattr(block, "model_dump") else block


def make_think_fn(client: Any, model: str):
    """`think(prompt)` for programs (stage 3): a plain completion with no tools and no memory."""
    def think(prompt: str, max_tokens: int) -> tuple[str, int]:
        resp = client.messages.create(model=model, max_tokens=max_tokens, output_config={"effort": "low"},
                                      messages=[{"role": "user", "content": prompt}])
        if resp.stop_reason == "refusal":
            return "[silence]", resp.usage.output_tokens
        text = "".join(b.text for b in resp.content if b.type == "text")
        return text, resp.usage.input_tokens + resp.usage.output_tokens
    return think
