"""Build three deterministic, explicitly synthetic VVTS TMA study windows.

The six FlightAware tracks remain unaltered, partial observations. All other
positions, event times, flight plans, and capacity assumptions are scenarios.
This script intentionally does not run optimization or analyze ATFM measures.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta, timezone
from io import StringIO
from functools import lru_cache
import json
import math
from pathlib import Path
import random
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from astra.airspace import load_profile, procedure_aircraft
from astra.interface.airnav_replay import AirNavDataset
from astra.interface.traffic_state import AircraftState
from astra.trajectory.procedure import advance_procedure
from astra.utils.geodesy import haversine_distance_nm

RECORDED = ROOT / "scenarios/recorded/vvts_cases"
OUT = ROOT / "scenarios/synthetic/vvts_cases"
BOARD = ROOT / "output/weather_capture/2026-10-07/traffic_board.json"
UTC = timezone.utc
STEP_S = 20
CAPACITY = {
    "bad_weather": (9, 8, 5, 3, 3, 5, 7, 8),  # assumed TSRA peak and recovery; sum 48
    "nominal": (11,) * 8,          # 44 combined movements/hour reference
    "holiday_peak": (11, 12) * 4,  # 46 combined movements/hour
}
SOURCE_URLS = {
    "caav_holiday_daily": "https://caa.gov.vn/hoat-dong-nganh/cang-hkqt-noi-bai-va-tan-son-nhat-san-sang-phuong-an-phuc-vu-hanh-khach-dip-cao-diem-tet-nguyen-dan-2026-20260209144210927.htm",
    "caav_holiday_slots": "https://caa.gov.vn/hoat-dong-nganh/dieu-chinh-tham-so-dieu-phoi-slot-tai-cang-hang-khong-quoc-te-tan-son-nhat-20251023163405728.htm",
    "caav_august_2026": "https://caa.gov.vn/hoat-dong-nganh/cang-hkqt-noi-bai-tan-son-nhat-trien-khai-dong-bo-cac-phuong-an-khai-thac-san-sang-phuc-vu-le-quoc-khanh-02-9-20260828093847766.htm",
    "caav_april_2026": "https://caa.gov.vn/hoat-dong-nganh/dieu-chinh-tham-so-dieu-phoi-gio-ha-cat-canh-tai-cang-hang-khong-quoc-te-tan-son-nhat-dip-nghi-le-30-4-1-5-2026-20260414082347431.htm",
    "vatm_storm_context_report": "https://baoxaydung.vn/mua-dong-phuc-tap-tai-tan-son-nhat-quan-ly-bay-tang-cuong-ung-truc-192261009182310606.htm",
}
ARRIVAL_PROCEDURES = {
    "north": ("SAPEN2H", "DALAP2H", "DALAP2J", "SAPEN2J"),
    "southwest": ("BITIS2H", "BITIS2J", "VICAL3H", "VICAL3J"),
    "east": ("ELSAS2H", "DALAP2H", "DALAP2J", "VICAL3H"),
}
DEPARTURE_PROCEDURES = {
    "north": ("ANTRI2D", "LANHI2D", "KADUM2D", "TANOS2D"),
    "southwest": ("SAPEN2D", "BACHU2D", "MISAN2D", "ENPAS2D"),
    "east": ("XOBAV2D", "KADUM2D", "ANTRI2D", "TANOS2D"),
}
NORTH = {"VVNB", "VVHP", "VVVH", "VVTH", "VVVII", "ZGGG", "VHHH", "RCTP", "RKSI", "ZUTF", "VVUI"}
SOUTHWEST = {"VVPQ", "VVCS", "WSSS", "WMKK", "VTBS", "WIII", "WADD", "VDSA"}
EAST = {"VVDN", "VVCR", "VVDL", "VVPC", "VVPK", "VVBB", "VVHU", "VVDH", "VVRG"}
OTHER_AIRPORTS = ("VVNB", "VVDN", "VVPQ", "VVHP", "VVCR", "WSSS", "WMKK", "VVCS", "VVDL", "VHHH")
AIRCRAFT_TYPES = ("A321", "A20N", "A21N", "A320", "B738", "B38M", "B78X", "A359", "AT72")


def iso(stamp: datetime | None) -> str:
    return stamp.astimezone(UTC).isoformat(timespec="seconds") if stamp else ""


def parse_stamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def csv_bytes(fields, rows) -> bytes:
    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def sector(airport: str) -> str:
    if airport in NORTH:
        return "north"
    if airport in SOUTHWEST:
        return "southwest"
    return "east"


def board_event_time(raw: str, day) -> datetime | None:
    match = re.search(r"\b(\d{1,2}):(\d{2})([ap])\s+\+07\b", raw, re.I)
    if not match:
        return None
    hour = int(match.group(1)) % 12 + (12 if match.group(3).lower() == "p" else 0)
    return datetime(day.year, day.month, day.day, hour, int(match.group(2)), tzinfo=timezone(timedelta(hours=7))).astimezone(UTC)


def bad_weather_flights(start: datetime, end: datetime) -> list[dict]:
    board = json.loads(BOARD.read_text(encoding="utf-8"))
    found = []
    for row in board["rows"]:
        match = re.search(r"/([A-Z]{4})/([A-Z]{4})(?:/|$)", row.get("flight_url", ""))
        if not match:
            continue
        adep, ades = match.groups()
        if ades == "VVTS":
            direction, raw_time = "arrival", row["cells"][5]
            other = adep
        elif adep == "VVTS":
            direction, raw_time = "departure", row["cells"][3]
            other = ades
        else:
            continue
        moment = board_event_time(raw_time, start.astimezone(timezone(timedelta(hours=7))).date())
        if moment is None or not start <= moment < end:
            continue
        found.append(dict(callsign=row["cells"][0], aircraft_type=row["cells"][1],
                          direction=direction, other_airport=other, planned=moment,
                          board_display_time=raw_time, board_flight_url=row["flight_url"],
                          identity_evidence="partial_flightaware_board"))
    # The airport-board snapshot is partial. Eight explicit filler movements
    # provide a defined start and end without pretending to be real flights.
    offsets = (8, 17, 28, 36, 47, 54, 109, 116)
    for index, minute in enumerate(offsets):
        direction = "arrival" if index % 2 == 0 else "departure"
        other = OTHER_AIRPORTS[(index * 3) % len(OTHER_AIRPORTS)]
        found.append(dict(callsign=f"MOSW{index + 1:03d}", aircraft_type=AIRCRAFT_TYPES[index],
                          direction=direction, other_airport=other,
                          planned=start + timedelta(minutes=minute), board_display_time="",
                          board_flight_url="", identity_evidence="synthetic"))
    return sorted(found, key=lambda item: (item["planned"], item["callsign"]))


def generated_flights(case_id: str, start: datetime, end: datetime) -> list[dict]:
    # Daily CAAV totals guide scale only. No per-flight identity is asserted.
    counts = {"nominal": (23, 43), "holiday_peak": (43, 53)}
    arrivals, departures = counts[case_id]
    rng = random.Random({"nominal": 20261008, "holiday_peak": 20260222}[case_id])
    result = []
    for direction, count, offset in (("arrival", arrivals, 0), ("departure", departures, 1)):
        for i in range(count):
            fraction = (i + 0.5) / count
            seconds = fraction * (end - start).total_seconds() + rng.randint(-55, 55)
            moment = start + timedelta(seconds=round(seconds))
            other = OTHER_AIRPORTS[(i * 3 + offset) % len(OTHER_AIRPORTS)]
            result.append(dict(callsign=f"MOS{case_id[0].upper()}{offset}{i + 1:03d}",
                               aircraft_type=AIRCRAFT_TYPES[(i + offset) % len(AIRCRAFT_TYPES)],
                               direction=direction, other_airport=other, planned=moment,
                               board_display_time="", board_flight_url="",
                               identity_evidence="synthetic"))
    return sorted(result, key=lambda item: (item["planned"], item["callsign"]))


def release_fix(spec: dict, ordinal: int) -> tuple[dict, str]:
    """Model direct-to a common merge fix from a permitted fan position."""
    legs = spec["procedure_profile"]["legs"]
    route = spec["route_waypoints"]
    fixes = [leg["fix"] for leg in legs]
    merge = "BOMSU" if "BOMSU" in fixes else "SOKAN"
    fan = [fix for fix in fixes if fix in {
        "VANLI", "TS488", "RUNSI", "TS458", "TS456", "TS454",
        "VIKEP", "TS452", "TS438", "TS436", "TS434", "TS432",
        "ANSUP", "TS448", "TS446", "TS444", "TS442",
        "TS468", "TS466", "TS464", "TS462",
    }]
    # Earlier fixes need extra distance for the modeled 2,000 fpm descent.
    if not fan:
        raise ValueError(f"No point-merge fan found for {spec['procedure_profile']['procedure_id']}")
    selected = fan[ordinal % len(fan)]
    release_i, merge_i = fixes.index(selected), fixes.index(merge)
    keep = list(range(release_i + 1)) + list(range(merge_i, len(fixes)))
    spec["route_waypoints"] = [route[i] for i in keep]
    spec["procedure_profile"]["legs"] = [legs[i] for i in keep]
    spec["procedure_profile"]["direct_from_fix"] = selected
    spec["procedure_profile"]["direct_to_fix"] = merge
    return spec, selected


@lru_cache(maxsize=None)
def template(procedure_id: str, release_ordinal: int) -> tuple[list[dict], list[str], str]:
    spec = procedure_aircraft("tsn_tma", procedure_id, "TEMPLATE",
                              "25R" if procedure_id.endswith(("H", "J")) else "25L")
    direct = ""
    if spec["procedure_profile"]["direction"] == "inbound":
        spec, direct = release_fix(spec, release_ordinal)
    profile = spec["procedure_profile"]
    route = spec["route_waypoints"]
    state = AircraftState("TEMPLATE", spec["lat"], spec["lon"], spec["altitude_ft"],
                          spec["speed_kt"], spec["heading_deg"], 0.0, "A320", 0.0)
    points = [state]
    for _ in range(450):
        step = advance_procedure(state, route, profile, STEP_S)
        state, route, profile = step.aircraft, step.remaining_route, step.profile
        points.append(state)
        if step.completed:
            break
    else:
        raise RuntimeError(f"Procedure {procedure_id} failed to terminate")
    rows = [dict(t_s=int(point.timestamp_s), latitude=round(point.lat, 6),
                 longitude=round(point.lon, 6), altitude=round(point.altitude_ft, 1),
                 ground_speed=round(point.ground_speed_kt, 1),
                 heading=round(point.heading_deg, 1), vertical_rate=round(point.vertical_speed_fpm, 1),
                 on_ground=(i == 0 and spec["procedure_profile"]["direction"] == "outbound") or
                           (i == len(points) - 1 and spec["procedure_profile"]["direction"] == "inbound"))
            for i, point in enumerate(points)]
    fixes = [leg["fix"] for leg in spec["procedure_profile"]["legs"]]
    if direct:
        merge = "BOMSU" if "BOMSU" in fixes else "SOKAN"
        waypoint = load_profile("tsn_tma")["waypoint_data"][merge]
        nearest = min(rows, key=lambda row: haversine_distance_nm(
            row["latitude"], row["longitude"], waypoint["lat"], waypoint["lon"]))
        nearest_nm = haversine_distance_nm(nearest["latitude"], nearest["longitude"],
                                            waypoint["lat"], waypoint["lon"])
        altitude_m = nearest["altitude"] * .3048
        minimum_m = 790 if merge == "BOMSU" else 730
        if nearest_nm > 1.5 or not minimum_m + 50 <= altitude_m <= 1450:
            raise ValueError(f"{procedure_id} direct from {direct} misses {merge} altitude window: "
                             f"{altitude_m:.0f} m at {nearest_nm:.2f} NM")
    first_fix = (load_profile("tsn_tma")["procedure_data"][procedure_id]["legs"][0]["fix"]
                 if direct else "RW25L")
    return rows, [first_fix] + fixes, direct


def slot_times(start: datetime, capacities: tuple[int, ...], count: int) -> list[datetime]:
    times = []
    quarter = 0
    while len(times) < count + 100:
        cap = capacities[quarter % len(capacities)]
        base = start + timedelta(minutes=15 * quarter)
        times.extend(base + timedelta(seconds=(i + .5) * 900 / cap) for i in range(cap))
        quarter += 1
    return times


def assign_slots(flights: list[dict], start: datetime, capacities: tuple[int, ...],
                 case_id: str, observed_callsigns: set[str]) -> None:
    slots = slot_times(start, capacities, len(flights))
    used = set()
    last_arrival = start - timedelta(hours=1)
    last_departure = start - timedelta(hours=1)
    # 20 NM same-track spacing at ~230 kt is about 5.2 minutes. It is
    # deliberately conservative and causes queue spill for overloaded cases.
    arrival_spacing = timedelta(seconds=360 if case_id == "bad_weather" else 320)
    departure_spacing = timedelta(seconds=150)
    for flight in flights:
        if flight["callsign"] in observed_callsigns:
            # A partial observed track never implies a verified landing time.
            flight["simulated_slot"] = None
            continue
        direction = flight["direction"]
        earliest = max(flight["planned"],
                       (last_arrival + arrival_spacing) if direction == "arrival"
                       else (last_departure + departure_spacing))
        chosen = next(i for i, slot in enumerate(slots) if i not in used and slot >= earliest)
        used.add(chosen)
        flight["simulated_slot"] = slots[chosen]
        if direction == "arrival":
            last_arrival = slots[chosen]
        else:
            last_departure = slots[chosen]


def resequence_synthetic_arrivals(flights: list[dict], observed_callsigns: set[str],
                                  start: datetime, capacities: tuple[int, ...], case_id: str) -> None:
    """Delay candidate arrivals until 4D merge-region spacing is satisfied.

    This is a simple deterministic baseline scheduler, not GA or ATFM control.
    It searches combined movement slots and checks all previously placed
    synthetic arrival samples inside the 40 NM, 3,000-16,570 ft study volume.
    """
    arrivals = [f for f in flights if f["direction"] == "arrival" and f["callsign"] not in observed_callsigns]
    arrivals.sort(key=lambda f: f["simulated_slot"])
    occupied_slots = {f["simulated_slot"] for f in flights if f["direction"] == "departure"}
    candidate_slots = slot_times(start, capacities, len(flights) + 350)
    center = load_profile("tsn_tma")["center"]
    occupancy = defaultdict(list)
    previous_arrival = start - timedelta(hours=1)
    spacing = timedelta(seconds=360 if case_id == "bad_weather" else 320)

    def samples(flight, slot):
        relative, _, _ = template(flight["_procedure"], flight["_index"])
        first = slot - timedelta(seconds=relative[-1]["t_s"])
        for point in relative:
            if point["on_ground"] or not 3000 <= point["altitude"] <= 16570:
                continue
            if haversine_distance_nm(point["latitude"], point["longitude"],
                                     center["lat"], center["lon"]) > 40:
                continue
            stamp = first.timestamp() + point["t_s"]
            yield int(stamp // STEP_S), (stamp, point["latitude"], point["longitude"],
                                         point["altitude"], point["heading"])

    for flight in arrivals:
        earliest = max(flight["simulated_slot"], previous_arrival + spacing)
        for slot in candidate_slots:
            if slot < earliest or slot in occupied_slots:
                continue
            candidate = list(samples(flight, slot))
            conflict = False
            for bucket, (stamp, lat, lon, altitude, heading) in candidate:
                for nearby_bucket in (bucket - 1, bucket, bucket + 1):
                    for old_stamp, old_lat, old_lon, old_altitude, old_heading in occupancy.get(nearby_bucket, ()):
                        if abs(stamp - old_stamp) > 30:
                            continue
                        distance = haversine_distance_nm(lat, lon, old_lat, old_lon)
                        heading_delta = abs((heading - old_heading + 180) % 360 - 180)
                        if distance < 10 or (distance < 20 and heading_delta <= 25):
                            conflict = True
                            break
                    if conflict:
                        break
                if conflict:
                    break
            if conflict:
                continue
            flight["simulated_slot"] = slot
            occupied_slots.add(slot)
            previous_arrival = slot
            for bucket, record in candidate:
                occupancy[bucket].append(record)
            break
        else:
            raise RuntimeError(f"Could not safely sequence arrival {flight['callsign']}")


def make_positions(flight: dict, relative: list[dict], start: datetime, end: datetime) -> list[dict]:
    is_arrival = flight["direction"] == "arrival"
    duration = relative[-1]["t_s"]
    first = flight["simulated_slot"] - timedelta(seconds=duration) if is_arrival else flight["simulated_slot"]
    positions = []
    for point in relative:
        moment = first + timedelta(seconds=point["t_s"])
        # Preserve the whole trajectory, including a queue tail after the
        # two-hour demand window. Later simulations need to see every release.
        positions.append(dict(timestamp=iso(moment), latitude=point["latitude"],
                              longitude=point["longitude"], altitude=point["altitude"],
                              groundSpeed=point["ground_speed"], heading=point["heading"],
                              verticalRate=point["vertical_rate"], onGround=point["on_ground"]))
    return positions


def flight_procedure(flight: dict, index: int) -> str:
    direction = flight["direction"]
    group = sector(flight["other_airport"])
    options = ARRIVAL_PROCEDURES[group] if direction == "arrival" else DEPARTURE_PROCEDURES[group]
    return options[index % len(options)]


def observed_tracks(start: datetime, end: datetime) -> dict[str, dict]:
    payload = json.loads((RECORDED / "bad_weather/observations.json").read_text(encoding="utf-8"))
    result = {}
    for flight in payload["flights"]:
        positions = [p for p in flight["positions"] if start <= parse_stamp(p["timestamp"]) <= end]
        if positions:
            result[flight["callsign"]] = {**flight, "positions": positions}
    return result


def conflict_audit(all_positions: dict[str, list[dict]], start: datetime, end: datetime,
                   directions: dict[str, str]) -> dict:
    """Count pair-minutes inside the TMA; diagnostic, not certified separation."""
    profile = load_profile("tsn_tma")
    center = profile["center"]
    by_minute = defaultdict(list)
    for callsign, points in all_positions.items():
        for point in points:
            stamp = parse_stamp(point["timestamp"])
            if not start <= stamp < end:
                continue
            if stamp.second >= STEP_S or point.get("onGround"):
                continue
            altitude = point.get("altitude")
            heading = point.get("heading")
            if altitude is None or heading is None or not 3000 <= float(altitude) <= 16570:
                continue
            if haversine_distance_nm(float(point["latitude"]), float(point["longitude"]),
                                     center["lat"], center["lon"]) > 40:
                continue
            key = int((stamp - start).total_seconds() // 60)
            by_minute[key].append((callsign, point))
    under10 = same_track20 = coalt10 = coalt_same20 = 0
    arrival_under10 = arrival_same20 = 0
    coalt_by_pair_type = Counter()
    examples = []
    closest = None
    for minute, states in by_minute.items():
        for i, (left_id, left) in enumerate(states):
            for right_id, right in states[i + 1:]:
                if left_id == right_id:
                    continue
                distance = haversine_distance_nm(float(left["latitude"]), float(left["longitude"]),
                                                 float(right["latitude"]), float(right["longitude"]))
                if closest is None or distance < closest:
                    closest = distance
                heading_delta = abs((float(left["heading"]) - float(right["heading"]) + 180) % 360 - 180)
                if distance < 10:
                    under10 += 1
                    if directions[left_id] == directions[right_id] == "arrival":
                        arrival_under10 += 1
                    if abs(float(left["altitude"]) - float(right["altitude"])) < 1000:
                        coalt10 += 1
                        pair_type = "_".join(sorted((directions[left_id], directions[right_id])))
                        coalt_by_pair_type[pair_type] += 1
                        if len(examples) < 8:
                            examples.append(dict(time_utc=iso(start + timedelta(minutes=minute)),
                                                 left=left_id, right=right_id,
                                                 pair_type=pair_type,
                                                 distance_nm=round(distance, 2),
                                                 vertical_difference_ft=round(abs(float(left["altitude"]) - float(right["altitude"])))))
                if distance < 20 and heading_delta <= 20:
                    same_track20 += 1
                    if directions[left_id] == directions[right_id] == "arrival":
                        arrival_same20 += 1
                    if abs(float(left["altitude"]) - float(right["altitude"])) < 1000:
                        coalt_same20 += 1
    return dict(method="one sample per minute; airborne 3,000-16,570 ft within 40 NM of TSH",
                units="aircraft-pair-minutes, not distinct conflicts or clearances",
                horizontal_under_10_nm=under10, same_heading_under_20_nm=same_track20,
                arrival_arrival_under_10_nm=arrival_under10,
                arrival_arrival_same_heading_under_20_nm=arrival_same20,
                horizontal_under_10_nm_and_vertical_under_1000_ft=coalt10,
                same_heading_under_20_nm_and_vertical_under_1000_ft=coalt_same20,
                close_pair_minutes_by_type=dict(coalt_by_pair_type),
                close_pair_examples=examples,
                closest_nm=round(closest, 2) if closest is not None else None,
                caveat="No controller clearance, surveillance error, wake category, or actual runway confirmed.")


FLIGHT_FIELDS = ("flight_id", "callsign", "aircraft_type", "adep", "ades", "status",
                 "scheduled_departure_utc", "scheduled_arrival_utc", "actual_takeoff_utc",
                 "actual_landing_utc", "actual_offblock_utc", "actual_inblock_utc", "runway", "source")
FPL_FIELDS = ("flight_id", "callsign", "aircraft_type", "adep", "ades", "eobt_utc",
              "eet_min", "filed_route", "issued_at_utc", "raw_fpl", "source")
TRACK_FIELDS = ("flight_id", "callsign", "aircraft_type", "adep", "ades", "time_utc",
                "lat", "lon", "altitude_ft", "ground_speed_kt", "heading_deg",
                "vertical_speed_fpm", "on_ground", "source")
FLOW_FIELDS = ("start_utc", "end_utc", "resource", "flights_per_interval", "evidence", "source")
WEATHER_FIELDS = ("report_type", "observation_utc", "issue_utc", "valid_from_utc",
                  "valid_to_utc", "raw", "source")


def build_case(case: dict) -> dict[str, bytes]:
    case_id = case["id"]
    start = parse_stamp(case["local_start"])
    end = parse_stamp(case["local_end"])
    planned = (bad_weather_flights(start, end) if case_id == "bad_weather"
               else generated_flights(case_id, start, end))
    callsigns = [flight["callsign"] for flight in planned]
    if len(set(callsigns)) != len(callsigns):
        raise ValueError(f"Duplicate callsign in {case_id}")
    observed = observed_tracks(start, end) if case_id == "bad_weather" else {}
    for index, flight in enumerate(planned):
        flight["_index"] = index
        flight["_procedure"] = flight_procedure(flight, index)
    # All planned flights receive counterfactual 25R/25L trajectories. The six
    # recorded 07-direction tracks are a separate evidence reference layer.
    assign_slots(planned, start, CAPACITY[case_id], case_id, set())
    resequence_synthetic_arrivals(planned, set(), start, CAPACITY[case_id], case_id)
    board_metadata = json.loads(BOARD.read_text(encoding="utf-8")) if case_id == "bad_weather" else None
    tracked = {}
    track_rows, flight_rows, fpl_rows, manifest_flights = [], [], [], []
    for index, flight in enumerate(planned):
        callsign = flight["callsign"]
        direction = flight["direction"]
        airport = flight["other_airport"]
        adep, ades = (airport, "VVTS") if direction == "arrival" else ("VVTS", airport)
        runway = "25R" if direction == "arrival" else "25L"
        flight_id = f"{case_id}:{callsign}"
        procedure = flight["_procedure"]
        has_reference = callsign in observed
        if direction == "arrival":
            # Board arrival display is a time hint, never verified schedule.
            scheduled_dep = flight["planned"] - timedelta(minutes=95)
            scheduled_arr = flight["planned"]
        else:
            scheduled_dep = flight["planned"]
            scheduled_arr = flight["planned"] + timedelta(minutes=90)
        if direction == "arrival" and procedure.endswith(("H", "J")):
            relative, route_fixes, release = template(procedure, index)
            merge = "BOMSU" if procedure.endswith("J") else "SOKAN"
        else:
            relative, route_fixes, _ = template(procedure, 0)
            release, merge = "", ""
        # The route column is a synthetic filed-route proxy. Tactical direct-to
        # clearances belong only in the scenario manifest, never in Item 15.
        filed_route = procedure
        positions = make_positions(flight, relative, start, end)
        position_source = "synthetic_counterfactual_25r" if has_reference else "synthetic_procedure"
        for point in positions:
            track_rows.append(dict(flight_id=flight_id, callsign=callsign,
                                   aircraft_type=flight["aircraft_type"], adep=adep, ades=ades,
                                   time_utc=point["timestamp"], lat=point["latitude"],
                                   lon=point["longitude"], altitude_ft=point["altitude"],
                                   ground_speed_kt=point["groundSpeed"], heading_deg=point["heading"],
                                   vertical_speed_fpm=point["verticalRate"],
                                   on_ground=str(point["onGround"]).lower(), source=position_source))
        if positions:
            tracked[callsign] = positions
        flight_rows.append(dict(flight_id=flight_id, callsign=callsign,
                                aircraft_type=flight["aircraft_type"], adep=adep, ades=ades,
                                status="simulated_counterfactual" if has_reference else "simulated_candidate",
                                scheduled_departure_utc=iso(scheduled_dep),
                                scheduled_arrival_utc=iso(scheduled_arr),
                                actual_takeoff_utc="", actual_landing_utc="",
                                actual_offblock_utc="", actual_inblock_utc="",
                                runway=runway,
                                source="scenario_board_anchored" if flight["identity_evidence"] != "synthetic" else "synthetic_scenario"))
        fpl_rows.append(dict(flight_id=flight_id, callsign=callsign,
                             aircraft_type=flight["aircraft_type"], adep=adep, ades=ades,
                             eobt_utc=iso(scheduled_dep - timedelta(minutes=15)), eet_min=95 if direction == "arrival" else 90,
                             filed_route=filed_route, issued_at_utc="", raw_fpl="", source="synthetic_route_assumption"))
        field_provenance = {
            "identity_type_airports": flight["identity_evidence"],
            "board_display_time": "flightaware_partial_board" if flight["board_display_time"] else "unavailable",
            "planned_event_time": "synthetic_target_using_board_display" if flight["board_display_time"] else "synthetic_schedule",
            "simulated_slot_and_fpl": "deterministic_scenario_model",
            "procedure_runway_direct_to": "scenario_assumption_25r_arrival_25l_departure",
            "positions": position_source,
            "observed_reference_positions": "reference_tracks.json" if has_reference else "none",
        }
        manifest_flights.append(dict(flight_id=flight_id, callsign=callsign, aircraft_type=flight["aircraft_type"],
                                     direction=direction, adep=adep, ades=ades,
                                     board_display_time_local=flight["board_display_time"],
                                     board_flight_url=flight["board_flight_url"],
                                     planned_event_utc=iso(flight["planned"]),
                                     simulated_slot_utc=iso(flight["simulated_slot"]),
                                     simulated_delay_min=round((flight["simulated_slot"] - flight["planned"]).total_seconds() / 60, 1),
                                     has_separate_observed_reference_track=has_reference,
                                     actual_landing_verified=False, actual_takeoff_verified=False,
                                     procedure=procedure, runway_assumption=runway,
                                     direct_from_fix=release, direct_to_fix=merge,
                                     route_fixes=route_fixes, field_provenance=field_provenance,
                                     first_track_utc=positions[0]["timestamp"] if positions else None,
                                     last_track_utc=positions[-1]["timestamp"] if positions else None,
                                     track_points_in_window=sum(start <= parse_stamp(p["timestamp"]) < end for p in positions),
                                     track_points_total=len(positions)))
    observed_flights = list(observed.values())
    # The observed 07-direction track and counterfactual 25R approach must not
    # be replayed as one realized traffic state. Keep references separate.
    observation_payload = dict(success=True, flights=[])
    counts = Counter(flight["direction"] for flight in planned)
    demand_rows, capacity_rows = [], []
    for quarter in range(8):
        qstart = start + timedelta(minutes=15 * quarter)
        qend = qstart + timedelta(minutes=15)
        for resource, subset in (("VVTS_RUNWAY_TOTAL", planned),
                                 ("VVTS_ARRIVAL_RUNWAY", [f for f in planned if f["direction"] == "arrival"]),
                                 ("VVTS_DEPARTURE_RUNWAY", [f for f in planned if f["direction"] == "departure"])):
            quantity = sum(qstart <= flight["planned"] < qend for flight in subset)
            demand_rows.append(dict(start_utc=iso(qstart), end_utc=iso(qend), resource=resource,
                                    flights_per_interval=quantity, evidence="synthetic_planned_demand",
                                    source="scenario_manifest"))
        capacity_rows.append(dict(start_utc=iso(qstart), end_utc=iso(qend), resource="VVTS_RUNWAY_TOTAL",
                                  flights_per_interval=CAPACITY[case_id][quarter],
                                  evidence="scenario_assumption" if case_id == "bad_weather" else "slot_parameter_reference",
                                  source="weather_reduction_assumption" if case_id == "bad_weather" else
                                         SOURCE_URLS["caav_holiday_slots" if case_id == "holiday_peak" else "caav_april_2026"]))
    if case_id == "holiday_peak":
        weather = csv_bytes(WEATHER_FIELDS, [])
        weather_assumption = "Fair-weather scenario assumption. No archived METAR for this window is present."
    else:
        weather = (RECORDED / case_id / "weather.csv").read_bytes()
        weather_assumption = "Archived METAR/TAF copied unchanged; no numerical weather simulation applied to synthetic tracks."
    audit = conflict_audit(tracked, start, end,
                           {f["callsign"]: f["direction"] for f in planned})
    simulated_flights = [flight for flight in planned if flight["simulated_slot"] is not None]
    slot_in_window = sum(start <= flight["simulated_slot"] < end for flight in simulated_flights)
    demand_total = len(planned)
    cap_total = sum(CAPACITY[case_id])
    window_tracked = {cs: pts for cs, pts in tracked.items()
                      if any(start <= parse_stamp(p["timestamp"]) < end for p in pts)}
    summary = dict(case_id=case_id, kind="synthetic_reconstruction_with_partial_observed_anchors" if observed else "synthetic_scenario",
                   window_start_utc=iso(start), window_end_utc=iso(end),
                   planned_movements=demand_total, planned_arrivals=counts["arrival"],
                   planned_departures=counts["departure"], combined_slot_capacity_reference=cap_total,
                   planned_excess_over_combined_capacity=max(0, demand_total - cap_total),
                   simulated_slots_within_window=slot_in_window,
                   synthetic_flights_spilling_after_window=len(simulated_flights) - slot_in_window,
                   flights_with_window_track=len(window_tracked),
                   observed_reference_tracks=len(observed), synthetic_trajectories_total=len(simulated_flights),
                   total_track_points_in_window=sum(sum(start <= parse_stamp(p["timestamp"]) < end for p in pts)
                                                    for pts in tracked.values()),
                   total_track_points_including_queue_tail=sum(map(len, tracked.values())),
                   weather_basis=weather_assumption, separation_audit=audit,
                   interpretation="Candidate unvalidated baseline trajectories. The separation audit contains close pairs to resolve during the next traffic-behavior test; not actual airport movements or ATC clearances.")
    manifest = dict(schema_version=1, case_id=case_id,
                    local_start=case["local_start"], local_end=case["local_end"],
                    generated_by="scripts/build_synthetic_vvts_cases.py",
                    scenario_kind=summary["kind"],
                    scheduled_vs_simulated="planned_event_utc is scenario demand; simulated_slot_utc is a deterministic queue assignment, not an observed actual time",
                    airport_board_retrieved_at_utc=board_metadata["retrieved_at_utc"] if board_metadata else None,
                    observed_track_source="scenarios/recorded/vvts_cases/bad_weather/observations.json" if observed else None,
                    observed_reference_file="reference_tracks.json" if observed else None,
                    geometry="25R arrival STAR/ILS and 25L departure SID common study geometry",
                    runway_caveat="Oct 7 METAR reports R07R and northeast wind; actual runway/clearance unknown, so 25R synthetic tracks are counterfactual study geometry." if case_id == "bad_weather" else "Runway configuration not independently verified for this window.",
                    weather_basis=weather_assumption,
                    capacity_basis="Assumed 15-minute combined movement caps 9,8,5,3,3,5,7,8; lower near the observed 18:00 +TSRA METAR, then recovery. Sum 48, not a declared capacity." if case_id == "bad_weather" else
                                   "44 movements/hour reference, not verified for this exact Oct 8 window" if case_id == "nominal" else
                                   "CAAV published 46 movements/hour slot parameter for Feb 2-Mar 3; not an operational arrival-only capacity",
                    arrival_slot_spacing_s=360 if case_id == "bad_weather" else 320,
                    departure_slot_spacing_s=150,
                    route_aware_arrival_sequencing="synthetic arrival pairs checked at 20-second samples for 10 NM horizontal and 20 NM same-heading, regardless of vertical separation, within the TMA",
                    sources=SOURCE_URLS, flights=manifest_flights)
    output = {
        "manifest.json": json_bytes(manifest),
        "summary.json": json_bytes(summary),
        "flights.csv": csv_bytes(FLIGHT_FIELDS, flight_rows),
        "fpl.csv": csv_bytes(FPL_FIELDS, fpl_rows),
        "tracks.csv": csv_bytes(TRACK_FIELDS, track_rows),
        "demand.csv": csv_bytes(FLOW_FIELDS, demand_rows),
        "capacity.csv": csv_bytes(FLOW_FIELDS, capacity_rows),
        "weather.csv": weather,
        "observations.json": json_bytes(observation_payload),
    }
    if observed:
        output["reference_tracks.json"] = json_bytes(dict(success=True, flights=observed_flights,
            note="Observed FlightAware positions only; reference layer excluded from counterfactual 25R replay."))
    return output


README = """# VVTS TMA synthetic case-study scenarios

