from __future__ import annotations

import json
import math
import re
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path

import pandas as pd
from sklearn.cluster import KMeans
try:
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2
    ORTOOLS_AVAILABLE = True
except Exception:
    pywrapcp = None
    routing_enums_pb2 = None
    ORTOOLS_AVAILABLE = False


BASE_DIR = Path(__file__).resolve().parents[1]
DATASETS_DIR = BASE_DIR / "datasets"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
EMPLOYER_OUTPUT_DIR = OUTPUT_DIR / "employer_format"

SHIFT_DATA_FILE = DATASETS_DIR / "Employee Shift data.xlsx"
BUS_ROUTES_FILE = DATASETS_DIR / "Bus Routes curent.xlsx"
GEO_FILE = DATASETS_DIR / "Geocoordinates.xlsx"
OVERVIEW_FILE = DATASETS_DIR / "Kuwait Route Optimization - Overview.xlsx"

DEPOT_NAME = "Mahboula Complex - Mix"
BUS_COUNT = 13
BUS_CAPACITY = 22
BUFFER_MIN = 30
SHORT_TRIP_BUFFER_MIN = 15
MEDIUM_TRIP_BUFFER_MIN = 20
SHORT_TRIP_THRESHOLD_MIN = 40
MEDIUM_TRIP_THRESHOLD_MIN = 90
SPLIT_DUTY_RESET_MIN = 180
SPLIT_DUTY_RESET_START_HOUR = 12
TARGET_DUTY_MIN = 9 * 60
HARD_DUTY_SPAN_MIN = 10 * 60
EVENING_SEED_HOUR = 14
MAX_STOPS_PER_TRIP = 6
MAX_TRIP_DURATION_MIN = 300
WAVE_BUCKET_MIN = 30
SALVAGE_WAVE_BUCKET_MIN = 60
COOP_MERGE_WAVE_BUCKET_MIN = 90
PEAK_BIN_MIN = 15
AVG_SPEED_KMPH = 38.0
ROAD_FACTOR = 1.18
STOP_DWELL_MIN = 5
IN_EARLY_LIMIT_MIN = 30
IN_TARGET_LEAD_MIN = 15
OUT_WAIT_LIMIT_MIN = 40
MIXED_MAX_WAIT_MIN = 20
MIXED_MAX_ATTACH_MIN = 60
MIXED_MAX_DETOUR_KM = 6.0
MIXED_SKIP_PENALTY_PER_PASSENGER = 1000
MIXED_MAX_EXTRA_STOPS = 5
MIXED_HOST_CANDIDATES = 8
FRAGMENT_HOST_CANDIDATES = 8
COOP_MERGE_MAX_PASSENGERS = 6
COOP_MERGE_MAX_STOPS = 3
REPAIR_SHIFT_OPTIONS_OUT = [10, 20, 30, 40]
REPAIR_SHIFT_OPTIONS_IN = [-15, 15, -30, 30]
BOTTLENECK_HOURS = {5, 18}
DONOR_SHIFT_OPTIONS = [-30, -20, -15, -10, 10, 15, 20, 30]
OVERTIME_IMPROVEMENT_PASSES = 2

# === SEARCH HOOK: CONSTANTS / TUNING KNOBS ===
# Fast place to inspect or tune the fleet cap, buffer policy, split-duty reset rule,
# mixed-trip tolerances, and repair limits.


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
    last_trip_duration_min: float | None = None
    segment_id: int = 1
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


def load_shift_service_dates() -> list[str]:
    workbook = pd.ExcelFile(SHIFT_DATA_FILE)
    dates: set[str] = set()
    for sheet in workbook.sheet_names:
        raw = workbook.parse(sheet, header=None)
        if raw.shape[0] < 2:
            continue
        date_row = raw.iloc[1].tolist()
        for start_col in range(8, len(date_row), 4):
            if start_col >= len(date_row):
                break
            base_date = date_row[start_col]
            if pd.isna(base_date):
                continue
            dates.add(pd.Timestamp(base_date).normalize().date().isoformat())
    return sorted(dates)


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
            employee_name = "" if pd.isna(row.get("EMPLOYEE NAME")) else str(row.get("EMPLOYEE NAME")).strip()
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
                        "employee_name": employee_name,
                        "store_id": point.store_id,
                        "store_name": point.store_name,
                        "latitude": point.latitude,
                        "longitude": point.longitude,
                        "shift_slot": shift_slot,
                        "shift_start_dt": shift_start,
                        "shift_end_dt": shift_end,
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
    return route_metrics_ordered(depot, ordered)


def route_metrics_ordered(depot: GeoPoint, ordered: list[GeoPoint]) -> tuple[float, float]:
    if not ordered:
        return 0.0, 0.0
    distance = road_km(depot, ordered[0])
    for prev, curr in zip(ordered, ordered[1:]):
        distance += road_km(prev, curr)
    distance += road_km(ordered[-1], depot)
    duration = km_to_minutes(distance) + STOP_DWELL_MIN * len(ordered)
    return distance, duration


def candidate_start_times(earliest: pd.Timestamp, latest: pd.Timestamp) -> list[pd.Timestamp]:
    if latest < earliest:
        return [earliest]
    current = earliest.floor(f"{PEAK_BIN_MIN}min")
    if current < earliest:
        current += timedelta(minutes=PEAK_BIN_MIN)
    starts = [earliest]
    while current < latest:
        starts.append(current)
        current += timedelta(minutes=PEAK_BIN_MIN)
    if latest not in starts:
        starts.append(latest)
    return sorted(set(starts))


def overlap_bins(start_dt: pd.Timestamp, end_dt: pd.Timestamp) -> list[pd.Timestamp]:
    current = start_dt.floor(f"{PEAK_BIN_MIN}min")
    end_floor = end_dt.floor(f"{PEAK_BIN_MIN}min")
    bins: list[pd.Timestamp] = []
    while current <= end_floor:
        bins.append(current)
        current += timedelta(minutes=PEAK_BIN_MIN)
    return bins


def choose_start_with_pressure(
    requested_start: pd.Timestamp,
    earliest_start: pd.Timestamp,
    latest_start: pd.Timestamp,
    duration_min: float,
    activity_counts: dict[pd.Timestamp, int],
) -> pd.Timestamp:
    best_start = requested_start
    best_score: tuple[float, float, pd.Timestamp] | None = None
    for candidate in candidate_start_times(earliest_start, latest_start):
        end_dt = candidate + timedelta(minutes=float(duration_min))
        bins = overlap_bins(candidate, end_dt)
        overload = sum(max(0, activity_counts.get(bin_dt, 0) + 1 - BUS_COUNT) for bin_dt in bins)
        pressure = sum(activity_counts.get(bin_dt, 0) for bin_dt in bins)
        deviation = abs((candidate - requested_start).total_seconds()) / 60.0
        score = (overload * 1000 + pressure, deviation, candidate)
        if best_score is None or score < best_score:
            best_score = score
            best_start = candidate
    return best_start


def add_trip_to_activity(start_dt: pd.Timestamp, end_dt: pd.Timestamp, activity_counts: dict[pd.Timestamp, int]) -> None:
    for bin_dt in overlap_bins(start_dt, end_dt):
        activity_counts[bin_dt] = activity_counts.get(bin_dt, 0) + 1


def build_base_trips(demand: pd.DataFrame, depot: GeoPoint) -> pd.DataFrame:
    trip_rows: list[dict[str, object]] = []
    trip_counter = 1
    activity_counts: dict[pd.Timestamp, int] = {}
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
            requested_start = max(earliest_start, min(requested_start, latest_start))
            planned_start = choose_start_with_pressure(requested_start, earliest_start, latest_start, duration, activity_counts)
            planned_end = planned_start + timedelta(minutes=duration)
            add_trip_to_activity(planned_start, planned_end, activity_counts)
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
                    "stop_data_json": json.dumps(selected_rows, default=str),
                }
            )
            trip_counter += 1
    return pd.DataFrame(trip_rows).sort_values(["planned_start_dt", "trip_type", "trip_id"]).reset_index(drop=True)


def solve_wave_routes_ortools(batch: pd.DataFrame, depot: GeoPoint) -> list[list[dict[str, object]]]:
    # === SEARCH HOOK: ORTOOLS / BASE ROUTE SOLVER ===
    # Purpose:
    # Build route groupings inside one time-compatible demand batch.
    # How:
    # Treat each store-wave row as a customer node and let OR-Tools decide which
    # stops belong together and in what order under capacity + duration limits.
    # Example:
    # Three 09:00 IN stores may come back as one route [B, A, C] instead of
    # three separate single-stop trips.
    if batch.empty or not ORTOOLS_AVAILABLE:
        return []
    rows = batch.to_dict(orient="records")
    demands = [0] + [int(row["employees"]) for row in rows]
    node_points = [depot] + [point_from_row(row) for row in rows]
    size = len(node_points)

    time_matrix: list[list[int]] = []
    for i in range(size):
        row_times: list[int] = []
        for j in range(size):
            if i == j:
                row_times.append(0)
            else:
                travel = km_to_minutes(road_km(node_points[i], node_points[j]))
                dwell = 0 if i == 0 else STOP_DWELL_MIN
                row_times.append(int(round(travel + dwell)))
        time_matrix.append(row_times)

    num_vehicles = len(rows)
    manager = pywrapcp.RoutingIndexManager(size, num_vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)

    def transit_callback(from_index: int, to_index: int) -> int:
        return time_matrix[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]

    transit_idx = routing.RegisterTransitCallback(transit_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)

    def demand_callback(from_index: int) -> int:
        return demands[manager.IndexToNode(from_index)]

    demand_idx = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(
        demand_idx,
        0,
        [BUS_CAPACITY] * num_vehicles,
        True,
        "Capacity",
    )
    routing.AddDimension(
        transit_idx,
        0,
        MAX_TRIP_DURATION_MIN,
        True,
        "Time",
    )
    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    search_params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search_params.time_limit.seconds = 1
    solution = routing.SolveWithParameters(search_params)
    if solution is None:
        return []

    routes: list[list[dict[str, object]]] = []
    for vehicle_id in range(num_vehicles):
        index = routing.Start(vehicle_id)
        route_nodes: list[dict[str, object]] = []
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            if node != 0:
                route_nodes.append(rows[node - 1].copy())
            index = solution.Value(routing.NextVar(index))
        if route_nodes:
            routes.append(route_nodes)
    return routes


def build_base_trips_ortools(demand: pd.DataFrame, depot: GeoPoint) -> pd.DataFrame:
    # === SEARCH HOOK: BASE TRIP BUILD ===
    # Purpose:
    # Convert store-wave demand into the first pass of IN / OUT trips.
    # How:
    # Batch nearby wave demand, solve with OR-Tools, then convert each route into
    # a trip record with route, timing, and load fields.
    if not ORTOOLS_AVAILABLE:
        return build_base_trips(demand, depot)
    trip_rows: list[dict[str, object]] = []
    trip_counter = 1
    activity_counts: dict[pd.Timestamp, int] = {}
    demand = demand.sort_values(["wave_dt", "direction", "store_name"]).reset_index(drop=True)
    for direction, direction_group in demand.groupby("direction", dropna=False):
        pool = direction_group.copy().reset_index(drop=True)
        pool["remaining"] = pool["employees"]
        while int(pool["remaining"].sum()) > 0:
            active = pool[pool["remaining"] > 0].copy()
            seed_wave = pd.Timestamp(active["wave_dt"].min())
            batch = active[active["wave_dt"].apply(lambda dt: abs((pd.Timestamp(dt) - seed_wave).total_seconds()) / 60.0 <= 60)].copy()
            routes = solve_wave_routes_ortools(batch, depot)
            if not routes:
                routes = [[row] for row in batch.to_dict(orient="records")]
            for route_rows in routes:
                selected_rows: list[dict[str, object]] = []
                for row in route_rows:
                    original = pool[(pool["store_id"] == row["store_id"]) & (pool["wave_dt"] == row["wave_dt"]) & (pool["remaining"] > 0)]
                    if original.empty:
                        continue
                    idx = original.index[0]
                    alloc = min(int(pool.loc[idx, "remaining"]), int(row["employees"]))
                    if alloc <= 0:
                        continue
                    selected_rows.append(
                        {
                            "store_id": int(pool.loc[idx, "store_id"]),
                            "store_name": str(pool.loc[idx, "store_name"]),
                            "latitude": float(pool.loc[idx, "latitude"]),
                            "longitude": float(pool.loc[idx, "longitude"]),
                            "cluster_id": int(pool.loc[idx, "cluster_id"]) if pd.notna(pool.loc[idx, "cluster_id"]) else None,
                            "wave_dt": pd.Timestamp(pool.loc[idx, "wave_dt"]),
                            "allocated_passengers": alloc,
                        }
                    )
                    pool.loc[idx, "remaining"] = int(pool.loc[idx, "remaining"]) - alloc
                if not selected_rows:
                    continue
                trip = build_trip_record(
                    selected_rows,
                    str(direction),
                    depot,
                    trip_id=f"ORT_{trip_counter:04d}",
                    activity_counts=activity_counts,
                    use_pressure=True,
                    preserve_order=True,
                )
                trip_rows.append(trip)
                add_trip_to_activity(pd.Timestamp(trip["planned_start_dt"]), pd.Timestamp(trip["planned_end_dt"]), activity_counts)
                trip_counter += 1
    return pd.DataFrame(trip_rows).sort_values(["planned_start_dt", "trip_type", "trip_id"]).reset_index(drop=True)


def build_trip_record(
    selected_rows: list[dict[str, object]],
    direction: str,
    depot: GeoPoint,
    trip_id: str,
    activity_counts: dict[pd.Timestamp, int] | None = None,
    use_pressure: bool = True,
    preserve_order: bool = False,
) -> dict[str, object]:
    # === SEARCH HOOK: TRIP RECORD / TIMING DERIVATION ===
    # Purpose:
    # Turn an ordered stop list into a schedulable trip object.
    # How:
    # Compute route distance + duration, then derive earliest/latest/planned start.
    # Example:
    # A 110-minute IN route for a 09:00 wave may get a planned start near 07:10.
    selected_points = [point_from_stop(row) for row in selected_rows]
    ordered_points = selected_points if preserve_order else nearest_neighbor_sequence(depot, selected_points)
    ordered_names = [point.store_name for point in ordered_points]
    ordered_rows = selected_rows if preserve_order else sorted(selected_rows, key=lambda row: ordered_names.index(str(row["store_name"])))
    distance, duration = route_metrics_ordered(depot, ordered_points)
    passengers = int(sum(int(row["allocated_passengers"]) for row in ordered_rows))
    min_wave = min(pd.Timestamp(row["wave_dt"]) for row in ordered_rows)
    max_wave = max(pd.Timestamp(row["wave_dt"]) for row in ordered_rows)
    if direction == "IN":
        latest_arrival = max_wave + timedelta(minutes=WAVE_BUCKET_MIN)
        earliest_start = min_wave - timedelta(minutes=IN_EARLY_LIMIT_MIN + duration)
        latest_start = latest_arrival - timedelta(minutes=duration)
        requested_start = latest_arrival - timedelta(minutes=IN_TARGET_LEAD_MIN + duration)
    else:
        earliest_start = min_wave
        latest_start = max_wave + timedelta(minutes=OUT_WAIT_LIMIT_MIN)
        requested_start = earliest_start
    requested_start = max(earliest_start, min(requested_start, latest_start))
    if use_pressure and activity_counts is not None:
        planned_start = choose_start_with_pressure(requested_start, earliest_start, latest_start, duration, activity_counts)
    else:
        planned_start = requested_start
    planned_end = planned_start + timedelta(minutes=duration)
    return {
        "trip_id": trip_id,
        "trip_type": direction,
        "direction": direction,
        "service_date": planned_start.date().isoformat(),
        "cluster_id": ordered_rows[0]["cluster_id"] if ordered_rows else None,
        "requested_wave_dt": min_wave,
        "requested_wave_label": min_wave.strftime("%Y-%m-%d %H:%M"),
        "earliest_start_dt": earliest_start,
        "latest_start_dt": latest_start,
        "planned_start_dt": planned_start,
        "planned_end_dt": planned_end,
        "trip_duration_min": round(float(duration), 2),
        "route_distance_km": round(float(distance), 3),
        "stop_count": len(ordered_rows),
        "peak_load": passengers,
        "assigned_passengers": passengers,
        "occupancy_pct": round((passengers / BUS_CAPACITY) * 100, 2),
        "store_sequence": " -> ".join(ordered_names),
        "store_passenger_plan": " | ".join(f"{row['store_name']} ({int(row['allocated_passengers'])})" for row in ordered_rows),
        "stop_data_json": json.dumps(ordered_rows, default=str),
    }


