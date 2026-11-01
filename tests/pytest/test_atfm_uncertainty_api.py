"""API/CLI boundaries: uncertainty selection, limits, persistence and exports."""
import csv
import importlib.util
import json
from pathlib import Path

from flask import Flask
import pytest
from astra.dashboard import atfm_routes


class ImmediateThread:
    def __init__(self, target, **kwargs):
        self.target = target

    def start(self):
        self.target()


class ReplayStub:
    def __init__(self, *args):
        self.method = None
        self.flights = None

    def status(self):
        return {"active": self.method is not None, "method": self.method}

    def load(self, method, flights):
        self.method, self.flights = method, flights


def result_fixture():
    nominal = {"objective": 12, "total_delay_min": 7}
    summary = dict(method="GA_UNCERTAINTY_11", split="test", count=12,
                   mean_objective=20, worst_objective=30, risk_objective=22.5,
                   mean_total_delay_min=10, mean_airborne_holding_min=2,
                   mean_airborne_extra_min=3)
    return dict(
        runs={"GA_UNCERTAINTY_11": dict(
            metrics=nominal, flights=[{"id": "NOMINAL"}], plan=[0, 0],
            history=[dict(generation=0, objective=22.5, evaluations=5)],
            evaluations=5, search=dict(preparation_evaluations=2, total_evaluations=7))},
        uncertainty=dict(risk_weight=.25, eta_jitter_min=2, capacity_drop=1,
                         training_count=5, test_count=12,
                         training_seeds=[101, 102, 103, 104], test_seeds=[201],
                         training_realizations=[{"nominal": True}],
                         test_realizations=[{"noise_seed": 201}]),
        uncertainty_summary=[summary], stress=[dict(method="GA_UNCERTAINTY_11", noise_seed=201,
                                                    split="test", objective=20)],
        sensitivity=[], exact_checks=[], elapsed_s=.1)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MOSAIC_ATFM_RESULTS", str(tmp_path / "results.json"))
    monkeypatch.setattr(atfm_routes, "ATFMReplay", ReplayStub)
    monkeypatch.setattr(atfm_routes, "Thread", ImmediateThread)
    app = Flask(__name__)
    app.register_blueprint(atfm_routes.build_atfm_blueprint(None, None, None, None))
    return app.test_client()


@pytest.mark.parametrize("field,value", [
    ("mode", "other"), ("mode", None), ("mode", []),
    ("risk_weight", -.1), ("risk_weight", 1.1), ("risk_weight", True),
    ("risk_weight", float("nan")), ("risk_weight", float("inf")), ("risk_weight", "0.25"),
    ("eta_jitter_min", -1), ("eta_jitter_min", 10.1), ("eta_jitter_min", False),
    ("eta_jitter_min", float("-inf")),
    ("capacity_drop", -1), ("capacity_drop", 3), ("capacity_drop", 1.0),
    ("capacity_drop", True),
    ("max_evaluations", 49), ("max_evaluations", 20001),
    ("max_evaluations", 50.0), ("max_evaluations", None), ("max_evaluations", True),
    ("population", 3), ("population", True), ("generations", 201),
])
def test_invalid_configuration_rejected_before_search(client, monkeypatch, field, value):
    def unexpected(**kwargs):
        pytest.fail("Invalid request reached optimization")
    monkeypatch.setattr(atfm_routes, "uncertainty_experiment", unexpected)
    payload = dict(mode="uncertainty", population=4, generations=1)
    payload[field] = value
    assert client.post("/api/atfm/run", json=payload).status_code == 400
    assert client.get("/api/atfm/status").json["status"] == "idle"


