"""Deterministic tick-stepping: the same program sequence from the same
starting state must produce identical simulated time and world outcomes.

In deterministic mode the game stays paused and time advances only through
explicit tick stepping (FactorioInstance.wait_ticks / settle), so wall-clock
scheduling, host load, and RCON latency cannot influence outcomes.
"""

import pytest

from fle.commons.cluster_ips import get_local_container_ips
from fle.env.instance import FactorioInstance
from fle.env.entities import Position
from fle.env.game_types import Prototype, Resource


@pytest.fixture(scope="module")
def det_instance():
    ips, _udp, tcp = get_local_container_ips()
    if not tcp:
        pytest.skip("No Factorio containers running")
    instance = FactorioInstance(
        address=ips[0],
        tcp_port=tcp[0],
        fast=True,
        deterministic=True,
        inventory={
            "burner-mining-drill": 2,
            "wooden-chest": 2,
            "coal": 50,
            "iron-plate": 10,
        },
    )
    yield instance
    # Leave the shared server in the state other test sessions expect.
    instance.set_speed_and_unpause(10)


def _game_tick(instance) -> int:
    return int(instance.rcon_client.send_command("/sc rcon.print(game.tick)"))


def _run_scenario(instance) -> dict:
    ns = instance.namespaces[0]
    instance.reset(reset_position=True)
    start_tick = _game_tick(instance)

    pos = ns.nearest(Resource.IronOre)
    ns.move_to(pos)
    drill = ns.place_entity(Prototype.BurnerMiningDrill, position=pos)
    ns.insert_item(Prototype.Coal, drill, quantity=10)
    chest = ns.place_entity(Prototype.WoodenChest, position=drill.drop_position)

    # 10 simulated seconds: exactly 600 ticks in deterministic mode.
    ns.sleep(10)

    chest_after = ns.get_entity(Prototype.WoodenChest, chest.position)
    drill_after = ns.get_entity(Prototype.BurnerMiningDrill, drill.position)

    return {
        "tick_delta": _game_tick(instance) - start_tick,
        "ore_pos": (pos.x, pos.y),
        "drill_status": str(drill_after.status),
        "chest_contents": dict(ns.inspect_inventory(entity=chest_after)),
        "player_inventory": dict(ns.inspect_inventory()),
    }


def test_game_stays_paused(det_instance):
    paused = det_instance.rcon_client.send_command(
        "/sc rcon.print(tostring(game.tick_paused))"
    )
    assert paused == "true"


def test_advance_ticks_is_exact(det_instance):
    before = _game_tick(det_instance)
    det_instance.game_control.advance_ticks(123)
    after = _game_tick(det_instance)
    assert after - before == 123


def test_sleep_advances_exact_ticks(det_instance):
    ns = det_instance.namespaces[0]
    before = _game_tick(det_instance)
    ns.sleep(2)
    after = _game_tick(det_instance)
    assert after - before == 120


def test_identical_replay(det_instance):
    first = _run_scenario(det_instance)
    second = _run_scenario(det_instance)
    assert first == second


def test_production_is_tick_driven(det_instance):
    """Drill output depends only on simulated ticks, not wall clock."""
    result = _run_scenario(det_instance)
    # The drill mined into the chest for 600 ticks; ore must have arrived
    # (the exact count is asserted stable by test_identical_replay).
    assert result["tick_delta"] > 600
    assert result["chest_contents"].get("iron-ore", 0) > 0