def decode_stop_data(stop_data_json: str) -> list[dict[str, object]]:
    return json.loads(stop_data_json) if isinstance(stop_data_json, str) and stop_data_json else []


def stop_signature(stop: dict[str, object]) -> tuple[int, str, int]:
    return (
        int(stop["store_id"]),
        pd.Timestamp(stop["wave_dt"]).isoformat(),
        int(stop["allocated_passengers"]),
    )


def point_from_stop(stop: dict[str, object]) -> GeoPoint:
    return GeoPoint(
        store_name=str(stop["store_name"]),
        store_id=int(stop["store_id"]),
        latitude=float(stop["latitude"]),
        longitude=float(stop["longitude"]),
    )


def solve_mixed_tail_ortools(
    last_in: GeoPoint,
    in_end: pd.Timestamp,
    candidate_stops: list[dict[str, object]],
    depot: GeoPoint,
    remaining_capacity: int,
    max_tail_minutes: float,
) -> list[dict[str, object]]:
    # === SEARCH HOOK: MIXED TAIL INSERTION ===
    # Purpose:
    # Decide which OUT pickups can be attached to the return leg of an IN trip.
    # How:
    # Start at the last inbound stop, add optional outbound nodes, and let OR-Tools
    # choose a feasible subset under readiness, capacity, and tail-time constraints.
    # Example:
    # After dropping IN riders, the bus may pick up one or two nearby OUT stores
    # on the way back instead of opening a new dedicated OUT trip.
    if not candidate_stops or not ORTOOLS_AVAILABLE or remaining_capacity <= 0 or max_tail_minutes <= 0:
        return []
    feasible_candidates: list[dict[str, object]] = []
    for stop in candidate_stops:
        ready_min = max(0, int((pd.Timestamp(stop["wave_dt"]) - in_end).total_seconds() / 60.0))
        upper = min(int(max_tail_minutes), ready_min + OUT_WAIT_LIMIT_MIN)
        if ready_min <= upper:
            feasible_candidates.append(stop)
    if not feasible_candidates:
        return []
    candidate_stops = feasible_candidates[:MIXED_MAX_EXTRA_STOPS]
    end_index = len(candidate_stops) + 1
    node_points = [last_in] + [point_from_stop(stop) for stop in candidate_stops] + [depot]
    size = len(node_points)
    manager = pywrapcp.RoutingIndexManager(size, 1, [0], [end_index])
    routing = pywrapcp.RoutingModel(manager)

    time_matrix: list[list[int]] = []
    for i in range(size):
        row_times: list[int] = []
        for j in range(size):
            if i == j:
                row_times.append(0)
            else:
                travel = km_to_minutes(road_km(node_points[i], node_points[j]))
                dwell = 0 if i in (0, end_index) else STOP_DWELL_MIN
                row_times.append(int(round(travel + dwell)))
        time_matrix.append(row_times)

    def transit_callback(from_index: int, to_index: int) -> int:
        return time_matrix[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]

    transit_idx = routing.RegisterTransitCallback(transit_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)

    demands = [0] + [int(stop["allocated_passengers"]) for stop in candidate_stops] + [0]

    def demand_callback(from_index: int) -> int:
        return demands[manager.IndexToNode(from_index)]

    demand_idx = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(
        demand_idx,
        0,
        [remaining_capacity],
        True,
        "Capacity",
    )

    routing.AddDimension(
        transit_idx,
        OUT_WAIT_LIMIT_MIN,
        int(max_tail_minutes),
        True,
        "Time",
    )
    time_dim = routing.GetDimensionOrDie("Time")
    time_dim.CumulVar(routing.Start(0)).SetRange(0, 0)
    time_dim.CumulVar(routing.End(0)).SetRange(0, int(max_tail_minutes))

    for idx, stop in enumerate(candidate_stops, start=1):
        ready_min = max(0, int((pd.Timestamp(stop["wave_dt"]) - in_end).total_seconds() / 60.0))
        due_min = ready_min + OUT_WAIT_LIMIT_MIN
        index = manager.NodeToIndex(idx)
        time_dim.CumulVar(index).SetRange(ready_min, min(int(max_tail_minutes), due_min))
        penalty = max(1, int(stop["allocated_passengers"])) * MIXED_SKIP_PENALTY_PER_PASSENGER
        routing.AddDisjunction([index], penalty)

    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    search_params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search_params.time_limit.seconds = 2
    solution = routing.SolveWithParameters(search_params)
    if solution is None:
        return []

    selected: list[dict[str, object]] = []
    index = routing.Start(0)
    while not routing.IsEnd(index):
        node = manager.IndexToNode(index)
        if 1 <= node <= len(candidate_stops):
            selected.append(candidate_stops[node - 1])
        index = solution.Value(routing.NextVar(index))
    return selected


def build_mixed_candidates(base_trips: pd.DataFrame, depot: GeoPoint) -> pd.DataFrame:
    # === SEARCH HOOK: MIXED CONVERSION PASS ===
    # Purpose:
    # Upgrade strong base IN trips into MIXED trips when return-leg pickups fit.
    # How:
    # Scan candidate OUT stops near each IN return path, run local tail insertion,
    # then shrink or remove the original OUT trip if its demand was absorbed.
    if base_trips.empty:
        return base_trips
    trips_by_id: dict[str, dict[str, object]] = {
        str(row["trip_id"]): row.to_dict()
        for _, row in base_trips.sort_values(["planned_start_dt", "trip_type", "trip_id"]).iterrows()
    }
    removed_trip_ids: set[str] = set()
    new_trips: list[dict[str, object]] = []
    mixed_counter = 1

    in_trip_ids = [
        trip_id for trip_id, row in sorted(
            trips_by_id.items(),
            key=lambda item: (pd.Timestamp(item[1]["planned_start_dt"]), str(item[1]["trip_type"]), str(item[1]["trip_id"]))
        )
        if row["trip_type"] == "IN"
    ]

    for trip_id in in_trip_ids:
        if trip_id in removed_trip_ids or trip_id not in trips_by_id:
            continue
        trip = trips_by_id[trip_id]
        in_stops = decode_stop_data(trip.get("stop_data_json", ""))
        if not in_stops:
            continue
        in_points = [point_from_stop(stop) for stop in in_stops]
        in_end = pd.Timestamp(trip["planned_end_dt"])
        in_duration = float(trip["trip_duration_min"])
        remaining_duration = MAX_TRIP_DURATION_MIN - in_duration
        if remaining_duration <= 0:
            continue
        last_in = in_points[-1]

        candidate_stops: list[dict[str, object]] = []
        for out_trip_id, out_trip in trips_by_id.items():
            if out_trip_id in removed_trip_ids or out_trip_id == trip_id or out_trip["trip_type"] != "OUT":
                continue
            if out_trip["service_date"] != trip["service_date"]:
                continue
            out_stops = decode_stop_data(out_trip.get("stop_data_json", ""))
            for stop_idx, stop in enumerate(out_stops):
                ready_dt = pd.Timestamp(stop["wave_dt"])
                gap_min = (ready_dt - in_end).total_seconds() / 60.0
                if gap_min < 0 or gap_min > MIXED_MAX_ATTACH_MIN:
                    continue
                detour = road_km(last_in, point_from_stop(stop))
                if detour > MIXED_MAX_DETOUR_KM:
                    continue
                candidate_stops.append(
                    {
                        **stop,
                        "__parent_trip_id": out_trip_id,
                        "__stop_idx": stop_idx,
                    }
                )
        if not candidate_stops:
            continue
        candidate_stops = sorted(
            candidate_stops,
            key=lambda stop: (
                max(0.0, (pd.Timestamp(stop["wave_dt"]) - in_end).total_seconds() / 60.0),
                road_km(last_in, point_from_stop(stop)),
                -int(stop["allocated_passengers"]),
            ),
        )
        selected_out_stops = solve_mixed_tail_ortools(
            last_in=last_in,
            in_end=in_end,
            candidate_stops=candidate_stops,
            depot=depot,
            remaining_capacity=BUS_CAPACITY,
            max_tail_minutes=remaining_duration,
        )
        if not selected_out_stops:
            continue

        tail_points = [point_from_stop(stop) for stop in selected_out_stops]
        combined_points = in_points + tail_points
        distance, duration = route_metrics_ordered(depot, combined_points)
        if duration > MAX_TRIP_DURATION_MIN:
            continue

        total_out_passengers = int(sum(int(stop["allocated_passengers"]) for stop in selected_out_stops))
        peak_load = max(int(trip["peak_load"]), total_out_passengers)
        if peak_load > BUS_CAPACITY:
            continue

        selected_keys_by_parent: dict[str, set[tuple[int, str, int]]] = {}
        for stop in selected_out_stops:
            parent = str(stop["__parent_trip_id"])
            selected_keys_by_parent.setdefault(parent, set()).add(stop_signature(stop))

        for parent_trip_id, selected_keys in selected_keys_by_parent.items():
            out_trip = trips_by_id.get(parent_trip_id)
            if out_trip is None:
                continue
            original_out_stops = decode_stop_data(out_trip.get("stop_data_json", ""))
            remaining_out_stops = [stop for stop in original_out_stops if stop_signature(stop) not in selected_keys]
            if remaining_out_stops:
                rebuilt = build_trip_record(
                    remaining_out_stops,
                    "OUT",
                    depot,
                    trip_id=str(out_trip["trip_id"]),
                    activity_counts=None,
                    use_pressure=False,
                    preserve_order=False,
                )
                trips_by_id[parent_trip_id] = rebuilt
            else:
                removed_trip_ids.add(parent_trip_id)

        mixed_trip = trip.copy()
        mixed_trip["trip_id"] = f"MIX_{mixed_counter:04d}"
        mixed_trip["trip_type"] = "MIXED"
        mixed_trip["direction"] = "MIXED"
        mixed_trip["planned_end_dt"] = pd.Timestamp(trip["planned_start_dt"]) + timedelta(minutes=float(duration))
        mixed_trip["trip_duration_min"] = round(float(duration), 2)
        mixed_trip["route_distance_km"] = round(float(distance), 3)
        mixed_trip["stop_count"] = len(combined_points)
        mixed_trip["assigned_passengers"] = int(trip["assigned_passengers"]) + total_out_passengers
        mixed_trip["peak_load"] = peak_load
        mixed_trip["occupancy_pct"] = round((peak_load / BUS_CAPACITY) * 100, 2)
        mixed_trip["store_sequence"] = " -> ".join(point.store_name for point in combined_points)
        mixed_trip["store_passenger_plan"] = (
            f"{trip['store_passenger_plan']} || RETURN || "
            + " | ".join(f"{stop['store_name']} ({int(stop['allocated_passengers'])})" for stop in selected_out_stops)
        )
        cleaned_out_stops = [
            {key: value for key, value in stop.items() if not str(key).startswith("__")}
            for stop in selected_out_stops
        ]
        mixed_trip["stop_data_json"] = json.dumps(in_stops + cleaned_out_stops, default=str)
        new_trips.append(mixed_trip)
        removed_trip_ids.add(trip_id)
        mixed_counter += 1

    final_rows: list[dict[str, object]] = []
    for trip_id, row in trips_by_id.items():
        if trip_id not in removed_trip_ids:
            final_rows.append(row)
    final_rows.extend(new_trips)
    return pd.DataFrame(final_rows).sort_values(["planned_start_dt", "trip_type", "trip_id"]).reset_index(drop=True)


def init_slots_for_demand(demand: pd.DataFrame, initial_assignments: pd.DataFrame | None = None) -> dict[tuple[str, int, str], DutySlot]:
    date_set: set[str] = set()
    if demand is not None and not demand.empty:
        start_day = demand["wave_dt"].min().normalize() - timedelta(days=1)
        end_day = demand["wave_dt"].max().normalize() + timedelta(days=1)
        date_set.update(dt.date().isoformat() for dt in pd.date_range(start_day, end_day, freq="D"))
    if initial_assignments is not None and not initial_assignments.empty:
        date_set.update(initial_assignments["service_date"].astype(str).tolist())
    if not date_set:
        return {}
    service_dates = sorted(date_set)
    return init_slots(service_dates)


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


def can_split_reset(slot: DutySlot, candidate_start: pd.Timestamp) -> bool:
    # === SEARCH HOOK: SPLIT DUTY RESET RULE ===
    # Purpose:
    # Decide whether a long midday gap is large enough to start a fresh duty segment.
    # Example:
    # If morning work ends at 09:00 and the next trip starts at 13:30, this can
    # prevent the scheduler from counting one long continuous duty span.
    if slot.available_after is None:
        return False
    gap_min = (candidate_start - slot.available_after).total_seconds() / 60.0
    return gap_min >= SPLIT_DUTY_RESET_MIN and candidate_start.hour >= SPLIT_DUTY_RESET_START_HOUR


def slot_is_feasible(
    slot: DutySlot,
    trip: pd.Series,
    day_assignments: pd.DataFrame,
    desired_start: pd.Timestamp,
    latest_extension_min: int = 0,
) -> tuple[bool, pd.Timestamp | None, float, str | None, bool]:
    # === SEARCH HOOK: SLOT FEASIBILITY CHECK ===
    # Purpose:
    # Check whether one trip can fit on one bus slot.
    # How:
    # Enforce earliest/latest timing, dynamic buffer, physical overlap, and duty span.
    # It also reports whether the trip qualifies for a split-duty reset.
    # Example:
    # A trip may fail on "buffer_violation" or pass because a long midday break
    # resets the effective duty segment.
    earliest = pd.Timestamp(trip["earliest_start_dt"])
    latest = pd.Timestamp(trip["latest_start_dt"]) + timedelta(minutes=latest_extension_min)
    if slot.slot_type == "evening":
        earliest = max(earliest, pd.Timestamp(earliest.date()) + timedelta(hours=EVENING_SEED_HOUR))
    candidate_start = desired_start
    candidate_start = max(candidate_start, earliest)
    buffer_needed = required_buffer_min(slot)
    if slot.available_after is not None:
        candidate_start = max(candidate_start, slot.available_after + timedelta(minutes=buffer_needed))
    if candidate_start > latest:
        if slot.available_after is not None and slot.available_after + timedelta(minutes=buffer_needed) > latest:
            return False, None, 0.0, "buffer_violation", False
        return False, None, 0.0, "slot_exhausted", False
    candidate_end = candidate_start + timedelta(minutes=float(trip["trip_duration_min"]))
    projected_span = float(trip["trip_duration_min"])
    split_reset = False
    if slot.first_start is not None:
        if can_split_reset(slot, candidate_start):
            split_reset = True
        else:
            projected_span = (candidate_end - slot.first_start).total_seconds() / 60.0
            if projected_span > HARD_DUTY_SPAN_MIN:
                return False, None, projected_span, "duty_span_block", False
    if not day_assignments.empty and "bus_id" in day_assignments.columns:
        for row in day_assignments[day_assignments["bus_id"] == slot.bus_id].itertuples(index=False):
            if not (candidate_end <= pd.Timestamp(row.planned_start_dt) or candidate_start >= pd.Timestamp(row.planned_end_dt)):
                return False, None, projected_span, "slot_exhausted", False
    return True, candidate_start, projected_span, None, split_reset


