"""
AEON Simulation - Aircraft Agent
Each aircraft is a state machine moving along a route.
"""
import math
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


class AircraftState(Enum):
    PARKED      = auto()   # at stand, engines off
    PUSHBACK    = auto()   # being pushed back (future)
    TAXIING     = auto()   # moving along taxiway
    HOLDING     = auto()   # stopped at holding point, waiting clearance
    LINING_UP   = auto()   # entered runway, lining up
    DEPARTED    = auto()   # left the map via RWY 25L end
    LANDED      = auto()   # touched down on RWY 25R
    ARRIVED     = auto()   # reached assigned stand


class AEONMode(Enum):
    ENGINE_ON   = "Engine ON"
    ENGINE_OFF  = "Engine OFF (TaxiBot)"
    ETAXI       = "E-Taxi"


# Speeds in SVG-units per second
# SVG viewBox ≈ 1421 wide ≈ real 3900m → 1 SVG unit ≈ 2.74m
SVG_SCALE = 2.74   # metres per SVG unit

SPEED_CONFIG = {
    AEONMode.ENGINE_ON: {
        'taxi_mps'   : 11.3,   # 22 kt
        'runway_mps' : 15.4,   # 30 kt (runway roll)
        'fuel_kgs'   : 0.080,  # kg/s both engines
    },
    AEONMode.ENGINE_OFF: {
        'taxi_mps'   : 2.6,    # 5 kt (TaxiBot)
        'runway_mps' : 15.4,
        'fuel_kgs'   : 0.012,  # APU only
    },
    AEONMode.ETAXI: {
        'taxi_mps'   : 3.6,    # 7 kt
        'runway_mps' : 15.4,
        'fuel_kgs'   : 0.018,
    },
}


@dataclass
class Aircraft:
    # Identity
    callsign   : str
    ac_type    : str            # e.g. "A321", "B787"
    operation  : str            # 'dep' | 'arr'
    stand_id   : str            # node id of assigned stand
    aeon_mode  : AEONMode       = AEONMode.ENGINE_ON

    # State
    state      : AircraftState  = AircraftState.PARKED
    route      : List[str]      = field(default_factory=list)
    seg_idx    : int            = 0     # current segment index in route
    seg_prog   : float          = 0.0  # 0.0 → 1.0 progress along segment

    # Position (SVG units)
    x          : float          = 0.0
    y          : float          = 0.0

    # Metrics
    taxi_time_s  : float        = 0.0
    fuel_kg      : float        = 0.0
    delay_s      : float        = 0.0
    hold_s       : float        = 0.0
    distance_svgu: float        = 0.0
    current_speed_mps: float    = 0.0  # current ground speed for both monitors
    flow_stand_hold_s: float    = 0.0

    # Trail for drawing
    trail      : List[Tuple[float,float]] = field(default_factory=list)
    TRAIL_LEN  : int            = 40

    # ATC clearance flags
    cleared_takeoff : bool      = False
    takeoff_roll_started: bool  = False
    cleared_cross   : bool      = False
    off_block_time_s: float     = 0.0
    ctot_s          : float     = 0.0
    atfm_off_block_s: float     = 0.0
    atfm_ctot_s    : float     = 0.0
    manual_route    : bool      = False

    def speed_svgu_per_s(self, on_runway: bool = False) -> float:
        cfg = SPEED_CONFIG[self.aeon_mode]
        mps = cfg['runway_mps'] if on_runway else cfg['taxi_mps']
        return mps / SVG_SCALE

    def fuel_rate_kgs(self) -> float:
        return SPEED_CONFIG[self.aeon_mode]['fuel_kgs']

    def is_moving(self) -> bool:
        return self.state == AircraftState.TAXIING

    def is_done(self) -> bool:
        return self.state in (AircraftState.DEPARTED, AircraftState.ARRIVED)

    def add_trail(self):
        self.trail.append((self.x, self.y))
        if len(self.trail) > self.TRAIL_LEN:
            self.trail.pop(0)

    def status_text(self) -> str:
        return self.state.name

    def aeon_label(self) -> str:
        return self.aeon_mode.value

    # Metrics summary
    def metrics(self) -> dict:
        return {
            'callsign'   : self.callsign,
            'type'       : self.ac_type,
            'op'         : self.operation,
            'aeon_mode'  : self.aeon_mode.name,
            'taxi_time_s': round(self.taxi_time_s, 1),
            'fuel_kg'    : round(self.fuel_kg, 2),
            'delay_s'    : round(self.delay_s, 1),
            'hold_s'     : round(self.hold_s, 1),
            'flow_stand_hold_s': round(self.flow_stand_hold_s, 1),
            'dist_svgu'  : round(self.distance_svgu, 0),
            'dist_m'     : round(self.distance_svgu * SVG_SCALE, 0),
        }
