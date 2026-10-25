import pytest

from machineplay.config import Config
from machineplay.world import World


def place(world, body, oid):
    """Teleport a body next to an object (tests only)."""
    o = world.objects[oid]
    body.pos = [o.pos[0] + 0.5, o.pos[1], 0.0]


@pytest.fixture
def make_world():
    def make(**kw):
        w = World(Config(**kw))
        return w, w.spawn_being()
    return make
