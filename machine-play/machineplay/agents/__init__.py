"""Minds. A mind is created at birth and discarded at death; nothing it holds survives except what its body
leaves in the world. Each `step()` is exactly one deliberation, the unit lifespans are measured in."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..world import Body, World


class Agent:
    name = "agent"

    def begin(self, world: "World", body: "Body") -> None:
        self.world, self.body = world, body

    def step(self) -> None:
        raise NotImplementedError

    def end(self) -> None:
        pass

    def act(self, fn: str, *args, **kwargs) -> dict:
        return self.world.dispatch(self.body, fn, args, kwargs, via="agent")
