"""Recorded-data integrity, causal recovery and coverage expiry contracts."""

from datetime import datetime, timezone
import json

import pytest

from astra.interface.airnav_replay import AirNavDataset, AirNavReplayConnector, ReplayPolicy
from astra.interface.connector_base import ConnectorProtocol
from astra.interface.state_reader import StateReader
from astra.studies.airnav import DEFAULT_DATA, forecast_errors
from astra.utils.config import ASTRAConfig


def position(second, **changes):
    row = dict(timestamp=f"2026-10-08T00:{second // 60:02}:{second % 60:02}+00:00",
               latitude=10.9, longitude=106.9, altitude=6000, groundSpeed=220,
               heading=270, verticalRate=-600, onGround=False)
    row.update(changes)
    return row


def dataset(rows):
    return AirNavDataset([dict(callsign="HVN243", aircraftType="A321", positions=rows)])


def test_offsets_are_normalized_to_utc_and_not_local_host_time():
    data = dataset([position(0, timestamp="2026-10-08T07:00:00+07:00")])
    point = data.points["HVN243"][0]
    assert point.utc == "2026-10-08T00:00:00+00:00"
    assert point.epoch_s == datetime(2026, 10, 8, tzinfo=timezone.utc).timestamp()


def test_null_fields_use_only_recent_past_and_preserve_zero():
    data = dataset([position(0, heading=0, verticalRate=0),
                    position(10, heading=None, altitude=None, verticalRate=None),
                    position(41, altitude=None), position(50, altitude=6100)])
    points = data.points["HVN243"]
    assert points[1].state.altitude_ft == 6000
    assert points[1].state.heading_deg == 0
    assert points[1].state.vertical_speed_fpm == 0
    assert points[1].field_sources["altitude"] == "carried"
    assert points[2].state is None  # A later valid altitude must not fill this gap.
    changed = dataset([position(0, heading=0, verticalRate=0),
                       position(10, heading=None, altitude=None, verticalRate=None),
                       position(50, altitude=10000)])
    assert changed.points["HVN243"][1].state == points[1].state


def test_ground_and_corrupt_positions_are_not_airborne_traffic():
    data = dataset([position(0, onGround=True), position(10, latitude=float("nan")),
                    position(20, longitude=181), position(30), position(40, altitude=38000)])
    assert data.quality["excluded_ground"] == 1
    assert data.quality["invalid_position_or_timestamp"] == 2
    assert data.quality["rejected_altitude"] == 1
    assert data.points["HVN243"][-1].state.altitude_ft == 6000
    assert data.points["HVN243"][-1].field_sources["altitude"] == "carried"


def test_replay_expires_gaps_is_finite_and_rejects_clearances():
    data = dataset([position(0), position(100)])
    replay = AirNavReplayConnector(data)
    assert isinstance(replay, ConnectorProtocol)
    replay.connect()
    assert len(replay.frame_at(10)[0]) == 1
    assert replay.frame_at(10)[1]["HVN243"]["position_kind"] == "extrapolated"
    assert len(replay.frame_at(31)[0]) == 0
    assert len(replay.frame_at(101)[0]) == 0
    with pytest.raises(RuntimeError, match="immutable"):
        replay.send_command("SPD HVN243 250")
    while not replay.finished:
        replay.poll()
    replay.poll()
    assert replay.latest_snapshot() is None
    assert not replay.has_active_node()


def test_shifted_aircraft_do_not_spawn_before_their_source_window():
    data = dataset([position(0), position(20)])
    replay = AirNavReplayConnector(data, offsets={"SYN001": ("HVN243", 30)})
    assert len(replay.frame_at(29)[0]) == 0
    snapshot, provenance = replay.frame_at(30)
    assert snapshot.get("SYN001").timestamp_s == 30
    assert provenance["SYN001"]["synthetic"] is True
    assert len(replay.frame_at(51)[0]) == 0


def test_reader_records_replay_as_non_mock_and_stops_at_eof():
    reader = StateReader.for_airnav(ASTRAConfig(), DEFAULT_DATA)
    reader.connect()
    assert reader.is_mock is False
    for _ in reader._connector.timeline:
        assert reader.poll() is not None
    assert reader.poll() is None
    assert reader._connector.finished


def test_csv_requires_identity_and_preserves_utc(tmp_path):
    path = tmp_path / "track.csv"
    path.write_text('"Date/Time (UTC)",Latitude,Longitude,Heading,"Altitude (ft)","Ground Speed (kts)","Vertical Speed (ft/min)",Source,Squawk\n'
                    '"2026-10-08 00:00:00",10.9,106.9,0,6000,220,0,ADS-B,4652\n', encoding="utf-8")
    with pytest.raises(ValueError, match="metadata"):
        AirNavDataset.load(path)
    data = AirNavDataset.load(path, callsign="HVN243", aircraft_type="A321")
    assert data.points["HVN243"][0].state.heading_deg == 0
    assert data.points["HVN243"][0].utc.endswith("+00:00")


def test_prediction_scores_actual_elapsed_time_and_reports_no_match():
    data = dataset([position(0), position(65, latitude=10.88, altitude=5350)])
    errors = forecast_errors(data.points["HVN243"], horizons_s=(30, 60, 300))
    assert len(errors) == 1
    assert errors[0]["requested_horizon_s"] == 60
    assert errors[0]["actual_horizon_s"] == 65
    assert errors[0]["altitude_error_ft"] == pytest.approx(0)  # 600 ft/min for 65 seconds.


def test_failed_payload_and_invalid_policy_fail_clearly(tmp_path):
    path = tmp_path / "failed.json"
    path.write_text(json.dumps(dict(success=False, flights=[])))
    with pytest.raises(ValueError, match="successful"):
        AirNavDataset.load(path)
    with pytest.raises(ValueError, match="positive"):
        ReplayPolicy(max_position_age_s=float("nan"))