def test_uncertainty_dispatch_persistence_and_separate_exports(client, monkeypatch, tmp_path):
    calls = []
    def fake(**kwargs):
        calls.append(kwargs)
        return result_fixture()
    monkeypatch.setattr(atfm_routes, "uncertainty_experiment", fake)
    response = client.post("/api/atfm/run", json=dict(
        mode="uncertainty", population=4, generations=1, max_evaluations=50,
        risk_weight=1, eta_jitter_min=0, capacity_drop=2))
    assert response.status_code == 202
    assert calls == [dict(population=4, generations=1, max_evaluations=50,
                          risk_weight=1, eta_jitter_min=0, capacity_drop=2)]
    assert client.get("/api/atfm/status").json["status"] == "done"
    saved = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert saved["uncertainty_summary"][0]["worst_objective"] == 30
    nominal = client.get("/api/atfm/export.csv")
    separate = client.get("/api/atfm/uncertainty.csv")
    samples = client.get("/api/atfm/uncertainty-realizations.json")
    assert nominal.status_code == separate.status_code == samples.status_code == 200
    assert "mean_objective" not in nominal.get_data(as_text=True)
    assert "worst_objective" in separate.get_data(as_text=True)
    assert samples.json["test_realizations"] == [{"noise_seed": 201}]
    assert client.post("/api/atfm/replay", json={"method": "GA_UNCERTAINTY_11"}).status_code == 200
    assert client.application.blueprints["atfm"].atfm_replay.flights == [{"id": "NOMINAL"}]


def test_uncertainty_defaults_are_bounded(client, monkeypatch):
    calls = []
    monkeypatch.setattr(atfm_routes, "uncertainty_experiment",
                        lambda **kwargs: calls.append(kwargs) or result_fixture())
    assert client.post("/api/atfm/run", json={"mode": "uncertainty"}).status_code == 202
    assert calls == [dict(population=40, generations=60, max_evaluations=6000,
                          risk_weight=.25, eta_jitter_min=2, capacity_drop=1)]


def test_legacy_default_dispatch_and_export_compatibility(client, monkeypatch):
    calls = []
    def fake(**kwargs):
        calls.append(kwargs)
        return {"runs": {"OLD": {"metrics": {"objective": 12}, "evaluations": 1}}}
    monkeypatch.setattr(atfm_routes, "experiment", fake)
    assert client.post("/api/atfm/run", json={}).status_code == 202
    assert calls == [dict(population=60, generations=100)]
    assert client.get("/api/atfm/export.csv").status_code == 200
    assert client.get("/api/atfm/uncertainty.csv").status_code == 404
    assert client.get("/api/atfm/uncertainty-realizations.json").status_code == 404


def test_cli_uncertainty_exports_held_out_records(tmp_path, monkeypatch, capsys):
    path = Path(__file__).resolve().parents[2] / "scripts" / "run_atfm_experiment.py"
    spec = importlib.util.spec_from_file_location("atfm_cli_under_test", path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    calls = []
    monkeypatch.setattr(cli, "uncertainty_experiment",
                        lambda **kwargs: calls.append(kwargs) or result_fixture())
    monkeypatch.setattr("sys.argv", ["run_atfm_experiment", "--uncertainty", "--out", str(tmp_path),
                                     "--population", "4", "--generations", "1",
                                     "--max-evaluations", "50"])
    cli.main()
    assert calls == [dict(population=4, generations=1, max_evaluations=50,
                          risk_weight=.25, eta_jitter_min=2, capacity_drop=1)]
    with (tmp_path / "uncertainty_summary.csv").open(encoding="utf-8-sig", newline="") as source:
        summary = list(csv.DictReader(source))
    assert summary[0]["split"] == "test"
    assert summary[0]["worst_objective"] == "30"
    assert (tmp_path / "held_out_realizations.csv").exists()
    assert not (tmp_path / "eta_stress.csv").exists()
    assert (tmp_path / "uncertainty_realizations.json").exists()
    with (tmp_path / "convergence.csv").open(encoding="utf-8-sig", newline="") as source:
        assert list(csv.DictReader(source))[0]["total_evaluations"] == "7"
    assert "Held-out uncertainty evaluation" in capsys.readouterr().out
