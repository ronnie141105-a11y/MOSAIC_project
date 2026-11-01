"""Serve the ASTRA planning page, Scenario Builder, and airport monitor."""

import logging
import os
import threading
from typing import Optional

from flask import Flask

from astra.dashboard.routes import build_blueprint
from astra.dashboard.scenario_routes import build_scenario_blueprint
from astra.dashboard.store import CycleStore
from astra.interface.state_reader import StateReader
from astra.pipeline import Pipeline
from astra.utils.config import ASTRAConfig
from astra.utils.logger import get_logger

_LOG = get_logger("astra.dashboard")

#: Where the Scenario Builder page saves/loads named scenarios. Kept
#: separate from `scenarios/*.scn` (the BlueSky-format demo files) so
#: the builder's JSON files never collide with those.
_DEFAULT_SCENARIOS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "scenarios", "builder"
)


def create_app(
    store: CycleStore,
    config: ASTRAConfig,
    reader: Optional[StateReader] = None,
    scenarios_dir: str = _DEFAULT_SCENARIOS_DIR,
    pipeline: Optional[Pipeline] = None,
) -> Flask:
    """Build the Flask app: register the dashboard's (and, if a `reader`
    is given, the Scenario Builder's) blueprints.

    Args:
        store: The `CycleStore` the poll loop publishes cycles into.
        config: The running `ASTRAConfig`.
        reader: The live `StateReader` the poll loop is reading from.
            Optional and defaults to `None` for backwards compatibility
            (existing callers/tests that only need the read-only `/state`
            endpoint). When given, the Scenario Builder's `/scenario*`
            routes and its `/scenario` page are also registered.
        scenarios_dir: Where saved Scenario Builder scenarios live.
        pipeline: The same `Pipeline`/`AsyncPipeline` instance the poll
            loop is running cycles through, if any. When given (and
            `reader` is also given), every Scenario Builder action that
            replaces the traffic wholesale (loading a saved scenario,
            clearing the sim, loading an operational preset) also calls
            `pipeline.reset()` -- see that method's own docstring for
            the stale-track bug this fixes. Safe to omit for callers
            that only need read-only access or don't run a live
            `Pipeline` alongside this `reader`.

    Returns:
        A configured `Flask` app, not yet running.
    """
    dashboard_dir = os.path.dirname(__file__)
    app = Flask(__name__, template_folder=dashboard_dir, static_folder=dashboard_dir)
    app.register_blueprint(build_blueprint(store, config))
    from astra.dashboard.airnav_routes import build_airnav_blueprint
    app.register_blueprint(build_airnav_blueprint())
    from astra.dashboard.vvts_case_routes import build_vvts_case_blueprint
    app.register_blueprint(build_vvts_case_blueprint())
    if reader is not None:
        if config.airspace_profile != 'hcm_fir' and scenarios_dir == _DEFAULT_SCENARIOS_DIR:
            scenarios_dir = os.path.join(scenarios_dir, config.airspace_profile)
        app.register_blueprint(build_scenario_blueprint(reader, scenarios_dir, pipeline=pipeline, config=config))
        if reader.is_mock and config.airspace_profile == 'tsn_tma':
            from astra.airport.integration import AirportIntegration
            from astra.airport.routes import build_airport_blueprint
            integration = AirportIntegration(reader, config.airspace_profile)
            integration.connected_fir = True
            reader._connector.on_tick = integration.on_mock_tick
            reader._connector.on_reset = integration.reset
            reader._connector.airport_integration = integration
            app.airport_integration = integration
            app.register_blueprint(build_airport_blueprint(integration))
            from astra.dashboard.atfm_routes import build_atfm_blueprint
            app.register_blueprint(build_atfm_blueprint(reader, config, pipeline, store))
            from astra.dashboard.case_scenario_routes import build_case_scenario_blueprint
            app.register_blueprint(build_case_scenario_blueprint(reader, pipeline, store))
            from astra.dashboard.centre_routes import build_centre_blueprint
            app.register_blueprint(build_centre_blueprint(reader, config, integration, pipeline, store))
    # Werkzeug's own request logging is noisy at INFO for a 1 Hz poll
    # loop being hit by a 1 Hz frontend; the astra.dashboard logger above
    # already reports startup, so quiet the per-request access log.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    return app


def run_dashboard_in_background(
    store: CycleStore,
    config: ASTRAConfig,
    reader: Optional[StateReader] = None,
    pipeline: Optional[Pipeline] = None,
) -> threading.Thread:
    """Start the dashboard's Flask dev server in a daemon thread.

    `main.py` calls this once, then runs its poll loop in the main
    thread as before -- so `Ctrl+C` still stops the process the same
    way it always has (the dashboard thread is `daemon=True` and exits
    with the process, it is never joined).

    Args:
        store: The `CycleStore` the poll loop will publish cycles into.
        config: The running `ASTRAConfig` (`dashboard_host`/`dashboard_port`).
        reader: The same `StateReader` instance `main.py`'s poll loop
            calls `.poll()` on. Passed through so the Scenario Builder's
            routes (running on Flask's request thread) can create/edit/
            delete aircraft and pause/resume/step/reset the *same*
            simulation the poll loop is advancing -- not a copy of it.
            If omitted, the Scenario Builder page is not registered.
        pipeline: The same `Pipeline` instance `main.py`'s poll loop
            calls `.run_cycle()` on, if any. Passed through for the same
            reason as `reader` -- see `create_app`'s own docstring for
            what calling `pipeline.reset()` on scenario changes fixes.

    Returns:
        The started `threading.Thread` (already running), in case the
        caller wants to inspect `.is_alive()`.
    """
    app = create_app(store, config, reader=reader, pipeline=pipeline)

    def _serve() -> None:
        app.run(
            host=config.dashboard_host,
            port=config.dashboard_port,
            debug=False,
            use_reloader=False,
            threaded=True,
        )

    thread = threading.Thread(target=_serve, name="astra-dashboard", daemon=True)
    thread.start()
    _LOG.info(
        "Dashboard live at http://%s:%d/ (updates every %.1fs)",
        config.dashboard_host,
        config.dashboard_port,
        config.poll_interval_s,
    )
    return thread