def is_small_isolated_trip(trip: pd.Series) -> bool:
    return int(trip["assigned_passengers"]) <= 3 and int(trip["stop_count"]) <= 2


def classify_rejection_reason(reason_counts: dict[str, int], trip: pd.Series) -> str:
    if is_small_isolated_trip(trip):
        return "small_isolated_demand"
    if not reason_counts:
        return "unclassified"
    priority = ["slot_exhausted", "buffer_violation", "duty_span_block"]
    return max(reason_counts.items(), key=lambda item: (item[1], -priority.index(item[0]) if item[0] in priority else -99))[0]


def required_buffer_min(slot: DutySlot) -> int:
    last_duration = slot.last_trip_duration_min
    if last_duration is None:
        return BUFFER_MIN
    if last_duration <= SHORT_TRIP_THRESHOLD_MIN:
        return SHORT_TRIP_BUFFER_MIN
    if last_duration <= MEDIUM_TRIP_THRESHOLD_MIN:
        return MEDIUM_TRIP_BUFFER_MIN
    return BUFFER_MIN


def choose_slot_assignment(
    trip: pd.Series,
    slots: dict[tuple[str, int, str], DutySlot],
    assignment_rows: list[dict[str, object]],
    repair_mode: bool = False,
    objective: str = "coverage",
) -> tuple[tuple[str, int, str], pd.Timestamp, bool, bool] | None:
    # === SEARCH HOOK: SLOT CHOICE / ASSIGNMENT SCORING ===
    # Purpose:
    # Pick the best legal bus slot for a trip.
    # How:
    # Test both rotation slots, all buses, and optional repair shifts, then score
    # the feasible choices for coverage or overtime.
    service_day = str(trip["service_date"])
    day_assignments = pd.DataFrame(assignment_rows)
    if not day_assignments.empty:
        day_assignments = day_assignments[day_assignments["service_date"] == service_day]
    deltas = [0]
    if repair_mode:
        deltas = REPAIR_SHIFT_OPTIONS_OUT if trip["trip_type"] == "OUT" else REPAIR_SHIFT_OPTIONS_IN
        deltas = [0] + deltas
    best_choice: tuple[tuple[str, int, str], pd.Timestamp, bool, bool] | None = None
    best_score: tuple[float, float, float, float, int, str] | None = None
    preferred_slots = slot_preference(str(trip["trip_type"]), pd.Timestamp(trip["planned_start_dt"]))
    for slot_type in ("morning", "evening"):
        slot_penalty = 0 if slot_type == preferred_slots[0] else 5
        for bus_id in range(1, BUS_COUNT + 1):
            slot_key = (service_day, bus_id, slot_type)
            slot = slots[slot_key]
            for delta in deltas:
                desired_start = pd.Timestamp(trip["planned_start_dt"]) + timedelta(minutes=delta)
                latest_extension = max(0, delta)
                ok, start_dt, projected_span, _, split_reset = slot_is_feasible(
                    slot,
                    trip,
                    day_assignments,
                    desired_start=desired_start,
                    latest_extension_min=latest_extension,
                )
                if not ok or start_dt is None:
                    continue
                delay = abs((start_dt - pd.Timestamp(trip["planned_start_dt"])).total_seconds()) / 60.0
                overtime_risk = max(0.0, projected_span - TARGET_DUTY_MIN)
                split_penalty = 0.0 if split_reset else 1.0
                if objective == "overtime":
                    score = (slot_penalty + overtime_risk, split_penalty, delay, projected_span, bus_id, slot_type)
                else:
                    score = (slot_penalty, split_penalty, delay, projected_span, bus_id, slot_type)
                if best_score is None or score < best_score:
                    best_score = score
                    best_choice = (slot_key, start_dt, delta != 0, split_reset)
    return best_choice


def collect_rejection_reasons(
    trip: pd.Series,
    slots: dict[tuple[str, int, str], DutySlot],
    assignment_rows: list[dict[str, object]],
    repair_mode: bool = True,
) -> dict[str, int]:
    service_day = str(trip["service_date"])
    day_assignments = pd.DataFrame(assignment_rows)
    if not day_assignments.empty:
        day_assignments = day_assignments[day_assignments["service_date"] == service_day]
    deltas = [0]
    if repair_mode:
        deltas = REPAIR_SHIFT_OPTIONS_OUT if trip["trip_type"] == "OUT" else REPAIR_SHIFT_OPTIONS_IN
        deltas = [0] + deltas
    reason_counts: dict[str, int] = {}
    for slot_type in ("morning", "evening"):
        for bus_id in range(1, BUS_COUNT + 1):
            slot_key = (service_day, bus_id, slot_type)
            slot = slots[slot_key]
            for delta in deltas:
                desired_start = pd.Timestamp(trip["planned_start_dt"]) + timedelta(minutes=delta)
                latest_extension = max(0, delta)
                ok, start_dt, projected_span, reason, _ = slot_is_feasible(
                    slot,
                    trip,
                    day_assignments,
                    desired_start=desired_start,
                    latest_extension_min=latest_extension,
                )
                if ok and start_dt is not None:
                    reason_counts["feasible_somewhere"] = reason_counts.get("feasible_somewhere", 0) + 1
                elif reason is not None:
                    reason_counts[reason] = reason_counts.get(reason, 0) + 1
    return reason_counts


def is_bottleneck_trip(trip: pd.Series) -> bool:
    start_dt = pd.Timestamp(trip["planned_start_dt"])
    return start_dt.hour in BOTTLENECK_HOURS


def apply_assignment(
    trip: pd.Series,
    slot_key: tuple[str, int, str],
    start_dt: pd.Timestamp,
    rescued: bool,
    split_reset: bool,
    slots: dict[tuple[str, int, str], DutySlot],
    scheduled_rows: list[dict[str, object]],
    assignment_rows: list[dict[str, object]],
) -> None:
    # === SEARCH HOOK: APPLY ASSIGNMENT / MUTATE SLOT STATE ===
    # Purpose:
    # Commit one chosen assignment into both live slot state and output rows.
    # How:
    # Update bus availability, remember last trip duration for future buffers,
    # and open a new duty segment when split_reset=True.
    service_day, bus_id, slot_type = slot_key
    end_dt = pd.Timestamp(start_dt) + timedelta(minutes=float(trip["trip_duration_min"]))
    slot = slots[slot_key]
    if slot.first_start is None:
        slot.first_start = pd.Timestamp(start_dt)
    elif split_reset:
        slot.segment_id += 1
        slot.first_start = pd.Timestamp(start_dt)
    slot.available_after = end_dt
    slot.last_end = end_dt
    slot.last_trip_duration_min = float(trip["trip_duration_min"])
    slot.trip_ids.append(str(trip["trip_id"]))
    trip_dict = trip.to_dict()
    trip_dict["service_date"] = service_day
    trip_dict["planned_start_dt"] = pd.Timestamp(start_dt)
    trip_dict["planned_end_dt"] = end_dt
    trip_dict["rescued_by_delay"] = rescued
    trip_dict["rotation_tag"] = slot_type
    trip_dict["duty_segment"] = int(slot.segment_id)
    trip_dict["split_reset_flag"] = bool(split_reset)
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
            "duty_segment": int(slot.segment_id),
            "split_reset_flag": bool(split_reset),
            "handover_flag": slot_type == "evening",
        }
    )


def rebuild_slot_state(
    slots: dict[tuple[str, int, str], DutySlot],
    assignment_rows: list[dict[str, object]],
) -> None:
    # === SEARCH HOOK: REBUILD SLOT STATE ===
    # Purpose:
    # Reconstruct all slot timing after removals, swaps, or repair attempts.
    for slot in slots.values():
        slot.available_after = None
        slot.first_start = None
        slot.last_end = None
        slot.last_trip_duration_min = None
        slot.segment_id = 1
        slot.trip_ids = []
    for row in sorted(assignment_rows, key=lambda item: (item["service_date"], item["bus_id"], item["rotation_tag"], item["planned_start_dt"])):
        slot_key = (row["service_date"], row["bus_id"], row["rotation_tag"])
        slot = slots[slot_key]
        start_dt = pd.Timestamp(row["planned_start_dt"])
        end_dt = pd.Timestamp(row["planned_end_dt"])
        row_segment = int(row.get("duty_segment", slot.segment_id))
        if slot.first_start is None or row_segment != slot.segment_id:
            slot.segment_id = row_segment
            slot.first_start = start_dt
        slot.available_after = end_dt
        slot.last_end = end_dt
        slot.last_trip_duration_min = float(row["trip_duration_min"])
        slot.trip_ids.append(str(row["trip_id"]))


def try_donor_swap(
    trip: pd.Series,
    slots: dict[tuple[str, int, str], DutySlot],
    assignment_rows: list[dict[str, object]],
    scheduled_rows: list[dict[str, object]],
    trip_lookup: dict[str, pd.Series],
) -> bool:
    # === SEARCH HOOK: DONOR SWAP REPAIR ===
    # Purpose:
    # Rescue a blocked bottleneck trip by moving a nearby scheduled donor trip.
    if not is_bottleneck_trip(trip):
        return False
    service_day = str(trip["service_date"])
    trip_start = pd.Timestamp(trip["planned_start_dt"])
    raw_donors = [
        row for row in assignment_rows
        if row["service_date"] == service_day
        and abs((pd.Timestamp(row["planned_start_dt"]) - trip_start).total_seconds()) / 60.0 <= 45
    ]
    candidate_donors: list[dict[str, object]] = []
    for row in raw_donors:
        donor_trip = trip_lookup.get(str(row["trip_id"]))
        if donor_trip is None:
            continue
        feasible_shift_count = 0
        donor_trip = donor_trip.copy()
        donor_trip["planned_start_dt"] = pd.Timestamp(row["planned_start_dt"])
        for delta in DONOR_SHIFT_OPTIONS:
            shifted = donor_trip.copy()
            shifted["planned_start_dt"] = pd.Timestamp(row["planned_start_dt"]) + timedelta(minutes=delta)
            if choose_slot_assignment(shifted, slots, assignment_rows, repair_mode=True, objective="coverage") is not None:
                feasible_shift_count += 1
        enriched = dict(row)
        enriched["feasible_shift_count"] = feasible_shift_count
        candidate_donors.append(enriched)
    candidate_donors.sort(
        key=lambda row: (
            -int(row["feasible_shift_count"]),
            float(row["occupancy_pct"]),
            int(row["assigned_passengers"]),
            pd.Timestamp(row["planned_start_dt"]),
        )
    )
    candidate_donors = candidate_donors[:8]
    for donor in candidate_donors:
        donor_trip = trip_lookup.get(str(donor["trip_id"]))
        if donor_trip is None:
            continue
        donor_series = donor_trip.copy()
        donor_series["planned_start_dt"] = pd.Timestamp(donor["planned_start_dt"])
        donor_series["planned_end_dt"] = pd.Timestamp(donor["planned_end_dt"])
        donor_series["service_date"] = donor["service_date"]
        donor_index = next((idx for idx, row in enumerate(assignment_rows) if row["trip_id"] == donor["trip_id"]), None)
        sched_index = next((idx for idx, row in enumerate(scheduled_rows) if str(row["trip_id"]) == str(donor["trip_id"])), None)
        if donor_index is None or sched_index is None:
            continue
        removed_assignment = assignment_rows.pop(donor_index)
        removed_schedule = scheduled_rows.pop(sched_index)
        rebuild_slot_state(slots, assignment_rows)
        donor_best = None
        for delta in DONOR_SHIFT_OPTIONS:
            donor_try = donor_series.copy()
            donor_try["planned_start_dt"] = pd.Timestamp(donor["planned_start_dt"]) + timedelta(minutes=delta)
            donor_best = choose_slot_assignment(donor_try, slots, assignment_rows, repair_mode=True, objective="coverage")
            if donor_best is not None:
                break
        if donor_best is None:
            assignment_rows.append(removed_assignment)
            scheduled_rows.append(removed_schedule)
            rebuild_slot_state(slots, assignment_rows)
            continue
        donor_slot_key, donor_start_dt, donor_rescued, donor_split_reset = donor_best
        apply_assignment(donor_series, donor_slot_key, donor_start_dt, donor_rescued, donor_split_reset, slots, scheduled_rows, assignment_rows)
        blocked_best = choose_slot_assignment(trip, slots, assignment_rows, repair_mode=True, objective="coverage")
        if blocked_best is not None:
            blocked_slot_key, blocked_start_dt, blocked_rescued, blocked_split_reset = blocked_best
            apply_assignment(trip, blocked_slot_key, blocked_start_dt, blocked_rescued, blocked_split_reset, slots, scheduled_rows, assignment_rows)
            return True
        # revert donor move and restore original assignment
        assignment_rows[:] = [row for row in assignment_rows if str(row["trip_id"]) != str(donor["trip_id"])]
        scheduled_rows[:] = [row for row in scheduled_rows if str(row["trip_id"]) != str(donor["trip_id"])]
        assignment_rows.append(removed_assignment)
        scheduled_rows.append(removed_schedule)
        rebuild_slot_state(slots, assignment_rows)
    return False


def remove_trip_from_schedule(
    trip_id: str,
    scheduled_rows: list[dict[str, object]],
    assignment_rows: list[dict[str, object]],
) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    removed_schedule = None
    removed_assignment = None
    for idx, row in enumerate(scheduled_rows):
        if str(row["trip_id"]) == str(trip_id):
            removed_schedule = scheduled_rows.pop(idx)
            break
    for idx, row in enumerate(assignment_rows):
        if str(row["trip_id"]) == str(trip_id):
            removed_assignment = assignment_rows.pop(idx)
            break
    return removed_schedule, removed_assignment


def restore_trip_to_schedule(
    removed_schedule: dict[str, object] | None,
    removed_assignment: dict[str, object] | None,
    scheduled_rows: list[dict[str, object]],
    assignment_rows: list[dict[str, object]],
    slots: dict[tuple[str, int, str], DutySlot],
) -> None:
    if removed_schedule is not None:
        scheduled_rows.append(removed_schedule)
    if removed_assignment is not None:
        assignment_rows.append(removed_assignment)
    rebuild_slot_state(slots, assignment_rows)


