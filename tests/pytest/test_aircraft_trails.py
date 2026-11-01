"""Observed track history survives browser reconnects within a simulation session."""
from types import SimpleNamespace

from astra.dashboard.store import CycleStore
from astra.dashboard.legacy_flask_app import create_app
from astra.interface.traffic_state import AircraftState, TrafficSnapshot
from astra.utils.config import ASTRAConfig


def publish(store, time_s, aircraft):
    snapshot = TrafficSnapshot(time_s, {
        callsign: AircraftState(callsign, lat, 106.0, 8000, 200, 90, 0, "A320", time_s)
        for callsign, lat in aircraft.items()
    })
    store.update(SimpleNamespace(snapshot=snapshot))


def test_trails_endpoint_retains_prior_positions_on_a_new_page_request():
    store = CycleStore()
    publish(store, 0, {"A": 10.0})
    publish(store, 1, {"A": 10.001})
    publish(store, 1, {"A": 10.001})  # paused frame does not duplicate a point
    app = create_app(store, ASTRAConfig())
    first = app.test_client().get("/aircraft/trails").json
    second = app.test_client().get("/aircraft/trails").json
    assert first == second
    assert [p["time_s"] for p in first["paths"]["A"]] == [0, 1]
    assert [p["lat"] for p in first["paths"]["A"]] == [10.0, 10.001]


def test_trails_drop_departed_aircraft_and_clear_on_scenario_reset():
    store = CycleStore()
    publish(store, 10, {"A": 10.0, "B": 10.2})
    publish(store, 11, {"A": 10.001})
    assert set(store.trails()["paths"]) == {"A"}
    store.clear_trails()
    publish(store, 0, {"A": 11.0})
    assert [p["lat"] for p in store.trails()["paths"]["A"]] == [11.0]
    assert store.trails()["generation"] == 1