These three two-hour scenarios are deterministic **reconstructions for simulation**.
They are not verified flight plans, airport movement logs, AirNav playback exports,
or ATC clearances. They are stored separately from `scenarios/recorded/vvts_cases`.

| Case | Local window (ICT) | Planned movements | Combined slot reference |
| --- | --- | ---: | ---: |
| Bad weather | 7 Oct 2026, 17:00–19:00 | 70 | 48, assumed storm reduction |
| Nominal | 8 Oct 2026, 09:00–11:00 | 66 | 88, 44/hour reference |
| Holiday peak | 22 Feb 2026, 10:00–12:00 | 96 | 92, published 46/hour slot parameter |

`manifest.json` lists every flight's origin, type, planned event time, assigned
simulated slot, 25R STAR or 25L SID, direct-to merge fix, and field-level
provenance. `flights.csv` and `fpl.csv` are **scenario inputs** even where a
callsign is grounded in the partial FlightAware airport board. No filed FPL was
obtained. Planned demand is counted in 15-minute bins in `demand.csv`;
`capacity.csv` contains combined runway/ATC movement references. It is not an
arrival-only capacity. Sequencing can spill flights beyond the study window.

`reference_tracks.json` contains six **partial observed FlightAware tracks**
for the bad-weather case. They are evidence references only: one recorded final
approach is eastbound while this simulation uses 25R westbound. The active
`observations.json` is empty and `tracks.csv` contains only synthetic
procedure tracks for all planned flights, including counterfactual 25R tracks
for the six observed identities, sampled every 20 seconds. Their simulated
slots and routes are alternatives, not continuations of the observed tracks. Thus
`astra.studies.vvts_cases.dataset_for_case(folder)` loads a coherent
counterfactual replay without mixing runway configurations. Synthetic tracks
retain the full queue tail after the two-hour demand window. Observed tracks
stop near 18:32 ICT. Their actual VVTS
landing times and runways are unknown; no later position is invented as an
observation. The synthetic arrival tracks use the existing STAR/ILS profile,
sampled with the 2,000 ft/min climb/descent cap and direct-to from a fan fix to
SOKAN or BOMSU. Every generated direct-to passes an altitude-window check at
the merge. Synthetic arrival pairs are sequenced against sampled TMA routes
for 10 NM horizontal and 20 NM similar-heading spacing within the TMA,
regardless of vertical separation. They are geometric study paths, not controller
instructions.