def try_fragment_reinsertion(
    trip: pd.Series,
    slots: dict[tuple[str, int, str], DutySlot],
    scheduled_rows: list[dict[str, object]],
    assignment_rows: list[dict[str, object]],
    depot: GeoPoint,
) -> bool:
    # === SEARCH HOOK: FRAGMENT REINSERTION ===
    # Purpose:
    # Absorb a very small failed trip into an already scheduled trip of the same type.
    # Example:
    # A 2-stop OUT fragment with 3 passengers can be folded into a larger OUT trip.
    if int(trip["assigned_passengers"]) > 4 or int(trip["stop_count"]) > 2:
        return False
    trip_start = pd.Timestamp(trip["planned_start_dt"])
    candidates = sorted(
        [
            row for row in scheduled_rows
            if str(row["service_date"]) == str(trip["service_date"])
            and str(row["trip_type"]) == str(trip["trip_type"])
            and str(row["trip_id"]) != str(trip["trip_id"])
            and abs((pd.Timestamp(row["planned_start_dt"]) - trip_start).total_seconds()) / 60.0 <= 90
        ],
        key=lambda row: (
            abs((pd.Timestamp(row["planned_start_dt"]) - trip_start).total_seconds()) / 60.0,
            -int(row["assigned_passengers"]),
            int(row["stop_count"]),
        ),
    )
    trip_stops = decode_stop_data(trip.get("stop_data_json", ""))
    if not trip_stops:
        return False
    for host in candidates[:FRAGMENT_HOST_CANDIDATES]:
        host_stops = decode_stop_data(host.get("stop_data_json", ""))
        if not host_stops:
            continue
        combined_stops = host_stops + trip_stops
        merged_trip = build_trip_record(
            combined_stops,
            str(host["trip_type"]),
            depot,
            trip_id=str(host["trip_id"]),
            activity_counts=None,
            use_pressure=False,
            preserve_order=False,
        )
        if int(merged_trip["peak_load"]) > BUS_CAPACITY:
            continue
        removed_schedule, removed_assignment = remove_trip_from_schedule(str(host["trip_id"]), scheduled_rows, assignment_rows)
        rebuild_slot_state(slots, assignment_rows)
        best_choice = choose_slot_assignment(pd.Series(merged_trip), slots, assignment_rows, repair_mode=True, objective="coverage")
        if best_choice is None:
            restore_trip_to_schedule(removed_schedule, removed_assignment, scheduled_rows, assignment_rows, slots)
            continue
        slot_key, start_dt, rescued, split_reset = best_choice
        apply_assignment(pd.Series(merged_trip), slot_key, start_dt, rescued, split_reset, slots, scheduled_rows, assignment_rows)
        return True
    return False


def try_stronger_mixed_recovery(
    trip: pd.Series,
    slots: dict[tuple[str, int, str], DutySlot],
    scheduled_rows: list[dict[str, object]],
    assignment_rows: list[dict[str, object]],
    depot: GeoPoint,
) -> bool:
    # === SEARCH HOOK: STRONGER MIXED RECOVERY ===
    # Purpose:
    # Recover a blocked OUT trip by attaching it to a scheduled IN return leg.
    if str(trip["trip_type"]) != "OUT":
        return False
    out_stops = decode_stop_data(trip.get("stop_data_json", ""))
    if not out_stops:
        return False
    trip_start = pd.Timestamp(trip["planned_start_dt"])
    host_candidates = sorted(
        [
            row for row in scheduled_rows
            if str(row["service_date"]) == str(trip["service_date"])
            and str(row["trip_type"]) == "IN"
        ],
        key=lambda row: (
            abs((pd.Timestamp(row["planned_end_dt"]) - trip_start).total_seconds()) / 60.0,
            -int(row["assigned_passengers"]),
        ),
    )
    for host in host_candidates[:MIXED_HOST_CANDIDATES]:
        in_stops = decode_stop_data(host.get("stop_data_json", ""))
        if not in_stops:
            continue
        in_points = [point_from_stop(stop) for stop in in_stops]
        host_end = pd.Timestamp(host["planned_end_dt"])
        selected_out_stops = solve_mixed_tail_ortools(
            last_in=in_points[-1],
            in_end=host_end,
            candidate_stops=out_stops,
            depot=depot,
            remaining_capacity=BUS_CAPACITY,
            max_tail_minutes=MAX_TRIP_DURATION_MIN - float(host["trip_duration_min"]),
        )
        if len(selected_out_stops) != len(out_stops):
            continue
        combined_points = in_points + [point_from_stop(stop) for stop in selected_out_stops]
        distance, duration = route_metrics_ordered(depot, combined_points)
        if duration > MAX_TRIP_DURATION_MIN:
            continue
        mixed_trip = dict(host)
        mixed_trip["trip_type"] = "MIXED"
        mixed_trip["direction"] = "MIXED"
        mixed_trip["trip_duration_min"] = round(float(duration), 2)
        mixed_trip["route_distance_km"] = round(float(distance), 3)
        mixed_trip["stop_count"] = len(combined_points)
        mixed_trip["assigned_passengers"] = int(host["assigned_passengers"]) + int(trip["assigned_passengers"])
        mixed_trip["peak_load"] = max(int(host["peak_load"]), int(trip["assigned_passengers"]))
        mixed_trip["occupancy_pct"] = round((float(mixed_trip["peak_load"]) / BUS_CAPACITY) * 100, 2)
        mixed_trip["store_sequence"] = " -> ".join(point.store_name for point in combined_points)
        mixed_trip["store_passenger_plan"] = (
            f"{host['store_passenger_plan']} || RETURN || "
            + " | ".join(f"{stop['store_name']} ({int(stop['allocated_passengers'])})" for stop in out_stops)
        )
        mixed_trip["stop_data_json"] = json.dumps(in_stops + out_stops, default=str)
        removed_schedule, removed_assignment = remove_trip_from_schedule(str(host["trip_id"]), scheduled_rows, assignment_rows)
        rebuild_slot_state(slots, assignment_rows)
        best_choice = choose_slot_assignment(pd.Series(mixed_trip), slots, assignment_rows, repair_mode=True, objective="coverage")
        if best_choice is None:
            restore_trip_to_schedule(removed_schedule, removed_assignment, scheduled_rows, assignment_rows, slots)
            continue
        slot_key, start_dt, rescued, split_reset = best_choice
        apply_assignment(pd.Series(mixed_trip), slot_key, start_dt, rescued, split_reset, slots, scheduled_rows, assignment_rows)
        return True
    return False


def total_overtime_from_rows(assignment_rows: list[dict[str, object]]) -> float:
    if not assignment_rows:
        return 0.0
    duties = build_duties(pd.DataFrame(assignment_rows))
    if duties.empty:
        return 0.0
    return float(duties["overtime_min"].sum())


def overtime_duty_keys(assignment_rows: list[dict[str, object]]) -> set[tuple[str, int, str, int]]:
    if not assignment_rows:
        return set()
    duties = build_duties(pd.DataFrame(assignment_rows))
    if duties.empty:
        return set()
    overtime = duties[duties["overtime_min"] > 0]
    return {
        (str(row["service_date"]), int(row["bus_id"]), str(row["rotation_tag"]), int(row.get("duty_segment", 1)))
        for _, row in overtime.iterrows()
    }


def improve_overtime_without_losing_coverage(
    slots: dict[tuple[str, int, str], DutySlot],
    scheduled_rows: list[dict[str, object]],
    assignment_rows: list[dict[str, object]],
) -> None:
    # === SEARCH HOOK: OVERTIME CLEANUP PASS ===
    # Purpose:
    # Reduce overtime after coverage has already been secured.
    # How:
    # Remove a trip from an overtime-heavy duty, try to re-place it elsewhere,
    # and keep the move only if total overtime drops without losing service.
    current_total = total_overtime_from_rows(assignment_rows)
    if current_total <= 0:
        return
    for _ in range(OVERTIME_IMPROVEMENT_PASSES):
        improved = False
        hot_keys = overtime_duty_keys(assignment_rows)
        if not hot_keys:
            break
        candidate_assignments = sorted(
            [
                row for row in assignment_rows
                if (str(row["service_date"]), int(row["bus_id"]), str(row["rotation_tag"]), int(row.get("duty_segment", 1))) in hot_keys
            ],
            key=lambda row: (
                -float(row["trip_duration_min"]),
                -int(row["assigned_passengers"]),
                pd.Timestamp(row["planned_start_dt"]),
            ),
        )
        for candidate in candidate_assignments:
            assign_index = next((idx for idx, row in enumerate(assignment_rows) if str(row["trip_id"]) == str(candidate["trip_id"])), None)
            sched_index = next((idx for idx, row in enumerate(scheduled_rows) if str(row["trip_id"]) == str(candidate["trip_id"])), None)
            if assign_index is None or sched_index is None:
                continue
            original_assignment = assignment_rows.pop(assign_index)
            original_schedule = scheduled_rows.pop(sched_index)
            rebuild_slot_state(slots, assignment_rows)
            trip_series = pd.Series(original_schedule)
            best_choice = choose_slot_assignment(
                trip_series,
                slots,
                assignment_rows,
                repair_mode=True,
                objective="overtime",
            )
            if best_choice is None:
                assignment_rows.append(original_assignment)
                scheduled_rows.append(original_schedule)
                rebuild_slot_state(slots, assignment_rows)
                continue
            slot_key, start_dt, rescued, split_reset = best_choice
            same_slot = (
                int(original_assignment["bus_id"]) == int(slot_key[1])
                and str(original_assignment["rotation_tag"]) == str(slot_key[2])
                and pd.Timestamp(original_assignment["planned_start_dt"]) == pd.Timestamp(start_dt)
            )
            if same_slot:
                assignment_rows.append(original_assignment)
                scheduled_rows.append(original_schedule)
                rebuild_slot_state(slots, assignment_rows)
                continue
            apply_assignment(trip_series, slot_key, start_dt, rescued, split_reset, slots, scheduled_rows, assignment_rows)
            new_total = total_overtime_from_rows(assignment_rows)
            if new_total + 1e-6 < current_total:
                current_total = new_total
                improved = True
            else:
                assignment_rows[:] = [row for row in assignment_rows if str(row["trip_id"]) != str(original_assignment["trip_id"])]
                scheduled_rows[:] = [row for row in scheduled_rows if str(row["trip_id"]) != str(original_assignment["trip_id"])]
                assignment_rows.append(original_assignment)
                scheduled_rows.append(original_schedule)
                rebuild_slot_state(slots, assignment_rows)
        if not improved:
            break


def schedule_with_rotation_reset(base_trips: pd.DataFrame, depot: GeoPoint) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    # === SEARCH HOOK: MAIN SCHEDULER / COVERAGE FIRST ===
    # Flow:
    # 1. First-pass assignment of the base trip set.
    # 2. Retry blocked trips with repair shifts.
    # 3. Donor swap / fragment reinsertion / stronger mixed recovery.
    # 4. Overtime cleanup without dropping covered demand.
    trips = base_trips.copy().sort_values(
        ["planned_start_dt", "assigned_passengers", "peak_load", "trip_id"],
        ascending=[True, False, False, True],
    ).reset_index(drop=True)
    service_dates = sorted(trips["service_date"].astype(str).unique())
    slots = init_slots(service_dates)
    scheduled_rows: list[dict[str, object]] = []
    assignment_rows: list[dict[str, object]] = []
    unscheduled_trips: list[pd.Series] = []
    trip_lookup = {str(row["trip_id"]): row for _, row in trips.iterrows()}

    for _, trip in trips.iterrows():
        best_choice = choose_slot_assignment(trip, slots, assignment_rows, repair_mode=False, objective="coverage")
        if best_choice is None:
            unscheduled_trips.append(trip)
            continue

        slot_key, start_dt, rescued, split_reset = best_choice
        apply_assignment(trip, slot_key, start_dt, rescued, split_reset, slots, scheduled_rows, assignment_rows)

    final_unscheduled_rows: list[dict[str, object]] = []
    for trip in unscheduled_trips:
        best_choice = choose_slot_assignment(trip, slots, assignment_rows, repair_mode=True, objective="coverage")
        if best_choice is None:
            swapped = try_donor_swap(trip, slots, assignment_rows, scheduled_rows, trip_lookup)
            if swapped:
                continue
            reinserted = try_fragment_reinsertion(trip, slots, scheduled_rows, assignment_rows, depot)
            if reinserted:
                continue
            mixed_recovered = try_stronger_mixed_recovery(trip, slots, scheduled_rows, assignment_rows, depot)
            if mixed_recovered:
                continue
            best_choice = choose_slot_assignment(trip, slots, assignment_rows, repair_mode=True, objective="coverage")
        if best_choice is None:
            reason_counts = collect_rejection_reasons(trip, slots, assignment_rows, repair_mode=True)
            primary_reason = classify_rejection_reason(reason_counts, trip)
            final_unscheduled_rows.append(
                {
                    "trip_id": trip["trip_id"],
                    "trip_type": trip["trip_type"],
                    "requested_wave_label": trip["requested_wave_label"],
                    "rejection_reason": primary_reason,
                    "rejection_reason_counts": json.dumps(reason_counts, sort_keys=True),
                    "assigned_passengers": int(trip["assigned_passengers"]),
                    "peak_load": int(trip["peak_load"]),
                    "stop_count": int(trip["stop_count"]),
                    "occupancy_pct": float(trip["occupancy_pct"]),
                }
            )
            continue
        slot_key, start_dt, rescued, split_reset = best_choice
        apply_assignment(trip, slot_key, start_dt, rescued, split_reset, slots, scheduled_rows, assignment_rows)

    improve_overtime_without_losing_coverage(slots, scheduled_rows, assignment_rows)

    scheduled = pd.DataFrame(scheduled_rows).sort_values(["planned_start_dt", "trip_id"]).reset_index(drop=True)
    assignments = pd.DataFrame(assignment_rows).sort_values(["planned_start_dt", "bus_id"]).reset_index(drop=True)
    unscheduled = pd.DataFrame(final_unscheduled_rows)
    return scheduled, assignments, unscheduled


