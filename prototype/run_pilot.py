from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path

import pandas as pd
from sklearn.cluster import KMeans


BASE_DIR = Path(__file__).resolve().parents[1]
DATASETS_DIR = BASE_DIR / "datasets"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"

SHIFT_DATA_FILE = DATASETS_DIR / "Employee Shift data.xlsx"
BUS_ROUTES_FILE = DATASETS_DIR / "Bus Routes curent.xlsx"
GEO_FILE = DATASETS_DIR / "Geocoordinates.xlsx"
OVERVIEW_FILE = DATASETS_DIR / "Kuwait Route Optimization - Overview.xlsx"

DEPOT_NAME = "Mahboula Complex - Mix"
BUS_COUNT = 13
BUS_CAPACITY = 22
BUFFER_MIN = 30
TARGET_DUTY_MIN = 9 * 60
HARD_DUTY_SPAN_MIN = 10 * 60
EVENING_SEED_HOUR = 14
MAX_STOPS_PER_TRIP = 6
MAX_TRIP_DURATION_MIN = 300
WAVE_BUCKET_MIN = 30
PEAK_BIN_MIN = 15
AVG_SPEED_KMPH = 38.0
ROAD_FACTOR = 1.18
STOP_DWELL_MIN = 5
IN_EARLY_LIMIT_MIN = 30
IN_TARGET_LEAD_MIN = 15
OUT_WAIT_LIMIT_MIN = 40
OUT_RESCUE_SHIFT_MIN = 40
MIXED_MAX_WAIT_MIN = 20


@dataclass(frozen=True)
class GeoPoint:
    store_name: str
    store_id: int
    latitude: float
    longitude: float


@dataclass
class DutySlot:
    bus_id: int
    slot_type: str
    available_after: pd.Timestamp | None = None
    first_start: pd.Timestamp | None = None
    last_end: pd.Timestamp | None = None
    trip_ids: list[str] | None = None

    def __post_init__(self) -> None:
        if self.trip_ids is None:
            self.trip_ids = []


