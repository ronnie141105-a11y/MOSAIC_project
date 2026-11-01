"""Local AirNav study jobs, isolated from the active mock simulation."""

import hashlib
import json
from pathlib import Path
from threading import Lock, Thread

from flask import Blueprint, Response, jsonify, render_template

from astra.studies.airnav import DEFAULT_DATA, csv_text, run_study
from astra.interface.airnav_replay import REPLAY_VERSION


def build_airnav_blueprint(data_path=DEFAULT_DATA, result_path=None):
    bp = Blueprint("airnav", __name__)
    lock = Lock()
    state = dict(status="idle", result=None, error=None)
    data_path = Path(data_path)
    result_path = Path(result_path) if result_path else Path(__file__).resolve().parents[2] / "output/airnav_case_study/report.json"
    if result_path.exists() and data_path.exists():
        try:
            saved = json.loads(result_path.read_text(encoding="utf-8"))
            if (saved.get("schema_version") == 1 and saved["source"].get("replay_version") == REPLAY_VERSION
                    and saved["source"]["source_sha256"] == hashlib.sha256(data_path.read_bytes()).hexdigest()):
                state.update(status="done", result=saved)
        except (OSError, ValueError, KeyError, TypeError):
            pass

    @bp.get("/airnav")
    def page():
        return render_template("airnav.html")

    @bp.get("/api/airnav/status")
    def status():
        with lock:
            return jsonify(status=state["status"], error=state["error"],
                           has_result=state["result"] is not None, data_available=data_path.exists())

    @bp.post("/api/airnav/run")
    def run():
        with lock:
            if state["status"] == "running":
                return jsonify(status="running"), 202
            if not data_path.exists():
                return jsonify(error="The saved AirNav recording is unavailable"), 404
            state.update(status="running", error=None)

        def work():
            try:
                result = run_study(data_path)
            except Exception as exc:
                with lock:
                    state.update(status="failed", error=str(exc))
                return
            with lock:
                state.update(status="done", result=result)

        Thread(target=work, name="airnav-case-study", daemon=True).start()
        return jsonify(status="running"), 202

    @bp.get("/api/airnav/results")
    def results():
        with lock:
            result = state["result"]
        if result is None:
            return jsonify(error="Run the case study first"), 404
        return jsonify(result)

    @bp.get("/api/airnav/export/<asset>")
    def export(asset):
        if asset not in ("report.json", "cycles.csv", "forecast_errors.csv"):
            return jsonify(error="Unknown study export"), 404
        with lock:
            result = state["result"]
        if result is None:
            return jsonify(error="No study result is available"), 404
        content = json.dumps(result, indent=2, allow_nan=False) if asset == "report.json" else csv_text(result, asset)
        return Response(content, mimetype="application/json" if asset.endswith(".json") else "text/csv",
                        headers={"Content-Disposition": f'attachment; filename="airnav_{asset}"'})

    return bp
