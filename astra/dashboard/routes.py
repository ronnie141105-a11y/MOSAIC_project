"""Serve the planning page and latest simulation state."""

from flask import Blueprint, Response, jsonify, render_template, url_for

from astra.dashboard import serializers
from astra.dashboard.store import CycleStore
from astra.utils.config import ASTRAConfig


def build_blueprint(store: CycleStore, config: ASTRAConfig) -> Blueprint:
    """Build the dashboard's Flask `Blueprint`, bound to one store/config.

    A factory (rather than module-level routes) so `astra.dashboard.server`
    can construct a fresh app per `Pipeline`/`CycleStore` instance --
    important for `tests/test_dashboard.py`, which builds its own
    isolated store per test rather than sharing global state.

    Args:
        store: The `CycleStore` `main.py`'s poll loop publishes into.
        config: The running `ASTRAConfig` (for `poll_interval_s`,
            `separation_horizontal_nm`, and the Phase 8 display-cap
            fields, read only via `serializers`).

    Returns:
        A `flask.Blueprint` ready to register on an `Flask` app.
    """
    blueprint = Blueprint("dashboard", __name__)

    @blueprint.route("/")
    def index() -> str:
        """Serve the single-page HMI shell (map + table + timeline panels)."""
        from astra.centre import centre_point
        return render_template(
            "index.html",
            poll_interval_s=config.poll_interval_s,
            dashboard_host=config.dashboard_host,
            dashboard_port=config.dashboard_port,
            separation_horizontal_nm=config.separation_horizontal_nm,
            alert_min_complexity_score=config.dashboard_alert_min_complexity_score,
            airspace_profile=config.airspace_profile,
            prediction_horizons=config.prediction_horizons_min,
            max_horizon=config.max_prediction_horizon_min,
            control_view='approach' if config.airspace_profile=='tsn_tma' else '',
            connected_views=config.airspace_profile=='tsn_tma',
            handoff_boundary=dict(lat=centre_point()[0],lon=centre_point()[1],radius_nm=40),
            geo_manifest_url=(url_for('dashboard.airspace_geo',asset='manifest.json')
                              if config.airspace_profile!='hcm_fir' else url_for('static',filename='geo/manifest.json')),
        )

    @blueprint.route('/airspace')
    def airspace_info():
        if config.airspace_profile=='hcm_fir':return jsonify(id='hcm_fir',kind='fir')
        from astra.airspace import load_profile
        return jsonify(load_profile(config.airspace_profile))

    @blueprint.route('/airspace/geo/<asset>')
    def airspace_geo(asset):
        from astra.airspace import geo_asset
        try:return jsonify(geo_asset(config.airspace_profile,asset))
        except ValueError:return jsonify(error='Unknown profile geographic asset'),404

    @blueprint.route("/aircraft/trails")
    def aircraft_trails() -> Response:
        """Observed aircraft positions retained by the running simulation."""
        return jsonify(store.trails())

    @blueprint.route("/state")
    def state() -> Response:
        """Return the latest `DashboardSnapshot` as JSON.

        Polled by the frontend every `poll_interval_s` (design review
        OQ-5(B)) -- see `static/js/dashboard.js`.
        """
        payload = serializers.serialize_dashboard_snapshot(store.snapshot(), config)
        return jsonify(payload)

    return blueprint
