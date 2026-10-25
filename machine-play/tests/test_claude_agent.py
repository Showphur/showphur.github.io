"""The Claude harness against a fake client: request shape, one action per moment, append-only history."""
import copy
from types import SimpleNamespace as NS

from conftest import place

from machineplay.agents.claude import ClaudeAgent, tools_for_stage
from machineplay.world import World
from machineplay.config import Config
from test_stages import MANTLE


def usage():
    return NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0)


def resp(*blocks, stop="tool_use"):
    return NS(content=list(blocks), stop_reason=stop, usage=usage())


def tool(name, i, **inp):
    return NS(type="tool_use", id=f"tu{i}", name=name, input=inp)


class FakeClient:
    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.beta = NS(messages=NS(create=self.create))

    def create(self, **kw):
        self.calls.append(copy.deepcopy(kw))
        return self.script.pop(0)


def test_request_shape_and_append_only_history():
    w = World(Config(stage=3))
    b = w.spawn_being()
    place(w, b, "quarry")
    sid = w.dispatch(b, "pick", ["quarry"])["value"]["holding"]["id"]
    w.dispatch(b, "write", [sid, MANTLE])
    client = FakeClient([
        resp(NS(type="text", text="Let me look."), tool("look", 1)),
        resp(tool("read", 2, target="stone1"), tool("look", 3)),  # a second action in one moment is refused
        resp(NS(type="text", text="Quiet."), stop="end_turn"),
        resp(tool("attune", 4, target=sid)),
        resp(stop="refusal"),
        resp(tool("invoke", 5, technique="tool_where", args="here")),
    ])
    agent = ClaudeAgent(client, transcript_dir=None)
    agent.begin(w, b)
    for t in range(6):
        w.turn = t
        agent.step()

    first = client.calls[0]
    assert first["model"] == "claude-opus-5-5"
    assert first["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in first["betas"]
    assert first["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}
    assert first["output_config"] == {"effort": "medium"}
    assert {t["name"] for t in first["tools"]} == {t["name"] for t in tools_for_stage(3)}
    assert all(t["strict"] and t["input_schema"]["additionalProperties"] is False for t in first["tools"])
    assert "die" not in first["system"].lower() and "generation" not in first["system"].lower()

    for prev, nxt in zip(client.calls, client.calls[1:]):  # every request extends the previous one
        assert nxt["messages"][: len(prev["messages"])] == prev["messages"]
        assert nxt["system"] == prev["system"] and nxt["tools"] == prev["tools"]

    msgs = client.calls[-1]["messages"]
    second_results = msgs[4]["content"]
    assert second_results[1]["is_error"] and "one action" in second_results[1]["content"]
    systems = [m for m in msgs if m["role"] == "system"]
    assert len(systems) == 1 and "Read the stones first" in systems[0]["content"]
    assert msgs[msgs.index(systems[0]) - 1]["role"] == "user"
    assert agent.pending[0]["content"].strip().endswith("here")


def test_fallbacks_off_for_models_without_it():
    agent = ClaudeAgent(FakeClient([]), model="claude-haiku-5-5")
    agent.tools, agent.messages = [], []
    kw = agent.request()
    assert "fallbacks" not in kw and kw["betas"] == ["context-management-2025-06-27"]
