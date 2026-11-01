"""Causal ingestion of saved AirNav observations; no network or API token needed."""

from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import csv
import hashlib
import json
import math
from pathlib import Path

from astra.interface.traffic_state import AircraftState, TrafficSnapshot
from astra.trajectory.engine import predict_constant_velocity
from astra.utils.geodesy import bearing_deg, haversine_distance_nm

FIELDS = {"altitude": "altitude_ft", "groundSpeed": "ground_speed_kt",
          "heading": "heading_deg", "verticalRate": "vertical_speed_fpm"}
REPLAY_VERSION = 2


@dataclass(frozen=True)
class ReplayPolicy:
    max_field_age_s: float = 30.0
    max_position_age_s: float = 30.0
    max_altitude_change_fpm: float = 6000.0

    def __post_init__(self):
        if any(not math.isfinite(v) or v <= 0 for v in
               (self.max_field_age_s, self.max_position_age_s, self.max_altitude_change_fpm)):
            raise ValueError("Replay age/rate limits must be finite and positive")


@dataclass(frozen=True)
class RecordedPoint:
    epoch_s: float
    utc: str
    lat: float
    lon: float
    state: AircraftState | None
    field_sources: dict
    on_ground: bool


def _number(value):
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _timestamp(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("AirNav JSON timestamps must include a timezone offset")
    return parsed.astimezone(timezone.utc)


class AirNavDataset:
    """Timestamped records with bounded past-only field recovery and provenance.

    Null fields never become zero. Invalid or excessively stale records remain
    gaps. Future observations are not available to state reconstruction.
    """

    def __init__(self, flights, policy=None, source_hash=None):
        self.policy = policy or ReplayPolicy()
        self.source_hash = source_hash
        self.metadata = {}
        self.points = {}
        self.quality = Counter()
        self.missing = Counter()
        self.raw_count = 0
        for flight in flights:
            callsign = str(flight.get("callsign") or flight.get("flightNumberIcao") or
                           flight.get("flightNumberIata") or "").strip().upper()
            aircraft_type = str(flight.get("aircraftType") or "").strip().upper()
            if not callsign or not aircraft_type or callsign in self.points:
                raise ValueError("Each recorded flight needs a unique callsign and aircraft type")
            self.metadata[callsign] = {key: flight.get(key) for key in
                ("callsign", "flightNumberIata", "aircraftType", "aircraftRegistration",
                 "depAirportIcao", "arrAirportIcao", "arrAirportLatitude", "arrAirportLongitude",
                 "scheduledDeparture", "actualTakeoff", "scheduledArrival", "actualLanding",
                 "takeoffRunway", "landingRunway", "icaoRoute", "waypoints")}
            self.points[callsign] = self._prepare(callsign, aircraft_type, flight.get("positions", []))
        all_points = [p for points in self.points.values() for p in points]
        if not all_points or not any(p.state is not None for p in all_points):
            raise ValueError("No usable airborne AirNav observations were found")
        self.start_epoch_s = min(p.epoch_s for p in all_points)
        self.end_epoch_s = max(p.epoch_s for p in all_points)
        self._times = {cs: [p.epoch_s for p in pts] for cs, pts in self.points.items()}

    @classmethod
    def load(cls, path, policy=None, *, callsign=None, aircraft_type=None):
        path = Path(path)
        content = path.read_bytes()
        if path.suffix.lower() == ".csv":
            if not callsign or not aircraft_type:
                raise ValueError("CSV replay requires explicit callsign and aircraft_type metadata")
            rows = list(csv.DictReader(content.decode("utf-8-sig").splitlines()))
            positions = []
            for row in rows:
                # The AirNav CSV header explicitly identifies the naive time as UTC.
                parsed = datetime.strptime(row["Date/Time (UTC)"], "%Y-%m-%d %H:%M:%S")
                positions.append(dict(timestamp=parsed.replace(tzinfo=timezone.utc).isoformat(),
                    latitude=row["Latitude"], longitude=row["Longitude"], heading=row["Heading"],
                    altitude=row["Altitude (ft)"], groundSpeed=row["Ground Speed (kts)"],
                    verticalRate=row["Vertical Speed (ft/min)"]))
            flights = [dict(callsign=callsign, aircraftType=aircraft_type, positions=positions)]
        else:
            payload = json.loads(content)
            if not isinstance(payload, dict) or payload.get("success") is False:
                raise ValueError("Expected a successful AirNav flight-search response")
            flights = payload.get("flights", [])
        return cls(flights, policy, hashlib.sha256(content).hexdigest())

    def _prepare(self, callsign, aircraft_type, positions):
        records = []
        for row in positions:
            self.raw_count += 1
            for key in FIELDS:
                if _number(row.get(key)) is None:
                    self.missing[key] += 1
            try:
                stamp = _timestamp(row["timestamp"])
                lat, lon = _number(row.get("latitude")), _number(row.get("longitude"))
                if lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
                    raise ValueError("Invalid coordinates")
                records.append((stamp.timestamp(), stamp, lat, lon, row))
            except (ValueError, KeyError, TypeError):
                self.quality["invalid_position_or_timestamp"] += 1
        records.sort(key=lambda r: r[0])
        # Equal timestamps are one observation instant; the last source row wins.
        unique = {}
        for record in records:
            if record[0] in unique:
                self.quality["duplicate_timestamp"] += 1
            unique[record[0]] = record
        prepared, last_fields, previous, previous_altitude = [], {}, None, None
        for epoch, stamp, lat, lon, row in unique.values():
            values, sources = {}, {}
            ground = row.get("onGround") is True
            for key in FIELDS:
                value = _number(row.get(key))
                valid = value is not None
                if key == "altitude" and valid:
                    valid = -1000 <= value <= 60000
                    old = last_fields.get(key)
                    if old is not None and epoch > old[1]:
                        rate = abs(value - old[0]) * 60 / (epoch - old[1])
                        valid = valid and rate <= self.policy.max_altitude_change_fpm
                if key == "groundSpeed" and valid:
                    valid = 0 <= value <= 750
                if key == "heading" and valid:
                    valid = 0 <= value <= 360
                    value %= 360
                if key == "verticalRate" and valid:
                    valid = abs(value) <= self.policy.max_altitude_change_fpm
                if valid:
                    values[key], sources[key] = value, "reported"
                    last_fields[key] = value, epoch
                else:
                    if value is not None:
                        self.quality["rejected_" + key] += 1
                    old = last_fields.get(key)
                    if old is not None and epoch - old[1] <= self.policy.max_field_age_s:
                        values[key], sources[key] = old[0], "carried"
            if previous is not None:
                dt = epoch - previous.epoch_s
                if 0 < dt <= self.policy.max_field_age_s:
                    distance = haversine_distance_nm(previous.lat, previous.lon, lat, lon)
                    derived_speed = distance * 3600 / dt
                    if "groundSpeed" not in values and derived_speed <= 750:
                        values["groundSpeed"], sources["groundSpeed"] = derived_speed, "derived"
                    if "heading" not in values and distance > 0.001:
                        values["heading"], sources["heading"] = bearing_deg(previous.lat, previous.lon, lat, lon), "derived"
                    if "verticalRate" not in values and "altitude" in values and previous_altitude is not None:
                        rate = (values["altitude"] - previous_altitude) * 60 / dt
                        if abs(rate) <= self.policy.max_altitude_change_fpm:
                            values["verticalRate"], sources["verticalRate"] = rate, "derived"
            state = None
            if ground:
                self.quality["excluded_ground"] += 1
                # Never carry a taxi/ground state into a subsequent airborne record.
                last_fields.clear()
            elif len(values) == len(FIELDS):
                state = AircraftState(callsign, lat, lon, values["altitude"], values["groundSpeed"],
                                      values["heading"], values["verticalRate"], aircraft_type, epoch)
                self.quality["usable_airborne"] += 1
                for source in sources.values():
                    self.quality[source + "_fields"] += 1
            else:
                self.quality["excluded_incomplete"] += 1
            point = RecordedPoint(epoch, stamp.isoformat(), lat, lon, state, sources, ground)
            prepared.append(point)
            previous = point
            # A past altitude can establish VS even when that past row lacked
            # VS itself. Never use a ground record or a future altitude.
            previous_altitude = values.get("altitude") if not ground else None
        return prepared

    def point_at(self, callsign, epoch_s):
        points = self.points[callsign]
        index = bisect_right(self._times[callsign], epoch_s) - 1
        if index < 0 or epoch_s > points[-1].epoch_s:
            return None
        point = points[index]
        if point.state is None or epoch_s - point.epoch_s > self.policy.max_position_age_s:
            return None
        return point

    def summary(self):
        return dict(source_sha256=self.source_hash, replay_version=REPLAY_VERSION, raw_positions=self.raw_count,
                    missing_raw_fields=dict(self.missing), quality=dict(self.quality),
                    policy=vars(self.policy), flights=list(self.metadata.values()))


class AirNavReplayConnector:
    """Finite event-time replay satisfying ConnectorProtocol, with immutable data."""

    def __init__(self, dataset, *, start_epoch_s=None, end_epoch_s=None, offsets=None):
        self.dataset = dataset
        self.start_epoch_s = dataset.start_epoch_s if start_epoch_s is None else start_epoch_s
        self.end_epoch_s = dataset.end_epoch_s if end_epoch_s is None else end_epoch_s
        if not self.start_epoch_s <= self.end_epoch_s:
            raise ValueError("Replay start must be before its end")
        self.offsets = offsets or {cs: (cs, 0.0) for cs in dataset.points}
        events = set()
        for target, (source, shift) in self.offsets.items():
            if source not in dataset.points or not math.isfinite(shift) or shift < 0:
                raise ValueError("Replay offsets need a known source and non-negative finite shift")
            for point in dataset.points[source]:
                if self.start_epoch_s <= point.epoch_s <= self.end_epoch_s:
                    t = point.epoch_s - self.start_epoch_s + shift
                    events.add(t)
                    # Explicit expiry frames prevent bridging long coverage gaps.
                    events.add(t + dataset.policy.max_position_age_s + 0.001)
            events.add(self.end_epoch_s - self.start_epoch_s + shift + 0.001)
        self.timeline = sorted(events)
        self._cursor = 0
        self._snapshot = None
        self._active = False

    def connect(self):
        self._cursor, self._snapshot, self._active = 0, None, True

    @property
    def finished(self):
        return self._cursor >= len(self.timeline)

    def has_active_node(self):
        return self._active and not self.finished

    def frame_at(self, time_s):
        aircraft, provenance = {}, {}
        for target, (source, shift) in self.offsets.items():
            epoch = self.start_epoch_s + time_s - shift
            if not self.start_epoch_s <= epoch <= self.end_epoch_s:
                continue
            point = self.dataset.point_at(source, epoch)
            if point is None:
                continue
            age = max(0.0, epoch - point.epoch_s)
            state = predict_constant_velocity(point.state, age, time_s)
            aircraft[target] = replace(state, callsign=target)
            provenance[target] = dict(source_callsign=source, source_utc=point.utc,
                source_age_s=round(age, 3), position_kind="reported" if age < 0.001 else "extrapolated",
                field_sources=point.field_sources, synthetic=target != source, shift_s=shift)
        return TrafficSnapshot(time_s, aircraft), provenance

    def poll(self):
        if not self._active or self.finished:
            self._snapshot = None
            return
        self._snapshot, _ = self.frame_at(self.timeline[self._cursor])
        self._cursor += 1

    def latest_snapshot(self):
        return self._snapshot

    def send_command(self, command_text):
        raise RuntimeError("Recorded AirNav replay is immutable; use a synthetic simulator for clearances")

    def create_aircraft(self, *args, **kwargs):
        raise RuntimeError("Recorded AirNav replay cannot create observed aircraft")