The October 7 METAR includes +TSRA, northeast wind, and an R07R runway visual
range report. Thus 25R synthetic approach geometry in that case is explicitly
counterfactual. October 7 and 8 `weather.csv` copy archived METAR/TAF evidence.
No February 22 METAR is available, so its fair-weather condition is an
assumption in the manifest; its `weather.csv` is header-only.
The bad-weather capacity assumption varies by 15-minute bin as
9, 8, 5, 3, 3, 5, 7, 8 combined movements, with its lowest values around the
observed 18:00 +TSRA report and later recovery. Those numbers are not
published airport capacity.

The `summary.json` separation audit counts aircraft pair-minutes inside the
40 NM TMA at 3,000–16,570 ft under 10 NM horizontal and under 20 NM with
similar heading. It is a diagnostic of these candidate trajectories, not an
ATC safety finding. The candidate baseline has close pairs that must be
resolved in the next traffic-behavior test before claiming realistic traffic
operation. Spacing, wake, runway throughput, weather effect, and actual
point-merge clearances need validation with playback material.

Regenerate deterministically in this project with
`.\\.venv\\Scripts\\python.exe scripts\\build_synthetic_vvts_cases.py`.
Add `--check` to compare the saved files to a fresh build and parse each saved case through the replay
adapter. No GA or ATFM measure optimization is run by this script.