def normalize_name(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip().casefold().replace("&", "and")
    text = re.sub(r"[()]", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def to_minutes(value: object) -> int | None:
    if pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime, time)):
        return value.hour * 60 + value.minute
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    for fmt in ("%H:%M:%S", "%I:%M %p", "%H:%M"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.hour * 60 + parsed.minute
        except ValueError:
            continue
    return None


def parse_duration_hours(value: object) -> float | None:
    if pd.isna(value):
        return None
    text = str(value).strip().lower().replace("hrs", "").replace("hr", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0088
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * radius_km * math.asin(math.sqrt(a))


def road_km(a: GeoPoint, b: GeoPoint) -> float:
    return haversine_km(a.latitude, a.longitude, b.latitude, b.longitude) * ROAD_FACTOR


def km_to_minutes(distance_km: float) -> float:
    return (distance_km / AVG_SPEED_KMPH) * 60.0


def load_overview_metrics() -> dict[str, object]:
    details = pd.read_excel(OVERVIEW_FILE, sheet_name="Details", header=None)
    pilot = details.iloc[:, 4:7].copy()
    pilot.columns = ["parameter", "value", "description"]
    pilot = pilot.iloc[1:].copy()
    pilot["parameter"] = pilot["parameter"].astype(str).str.strip()
    pilot = pilot[pilot["parameter"].ne("") & pilot["parameter"].ne("nan")]
    return {str(row["parameter"]): row["value"] for _, row in pilot.iterrows()}


def load_geocoordinates() -> dict[str, GeoPoint]:
    geo = pd.read_excel(GEO_FILE)
    geo["Store ID"] = pd.to_numeric(geo["Store ID"], errors="coerce")
    geo["latitude"] = pd.to_numeric(geo["latitude"], errors="coerce")
    geo["longitude"] = pd.to_numeric(geo["longitude"], errors="coerce")
    geo = geo.dropna(subset=["Store Name", "Store ID", "latitude", "longitude"]).copy()
    lookup: dict[str, GeoPoint] = {}
    for _, row in geo.iterrows():
        point = GeoPoint(
            store_name=str(row["Store Name"]).strip(),
            store_id=int(row["Store ID"]),
            latitude=float(row["latitude"]),
            longitude=float(row["longitude"]),
        )
        lookup[normalize_name(point.store_name)] = point
    return lookup


def build_strict_lookup(geo_lookup: dict[str, GeoPoint]) -> tuple[dict[str, GeoPoint], pd.DataFrame]:
    workbook = pd.ExcelFile(SHIFT_DATA_FILE)
    rows: list[dict[str, object]] = []
    for sheet in workbook.sheet_names:
        raw = workbook.parse(sheet, header=None)
        header = raw.iloc[2].tolist()
        body = raw.iloc[3:].copy()
        body.columns = header
        if "Store ID" not in body.columns or "Store Name" not in body.columns:
            continue
        tmp = body[["Store ID", "Store Name"]].dropna(subset=["Store ID", "Store Name"]).copy()
        tmp["Store ID"] = pd.to_numeric(tmp["Store ID"], errors="coerce")
        tmp = tmp.dropna(subset=["Store ID"]).copy()
        tmp["Store ID"] = tmp["Store ID"].astype(int)
        tmp["Store Name"] = tmp["Store Name"].astype(str).str.strip()
        tmp["norm_name"] = tmp["Store Name"].map(normalize_name)
        rows.extend(tmp.to_dict(orient="records"))
    shift_rows = pd.DataFrame(rows)
    grouped = (
        shift_rows.groupby("norm_name")
        .agg(
            shift_ids=("Store ID", lambda s: sorted(set(int(x) for x in s))),
            shift_names=("Store Name", lambda s: sorted(set(str(x) for x in s))),
        )
        .reset_index()
    )
    strict_lookup: dict[str, GeoPoint] = {}
    out_rows: list[dict[str, object]] = []
    for norm_name, point in geo_lookup.items():
        match = grouped[grouped["norm_name"] == norm_name]
        shift_ids = match["shift_ids"].iloc[0] if not match.empty else None
        strict_match = isinstance(shift_ids, list) and len(shift_ids) == 1 and shift_ids[0] == point.store_id
        out_rows.append(
            {
                "normalized_store_name": norm_name,
                "geo_store_name": point.store_name,
                "geo_store_id": point.store_id,
                "shift_store_names": None if match.empty else match["shift_names"].iloc[0],
                "shift_ids": shift_ids,
                "strict_match": strict_match,
            }
        )
        if strict_match:
            strict_lookup[norm_name] = point
    return strict_lookup, pd.DataFrame(out_rows)


def extract_shift_events(strict_lookup: dict[str, GeoPoint]) -> tuple[pd.DataFrame, pd.DataFrame]:
    workbook = pd.ExcelFile(SHIFT_DATA_FILE)
    event_rows: list[dict[str, object]] = []
    unmatched_rows: list[dict[str, object]] = []
    for sheet in workbook.sheet_names:
        raw = workbook.parse(sheet, header=None)
        date_row = raw.iloc[1].tolist()
        header_row = raw.iloc[2].tolist()
        body = raw.iloc[3:].copy()
        body.columns = header_row
        for row_idx, row in body.iterrows():
            store_name = "" if pd.isna(row.get("Store Name")) else str(row.get("Store Name")).strip()
            store_id = pd.to_numeric(row.get("Store ID"), errors="coerce")
            if not store_name:
                continue
            norm_name = normalize_name(store_name)
            point = strict_lookup.get(norm_name)
            employee_code = str(row.get("EMPLOYEE CODE", row_idx)).strip()
            if point is None or pd.isna(store_id) or int(store_id) != point.store_id:
                unmatched_rows.append(
                    {
                        "source_dataset": "Employee Shift data.xlsx",
                        "source_sheet": sheet,
                        "source_column": "Store Name",
                        "origin_id": employee_code,
                        "store_name": store_name,
                        "normalized_store_name": norm_name,
                        "source_store_id": "" if pd.isna(store_id) else int(store_id),
                        "reason": "no_strict_name_id_match",
                    }
                )
                continue
            for start_col in range(8, len(header_row), 4):
                if start_col + 3 >= len(header_row):
                    break
                base_date = date_row[start_col]
                if pd.isna(base_date):
                    continue
                base_date = pd.Timestamp(base_date).normalize()
                for shift_slot, start_idx, end_idx in ((1, start_col, start_col + 1), (2, start_col + 2, start_col + 3)):
                    start_min = to_minutes(row.iloc[start_idx])
                    end_min = to_minutes(row.iloc[end_idx])
                    if start_min is None or end_min is None:
                        continue
                    shift_start = base_date + timedelta(minutes=start_min)
                    shift_end = base_date + timedelta(minutes=end_min)
                    if end_min < start_min:
                        shift_end += timedelta(days=1)
                    common = {
                        "employee_code": employee_code,
                        "store_id": point.store_id,
                        "store_name": point.store_name,
                        "latitude": point.latitude,
                        "longitude": point.longitude,
                        "shift_slot": shift_slot,
                    }
                    event_rows.append({**common, "direction": "IN", "event_dt": shift_start, "event_date": shift_start.date().isoformat()})
                    event_rows.append({**common, "direction": "OUT", "event_dt": shift_end, "event_date": shift_end.date().isoformat()})
    return pd.DataFrame(event_rows), pd.DataFrame(unmatched_rows)


def cluster_stores(events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    stores = (
        events.groupby(["store_id", "store_name", "latitude", "longitude"], dropna=False)
        .size()
        .reset_index(name="weekly_employee_events")
    )
    cluster_count = max(1, min(len(stores), math.ceil(len(stores) / 14)))
    model = KMeans(n_clusters=cluster_count, random_state=42, n_init=10)
    stores["cluster_id"] = model.fit_predict(stores[["latitude", "longitude"]], sample_weight=stores["weekly_employee_events"])
    summary = (
        stores.groupby("cluster_id")
        .agg(store_count=("store_name", "count"), weekly_employee_events=("weekly_employee_events", "sum"))
        .reset_index()
    )
    return stores, summary


def aggregate_store_waves(events: pd.DataFrame, stores_with_clusters: pd.DataFrame) -> pd.DataFrame:
    demand = events.merge(stores_with_clusters[["store_id", "cluster_id"]], on="store_id", how="left")
    demand["wave_dt"] = demand["event_dt"].dt.floor(f"{WAVE_BUCKET_MIN}min")
    grouped = (
        demand.groupby(
            ["event_date", "direction", "wave_dt", "store_id", "store_name", "latitude", "longitude", "cluster_id"],
            dropna=False,
        )
        .size()
        .reset_index(name="employees")
    )
    grouped["wave_label"] = grouped["wave_dt"].dt.strftime("%Y-%m-%d %H:%M")
    return grouped.sort_values(["wave_dt", "direction", "store_name"]).reset_index(drop=True)


def build_peak_pressure(demand: pd.DataFrame) -> pd.DataFrame:
    bins = demand.copy()
    bins["peak_bin_dt"] = bins["wave_dt"].dt.floor(f"{PEAK_BIN_MIN}min")
    summary = bins.groupby(["peak_bin_dt", "direction"], dropna=False)["employees"].sum().reset_index()
    summary["theoretical_buses"] = summary["employees"].apply(lambda x: math.ceil(x / BUS_CAPACITY))
    return summary


def point_from_row(row: pd.Series | dict[str, object]) -> GeoPoint:
    return GeoPoint(str(row["store_name"]), int(row["store_id"]), float(row["latitude"]), float(row["longitude"]))


def nearest_neighbor_sequence(depot: GeoPoint, stops: list[GeoPoint]) -> list[GeoPoint]:
    remaining = stops.copy()
    ordered: list[GeoPoint] = []
    current = depot
    while remaining:
        next_point = min(remaining, key=lambda point: road_km(current, point))
        ordered.append(next_point)
        remaining.remove(next_point)
        current = next_point
    return ordered


def route_metrics(depot: GeoPoint, stops: list[GeoPoint]) -> tuple[float, float]:
    if not stops:
        return 0.0, 0.0
    ordered = nearest_neighbor_sequence(depot, stops)
    distance = road_km(depot, ordered[0])
    for prev, curr in zip(ordered, ordered[1:]):
        distance += road_km(prev, curr)
    distance += road_km(ordered[-1], depot)
    duration = km_to_minutes(distance) + STOP_DWELL_MIN * len(ordered)
    return distance, duration


def build_base_trips(demand: pd.DataFrame, depot: GeoPoint) -> pd.DataFrame:
    trip_rows: list[dict[str, object]] = []
    trip_counter = 1
    for direction, direction_group in demand.groupby("direction", dropna=False):
        pool = direction_group.copy().reset_index(drop=True)
        pool["remaining"] = pool["employees"]
        while int(pool["remaining"].sum()) > 0:
            active = pool[pool["remaining"] > 0].copy()
            seed_idx = active.sort_values(["wave_dt", "remaining", "store_name"], ascending=[True, False, True]).index[0]
            seed = pool.loc[seed_idx]
            seed_wave = pd.Timestamp(seed["wave_dt"])
            seed_point = point_from_row(seed)
            candidates = pool[pool["remaining"] > 0].copy()
            candidates["wave_gap"] = candidates["wave_dt"].apply(lambda dt: abs((pd.Timestamp(dt) - seed_wave).total_seconds()) / 60.0)
            candidates["distance"] = [road_km(seed_point, point_from_row(candidates.loc[idx])) for idx in candidates.index]
            candidates = candidates.sort_values(["wave_gap", "distance", "remaining", "store_name"], ascending=[True, True, False, True])
            selected_rows: list[dict[str, object]] = []
            selected_points: list[GeoPoint] = []
            remaining_capacity = BUS_CAPACITY
            for idx in candidates.index:
                row = pool.loc[idx]
                if int(row["remaining"]) <= 0:
                    continue
                if abs((pd.Timestamp(row["wave_dt"]) - seed_wave).total_seconds()) / 60.0 > 60:
                    continue
                point = point_from_row(row)
                trial_points = selected_points + [point]
                _, trial_duration = route_metrics(depot, trial_points)
                if len(trial_points) > MAX_STOPS_PER_TRIP or trial_duration > MAX_TRIP_DURATION_MIN:
                    continue
                allocated = min(int(row["remaining"]), remaining_capacity)
                if allocated <= 0:
                    continue
                selected_rows.append(
                    {
                        "store_id": int(row["store_id"]),
                        "store_name": str(row["store_name"]),
                        "latitude": float(row["latitude"]),
                        "longitude": float(row["longitude"]),
                        "cluster_id": int(row["cluster_id"]) if pd.notna(row["cluster_id"]) else None,
                        "wave_dt": pd.Timestamp(row["wave_dt"]),
                        "allocated_passengers": allocated,
                    }
                )
                selected_points.append(point)
                pool.loc[idx, "remaining"] = int(row["remaining"]) - allocated
                remaining_capacity -= allocated
                if remaining_capacity == 0:
                    break
            ordered_points = nearest_neighbor_sequence(depot, selected_points)
            ordered_names = [point.store_name for point in ordered_points]
            selected_rows = sorted(selected_rows, key=lambda row: ordered_names.index(row["store_name"]))
            distance, duration = route_metrics(depot, ordered_points)
            passengers = int(sum(int(row["allocated_passengers"]) for row in selected_rows))
            min_wave = min(row["wave_dt"] for row in selected_rows)
            max_wave = max(row["wave_dt"] for row in selected_rows)
            if direction == "IN":
                latest_arrival = max_wave + timedelta(minutes=WAVE_BUCKET_MIN)
                earliest_start = min_wave - timedelta(minutes=IN_EARLY_LIMIT_MIN + duration)
                latest_start = latest_arrival - timedelta(minutes=duration)
                requested_start = latest_arrival - timedelta(minutes=IN_TARGET_LEAD_MIN + duration)
            else:
                earliest_start = min_wave
                latest_start = max_wave + timedelta(minutes=OUT_WAIT_LIMIT_MIN)
                requested_start = earliest_start
            planned_start = max(earliest_start, min(requested_start, latest_start))
            planned_end = planned_start + timedelta(minutes=duration)
            trip_rows.append(
                {
                    "trip_id": f"NEW_{trip_counter:04d}",
                    "trip_type": direction,
                    "direction": direction,
                    "service_date": planned_start.date().isoformat(),
                    "cluster_id": selected_rows[0]["cluster_id"] if selected_rows else None,
                    "requested_wave_dt": seed_wave,
                    "requested_wave_label": seed_wave.strftime("%Y-%m-%d %H:%M"),
                    "earliest_start_dt": earliest_start,
                    "latest_start_dt": latest_start,
                    "planned_start_dt": planned_start,
                    "planned_end_dt": planned_end,
                    "trip_duration_min": round(float(duration), 2),
                    "route_distance_km": round(float(distance), 3),
                    "stop_count": len(selected_rows),
                    "peak_load": passengers,
                    "assigned_passengers": passengers,
                    "occupancy_pct": round((passengers / BUS_CAPACITY) * 100, 2),
                    "store_sequence": " -> ".join(ordered_names),
                    "store_passenger_plan": " | ".join(f"{row['store_name']} ({int(row['allocated_passengers'])})" for row in selected_rows),
                }
            )
            trip_counter += 1
    return pd.DataFrame(trip_rows).sort_values(["planned_start_dt", "trip_type", "trip_id"]).reset_index(drop=True)


def init_slots(service_dates: list[str]) -> dict[tuple[str, int, str], DutySlot]:
    slots: dict[tuple[str, int, str], DutySlot] = {}
    for service_day in service_dates:
        for bus_id in range(1, BUS_COUNT + 1):
            slots[(service_day, bus_id, "morning")] = DutySlot(bus_id=bus_id, slot_type="morning")
            slots[(service_day, bus_id, "evening")] = DutySlot(bus_id=bus_id, slot_type="evening")
    return slots


def slot_preference(trip_type: str, start_dt: pd.Timestamp) -> list[str]:
    if trip_type == "OUT" or start_dt.hour >= EVENING_SEED_HOUR:
        return ["evening", "morning"]
    return ["morning", "evening"]


def slot_is_feasible(slot: DutySlot, trip: pd.Series, day_assignments: pd.DataFrame, extra_delay_min: int = 0) -> tuple[bool, pd.Timestamp | None]:
    earliest = pd.Timestamp(trip["earliest_start_dt"])
    latest = pd.Timestamp(trip["latest_start_dt"]) + timedelta(minutes=extra_delay_min)
    if slot.slot_type == "evening":
        earliest = max(earliest, pd.Timestamp(earliest.date()) + timedelta(hours=EVENING_SEED_HOUR))
    candidate_start = earliest if slot.available_after is None else max(earliest, slot.available_after + timedelta(minutes=BUFFER_MIN))
    if candidate_start > latest:
        return False, None
    candidate_end = candidate_start + timedelta(minutes=float(trip["trip_duration_min"]))
    if slot.first_start is not None:
        span = (candidate_end - slot.first_start).total_seconds() / 60.0
        if span > HARD_DUTY_SPAN_MIN:
            return False, None
    if not day_assignments.empty and "bus_id" in day_assignments.columns:
        for row in day_assignments[day_assignments["bus_id"] == slot.bus_id].itertuples(index=False):
            if not (candidate_end <= pd.Timestamp(row.planned_start_dt) or candidate_start >= pd.Timestamp(row.planned_end_dt)):
                return False, None
    return True, candidate_start


def schedule_with_rotation_reset(base_trips: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    trips = base_trips.copy().sort_values(["planned_start_dt", "peak_load", "trip_id"], ascending=[True, False, True]).reset_index(drop=True)
    service_dates = sorted(trips["service_date"].astype(str).unique())
    slots = init_slots(service_dates)
    scheduled_rows: list[dict[str, object]] = []
    assignment_rows: list[dict[str, object]] = []
    unscheduled_rows: list[dict[str, object]] = []

    for _, trip in trips.iterrows():
        service_day = str(trip["service_date"])
        day_assignments = pd.DataFrame(assignment_rows)
        if not day_assignments.empty:
            day_assignments = day_assignments[day_assignments["service_date"] == service_day]
        best_choice: tuple[tuple[str, int, str], pd.Timestamp, bool] | None = None
        for rescue in (False, True):
            extra_delay = OUT_RESCUE_SHIFT_MIN if rescue and trip["trip_type"] == "OUT" else 0
            for slot_type in slot_preference(str(trip["trip_type"]), pd.Timestamp(trip["planned_start_dt"])):
                for bus_id in range(1, BUS_COUNT + 1):
                    slot_key = (service_day, bus_id, slot_type)
                    ok, start_dt = slot_is_feasible(slots[slot_key], trip, day_assignments, extra_delay_min=extra_delay)
                    if not ok or start_dt is None:
                        continue
                    candidate = (slot_key, start_dt, rescue)
                    if best_choice is None or (start_dt, rescue, bus_id) < (best_choice[1], best_choice[2], best_choice[0][1]):
                        best_choice = candidate
            if best_choice is not None:
                break
        if best_choice is None:
            unscheduled_rows.append(
                {
                    "trip_id": trip["trip_id"],
                    "trip_type": trip["trip_type"],
                    "requested_wave_label": trip["requested_wave_label"],
                    "reason": "fleet_or_freshness_block",
                    "assigned_passengers": int(trip["assigned_passengers"]),
                    "peak_load": int(trip["peak_load"]),
                }
            )
            continue

        slot_key, start_dt, rescued = best_choice
        service_day, bus_id, slot_type = slot_key
        end_dt = pd.Timestamp(start_dt) + timedelta(minutes=float(trip["trip_duration_min"]))
        slot = slots[slot_key]
        if slot.first_start is None:
            slot.first_start = pd.Timestamp(start_dt)
        slot.available_after = end_dt
        slot.last_end = end_dt
        slot.trip_ids.append(str(trip["trip_id"]))
        trip_dict = trip.to_dict()
        trip_dict["service_date"] = service_day
        trip_dict["planned_start_dt"] = pd.Timestamp(start_dt)
        trip_dict["planned_end_dt"] = end_dt
        trip_dict["rescued_by_delay"] = rescued
        trip_dict["rotation_tag"] = slot_type
        scheduled_rows.append(trip_dict)
        assignment_rows.append(
            {
                "trip_id": trip["trip_id"],
                "trip_type": trip["trip_type"],
                "service_date": service_day,
                "bus_id": bus_id,
                "rotation_tag": slot_type,
                "planned_start_dt": pd.Timestamp(start_dt),
                "planned_end_dt": end_dt,
                "trip_duration_min": float(trip["trip_duration_min"]),
                "occupancy_pct": float(trip["occupancy_pct"]),
                "assigned_passengers": int(trip["assigned_passengers"]),
                "rescued_by_delay": rescued,
                "handover_flag": slot_type == "evening",
            }
        )

    scheduled = pd.DataFrame(scheduled_rows).sort_values(["planned_start_dt", "trip_id"]).reset_index(drop=True)
    assignments = pd.DataFrame(assignment_rows).sort_values(["planned_start_dt", "bus_id"]).reset_index(drop=True)
    unscheduled = pd.DataFrame(unscheduled_rows)
    return scheduled, assignments, unscheduled


def add_mixed_labels(scheduled: pd.DataFrame, assignments: pd.DataFrame) -> pd.DataFrame:
    if scheduled.empty or assignments.empty:
        return scheduled
    updated = scheduled.copy()
    for _, group in assignments.sort_values(["bus_id", "planned_start_dt"]).groupby(["service_date", "bus_id"], dropna=False):
        rows = list(group.itertuples(index=False))
        for prev, curr in zip(rows, rows[1:]):
            if prev.trip_type != "IN" or curr.trip_type != "OUT":
                continue
            gap_min = (pd.Timestamp(curr.planned_start_dt) - pd.Timestamp(prev.planned_end_dt)).total_seconds() / 60.0
            if 0 <= gap_min <= MIXED_MAX_WAIT_MIN:
                updated.loc[updated["trip_id"] == prev.trip_id, "trip_type"] = "MIXED"
    return updated


def build_duties(assignments: pd.DataFrame) -> pd.DataFrame:
    if assignments.empty:
        return pd.DataFrame()
    duty_rows: list[dict[str, object]] = []
    duty_counter = 1
    for (service_day, bus_id, rotation_tag), group in assignments.groupby(["service_date", "bus_id", "rotation_tag"], dropna=False):
        group = group.sort_values("planned_start_dt")
        first_start = pd.Timestamp(group["planned_start_dt"].min())
        last_end = pd.Timestamp(group["planned_end_dt"].max())
        duty_rows.append(
            {
                "duty_id": f"DUTY_{duty_counter:04d}",
                "bus_id": bus_id,
                "service_date": service_day,
                "rotation_tag": rotation_tag,
                "first_trip_start_dt": first_start,
                "last_trip_end_dt": last_end,
                "trip_count": int(len(group)),
                "trip_minutes": float(group["trip_duration_min"].sum()),
                "avg_occupancy_pct": float(group["occupancy_pct"].mean()),
                "rescued_trip_count": int(group["rescued_by_delay"].sum()),
                "handover_trip_count": int(group["handover_flag"].sum()),
            }
        )
        duty_counter += 1
    duties = pd.DataFrame(duty_rows).sort_values(["first_trip_start_dt", "bus_id"]).reset_index(drop=True)
    duties["duty_span_min"] = (pd.to_datetime(duties["last_trip_end_dt"]) - pd.to_datetime(duties["first_trip_start_dt"])).dt.total_seconds() / 60.0
    duties["overtime_min"] = (duties["duty_span_min"] - TARGET_DUTY_MIN).clip(lower=0)
    duties["over_10h_flag"] = duties["duty_span_min"] > HARD_DUTY_SPAN_MIN
    return duties


def calibrate_baseline() -> tuple[pd.DataFrame, dict[str, float]]:
    issues_raw = pd.read_excel(BUS_ROUTES_FILE, sheet_name="Issues - Bus Route", header=None)
    issues = issues_raw.iloc[2:].copy()
    issues.columns = [
        "driver_key",
        "driver_number",
        "driver_name",
        "new_trips",
        "schedule_trip_count",
        "schedule_avg_trip_hours",
        "schedule_total_working_hours",
        "payment_trip_count",
        "payment_avg_trip_hours",
        "payment_total_working_hours",
        "overtime_hours",
        "issue",
    ]
    issues = issues.dropna(subset=["driver_key", "driver_name"], how="all").copy()
    issues["reported_overtime_hours"] = issues["overtime_hours"].map(parse_duration_hours)
    issues["schedule_avg_trip_hours_num"] = issues["schedule_avg_trip_hours"].map(parse_duration_hours)
    metrics = {
        "reported_overtime_minutes": float(issues["reported_overtime_hours"].fillna(0).sum() * 60),
        "baseline_avg_trip_minutes": float(issues["schedule_avg_trip_hours_num"].dropna().mean() * 60) if issues["schedule_avg_trip_hours_num"].dropna().any() else 0.0,
    }
    return issues, metrics


def compute_max_concurrent(assignments: pd.DataFrame) -> int:
    if assignments.empty:
        return 0
    events: list[tuple[pd.Timestamp, int]] = []
    for row in assignments.itertuples(index=False):
        events.append((pd.Timestamp(row.planned_start_dt), 1))
        events.append((pd.Timestamp(row.planned_end_dt), -1))
    events.sort(key=lambda item: (item[0], -item[1]))
    current = 0
    peak = 0
    for _, delta in events:
        current += delta
        peak = max(peak, current)
    return peak


def build_kpis(
    overview: dict[str, object],
    strict_matches: pd.DataFrame,
    demand: pd.DataFrame,
    peak_pressure: pd.DataFrame,
    base_trips: pd.DataFrame,
    scheduled: pd.DataFrame,
    assignments: pd.DataFrame,
    duties: pd.DataFrame,
    unmatched: pd.DataFrame,
    unscheduled: pd.DataFrame,
    baseline_metrics: dict[str, float],
) -> pd.DataFrame:
    assigned_passengers = int(scheduled["assigned_passengers"].sum()) if not scheduled.empty else 0
    total_demand = int(demand["employees"].sum()) if not demand.empty else 0
    total_offered_seats = int(len(scheduled) * BUS_CAPACITY)
    weighted_occ = (assigned_passengers / total_offered_seats) * 100 if total_offered_seats else 0.0
    max_concurrent = compute_max_concurrent(assignments)
    rows = [
        ("pilot_total_stores_overview", overview.get("Total Stores", "")),
        ("pilot_vehicle_count_overview", overview.get("Vehicle No", BUS_COUNT)),
        ("strict_store_name_id_matches", int(strict_matches["strict_match"].sum()) if not strict_matches.empty else 0),
        ("demand_rows", int(len(demand))),
        ("total_weekly_employee_demand_events", total_demand),
        ("unique_routeable_demand_stores", int(demand["store_name"].nunique()) if not demand.empty else 0),
        ("theoretical_peak_buses_from_demand", int(peak_pressure["theoretical_buses"].max()) if not peak_pressure.empty else 0),
        ("designed_trip_count", int(len(base_trips))),
        ("scheduled_trip_count", int(len(scheduled))),
        ("unscheduled_trip_count", int(len(unscheduled))),
        ("in_trip_count", int((scheduled["trip_type"] == "IN").sum()) if not scheduled.empty else 0),
        ("out_trip_count", int((scheduled["trip_type"] == "OUT").sum()) if not scheduled.empty else 0),
        ("mixed_trip_count", int((scheduled["trip_type"] == "MIXED").sum()) if not scheduled.empty else 0),
        ("avg_trip_duration_min", round(float(scheduled["trip_duration_min"].mean()), 2) if not scheduled.empty else 0.0),
        ("total_designed_route_distance_km", round(float(scheduled["route_distance_km"].sum()), 3) if not scheduled.empty else 0.0),
        ("avg_stop_count_per_trip", round(float(scheduled["stop_count"].mean()), 2) if not scheduled.empty else 0.0),
        ("avg_trip_occupancy_pct", round(float(scheduled["occupancy_pct"].mean()), 2) if not scheduled.empty else 0.0),
        ("weighted_avg_occupancy_pct", round(weighted_occ, 2)),
        ("total_offered_seats", total_offered_seats),
        ("total_assigned_passengers", assigned_passengers),
        ("coverage_pct_of_demand", round((assigned_passengers / total_demand) * 100, 2) if total_demand else 0.0),
        ("max_concurrent_trips", max_concurrent),
        ("fleet_limit_breach_vs_13_buses", max(0, max_concurrent - BUS_COUNT)),
        ("duty_count", int(len(duties))),
        ("duty_count_over_9h", int((duties["overtime_min"] > 0).sum()) if not duties.empty else 0),
        ("duty_count_over_10h", int(duties["over_10h_flag"].sum()) if not duties.empty else 0),
        ("avg_duty_span_min", round(float(duties["duty_span_min"].mean()), 2) if not duties.empty else 0.0),
        ("total_overtime_minutes_over_9h", round(float(duties["overtime_min"].sum()), 2) if not duties.empty else 0.0),
        ("max_duty_overtime_minutes", round(float(duties["overtime_min"].max()), 2) if not duties.empty else 0.0),
        ("rescued_trip_count", int(assignments["rescued_by_delay"].sum()) if not assignments.empty else 0),
        ("handover_trip_count", int(assignments["handover_flag"].sum()) if not assignments.empty else 0),
        ("baseline_reported_overtime_minutes", round(float(baseline_metrics["reported_overtime_minutes"]), 2)),
        ("baseline_reported_avg_trip_minutes", round(float(baseline_metrics["baseline_avg_trip_minutes"]), 2)),
        ("unique_unmatched_places", int(unmatched["store_name"].nunique()) if not unmatched.empty else 0),
        ("unmatched_place_occurrences", int(len(unmatched))),
    ]
    return pd.DataFrame(rows, columns=["metric", "value"])


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    overview = load_overview_metrics()
    geo_lookup = load_geocoordinates()
    strict_lookup, strict_matches = build_strict_lookup(geo_lookup)
    events, unmatched = extract_shift_events(strict_lookup)
    stores_with_clusters, clusters_summary = cluster_stores(events)
    demand = aggregate_store_waves(events, stores_with_clusters)
    peak_pressure = build_peak_pressure(demand)
    depot = geo_lookup.get(normalize_name(DEPOT_NAME))
    if depot is None:
        raise RuntimeError(f"Depot '{DEPOT_NAME}' not found in geocoordinates.")
    base_trips = build_base_trips(demand, depot)
    scheduled, assignments, unscheduled = schedule_with_rotation_reset(base_trips)
    scheduled = add_mixed_labels(scheduled, assignments)
    duties = build_duties(assignments)
    baseline_issues, baseline_metrics = calibrate_baseline()
    kpis = build_kpis(overview, strict_matches, demand, peak_pressure, base_trips, scheduled, assignments, duties, unmatched, unscheduled, baseline_metrics)
    strict_matches.to_csv(OUTPUT_DIR / "strict_store_matches.csv", index=False)
    stores_with_clusters.to_csv(OUTPUT_DIR / "stores_with_clusters.csv", index=False)
    clusters_summary.to_csv(OUTPUT_DIR / "clusters_summary.csv", index=False)
    demand.to_csv(OUTPUT_DIR / "demand_by_store_shift_window.csv", index=False)
    peak_pressure.to_csv(OUTPUT_DIR / "peak_pressure_summary.csv", index=False)
    base_trips.to_csv(OUTPUT_DIR / "designed_trips_raw.csv", index=False)
    scheduled.to_csv(OUTPUT_DIR / "trip_routes.csv", index=False)
    assignments.to_csv(OUTPUT_DIR / "trip_assignments.csv", index=False)
    duties.to_csv(OUTPUT_DIR / "driver_metrics.csv", index=False)
    unscheduled.to_csv(OUTPUT_DIR / "unscheduled_trips.csv", index=False)
    unmatched.to_csv(OUTPUT_DIR / "unmatched_stores.csv", index=False)
    baseline_issues.to_csv(OUTPUT_DIR / "baseline_overtime_reference.csv", index=False)
    kpis.to_csv(OUTPUT_DIR / "kpi_summary.csv", index=False)
    print("Prototype rebuilt from scratch.")
    print(f"Designed trips: {len(base_trips)}")
    print(f"Scheduled trips: {len(scheduled)}")
    print(f"Outputs written to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
