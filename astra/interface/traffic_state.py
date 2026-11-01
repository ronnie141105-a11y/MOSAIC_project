"""Traffic state models shared by the local simulator and ATFM planner."""

from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional


@dataclass(frozen=True)
class AircraftState:
    """A single aircraft's state at one instant in simulation time.

    Frozen so observed traffic is not changed after a snapshot is recorded.
    """

    #: Aircraft callsign / flight identifier, stored in upper case.
    callsign: str

    #: Latitude in decimal degrees (WGS84).
    lat: float

    #: Longitude in decimal degrees (WGS84).
    lon: float

    #: Altitude in feet above mean sea level.
    altitude_ft: float

    #: Ground speed in knots.
    ground_speed_kt: float

    #: True/track heading in degrees (0-360, 0 = true north).
    heading_deg: float

    #: Vertical speed in feet per minute. Positive = climbing.
    vertical_speed_fpm: float

    #: ICAO aircraft type designator, e.g. "A320".
    aircraft_type: str

    #: Seconds since the local scenario started, independent of wall time.
    timestamp_s: float


@dataclass
class TrafficSnapshot:
    """The state of every aircraft in the simulation at one simulation time.

    This is intentionally a thin wrapper around a dict rather than a list:
    downstream code very frequently needs "give me aircraft X's state"
    (O(1) lookup) rather than "iterate position i" and keying by callsign
    also makes it trivial to detect aircraft that appeared/disappeared
    between two consecutive snapshots (set difference of `.callsigns()`).
    """

    #: Simulation time (seconds) this snapshot corresponds to.
    timestamp_s: float

    #: Mapping of callsign -> AircraftState for every aircraft present in
    #: the simulation at `timestamp_s`.
    aircraft: Dict[str, AircraftState] = field(default_factory=dict)

    def __len__(self) -> int:
        """Number of aircraft in this snapshot."""
        return len(self.aircraft)

    def __iter__(self) -> Iterator[AircraftState]:
        """Iterate over the AircraftState objects in this snapshot."""
        return iter(self.aircraft.values())

    def callsigns(self) -> List[str]:
        """Return all callsigns present in this snapshot.

        Returns:
            A list of callsign strings (no particular order is guaranteed,
            since the underlying storage is a dict).
        """
        return list(self.aircraft.keys())

    def get(self, callsign: str) -> Optional[AircraftState]:
        """Look up a single aircraft's state by callsign.

        Args:
            callsign: The callsign to look up. Matching is case-insensitive
                (the callsign is upper-cased before lookup).

        Returns:
            The matching AircraftState, or None if no aircraft with that
            callsign is present in this snapshot.
        """
        return self.aircraft.get(callsign.upper())

    def as_list(self) -> List[AircraftState]:
        """Return all aircraft states as a plain list.

        Returns:
            A list of AircraftState objects, useful wherever an
            order-agnostic, indexable collection is more convenient than
            the dict.
        """
        return list(self.aircraft.values())