Sources for scale and capacity context:

- [CAAV Tết 2026 outlook, about 1,025 VVTS flights planned on 22 Feb](https://caa.gov.vn/hoat-dong-nganh/cang-hkqt-noi-bai-va-tan-son-nhat-san-sang-phuong-an-phuc-vu-hanh-khach-dip-cao-diem-tet-nguyen-dan-2026-20260209144210927.htm)
- [CAAV temporary 46 movements/hour slot parameter for 2 Feb–3 Mar 2026](https://caa.gov.vn/hoat-dong-nganh/dieu-chinh-tham-so-dieu-phoi-slot-tai-cang-hang-khong-quoc-te-tan-son-nhat-20251023163405728.htm)
- [CAAV August 2026 traffic scale, about 740 flights/day](https://caa.gov.vn/hoat-dong-nganh/cang-hkqt-noi-bai-tan-son-nhat-trien-khai-dong-bo-cac-phuong-an-khai-thac-san-sang-phuc-vu-le-quoc-khanh-02-9-20260828093847766.htm)
- [CAAV April 2026 44/hour ordinary reference raised to 46/hour temporarily](https://caa.gov.vn/hoat-dong-nganh/dieu-chinh-tham-so-dieu-phoi-gio-ha-cat-canh-tai-cang-hang-khong-quoc-te-tan-son-nhat-dip-nghi-le-30-4-1-5-2026-20260414082347431.htm)
- [VATM storm response context reported by Báo Xây Dựng](https://baoxaydung.vn/mua-dong-phuc-tap-tai-tan-son-nhat-quan-ly-bay-tang-cuong-ung-truc-192261009182310606.htm)

The scale references do not establish the true traffic count in any of these
two-hour windows. The partial October 7 FlightAware board and six track
sources are documented under `scenarios/recorded/vvts_cases/bad_weather`.
"""


def build_all() -> dict[str, bytes]:
    study = json.loads((RECORDED / "study.json").read_text(encoding="utf-8"))
    result = {"README.md": README.encode("utf-8")}
    study["scenario_kind"] = "synthetic_reconstruction"
    study["recorded_source_package"] = "scenarios/recorded/vvts_cases"
    study["source_context"] = SOURCE_URLS
    result["study.json"] = json_bytes(study)
    for case in study["windows"]:
        for name, content in build_case(case).items():
            result[f"{case['id']}/{name}"] = content
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check deterministic outputs and replay parse")
    args = parser.parse_args()
    generated = build_all()
    if args.check:
        mismatches = [path for path, content in generated.items()
                      if not (OUT / path).exists() or (OUT / path).read_bytes() != content]
        if mismatches:
            raise SystemExit("Missing or stale generated files: " + ", ".join(mismatches))
        from astra.studies.vvts_cases import dataset_for_case
        for case_id in CAPACITY:
            data = dataset_for_case(OUT / case_id)
            if data is None or not data.points:
                raise SystemExit(f"No usable replay tracks in {case_id}")
            print(f"{case_id}: {len(data.points)} replay flights, {data.raw_count} samples")
        print("Synthetic scenario package is reproducible and replay-readable.")
    else:
        for path, content in generated.items():
            target = OUT / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        for case_id in CAPACITY:
            summary = json.loads(generated[f"{case_id}/summary.json"])
            print(f"{case_id}: {summary['planned_movements']} planned, "
                  f"{summary['flights_with_window_track']} tracked, "
                  f"{summary['synthetic_flights_spilling_after_window']} synthetic slots spill")
        print(f"Wrote {len(generated)} files under {OUT}")


if __name__ == "__main__":
    main()