def build_and_schedule_integrated(
    demand: pd.DataFrame,
    depot: GeoPoint,
    initial_scheduled: pd.DataFrame | None = None,
    initial_assignments: pd.DataFrame | None = None,
    trip_prefix: str = "INT",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    # === SEARCH HOOK: REPAIR BUILD-AND-SCHEDULE LOOP ===
    # Purpose:
    # Build a new trip set only for leftover repair demand, then schedule it immediately.
    # Example:
    # Salvage, cooperative-merge, or bottleneck demand becomes SLV_ / MRG_ / REP_ trips here.
    demand = demand.sort_values(["wave_dt", "direction", "store_name"]).reset_index(drop=True).copy()
    demand["remaining"] = demand["employees"]
    initial_assignments_df = None if initial_assignments is None else initial_assignments
    slots = init_slots_for_demand(demand, initial_assignments_df)
    scheduled_rows: list[dict[str, object]] = [] if initial_scheduled is None else initial_scheduled.to_dict(orient="records")
    assignment_rows: list[dict[str, object]] = [] if initial_assignments is None else initial_assignments.to_dict(orient="records")
    unscheduled_rows: list[dict[str, object]] = []
    designed_rows: list[dict[str, object]] = []
    activity_counts: dict[pd.Timestamp, int] = {}
    rebuild_slot_state(slots, assignment_rows)
    if initial_assignments is not None and not initial_assignments.empty:
        for row in initial_assignments.itertuples(index=False):
            add_trip_to_activity(pd.Timestamp(row.planned_start_dt), pd.Timestamp(row.planned_end_dt), activity_counts)
    trip_counter = 1

    grouped_keys = (
        demand[["wave_dt", "direction"]]
        .drop_duplicates()
        .sort_values(["wave_dt", "direction"])
        .itertuples(index=False, name=None)
    )

    for wave_dt, direction in grouped_keys:
        while True:
            mask = (demand["wave_dt"] == wave_dt) & (demand["direction"] == direction) & (demand["remaining"] > 0)
            pool = demand[mask].copy()
            if pool.empty:
                break
            seed_idx = pool.sort_values(["remaining", "store_name"], ascending=[False, True]).index[0]
            seed = demand.loc[seed_idx]
            seed_point = point_from_row(seed)
            candidates = pool.copy()
            candidates["distance"] = [road_km(seed_point, point_from_row(candidates.loc[idx])) for idx in candidates.index]
            candidates = candidates.sort_values(["distance", "remaining", "store_name"], ascending=[True, False, True])

            selected_rows: list[dict[str, object]] = []
            remaining_capacity = BUS_CAPACITY
            best_trip: dict[str, object] | None = None
            best_assignment: tuple[tuple[str, int, str], pd.Timestamp, bool] | None = None

            for idx in candidates.index:
                row = demand.loc[idx]
                if int(row["remaining"]) <= 0:
                    continue
                allocated = min(int(row["remaining"]), remaining_capacity)
                if allocated <= 0:
                    continue
                candidate_stop = {
                    "store_id": int(row["store_id"]),
                    "store_name": str(row["store_name"]),
                    "latitude": float(row["latitude"]),
                    "longitude": float(row["longitude"]),
                    "cluster_id": int(row["cluster_id"]) if pd.notna(row["cluster_id"]) else None,
                    "wave_dt": pd.Timestamp(row["wave_dt"]),
                    "allocated_passengers": allocated,
                }
                trial_rows = selected_rows + [candidate_stop]
                trial_trip = build_trip_record(
                    trial_rows,
                    str(direction),
                    depot,
                    trip_id=f"{trip_prefix}_{trip_counter:04d}",
                    activity_counts=activity_counts,
                    use_pressure=True,
                )
                if int(trial_trip["stop_count"]) > MAX_STOPS_PER_TRIP or float(trial_trip["trip_duration_min"]) > MAX_TRIP_DURATION_MIN:
                    continue
                selected_rows = trial_rows
                remaining_capacity -= allocated
                if remaining_capacity == 0:
                    break

            # Evaluate the fullest route-feasible prefixes first, then choose the best schedulable one.
            best_score: tuple[int, float, float, int] | None = None
            for k in range(len(selected_rows), 0, -1):
                trial_trip = build_trip_record(
                    selected_rows[:k],
                    str(direction),
                    depot,
                    trip_id=f"{trip_prefix}_{trip_counter:04d}",
                    activity_counts=activity_counts,
                    use_pressure=True,
                )
                trial_series = pd.Series(trial_trip)
                assignment = choose_slot_assignment(trial_series, slots, assignment_rows, repair_mode=False)
                if assignment is None:
                    assignment = choose_slot_assignment(trial_series, slots, assignment_rows, repair_mode=True)
                if assignment is None:
                    continue
                score = (
                    int(trial_trip["assigned_passengers"]),
                    float(trial_trip["occupancy_pct"]),
                    -float(trial_trip["trip_duration_min"]),
                    int(trial_trip["stop_count"]),
                )
                if best_score is None or score > best_score:
                    best_score = score
                    best_trip = trial_trip
                    best_assignment = assignment

            if best_trip is None or best_assignment is None:
                single_stop = {
                    "store_id": int(seed["store_id"]),
                    "store_name": str(seed["store_name"]),
                    "latitude": float(seed["latitude"]),
                    "longitude": float(seed["longitude"]),
                    "cluster_id": int(seed["cluster_id"]) if pd.notna(seed["cluster_id"]) else None,
                    "wave_dt": pd.Timestamp(seed["wave_dt"]),
                    "allocated_passengers": min(int(seed["remaining"]), BUS_CAPACITY),
                }
                fallback_trip = build_trip_record(
                    [single_stop],
                    str(direction),
                    depot,
                    trip_id=f"{trip_prefix}_{trip_counter:04d}",
                    activity_counts=activity_counts,
                    use_pressure=True,
                )
                designed_rows.append(fallback_trip)
                reason_counts = collect_rejection_reasons(pd.Series(fallback_trip), slots, assignment_rows, repair_mode=True)
                primary_reason = classify_rejection_reason(reason_counts, pd.Series(fallback_trip))
                unscheduled_rows.append(
                    {
                        "trip_id": fallback_trip["trip_id"],
                        "trip_type": fallback_trip["trip_type"],
                        "requested_wave_label": fallback_trip["requested_wave_label"],
                        "rejection_reason": primary_reason,
                        "rejection_reason_counts": json.dumps(reason_counts, sort_keys=True),
                        "assigned_passengers": int(fallback_trip["assigned_passengers"]),
                        "peak_load": int(fallback_trip["peak_load"]),
                        "stop_count": int(fallback_trip["stop_count"]),
                        "occupancy_pct": float(fallback_trip["occupancy_pct"]),
                    }
                )
                demand.loc[seed_idx, "remaining"] = int(seed["remaining"]) - int(single_stop["allocated_passengers"])
                trip_counter += 1
                continue

            designed_rows.append(best_trip)
            for stop in decode_stop_data(best_trip["stop_data_json"]):
                stop_mask = (
                    (demand["wave_dt"] == pd.Timestamp(stop["wave_dt"]))
                    & (demand["direction"] == direction)
                    & (demand["store_id"] == int(stop["store_id"]))
                )
                demand.loc[stop_mask, "remaining"] = demand.loc[stop_mask, "remaining"] - int(stop["allocated_passengers"])
            slot_key, start_dt, rescued, split_reset = best_assignment
            apply_assignment(pd.Series(best_trip), slot_key, start_dt, rescued, split_reset, slots, scheduled_rows, assignment_rows)
            add_trip_to_activity(pd.Timestamp(start_dt), pd.Timestamp(start_dt) + timedelta(minutes=float(best_trip["trip_duration_min"])), activity_counts)
            trip_counter += 1

    scheduled = pd.DataFrame(scheduled_rows).sort_values(["planned_start_dt", "trip_id"]).reset_index(drop=True)
    assignments = pd.DataFrame(assignment_rows).sort_values(["planned_start_dt", "bus_id"]).reset_index(drop=True)
    unscheduled = pd.DataFrame(unscheduled_rows)
    designed = pd.DataFrame(designed_rows).sort_values(["planned_start_dt", "trip_id"]).reset_index(drop=True)
    return designed, scheduled, assignments, unscheduled


def add_mixed_labels(scheduled: pd.DataFrame, assignments: pd.DataFrame) -> pd.DataFrame:
    # === SEARCH HOOK: MIXED LABEL CLEANUP ===
    # Purpose:
    # Add a lighter MIXED label when an IN trip is immediately followed by a short-gap OUT trip
    # on the same bus, even if no full mixed reconstruction happened earlier.
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


def build_employee_bus_schedule(events: pd.DataFrame, scheduled: pd.DataFrame, assignments: pd.DataFrame) -> pd.DataFrame:
    # Build a schedule-style employee mapping by pairing each trip stop's allocated seats
    # with the employee event pool at the same direction/store/wave whenever possible.
    columns = [
        "employee_code",
        "employee_event_dt",
        "employee_direction",
        "service_date",
        "trip_id",
        "trip_type",
        "bus_id",
        "rotation_tag",
        "duty_segment",
        "store_id",
        "store_name",
        "trip_wave_dt",
        "planned_start_dt",
        "planned_end_dt",
        "mapping_status",
    ]
    if events.empty or scheduled.empty or assignments.empty:
        return pd.DataFrame(columns=columns)

    pool = events.copy()
    pool["event_dt"] = pd.to_datetime(pool["event_dt"])
    pool["event_wave_dt"] = pool["event_dt"].dt.floor(f"{WAVE_BUCKET_MIN}min")
    pool = pool.sort_values(["event_dt", "employee_code", "store_id", "direction"]).reset_index(drop=True)

    event_pool: dict[tuple[str, int, pd.Timestamp], deque[dict[str, object]]] = defaultdict(deque)
    for row in pool.itertuples(index=False):
        key = (str(row.direction), int(row.store_id), pd.Timestamp(row.event_wave_dt))
        event_pool[key].append(
            {
                "employee_code": str(row.employee_code),
                "employee_event_dt": pd.Timestamp(row.event_dt),
                "employee_direction": str(row.direction),
            }
        )

    assignment_lookup = assignments.set_index("trip_id")[["bus_id", "rotation_tag", "duty_segment"]].to_dict(orient="index")
    rows: list[dict[str, object]] = []

    def pop_candidates(
        direction: str,
        store_id: int,
        wave_dt: pd.Timestamp,
        count: int,
    ) -> tuple[list[dict[str, object]], str]:
        exact_key = (direction, store_id, wave_dt)
        exact_bucket = event_pool.get(exact_key)
        exact_take: list[dict[str, object]] = []
        while exact_bucket and len(exact_take) < count:
            exact_take.append(exact_bucket.popleft())
        if len(exact_take) == count:
            return exact_take, "exact_wave"

        remaining = count - len(exact_take)
        fallback_keys = sorted(
            [k for k in event_pool if k[0] == direction and k[1] == store_id and event_pool[k]],
            key=lambda k: (abs((pd.Timestamp(k[2]) - wave_dt).total_seconds()), pd.Timestamp(k[2])),
        )
        fallback_take = exact_take
        for key in fallback_keys:
            if key == exact_key:
                continue
            bucket = event_pool[key]
            while bucket and len(fallback_take) < count:
                fallback_take.append(bucket.popleft())
            if len(fallback_take) == count:
                return fallback_take, "nearest_wave"
        if fallback_take:
            return fallback_take, "partial"
        return [], "unmapped"

    for trip in scheduled.sort_values(["planned_start_dt", "trip_id"]).itertuples(index=False):
        trip_id = str(trip.trip_id)
        trip_type = str(trip.trip_type)
        service_date = str(trip.service_date)
        assignment_info = assignment_lookup.get(trip_id, {})
        bus_id = assignment_info.get("bus_id")
        rotation_tag = assignment_info.get("rotation_tag")
        duty_segment = assignment_info.get("duty_segment")
        stops = decode_stop_data(getattr(trip, "stop_data_json", ""))
        for stop in stops:
            store_id = int(stop["store_id"])
            store_name = str(stop["store_name"])
            wave_dt = pd.Timestamp(stop["wave_dt"]).floor(f"{WAVE_BUCKET_MIN}min")
            required = max(0, int(stop.get("allocated_passengers", 0)))

            if required == 0:
                continue
            if trip_type in {"IN", "OUT"}:
                directions = [trip_type]
            else:
                in_size = len(event_pool.get(("IN", store_id, wave_dt), []))
                out_size = len(event_pool.get(("OUT", store_id, wave_dt), []))
                directions = ["IN", "OUT"] if in_size >= out_size else ["OUT", "IN"]

            mapped_people: list[dict[str, object]] = []
            mapping_status = "unmapped"
            for direction in directions:
                if len(mapped_people) >= required:
                    break
                pulled, status = pop_candidates(direction, store_id, wave_dt, required - len(mapped_people))
                if pulled:
                    mapped_people.extend(pulled)
                    if mapping_status == "unmapped":
                        mapping_status = status

            for person in mapped_people:
                rows.append(
                    {
                        "employee_code": person["employee_code"],
                        "employee_event_dt": person["employee_event_dt"],
                        "employee_direction": person["employee_direction"],
                        "service_date": service_date,
                        "trip_id": trip_id,
                        "trip_type": trip_type,
                        "bus_id": bus_id,
                        "rotation_tag": rotation_tag,
                        "duty_segment": duty_segment,
                        "store_id": store_id,
                        "store_name": store_name,
                        "trip_wave_dt": wave_dt,
                        "planned_start_dt": trip.planned_start_dt,
                        "planned_end_dt": trip.planned_end_dt,
                        "mapping_status": mapping_status,
                    }
                )

            if len(mapped_people) < required:
                shortfall = required - len(mapped_people)
                for idx in range(1, shortfall + 1):
                    rows.append(
                        {
                            "employee_code": f"UNMAPPED_{trip_id}_{store_id}_{idx}",
                            "employee_event_dt": pd.NaT,
                            "employee_direction": trip_type if trip_type in {"IN", "OUT"} else "",
                            "service_date": service_date,
                            "trip_id": trip_id,
                            "trip_type": trip_type,
                            "bus_id": bus_id,
                            "rotation_tag": rotation_tag,
                            "duty_segment": duty_segment,
                            "store_id": store_id,
                            "store_name": store_name,
                            "trip_wave_dt": wave_dt,
                            "planned_start_dt": trip.planned_start_dt,
                            "planned_end_dt": trip.planned_end_dt,
                            "mapping_status": "unmapped",
                        }
                    )

    if not rows:
        return pd.DataFrame(columns=columns)
    schedule = pd.DataFrame(rows)
    return schedule.sort_values(["service_date", "bus_id", "planned_start_dt", "trip_id", "store_id", "employee_code"]).reset_index(drop=True)


def build_daily_driver_schedule(
    scheduled: pd.DataFrame,
    assignments: pd.DataFrame,
    service_dates: list[str],
) -> dict[str, pd.DataFrame]:
    columns = ["Trip No"] + [f"D{i}" for i in range(1, BUS_COUNT + 1)]
    if scheduled.empty or assignments.empty:
        return {service_date: pd.DataFrame(columns=columns) for service_date in service_dates}

    merged = assignments.merge(
        scheduled[["trip_id", "store_sequence", "trip_type", "planned_start_dt", "planned_end_dt", "service_date"]],
        on="trip_id",
        how="left",
        suffixes=("_assign", ""),
    )
    merged["trip_type"] = merged["trip_type"].fillna(merged.get("trip_type_assign"))
    merged["service_date"] = merged["service_date"].fillna(merged.get("service_date_assign"))
    merged["planned_start_dt"] = pd.to_datetime(merged["planned_start_dt"].fillna(merged.get("planned_start_dt_assign")))
    merged["planned_end_dt"] = pd.to_datetime(merged["planned_end_dt"].fillna(merged.get("planned_end_dt_assign")))
    merged["service_date"] = pd.to_datetime(merged["service_date"]).dt.date.astype(str)
    merged["bus_id"] = pd.to_numeric(merged["bus_id"], errors="coerce")
    merged = merged.dropna(subset=["bus_id", "service_date", "planned_start_dt"]).copy()
    merged["bus_id"] = merged["bus_id"].astype(int)
    merged = merged[merged["service_date"].isin(set(service_dates))].copy()
    merged = merged.sort_values(["service_date", "bus_id", "planned_start_dt", "trip_id"]).reset_index(drop=True)
    merged["driver_trip_no"] = merged.groupby(["service_date", "bus_id"]).cumcount() + 1

    sheet_map: dict[str, pd.DataFrame] = {}
    for service_date in service_dates:
        day_df = merged[merged["service_date"] == service_date].copy()
        max_trip_no = int(day_df["driver_trip_no"].max()) if not day_df.empty else 0
        rows: list[dict[str, object]] = []
        for trip_no in range(1, max_trip_no + 1):
            row: dict[str, object] = {"Trip No": f"Trip {trip_no}"}
            for bus_id in range(1, BUS_COUNT + 1):
                driver_key = f"D{bus_id}"
                match = day_df[(day_df["bus_id"] == bus_id) & (day_df["driver_trip_no"] == trip_no)]
                if match.empty:
                    row[driver_key] = ""
                    continue
                rec = match.iloc[0]
                start_text = pd.Timestamp(rec["planned_start_dt"]).strftime("%H:%M")
                end_text = pd.Timestamp(rec["planned_end_dt"]).strftime("%H:%M")
                sequence = str(rec.get("store_sequence", "") or "").strip()
                row[driver_key] = f"{rec['trip_id']} ({rec['trip_type']}) | {start_text}-{end_text} | {sequence}"
            rows.append(row)
        if rows:
            sheet_map[service_date] = pd.DataFrame(rows, columns=columns)
        else:
            sheet_map[service_date] = pd.DataFrame(columns=columns)
    return sheet_map


def load_driver_reference() -> dict[int, tuple[str, str]]:
    ref = pd.read_excel(BUS_ROUTES_FILE, sheet_name="Bus Route Details")
    mapping: dict[int, tuple[str, str]] = {}
    if "Drive #" not in ref.columns:
        return mapping
    for _, row in ref.iterrows():
        drive_raw = "" if pd.isna(row.get("Drive #")) else str(row.get("Drive #")).strip()
        if not drive_raw:
            continue
        match = re.match(r"^D(\d+)$", drive_raw, flags=re.IGNORECASE)
        if not match:
            continue
        bus_id = int(match.group(1))
        driver_no = "" if pd.isna(row.get("Driver Number")) else str(row.get("Driver Number")).strip().rstrip(".0")
        driver_name = "" if pd.isna(row.get("Driver Name")) else str(row.get("Driver Name")).strip()
        if bus_id not in mapping and (driver_no or driver_name):
            mapping[bus_id] = (driver_no, driver_name)
    return mapping


def build_daily_bus_route_details(
    scheduled: pd.DataFrame,
    assignments: pd.DataFrame,
    service_dates: list[str],
    driver_reference: dict[int, tuple[str, str]],
) -> dict[str, pd.DataFrame]:
    columns = [
        "Drive #",
        "Driver Number",
        "Driver Name",
        "Trip Start/ End",
        "Bus Seating Capacity",
        "Trip No",
        "Trip ID",
        "No of Stores",
        "Time",
        "AM/PM",
        "Store/ Location",
        "Store ID",
        "Store Name",
        "Issues",
        "Remarks by Barakat",
    ]
    if scheduled.empty or assignments.empty:
        return {service_date: pd.DataFrame(columns=columns) for service_date in service_dates}

    merged = assignments.merge(
        scheduled[["trip_id", "trip_type", "service_date", "planned_start_dt", "planned_end_dt", "stop_data_json"]],
        on="trip_id",
        how="left",
        suffixes=("_assign", ""),
    )
    merged["trip_type"] = merged["trip_type"].fillna(merged.get("trip_type_assign"))
    merged["service_date"] = merged["service_date"].fillna(merged.get("service_date_assign"))
    merged["planned_start_dt"] = pd.to_datetime(merged["planned_start_dt"].fillna(merged.get("planned_start_dt_assign")))
    merged["planned_end_dt"] = pd.to_datetime(merged["planned_end_dt"].fillna(merged.get("planned_end_dt_assign")))
    merged["service_date"] = pd.to_datetime(merged["service_date"]).dt.date.astype(str)
    merged["bus_id"] = pd.to_numeric(merged["bus_id"], errors="coerce")
    merged = merged.dropna(subset=["bus_id", "service_date", "planned_start_dt", "planned_end_dt"]).copy()
    merged["bus_id"] = merged["bus_id"].astype(int)
    merged = merged[merged["service_date"].isin(set(service_dates))].copy()
    merged = merged.sort_values(["service_date", "bus_id", "planned_start_dt", "trip_id"]).reset_index(drop=True)
    merged["driver_trip_no"] = merged.groupby(["service_date", "bus_id"]).cumcount() + 1

    def time_fields(ts: pd.Timestamp) -> tuple[time, str]:
        ts = pd.Timestamp(ts)
        return ts.time().replace(microsecond=0), ts.strftime("%p")

    sheet_map: dict[str, pd.DataFrame] = {}
    for service_date in service_dates:
        rows: list[dict[str, object]] = []
        day_df = merged[merged["service_date"] == service_date].copy()
        for rec in day_df.itertuples(index=False):
            bus_id = int(rec.bus_id)
            drive = f"D{bus_id}"
            driver_no, driver_name = driver_reference.get(bus_id, ("", ""))
            trip_no = int(rec.driver_trip_no)
            trip_code = f"T{trip_no}"
            start_time, start_ampm = time_fields(rec.planned_start_dt)
            end_time, end_ampm = time_fields(rec.planned_end_dt)
            common = {
                "Drive #": drive,
                "Driver Number": driver_no,
                "Driver Name": driver_name,
                "Bus Seating Capacity": BUS_CAPACITY,
                "Trip No": trip_no,
                "Trip ID": trip_code,
                "Issues": "",
                "Remarks by Barakat": "",
            }
            rows.append(
                {
                    **common,
                    "Trip Start/ End": "Trip Start",
                    "No of Stores": "",
                    "Time": start_time,
                    "AM/PM": start_ampm,
                    "Store/ Location": "B1 Mahboula Acc",
                    "Store ID": "",
                    "Store Name": "",
                }
            )
            for stop in decode_stop_data(getattr(rec, "stop_data_json", "")):
                stop_dt = pd.Timestamp(stop.get("wave_dt", rec.planned_start_dt))
                stop_time, stop_ampm = time_fields(stop_dt)
                rows.append(
                    {
                        **common,
                        "Trip Start/ End": "",
                        "No of Stores": int(stop.get("allocated_passengers", 0)) if pd.notna(stop.get("allocated_passengers", 0)) else "",
                        "Time": stop_time,
                        "AM/PM": stop_ampm,
                        "Store/ Location": "",
                        "Store ID": int(stop["store_id"]) if pd.notna(stop.get("store_id")) else "",
                        "Store Name": str(stop.get("store_name", "")),
                    }
                )
            rows.append(
                {
                    **common,
                    "Trip Start/ End": "Trip End",
                    "No of Stores": "",
                    "Time": end_time,
                    "AM/PM": end_ampm,
                    "Store/ Location": "B2 Mahboula Acc",
                    "Store ID": "",
                    "Store Name": "",
                }
            )
        sheet_map[service_date] = pd.DataFrame(rows, columns=columns)
    return sheet_map


def build_daily_employee_trip_mapping(
    employee_bus_schedule: pd.DataFrame,
    assignments: pd.DataFrame,
    service_dates: list[str],
) -> dict[str, pd.DataFrame]:
    columns = [
        "Drive #",
        "Trip No",
        "Trip ID",
        "Trip Start",
        "Trip End",
        "Employee Count",
        "Employees",
        "Unmapped Seats",
    ]
    if assignments.empty:
        return {service_date: pd.DataFrame(columns=columns) for service_date in service_dates}

    base = assignments.copy()
    base["service_date"] = pd.to_datetime(base["service_date"]).dt.date.astype(str)
    base["planned_start_dt"] = pd.to_datetime(base["planned_start_dt"])
    base["planned_end_dt"] = pd.to_datetime(base["planned_end_dt"])
    base["bus_id"] = pd.to_numeric(base["bus_id"], errors="coerce")
    base = base.dropna(subset=["bus_id", "service_date", "planned_start_dt"]).copy()
    base["bus_id"] = base["bus_id"].astype(int)
    base = base[base["service_date"].isin(set(service_dates))].copy()
    base = base.sort_values(["service_date", "bus_id", "planned_start_dt", "trip_id"]).reset_index(drop=True)
    base["driver_trip_no"] = base.groupby(["service_date", "bus_id"]).cumcount() + 1

    grouped_employees = pd.DataFrame(columns=["service_date", "trip_id", "employee_count", "employees", "unmapped_seats"])
    if not employee_bus_schedule.empty:
        em = employee_bus_schedule.copy()
        em["service_date"] = pd.to_datetime(em["service_date"]).dt.date.astype(str)
        em["employee_code"] = em["employee_code"].astype(str)
        em["is_unmapped"] = em["employee_code"].str.startswith("UNMAPPED_")
        grouped_rows: list[dict[str, object]] = []
        for (service_date, trip_id), grp in em.groupby(["service_date", "trip_id"], dropna=False):
            mapped_codes = sorted(grp.loc[~grp["is_unmapped"], "employee_code"].dropna().astype(str).unique().tolist())
            grouped_rows.append(
                {
                    "service_date": service_date,
                    "trip_id": trip_id,
                    "employee_count": int((~grp["is_unmapped"]).sum()),
                    "employees": ", ".join(mapped_codes),
                    "unmapped_seats": int(grp["is_unmapped"].sum()),
                }
            )
        grouped_employees = pd.DataFrame(grouped_rows)

    merged = base.merge(grouped_employees, on=["service_date", "trip_id"], how="left")
    merged["employee_count"] = pd.to_numeric(merged.get("employee_count"), errors="coerce").fillna(0).astype(int)
    merged["employees"] = merged.get("employees").fillna("")
    merged["unmapped_seats"] = pd.to_numeric(merged.get("unmapped_seats"), errors="coerce").fillna(0).astype(int)

    sheet_map: dict[str, pd.DataFrame] = {}
    for service_date in service_dates:
        day = merged[merged["service_date"] == service_date].copy()
        rows: list[dict[str, object]] = []
        for rec in day.itertuples(index=False):
            trip_no = int(rec.driver_trip_no)
            rows.append(
                {
                    "Drive #": f"D{int(rec.bus_id)}",
                    "Trip No": f"Trip {trip_no}",
                    "Trip ID": f"T{trip_no}",
                    "Trip Start": pd.Timestamp(rec.planned_start_dt).strftime("%H:%M"),
                    "Trip End": pd.Timestamp(rec.planned_end_dt).strftime("%H:%M"),
                    "Employee Count": int(rec.employee_count),
                    "Employees": str(rec.employees),
                    "Unmapped Seats": int(rec.unmapped_seats),
                }
            )
        sheet_map[service_date] = pd.DataFrame(rows, columns=columns)
    return sheet_map


def build_daily_driver_schedule_with_stops(
    scheduled: pd.DataFrame,
    assignments: pd.DataFrame,
    service_dates: list[str],
) -> dict[str, pd.DataFrame]:
    columns = [
        "Drive #",
        "Trip ID",
        "Time",
        "Event",
        "Location",
        "Store ID",
        "Store Name",
        "Passenger Count",
        "Trip Start",
        "Trip End",
    ]
    if scheduled.empty or assignments.empty:
        return {service_date: pd.DataFrame(columns=columns) for service_date in service_dates}

    merged = assignments.merge(
        scheduled[["trip_id", "trip_type", "service_date", "planned_start_dt", "planned_end_dt", "stop_data_json"]],
        on="trip_id",
        how="left",
        suffixes=("_assign", ""),
    )
    merged["trip_type"] = merged["trip_type"].fillna(merged.get("trip_type_assign"))
    merged["service_date"] = merged["service_date"].fillna(merged.get("service_date_assign"))
    merged["planned_start_dt"] = pd.to_datetime(merged["planned_start_dt"].fillna(merged.get("planned_start_dt_assign")))
    merged["planned_end_dt"] = pd.to_datetime(merged["planned_end_dt"].fillna(merged.get("planned_end_dt_assign")))
    merged["service_date"] = pd.to_datetime(merged["service_date"]).dt.date.astype(str)
    merged["bus_id"] = pd.to_numeric(merged["bus_id"], errors="coerce")
    merged = merged.dropna(subset=["bus_id", "service_date", "planned_start_dt", "planned_end_dt"]).copy()
    merged["bus_id"] = merged["bus_id"].astype(int)
    merged = merged[merged["service_date"].isin(set(service_dates))].copy()
    merged = merged.sort_values(["service_date", "bus_id", "planned_start_dt", "trip_id"]).reset_index(drop=True)
    merged["driver_trip_no"] = merged.groupby(["service_date", "bus_id"]).cumcount() + 1

    def time_str(value: pd.Timestamp | object) -> str:
        return pd.Timestamp(value).strftime("%I:%M %p")

    sheet_map: dict[str, pd.DataFrame] = {}
    for service_date in service_dates:
        day = merged[merged["service_date"] == service_date].copy()
        rows: list[dict[str, object]] = []
        for rec in day.itertuples(index=False):
            drive = f"D{int(rec.bus_id)}"
            trip_no = int(rec.driver_trip_no)
            trip_id = f"T{trip_no}"
            trip_start = pd.Timestamp(rec.planned_start_dt)
            trip_end = pd.Timestamp(rec.planned_end_dt)
            start_text = time_str(trip_start)
            end_text = time_str(trip_end)

            rows.append(
                {
                    "Drive #": drive,
                    "Trip ID": trip_id,
                    "Time": start_text,
                    "Event": "Trip Start",
                    "Location": "B1 Mahboula Acc",
                    "Store ID": "",
                    "Store Name": "",
                    "Passenger Count": "",
                    "Trip Start": start_text,
                    "Trip End": end_text,
                }
            )

            stops = decode_stop_data(getattr(rec, "stop_data_json", ""))
            for stop in stops:
                stop_dt = pd.Timestamp(stop.get("wave_dt", trip_start))
                rows.append(
                    {
                        "Drive #": drive,
                        "Trip ID": trip_id,
                        "Time": time_str(stop_dt),
                        "Event": "Stop",
                        "Location": str(stop.get("store_name", "")),
                        "Store ID": int(stop["store_id"]) if pd.notna(stop.get("store_id")) else "",
                        "Store Name": str(stop.get("store_name", "")),
                        "Passenger Count": int(stop.get("allocated_passengers", 0)) if pd.notna(stop.get("allocated_passengers")) else "",
                        "Trip Start": start_text,
                        "Trip End": end_text,
                    }
                )

            rows.append(
                {
                    "Drive #": drive,
                    "Trip ID": trip_id,
                    "Time": end_text,
                    "Event": "Trip End",
                    "Location": "B2 Mahboula Acc",
                    "Store ID": "",
                    "Store Name": "",
                    "Passenger Count": "",
                    "Trip Start": start_text,
                    "Trip End": end_text,
                }
            )
        sheet_map[service_date] = pd.DataFrame(rows, columns=columns)
    return sheet_map


def build_daily_final_schedule_schema(
    scheduled: pd.DataFrame,
    assignments: pd.DataFrame,
    service_dates: list[str],
) -> dict[str, pd.DataFrame]:
    columns = [
        "Bus ID",
        "Trip ID",
        "Type",
        "Shift Time",
        "Trip Start Time",
        "Trip End Time",
        "Trip Duration (Min)",
        "Deadhead (min)",
        "Stops",
        "Mission Passengers",
    ]
    if scheduled.empty or assignments.empty:
        return {service_date: pd.DataFrame(columns=columns) for service_date in service_dates}

    merged = assignments.merge(
        scheduled[["trip_id", "trip_type", "store_sequence", "service_date", "planned_start_dt", "planned_end_dt"]],
        on="trip_id",
        how="left",
        suffixes=("_assign", ""),
    )
    merged["trip_type"] = merged["trip_type"].fillna(merged.get("trip_type_assign"))
    merged["service_date"] = merged["service_date"].fillna(merged.get("service_date_assign"))
    merged["planned_start_dt"] = pd.to_datetime(merged["planned_start_dt"].fillna(merged.get("planned_start_dt_assign")))
    merged["planned_end_dt"] = pd.to_datetime(merged["planned_end_dt"].fillna(merged.get("planned_end_dt_assign")))
    merged["service_date"] = pd.to_datetime(merged["service_date"]).dt.date.astype(str)
    merged["bus_id"] = pd.to_numeric(merged["bus_id"], errors="coerce")
    merged = merged.dropna(subset=["bus_id", "service_date", "planned_start_dt", "planned_end_dt"]).copy()
    merged["bus_id"] = merged["bus_id"].astype(int)
    merged = merged[merged["service_date"].isin(set(service_dates))].copy()
    merged = merged.sort_values(["service_date", "planned_start_dt", "bus_id", "trip_id"]).reset_index(drop=True)

    def to_ampm(ts: pd.Timestamp) -> str:
        return pd.Timestamp(ts).strftime("%I:%M %p")

    type_map = {"IN": "INBOUND", "OUT": "OUTBOUND", "MIXED": "MIXED"}
    sheet_map: dict[str, pd.DataFrame] = {}
    for service_date in service_dates:
        day_df = merged[merged["service_date"] == service_date].copy()
        rows: list[dict[str, object]] = []
        for rec in day_df.itertuples(index=False):
            start_dt = pd.Timestamp(rec.planned_start_dt)
            end_dt = pd.Timestamp(rec.planned_end_dt)
            rows.append(
                {
                    "Bus ID": int(rec.bus_id),
                    "Trip ID": str(rec.trip_id),
                    "Type": type_map.get(str(rec.trip_type), str(rec.trip_type)),
                    "Shift Time": to_ampm(start_dt),
                    "Trip Start Time": to_ampm(start_dt),
                    "Trip End Time": to_ampm(end_dt),
                    "Trip Duration (Min)": int(round(float(rec.trip_duration_min))) if pd.notna(rec.trip_duration_min) else "",
                    "Deadhead (min)": 0,
                    "Stops": str(rec.store_sequence) if pd.notna(rec.store_sequence) else "",
                    "Mission Passengers": int(rec.assigned_passengers) if pd.notna(rec.assigned_passengers) else 0,
                }
            )
        sheet_map[service_date] = pd.DataFrame(rows, columns=columns)
    return sheet_map


def build_daily_passenger_itinerary(
    events: pd.DataFrame,
    employee_bus_schedule: pd.DataFrame,
    service_dates: list[str],
) -> dict[str, pd.DataFrame]:
    columns = [
        "Employee ID",
        "Employee Name",
        "Store",
        "Shift Start",
        "Shift End",
        "Transport Leg 1",
        "Transport Leg 2",
    ]
    if events.empty:
        return {service_date: pd.DataFrame(columns=columns) for service_date in service_dates}

    in_events = events[events["direction"] == "IN"].copy()
    if in_events.empty:
        return {service_date: pd.DataFrame(columns=columns) for service_date in service_dates}

    in_events["shift_start_dt"] = pd.to_datetime(in_events["shift_start_dt"])
    in_events["shift_end_dt"] = pd.to_datetime(in_events["shift_end_dt"])
    in_events["service_date"] = in_events["shift_start_dt"].dt.date.astype(str)
    in_events = in_events[in_events["service_date"].isin(set(service_dates))].copy()
    in_events = in_events.sort_values(["service_date", "shift_start_dt", "employee_code"]).reset_index(drop=True)

    sched = employee_bus_schedule.copy()
    if not sched.empty:
        sched["employee_event_dt"] = pd.to_datetime(sched["employee_event_dt"], errors="coerce")
        sched["planned_start_dt"] = pd.to_datetime(sched["planned_start_dt"], errors="coerce")
        sched["planned_end_dt"] = pd.to_datetime(sched["planned_end_dt"], errors="coerce")
        sched["employee_code"] = sched["employee_code"].astype(str)
        sched = sched[~sched["employee_code"].str.startswith("UNMAPPED_")].copy()

    def pick_leg(
        employee_code: str,
        direction: str,
        target_event_dt: pd.Timestamp,
    ) -> pd.Series | None:
        if sched.empty:
            return None
        cand = sched[
            (sched["employee_code"] == str(employee_code))
            & (sched["employee_direction"] == direction)
            & sched["employee_event_dt"].notna()
        ].copy()
        if cand.empty:
            return None
        cand["delta_min"] = (cand["employee_event_dt"] - pd.Timestamp(target_event_dt)).abs().dt.total_seconds() / 60.0
        cand = cand.sort_values(["delta_min", "planned_start_dt"]).reset_index(drop=True)
        return cand.iloc[0]

    def format_leg(leg: pd.Series | None, direction: str) -> str:
        if leg is None:
            return ""
        leg_type = str(leg["trip_type"]) if str(leg["trip_type"]) == "MIXED" else direction
        if direction == "IN":
            board_dt = pd.Timestamp(leg["planned_start_dt"])
            drop_dt = pd.Timestamp(leg["employee_event_dt"])
        else:
            board_dt = pd.Timestamp(leg["employee_event_dt"])
            drop_dt = pd.Timestamp(leg["planned_end_dt"])
        return (
            f"Bus {int(leg['bus_id'])} ({leg_type}) | "
            f"Board: {board_dt.strftime('%I:%M %p')} | "
            f"Drop: {drop_dt.strftime('%I:%M %p')}"
        )

    sheet_map: dict[str, pd.DataFrame] = {}
    for service_date in service_dates:
        day_df = in_events[in_events["service_date"] == service_date].copy()
        rows: list[dict[str, object]] = []
        for rec in day_df.itertuples(index=False):
            in_leg = pick_leg(str(rec.employee_code), "IN", pd.Timestamp(rec.shift_start_dt))
            out_leg = pick_leg(str(rec.employee_code), "OUT", pd.Timestamp(rec.shift_end_dt))
            rows.append(
                {
                    "Employee ID": str(rec.employee_code),
                    "Employee Name": str(rec.employee_name) if pd.notna(rec.employee_name) else "",
                    "Store": str(rec.store_name),
                    "Shift Start": pd.Timestamp(rec.shift_start_dt).strftime("%I:%M %p"),
                    "Shift End": pd.Timestamp(rec.shift_end_dt).strftime("%I:%M %p"),
                    "Transport Leg 1": format_leg(in_leg, "IN"),
                    "Transport Leg 2": format_leg(out_leg, "OUT"),
                }
            )
        sheet_map[service_date] = pd.DataFrame(rows, columns=columns)
    return sheet_map


def build_duties(assignments: pd.DataFrame) -> pd.DataFrame:
    # === SEARCH HOOK: DUTY METRICS / OVERTIME BASIS ===
    # Purpose:
    # Convert trip assignments into duty blocks used for overtime and legality KPIs.
    # Important:
    # After split-duty reset, one physical bus can contribute multiple duty segments in one day.
    if assignments.empty:
        return pd.DataFrame()
    duty_rows: list[dict[str, object]] = []
    duty_counter = 1
    group_cols = ["service_date", "bus_id", "rotation_tag", "duty_segment"] if "duty_segment" in assignments.columns else ["service_date", "bus_id", "rotation_tag"]
    for group_key, group in assignments.groupby(group_cols, dropna=False):
        if len(group_cols) == 4:
            service_day, bus_id, rotation_tag, duty_segment = group_key
        else:
            service_day, bus_id, rotation_tag = group_key
            duty_segment = 1
        group = group.sort_values("planned_start_dt")
        first_start = pd.Timestamp(group["planned_start_dt"].min())
        last_end = pd.Timestamp(group["planned_end_dt"].max())
        duty_rows.append(
            {
                "duty_id": f"DUTY_{duty_counter:04d}",
                "bus_id": bus_id,
                "service_date": service_day,
                "rotation_tag": rotation_tag,
                "duty_segment": int(duty_segment),
                "first_trip_start_dt": first_start,
                "last_trip_end_dt": last_end,
                "trip_count": int(len(group)),
                "trip_minutes": float(group["trip_duration_min"].sum()),
                "avg_occupancy_pct": float(group["occupancy_pct"].mean()),
                "rescued_trip_count": int(group["rescued_by_delay"].sum()),
                "handover_trip_count": int(group["handover_flag"].sum()),
                "split_reset_trip_count": int(group["split_reset_flag"].sum()) if "split_reset_flag" in group.columns else 0,
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


def summarize_unscheduled_reasons(unscheduled: pd.DataFrame) -> pd.DataFrame:
    if unscheduled.empty or "rejection_reason" not in unscheduled.columns:
        return pd.DataFrame(columns=["rejection_reason", "trip_count", "passenger_count"])
    summary = (
        unscheduled.groupby("rejection_reason", dropna=False)
        .agg(
            trip_count=("trip_id", "count"),
            passenger_count=("assigned_passengers", "sum"),
        )
        .reset_index()
        .sort_values(["trip_count", "passenger_count"], ascending=[False, False])
        .reset_index(drop=True)
    )
    return summary


def build_bottleneck_repair_demand(base_trips: pd.DataFrame, unscheduled: pd.DataFrame) -> pd.DataFrame:
    # === SEARCH HOOK: BOTTLENECK REPAIR DEMAND ===
    # Purpose:
    # Extract leftover stops from the known hard windows (05:00 and 18:00) for a focused retry pass.
    if base_trips.empty or unscheduled.empty:
        return pd.DataFrame()
    merged = unscheduled.merge(
        base_trips[["trip_id", "trip_type", "planned_start_dt", "requested_wave_dt", "stop_data_json"]],
        on="trip_id",
        how="left",
    )
    rows: list[dict[str, object]] = []
    for _, row in merged.iterrows():
        start_dt = pd.Timestamp(row["planned_start_dt"]) if pd.notna(row["planned_start_dt"]) else None
        if start_dt is None or start_dt.hour not in BOTTLENECK_HOURS:
            continue
        trip_type = row["trip_type_x"] if "trip_type_x" in row.index else row["trip_type"]
        if trip_type not in {"IN", "OUT"} and "trip_type_y" in row.index:
            trip_type = row["trip_type_y"]
        for stop in decode_stop_data(row.get("stop_data_json", "")):
            rows.append(
                {
                    "event_date": pd.Timestamp(stop["wave_dt"]).date().isoformat(),
                    "direction": trip_type if trip_type in {"IN", "OUT"} else row.get("direction", "OUT"),
                    "wave_dt": pd.Timestamp(stop["wave_dt"]),
                    "store_id": int(stop["store_id"]),
                    "store_name": str(stop["store_name"]),
                    "latitude": float(stop["latitude"]),
                    "longitude": float(stop["longitude"]),
                    "cluster_id": stop.get("cluster_id"),
                    "employees": int(stop["allocated_passengers"]),
                    "wave_label": pd.Timestamp(stop["wave_dt"]).strftime("%Y-%m-%d %H:%M"),
                }
            )
    if not rows:
        return pd.DataFrame()
    repair = pd.DataFrame(rows)
    repair = (
        repair.groupby(
            ["event_date", "direction", "wave_dt", "store_id", "store_name", "latitude", "longitude", "cluster_id", "wave_label"],
            dropna=False,
        )["employees"]
        .sum()
        .reset_index()
    )
    return repair.sort_values(["wave_dt", "direction", "store_name"]).reset_index(drop=True)


def build_small_fragment_repair_demand(base_trips: pd.DataFrame, unscheduled: pd.DataFrame) -> pd.DataFrame:
    # === SEARCH HOOK: SMALL FRAGMENT SALVAGE DEMAND ===
    # Purpose:
    # Pool tiny failed trips into broader salvage buckets before final rejection.
    if base_trips.empty or unscheduled.empty or "rejection_reason" not in unscheduled.columns:
        return pd.DataFrame()
    fragment_unscheduled = unscheduled[
        (unscheduled["rejection_reason"] == "small_isolated_demand")
        | (
            unscheduled["rejection_reason"].isin(["buffer_violation", "slot_exhausted"])
            & (pd.to_numeric(unscheduled["assigned_passengers"], errors="coerce").fillna(0) <= 4)
            & (pd.to_numeric(unscheduled["stop_count"], errors="coerce").fillna(99) <= 2)
        )
    ].copy()
    if fragment_unscheduled.empty:
        return pd.DataFrame()
    merged = fragment_unscheduled.merge(
        base_trips[["trip_id", "trip_type", "requested_wave_dt", "stop_data_json"]],
        on="trip_id",
        how="left",
    )
    rows: list[dict[str, object]] = []
    for _, row in merged.iterrows():
        trip_type = row["trip_type_x"] if "trip_type_x" in row.index else row["trip_type"]
        if trip_type not in {"IN", "OUT"} and "trip_type_y" in row.index:
            trip_type = row["trip_type_y"]
        for stop in decode_stop_data(row.get("stop_data_json", "")):
            wave_dt = pd.Timestamp(stop["wave_dt"]).floor(f"{SALVAGE_WAVE_BUCKET_MIN}min")
            rows.append(
                {
                    "event_date": wave_dt.date().isoformat(),
                    "direction": trip_type if trip_type in {"IN", "OUT"} else row.get("direction", "OUT"),
                    "wave_dt": wave_dt,
                    "store_id": int(stop["store_id"]),
                    "store_name": str(stop["store_name"]),
                    "latitude": float(stop["latitude"]),
                    "longitude": float(stop["longitude"]),
                    "cluster_id": stop.get("cluster_id"),
                    "employees": int(stop["allocated_passengers"]),
                    "wave_label": wave_dt.strftime("%Y-%m-%d %H:%M"),
                }
            )
    if not rows:
        return pd.DataFrame()
    repair = pd.DataFrame(rows)
    repair = (
        repair.groupby(
            ["event_date", "direction", "wave_dt", "store_id", "store_name", "latitude", "longitude", "cluster_id", "wave_label"],
            dropna=False,
        )["employees"]
        .sum()
        .reset_index()
    )
    return repair.sort_values(["wave_dt", "direction", "store_name"]).reset_index(drop=True)


def build_cooperative_merge_repair_demand(base_trips: pd.DataFrame, unscheduled: pd.DataFrame) -> pd.DataFrame:
    # === SEARCH HOOK: COOPERATIVE MERGE DEMAND ===
    # Purpose:
    # Build a second, wider leftover pool aimed at merging multiple failed fragments together.
    # Example:
    # Three small failures across adjacent windows can become one merged retry opportunity.
    if base_trips.empty or unscheduled.empty or "rejection_reason" not in unscheduled.columns:
        return pd.DataFrame()
    merge_unscheduled = unscheduled[
        unscheduled["rejection_reason"].isin(["small_isolated_demand", "buffer_violation", "slot_exhausted"])
        & (pd.to_numeric(unscheduled["assigned_passengers"], errors="coerce").fillna(0) <= COOP_MERGE_MAX_PASSENGERS)
        & (pd.to_numeric(unscheduled["stop_count"], errors="coerce").fillna(99) <= COOP_MERGE_MAX_STOPS)
    ].copy()
    if merge_unscheduled.empty:
        return pd.DataFrame()
    merged = merge_unscheduled.merge(
        base_trips[["trip_id", "trip_type", "stop_data_json"]],
        on="trip_id",
        how="left",
    )
    rows: list[dict[str, object]] = []
    for _, row in merged.iterrows():
        trip_type = row["trip_type_x"] if "trip_type_x" in row.index else row["trip_type"]
        if trip_type not in {"IN", "OUT"} and "trip_type_y" in row.index:
            trip_type = row["trip_type_y"]
        for stop in decode_stop_data(row.get("stop_data_json", "")):
            wave_dt = pd.Timestamp(stop["wave_dt"]).floor(f"{COOP_MERGE_WAVE_BUCKET_MIN}min")
            rows.append(
                {
                    "event_date": wave_dt.date().isoformat(),
                    "direction": trip_type if trip_type in {"IN", "OUT"} else row.get("direction", "OUT"),
                    "wave_dt": wave_dt,
                    "store_id": int(stop["store_id"]),
                    "store_name": str(stop["store_name"]),
                    "latitude": float(stop["latitude"]),
                    "longitude": float(stop["longitude"]),
                    "cluster_id": None,
                    "employees": int(stop["allocated_passengers"]),
                    "wave_label": wave_dt.strftime("%Y-%m-%d %H:%M"),
                }
            )
    if not rows:
        return pd.DataFrame()
    repair = pd.DataFrame(rows)
    repair = (
        repair.groupby(
            ["event_date", "direction", "wave_dt", "store_id", "store_name", "latitude", "longitude", "cluster_id", "wave_label"],
            dropna=False,
        )["employees"]
        .sum()
        .reset_index()
    )
    return repair.sort_values(["wave_dt", "direction", "store_name"]).reset_index(drop=True)


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
    occupied_seats = float(scheduled["peak_load"].sum()) if not scheduled.empty else 0.0
    weighted_occ = (occupied_seats / total_offered_seats) * 100 if total_offered_seats else 0.0
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
        ("split_duty_count", int((duties["duty_segment"] > 1).sum()) if not duties.empty and "duty_segment" in duties.columns else 0),
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


def build_kpi_comparison(baseline_kpis: pd.DataFrame, integrated_kpis: pd.DataFrame) -> pd.DataFrame:
    baseline_map = dict(zip(baseline_kpis["metric"], baseline_kpis["value"]))
    integrated_map = dict(zip(integrated_kpis["metric"], integrated_kpis["value"]))
    metrics = sorted(set(baseline_map) | set(integrated_map))
    rows: list[dict[str, object]] = []
    for metric in metrics:
        base_val = baseline_map.get(metric)
        int_val = integrated_map.get(metric)
        diff = None
        try:
            if base_val is not None and int_val is not None:
                diff = float(int_val) - float(base_val)
        except (TypeError, ValueError):
            diff = None
        rows.append(
            {
                "metric": metric,
                "baseline_staged": base_val,
                "integrated_base": int_val,
                "difference_integrated_minus_baseline": diff,
            }
        )
    return pd.DataFrame(rows)


def safe_csv_export(df: pd.DataFrame, path: Path) -> Path:
    try:
        df.to_csv(path, index=False)
        return path
    except PermissionError:
        fallback = path.with_name(f"{path.stem}_latest{path.suffix}")
        df.to_csv(fallback, index=False)
        print(f"Warning: '{path.name}' was locked. Wrote '{fallback.name}' instead.")
        return fallback


def safe_daily_schedule_export(sheet_map: dict[str, pd.DataFrame], service_dates: list[str], path: Path) -> Path:
    cols = ["Trip No"] + [f"D{i}" for i in range(1, BUS_COUNT + 1)]

    def write_to(target: Path) -> None:
        with pd.ExcelWriter(target, engine="openpyxl") as writer:
            for service_date in service_dates:
                sheet_df = sheet_map.get(service_date, pd.DataFrame(columns=cols))
                sheet_df.to_excel(writer, sheet_name=service_date[:31], index=False)

    try:
        write_to(path)
        return path
    except PermissionError:
        fallback = path.with_name(f"{path.stem}_latest{path.suffix}")
        write_to(fallback)
        print(f"Warning: '{path.name}' was locked. Wrote '{fallback.name}' instead.")
        return fallback


def prune_directory_to_whitelist(directory: Path, keep_filenames: set[str]) -> None:
    if not directory.exists():
        return
    for item in directory.iterdir():
        if not item.is_file():
            continue
        if item.name in keep_filenames:
            continue
        try:
            item.unlink()
        except PermissionError:
            print(f"Warning: could not delete locked file '{item.name}'")


def export_all_outputs(
    strict_matches: pd.DataFrame,
    stores_with_clusters: pd.DataFrame,
    clusters_summary: pd.DataFrame,
    demand: pd.DataFrame,
    peak_pressure: pd.DataFrame,
    hybrid_trips: pd.DataFrame,
    scheduled: pd.DataFrame,
    assignments: pd.DataFrame,
    employee_bus_schedule: pd.DataFrame,
    daily_driver_schedule: dict[str, pd.DataFrame],
    daily_bus_route_details: dict[str, pd.DataFrame],
    daily_employee_trip_mapping: dict[str, pd.DataFrame],
    daily_driver_schedule_with_stops: dict[str, pd.DataFrame],
    daily_final_schedule_schema: dict[str, pd.DataFrame],
    daily_passenger_itinerary: dict[str, pd.DataFrame],
    duties: pd.DataFrame,
    unscheduled: pd.DataFrame,
    unscheduled_reason_summary: pd.DataFrame,
    unmatched: pd.DataFrame,
    baseline_issues: pd.DataFrame,
    baseline_kpis: pd.DataFrame,
    kpi_comparison: pd.DataFrame,
    fragment_repair_demand: pd.DataFrame,
    fragment_repair_trips: pd.DataFrame,
    cooperative_merge_demand: pd.DataFrame,
    cooperative_merge_trips: pd.DataFrame,
    repair_demand: pd.DataFrame,
    repair_trips: pd.DataFrame,
    kpis: pd.DataFrame,
    shift_service_dates: list[str],
) -> None:
    unscheduled.to_csv(OUTPUT_DIR / "unscheduled_trips.csv", index=False)
    baseline_kpis.to_csv(OUTPUT_DIR / "baseline_staged_kpi_summary.csv", index=False)
    kpis.to_csv(OUTPUT_DIR / "kpi_summary.csv", index=False)
    safe_daily_schedule_export(daily_driver_schedule_with_stops, shift_service_dates, EMPLOYER_OUTPUT_DIR / "trips_per_day.xlsx")
    safe_daily_schedule_export(daily_employee_trip_mapping, shift_service_dates, EMPLOYER_OUTPUT_DIR / "employee_to_bus_mapping_per_day.xlsx")

    prune_directory_to_whitelist(
        OUTPUT_DIR,
        {
            "kpi_summary.csv",
            "baseline_staged_kpi_summary.csv",
            "unscheduled_trips.csv",
        },
    )
    prune_directory_to_whitelist(
        EMPLOYER_OUTPUT_DIR,
        {
            "trips_per_day.xlsx",
            "employee_to_bus_mapping_per_day.xlsx",
        },
    )


def main() -> None:
    # === SEARCH HOOK: PIPELINE ENTRYPOINT ===
    # End-to-end order:
    # demand -> base OR-Tools trips -> mixed conversion -> main scheduling ->
    # fragment salvage -> cooperative merge -> bottleneck repair -> KPI export.
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    EMPLOYER_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    overview = load_overview_metrics()
    shift_service_dates = load_shift_service_dates()
    driver_reference = load_driver_reference()
    geo_lookup = load_geocoordinates()
    strict_lookup, strict_matches = build_strict_lookup(geo_lookup)
    events, unmatched = extract_shift_events(strict_lookup)
    stores_with_clusters, clusters_summary = cluster_stores(events)
    demand = aggregate_store_waves(events, stores_with_clusters)
    peak_pressure = build_peak_pressure(demand)
    depot = geo_lookup.get(normalize_name(DEPOT_NAME))
    if depot is None:
        raise RuntimeError(f"Depot '{DEPOT_NAME}' not found in geocoordinates.")
    baseline_trips = build_base_trips_ortools(demand, depot)
    baseline_trips = build_mixed_candidates(baseline_trips, depot)
    baseline_scheduled, baseline_assignments, baseline_unscheduled = schedule_with_rotation_reset(baseline_trips, depot)
    baseline_scheduled = add_mixed_labels(baseline_scheduled, baseline_assignments)
    baseline_duties = build_duties(baseline_assignments)

    fragment_repair_demand = build_small_fragment_repair_demand(baseline_trips, baseline_unscheduled)
    fragment_repair_trips = pd.DataFrame()
    fragment_repair_scheduled = baseline_scheduled.copy()
    fragment_repair_assignments = baseline_assignments.copy()
    fragment_repair_unscheduled = pd.DataFrame()
    remaining_after_fragment = baseline_unscheduled.copy()
    base_for_repair = baseline_trips.copy()
    if not fragment_repair_demand.empty:
        fragment_repair_trips, fragment_repair_scheduled, fragment_repair_assignments, fragment_repair_unscheduled = build_and_schedule_integrated(
            fragment_repair_demand,
            depot,
            initial_scheduled=baseline_scheduled,
            initial_assignments=baseline_assignments,
            trip_prefix="SLV",
        )
        if not fragment_repair_trips.empty:
            repaired_keys = {
                (pd.Timestamp(stop["wave_dt"]).floor(f"{SALVAGE_WAVE_BUCKET_MIN}min"), int(stop["store_id"]), stop["store_name"], trip["trip_type"])
                for _, trip in fragment_repair_trips.iterrows()
                for stop in decode_stop_data(trip.get("stop_data_json", ""))
            }
            keep_rows = []
            for _, row in baseline_unscheduled.iterrows():
                if str(row.get("rejection_reason", "")) != "small_isolated_demand":
                    keep_rows.append(row.to_dict())
                    continue
                trip_match = baseline_trips[baseline_trips["trip_id"] == row["trip_id"]]
                remove = False
                if not trip_match.empty:
                    trip_type = str(trip_match.iloc[0]["trip_type"])
                    for stop in decode_stop_data(trip_match.iloc[0].get("stop_data_json", "")):
                        key = (pd.Timestamp(stop["wave_dt"]).floor(f"{SALVAGE_WAVE_BUCKET_MIN}min"), int(stop["store_id"]), stop["store_name"], trip_type)
                        if key in repaired_keys:
                            remove = True
                            break
                if not remove:
                    keep_rows.append(row.to_dict())
            remaining_after_fragment = pd.DataFrame(keep_rows)
            base_for_repair = pd.concat([baseline_trips, fragment_repair_trips], ignore_index=True)
        if not fragment_repair_unscheduled.empty:
            remaining_after_fragment = pd.concat([remaining_after_fragment, fragment_repair_unscheduled], ignore_index=True)

    cooperative_merge_demand = build_cooperative_merge_repair_demand(base_for_repair, remaining_after_fragment)
    cooperative_merge_trips = pd.DataFrame()
    cooperative_merge_scheduled = fragment_repair_scheduled.copy()
    cooperative_merge_assignments = fragment_repair_assignments.copy()
    cooperative_merge_unscheduled = pd.DataFrame()
    remaining_after_merge = remaining_after_fragment.copy()
    if not cooperative_merge_demand.empty:
        cooperative_merge_trips, cooperative_merge_scheduled, cooperative_merge_assignments, cooperative_merge_unscheduled = build_and_schedule_integrated(
            cooperative_merge_demand,
            depot,
            initial_scheduled=fragment_repair_scheduled,
            initial_assignments=fragment_repair_assignments,
            trip_prefix="MRG",
        )
        if not cooperative_merge_trips.empty:
            repaired_keys = {
                (pd.Timestamp(stop["wave_dt"]).floor(f"{COOP_MERGE_WAVE_BUCKET_MIN}min"), int(stop["store_id"]), stop["store_name"], trip["trip_type"])
                for _, trip in cooperative_merge_trips.iterrows()
                for stop in decode_stop_data(trip.get("stop_data_json", ""))
            }
            keep_rows = []
            for _, row in remaining_after_fragment.iterrows():
                trip_match = base_for_repair[base_for_repair["trip_id"] == row["trip_id"]]
                remove = False
                if not trip_match.empty:
                    trip_type = str(trip_match.iloc[0]["trip_type"])
                    for stop in decode_stop_data(trip_match.iloc[0].get("stop_data_json", "")):
                        key = (pd.Timestamp(stop["wave_dt"]).floor(f"{COOP_MERGE_WAVE_BUCKET_MIN}min"), int(stop["store_id"]), stop["store_name"], trip_type)
                        if key in repaired_keys:
                            remove = True
                            break
                if not remove:
                    keep_rows.append(row.to_dict())
            remaining_after_merge = pd.DataFrame(keep_rows)
            base_for_repair = pd.concat([base_for_repair, cooperative_merge_trips], ignore_index=True)
        if not cooperative_merge_unscheduled.empty:
            remaining_after_merge = pd.concat([remaining_after_merge, cooperative_merge_unscheduled], ignore_index=True)

    repair_demand = build_bottleneck_repair_demand(base_for_repair, remaining_after_merge)
    repair_trips = pd.DataFrame()
    repair_scheduled = cooperative_merge_scheduled.copy()
    repair_assignments = cooperative_merge_assignments.copy()
    repair_unscheduled = pd.DataFrame()
    if not repair_demand.empty:
        repair_trips, repair_scheduled, repair_assignments, repair_unscheduled = build_and_schedule_integrated(
            repair_demand,
            depot,
            initial_scheduled=cooperative_merge_scheduled,
            initial_assignments=cooperative_merge_assignments,
            trip_prefix="REP",
        )

    repair_only_trip_ids = set(repair_trips["trip_id"]) if not repair_trips.empty else set()
    scheduled = repair_scheduled.copy()
    assignments = repair_assignments.copy()
    scheduled = add_mixed_labels(scheduled, assignments)
    employee_bus_schedule = build_employee_bus_schedule(events, scheduled, assignments)
    daily_driver_schedule = build_daily_driver_schedule(scheduled, assignments, shift_service_dates)
    daily_bus_route_details = build_daily_bus_route_details(scheduled, assignments, shift_service_dates, driver_reference)
    daily_employee_trip_mapping = build_daily_employee_trip_mapping(employee_bus_schedule, assignments, shift_service_dates)
    daily_driver_schedule_with_stops = build_daily_driver_schedule_with_stops(scheduled, assignments, shift_service_dates)
    daily_final_schedule_schema = build_daily_final_schedule_schema(scheduled, assignments, shift_service_dates)
    daily_passenger_itinerary = build_daily_passenger_itinerary(events, employee_bus_schedule, shift_service_dates)
    duties = build_duties(assignments)
    remaining_unscheduled = remaining_after_merge.copy()
    if not repair_demand.empty and not repair_trips.empty:
        repaired_keys = {
            (pd.Timestamp(stop["wave_dt"]), int(stop["store_id"]), stop["store_name"], trip["trip_type"])
            for _, trip in repair_trips.iterrows()
            for stop in decode_stop_data(trip.get("stop_data_json", ""))
        }
        keep_rows = []
        for _, row in remaining_after_merge.iterrows():
            trip_match = base_for_repair[base_for_repair["trip_id"] == row["trip_id"]]
            remove = False
            if not trip_match.empty:
                trip_type = str(trip_match.iloc[0]["trip_type"])
                for stop in decode_stop_data(trip_match.iloc[0].get("stop_data_json", "")):
                    key = (pd.Timestamp(stop["wave_dt"]), int(stop["store_id"]), stop["store_name"], trip_type)
                    if key in repaired_keys:
                        remove = True
                        break
            if not remove:
                keep_rows.append(row.to_dict())
        remaining_unscheduled = pd.DataFrame(keep_rows)
    if not repair_unscheduled.empty:
        unscheduled = pd.concat([remaining_unscheduled, repair_unscheduled], ignore_index=True)
    else:
        unscheduled = remaining_unscheduled
    unscheduled_reason_summary = summarize_unscheduled_reasons(unscheduled)
    baseline_issues, baseline_metrics = calibrate_baseline()
    baseline_kpis = build_kpis(
        overview,
        strict_matches,
        demand,
        peak_pressure,
        baseline_trips,
        baseline_scheduled,
        baseline_assignments,
        baseline_duties,
        unmatched,
        baseline_unscheduled,
        baseline_metrics,
    )
    hybrid_trip_parts = [baseline_trips]
    if not fragment_repair_trips.empty:
        hybrid_trip_parts.append(fragment_repair_trips)
    if not cooperative_merge_trips.empty:
        hybrid_trip_parts.append(cooperative_merge_trips)
    if not repair_trips.empty:
        hybrid_trip_parts.append(repair_trips)
    hybrid_trips = pd.concat(hybrid_trip_parts, ignore_index=True) if len(hybrid_trip_parts) > 1 else baseline_trips.copy()
    kpis = build_kpis(overview, strict_matches, demand, peak_pressure, hybrid_trips, scheduled, assignments, duties, unmatched, unscheduled, baseline_metrics)
    kpi_comparison = build_kpi_comparison(baseline_kpis, kpis)
    export_all_outputs(
        strict_matches,
        stores_with_clusters,
        clusters_summary,
        demand,
        peak_pressure,
        hybrid_trips,
        scheduled,
        assignments,
        employee_bus_schedule,
        daily_driver_schedule,
        daily_bus_route_details,
        daily_employee_trip_mapping,
        daily_driver_schedule_with_stops,
        daily_final_schedule_schema,
        daily_passenger_itinerary,
        duties,
        unscheduled,
        unscheduled_reason_summary,
        unmatched,
        baseline_issues,
        baseline_kpis,
        kpi_comparison,
        fragment_repair_demand,
        fragment_repair_trips,
        cooperative_merge_demand,
        cooperative_merge_trips,
        repair_demand,
        repair_trips,
        kpis,
        shift_service_dates,
    )
    print("Prototype rebuilt from scratch.")
    print(f"Designed trips: {len(hybrid_trips)}")
    print(f"Scheduled trips: {len(scheduled)}")
    print(f"Outputs written to: {OUTPUT_DIR}")
    print(f"Employer-format outputs written to: {EMPLOYER_OUTPUT_DIR}")


if __name__ == "__main__":
    main()
