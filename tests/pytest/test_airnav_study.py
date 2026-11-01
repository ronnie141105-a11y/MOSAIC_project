"""Study provenance and dashboard jobs remain independent of mock traffic."""

import hashlib
import json
import time

from flask import Flask

from astra.dashboard.airnav_routes import build_airnav_blueprint
from astra.dashboard.legacy_flask_app import create_app
from astra.dashboard.store import CycleStore
from astra.interface.state_reader import StateReader
from astra.studies.airnav import CASE_SPECS, DEFAULT_DATA, csv_text, export_study, run_study
from astra.utils.config import ASTRAConfig


def test_observed_case_is_single_flight_and_has_prediction_evidence(tmp_path):
    result = run_study(case_specs=CASE_SPECS[:1])
    case = result["cases"][0]
    assert result["source"]["source_sha256"] == hashlib.sha256(DEFAULT_DATA.read_bytes()).hexdigest()
    assert result["source"]["raw_positions"] == 698
    assert case["summary"]["peak_aircraft"] == 1
    assert case["summary"]["conflict_pair_exposure_s"] == 0
    assert result["forecast_errors"]
    assert all(set(frame["provenance"]) <= {"HVN243"} for frame in case["frames"])
    export_study(result, tmp_path)
    restored = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert restored["source"] == result["source"]
    assert "horizontal_error_nm" in (tmp_path / "forecast_errors.csv").read_text()
    assert "observed" in csv_text(result, "cycles.csv")


def test_study_page_is_available_in_normal_dashboard_without_changing_simulator():
    config = ASTRAConfig()
    reader = StateReader.for_mock(config)
    reader.connect()
    reader.create_aircraft("TEST01", "A320", 10.9, 106.9, 270, 6000, 220)
    before = reader.list_aircraft()
    app = create_app(CycleStore(), config, reader=reader)
    client = app.test_client()
    assert client.get("/airnav").status_code == 200
    assert "AirNav case study" in client.get("/").text
    assert client.get("/api/airnav/status").json["data_available"] is True
    assert reader.list_aircraft() == before


def test_arrival_wave_comparison_preserves_synthetic_identity_and_spacing():
    result = run_study(case_specs=CASE_SPECS[1:])
    compressed, spaced = result["cases"]
    for case in result["cases"]:
        assert case["kind"] == "synthetic"
        assert case["summary"]["peak_aircraft"] == 4
        assert all(ac["callsign"].startswith("SYN") for frame in case["frames"] for ac in frame["aircraft"])
        for frame in case["frames"]:
            for callsign, provenance in frame["provenance"].items():
                assert provenance["synthetic"] is True
                assert provenance["source_callsign"] == "HVN243"
                assert provenance["shift_s"] == (int(callsign[3:]) - 1) * case["spacing_s"]
    assert compressed["summary"]["conflict_pair_exposure_s"] > 0
    assert spaced["summary"]["conflict_pair_exposure_s"] == 0
    assert compressed["summary"]["peak_complexity"] > spaced["summary"]["peak_complexity"]


def test_job_uses_worker_and_exports_only_allowed_assets(tmp_path, monkeypatch):
    import astra.dashboard.airnav_routes as routes
    fake = dict(schema_version=1, cases=[], forecast_errors=[])
    calls = []
    def study(path):
        calls.append(path)
        time.sleep(.04)
        return fake
    monkeypatch.setattr(routes, "run_study", study)
    app = Flask(__name__)
    app.register_blueprint(build_airnav_blueprint(result_path=tmp_path / "absent.json"))
    client = app.test_client()
    assert client.get("/api/airnav/results").status_code == 404
    assert client.post("/api/airnav/run").status_code == 202
    assert client.post("/api/airnav/run").status_code == 202
    deadline = time.monotonic() + 2
    while client.get("/api/airnav/status").json["status"] == "running" and time.monotonic() < deadline:
        time.sleep(.01)
    assert len(calls) == 1
    assert client.get("/api/airnav/results").json == fake
    assert client.get("/api/airnav/export/report.json").status_code == 200
    assert client.get("/api/airnav/export/cycles.csv").status_code == 200
    assert client.get("/api/airnav/export/secrets.json").status_code == 404


def test_missing_recording_reports_actionable_error(tmp_path):
    app = Flask(__name__)
    app.register_blueprint(build_airnav_blueprint(data_path=tmp_path / "missing.json", result_path=tmp_path / "none.json"))
    client = app.test_client()
    assert client.get("/api/airnav/status").json["data_available"] is False
    assert client.post("/api/airnav/run").status_code == 404
