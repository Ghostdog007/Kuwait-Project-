from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, time
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


@dataclass(frozen=True)
class GeoPoint:
    canonical_name: str
    store_id: str
    latitude: float
    longitude: float


ALIAS_MAP = {
    "hardees sabah al salem block 1": "Hardees - Sabah Al Salem Block",
    "krispy kre mangaf sultan centr": "Krispy Kreme Mangaf Sultan Centr",
    "krispy kreme mangaf sultan center": "Krispy Kreme Mangaf Sultan Centr",
    "krispy kreme mangaf sultan centre": "Krispy Kreme Mangaf Sultan Centr",
    "krispy kreme alyia and ghalyia towers": "Krispy Kreme Alyia Ghalyia Tower",
    "krispy kreme sabah al ahmed": "Krispy Kreme - Sabah Al Ahmed",
    "krispy kreme khiran hybrid outlet": "Krispy Kreme - Khiran Hybrid O",
    "krispy kreme khiran square mall": "Krispy Kreme - Khiran Square M",
    "kfc mubarek el kaber qurain 2": "KFC Mubarek El-Kaber(Qurain 2)",
}


def normalize_name(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip().casefold().replace("&", "and")
    text = re.sub(r"[()]", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def to_minutes(value: object) -> int | None:
    if pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value.hour * 60 + value.minute
    if isinstance(value, time):
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
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("Hrs", "").replace("Hr", "").replace("hrs", "").replace("hr", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def build_geo_lookup() -> dict[str, GeoPoint]:
    geo = pd.read_excel(GEO_FILE)
    geo["latitude"] = pd.to_numeric(geo["latitude"], errors="coerce")
    geo["longitude"] = pd.to_numeric(geo["longitude"], errors="coerce")
    geo = geo.dropna(subset=["Store Name", "latitude", "longitude"]).copy()

    lookup: dict[str, GeoPoint] = {}
    for _, row in geo.iterrows():
        store_id = row["Store ID"]
        if pd.isna(store_id):
            store_id_str = ""
        else:
            store_id_float = float(store_id)
            store_id_str = str(int(store_id_float)) if store_id_float.is_integer() else str(store_id)
        point = GeoPoint(
            canonical_name=str(row["Store Name"]).strip(),
            store_id=store_id_str,
            latitude=float(row["latitude"]),
            longitude=float(row["longitude"]),
        )
        lookup[normalize_name(point.canonical_name)] = point
    return lookup


def resolve_store(name: str, geo_lookup: dict[str, GeoPoint]) -> GeoPoint | None:
    key = normalize_name(name)
    if not key:
        return None
    if key in geo_lookup:
        return geo_lookup[key]
    alias = ALIAS_MAP.get(key)
    if alias:
        return geo_lookup.get(normalize_name(alias))
    return None


def parse_overview() -> dict[str, str]:
    overview = pd.read_excel(OVERVIEW_FILE)
    overview.columns = ["market_parameter", "market_value", "market_description", "_gap", "pilot_parameter", "pilot_value", "pilot_description"]
    values: dict[str, str] = {}
    for _, row in overview.iterrows():
        key = str(row["pilot_parameter"]).strip() if pd.notna(row["pilot_parameter"]) else ""
        value = str(row["pilot_value"]).strip() if pd.notna(row["pilot_value"]) else ""
        if key:
            values[key] = value
    return values


def parse_shift_workbook(geo_lookup: dict[str, GeoPoint]) -> tuple[pd.DataFrame, pd.DataFrame]:
    workbook = pd.ExcelFile(SHIFT_DATA_FILE)
    demand_rows: list[dict[str, object]] = []
    unmatched_rows: list[dict[str, object]] = []

    for sheet in workbook.sheet_names:
        raw = workbook.parse(sheet, header=None)
        if raw.shape[0] < 4:
            continue

        date_row = raw.iloc[1].tolist()
        header_row = raw.iloc[2].tolist()
        body = raw.iloc[3:].copy()
        body.columns = header_row

        for row_idx, row in body.iterrows():
            store_name = "" if pd.isna(row.get("Store Name")) else str(row.get("Store Name")).strip()
            if not store_name:
                continue

            point = resolve_store(store_name, geo_lookup)
            employee_code = str(row.get("EMPLOYEE CODE", row_idx))

            if point is None:
                unmatched_rows.append(
                    {
                        "source_dataset": "Employee Shift data.xlsx",
                        "source_sheet": sheet,
                        "source_column": "Store Name",
                        "origin_id": employee_code,
                        "store_name": store_name,
                        "normalized_store_name": normalize_name(store_name),
                    }
                )
                continue

            for col_idx in range(8, len(header_row), 4):
                if col_idx + 3 >= len(header_row):
                    break

                service_date = date_row[col_idx]
                shift_start = to_minutes(row.iloc[col_idx])
                shift_end = to_minutes(row.iloc[col_idx + 1])
                shift2_start = to_minutes(row.iloc[col_idx + 2])
                shift2_end = to_minutes(row.iloc[col_idx + 3])

                day_value = header_row[col_idx]
                day_name = "" if pd.isna(day_value) else str(day_value).strip()
                service_date_str = ""
                if isinstance(service_date, (pd.Timestamp, datetime, date)):
                    service_date_str = pd.Timestamp(service_date).date().isoformat()

                def append_shift(start_min: int | None, end_min: int | None, shift_slot: int) -> None:
                    if start_min is None or end_min is None:
                        return
                    end_for_order = end_min + 24 * 60 if end_min < start_min else end_min
                    demand_rows.append(
                        {
                            "source_sheet": sheet,
                            "employee_code": employee_code,
                            "accommodation_name": "" if pd.isna(row.get("Accommodation Name")) else str(row.get("Accommodation Name")).strip(),
                            "brand": "" if pd.isna(row.get("Brand")) else str(row.get("Brand")).strip(),
                            "store_id": point.store_id,
                            "store_name": point.canonical_name,
                            "service_date": service_date_str,
                            "day_name": day_name,
                            "shift_slot": shift_slot,
                            "shift_start_min": start_min,
                            "shift_end_min": end_for_order,
                            "inbound_wave_min": start_min,
                            "outbound_wave_min": end_for_order,
                            "demand_units": 1,
                            "latitude": point.latitude,
                            "longitude": point.longitude,
                        }
                    )

                append_shift(shift_start, shift_end, 1)
                append_shift(shift2_start, shift2_end, 2)

    demand = pd.DataFrame(demand_rows)
    unmatched = pd.DataFrame(unmatched_rows)
    return demand, unmatched


def aggregate_demand(demand: pd.DataFrame) -> pd.DataFrame:
    inbound = (
        demand.groupby(["store_id", "store_name", "source_sheet", "service_date", "day_name", "inbound_wave_min", "latitude", "longitude"], dropna=False)["demand_units"]
        .sum()
        .reset_index()
        .rename(columns={"inbound_wave_min": "wave_min", "demand_units": "employees"})
    )
    inbound["direction"] = "IN"

    outbound = (
        demand.groupby(["store_id", "store_name", "source_sheet", "service_date", "day_name", "outbound_wave_min", "latitude", "longitude"], dropna=False)["demand_units"]
        .sum()
        .reset_index()
        .rename(columns={"outbound_wave_min": "wave_min", "demand_units": "employees"})
    )
    outbound["direction"] = "OUT"

    combined = pd.concat([inbound, outbound], ignore_index=True)
    combined["wave_label"] = combined["wave_min"].map(lambda x: f"{int(x // 60):02d}:{int(x % 60):02d}" if pd.notna(x) else "")
    combined = combined.sort_values(["service_date", "wave_min", "direction", "store_name"]).reset_index(drop=True)
    return combined


def parse_bus_routes(geo_lookup: dict[str, GeoPoint]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    routes = pd.read_excel(BUS_ROUTES_FILE, sheet_name="Bus Route Details").copy()
    routes["Trip Start/ End"] = routes["Trip Start/ End"].astype(str).str.strip().str.casefold()

    trip_rows: list[dict[str, object]] = []
    unmatched_rows: list[dict[str, object]] = []

    def time_from_row(row: pd.Series) -> int | None:
        timestamp = row.get("Time")
        am_pm = row.get("AM/PM")
        if pd.isna(timestamp):
            return None
        if isinstance(timestamp, pd.Timestamp):
            base = timestamp.to_pydatetime()
            if isinstance(am_pm, str) and am_pm.strip().upper() in {"AM", "PM"}:
                hour = base.hour % 12
                if am_pm.strip().upper() == "PM":
                    hour += 12
                return hour * 60 + base.minute
            return base.hour * 60 + base.minute
        return None

    for (drive, trip_no, trip_id), group in routes.groupby(["Drive #", "Trip No", "Trip ID"], dropna=False):
        if pd.isna(drive) or pd.isna(trip_no) or pd.isna(trip_id):
            continue
        group = group.copy()
        group["time_min"] = group.apply(time_from_row, axis=1)
        group = group.sort_values(["time_min"], na_position="last")

        stop_names: list[str] = []
        for store_value in group["Store Name"].dropna():
            for part in str(store_value).split(","):
                cleaned = part.strip()
                if cleaned:
                    stop_names.append(cleaned)

        matched_points: list[GeoPoint] = []
        for seq, stop_name in enumerate(stop_names, start=1):
            point = resolve_store(stop_name, geo_lookup)
            if point is None:
                unmatched_rows.append(
                    {
                        "source_dataset": "Bus Routes curent.xlsx",
                        "source_sheet": "Bus Route Details",
                        "source_column": "Store Name",
                        "origin_id": f"{drive}|{trip_no}|{trip_id}",
                        "store_name": stop_name,
                        "normalized_store_name": normalize_name(stop_name),
                    }
                )
                continue
            matched_points.append(point)

        route_km = 0.0
        for prev, curr in zip(matched_points, matched_points[1:]):
            route_km += haversine_km(prev.latitude, prev.longitude, curr.latitude, curr.longitude)

        time_values = [val for val in group["time_min"].tolist() if val is not None]
        start_min = min(time_values) if time_values else None
        end_min = max(time_values) if time_values else None
        duration_min = None if start_min is None or end_min is None else end_min - start_min

        first_row = group.iloc[0]
        trip_rows.append(
            {
                "drive_id": "" if pd.isna(drive) else str(drive),
                "driver_number": "" if pd.isna(first_row.get("Driver Number")) else str(int(first_row.get("Driver Number"))),
                "driver_name": "" if pd.isna(first_row.get("Driver Name")) else str(first_row.get("Driver Name")).strip(),
                "trip_no": "" if pd.isna(trip_no) else str(int(trip_no)),
                "trip_id": "" if pd.isna(trip_id) else str(trip_id),
                "trip_key": f"{'' if pd.isna(drive) else drive}|{'' if pd.isna(trip_no) else int(trip_no)}|{'' if pd.isna(trip_id) else trip_id}",
                "scheduled_capacity": pd.to_numeric(first_row.get("Bus Seating Capacity"), errors="coerce"),
                "original_stop_count": len(stop_names),
                "matched_stop_count": len(matched_points),
                "routeable_trip": len(matched_points) >= 1,
                "trip_start_min": start_min,
                "trip_end_min": end_min,
                "trip_duration_min": duration_min,
                "route_distance_km": round(route_km, 3),
                "routed_store_sequence": " -> ".join(point.canonical_name for point in matched_points),
            }
        )

    trips = pd.DataFrame(trip_rows).sort_values(["drive_id", "trip_start_min", "trip_no"], na_position="last")

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
    issues["reported_payment_total_hours"] = issues["payment_total_working_hours"].map(parse_duration_hours)

    unmatched = pd.DataFrame(unmatched_rows)
    return trips, issues, unmatched


def build_clusters(demand_summary: pd.DataFrame, geo_lookup: dict[str, GeoPoint]) -> tuple[pd.DataFrame, pd.DataFrame]:
    store_totals = (
        demand_summary.groupby(["store_id", "store_name", "latitude", "longitude"], dropna=False)["employees"]
        .sum()
        .reset_index()
        .rename(columns={"employees": "weekly_employee_demand"})
    )
    routeable = store_totals.dropna(subset=["latitude", "longitude"]).copy()
    if routeable.empty:
        routeable["cluster_id"] = []
        return routeable, pd.DataFrame(columns=["cluster_id", "store_count", "weekly_employee_demand", "centroid_latitude", "centroid_longitude"])

    cluster_count = max(1, min(len(routeable), math.ceil(len(routeable) / 12)))
    coords = routeable[["latitude", "longitude"]]
    model = KMeans(n_clusters=cluster_count, n_init=10, random_state=42)
    routeable["cluster_id"] = model.fit_predict(coords, sample_weight=routeable["weekly_employee_demand"])

    summary = (
        routeable.groupby("cluster_id")
        .agg(
            store_count=("store_name", "count"),
            weekly_employee_demand=("weekly_employee_demand", "sum"),
            centroid_latitude=("latitude", "mean"),
            centroid_longitude=("longitude", "mean"),
        )
        .reset_index()
        .sort_values("cluster_id")
    )
    return routeable.sort_values(["cluster_id", "store_name"]), summary


def build_driver_metrics(trips: pd.DataFrame, issues: pd.DataFrame) -> pd.DataFrame:
    metrics = (
        trips.groupby(["drive_id", "driver_number", "driver_name"], dropna=False)
        .agg(
            trip_count=("trip_key", "count"),
            routeable_trip_count=("routeable_trip", "sum"),
            total_trip_minutes=("trip_duration_min", "sum"),
            total_route_distance_km=("route_distance_km", "sum"),
        )
        .reset_index()
    )
    metrics["trip_minutes_over_9h"] = metrics["total_trip_minutes"].fillna(0).clip(lower=0) - 540
    metrics["trip_minutes_over_9h"] = metrics["trip_minutes_over_9h"].clip(lower=0)

    issues_subset = issues[["driver_key", "driver_number", "driver_name", "reported_overtime_hours", "reported_payment_total_hours"]].copy()
    issues_subset["driver_number"] = issues_subset["driver_number"].astype(str)
    metrics["driver_number"] = metrics["driver_number"].astype(str)
    metrics = metrics.merge(issues_subset, on=["driver_number"], how="left", suffixes=("", "_issues"))
    metrics = metrics.sort_values(["drive_id", "driver_number"])
    return metrics


def build_unmatched(active_unmatched: list[pd.DataFrame]) -> pd.DataFrame:
    frames = [frame for frame in active_unmatched if not frame.empty]
    if not frames:
        return pd.DataFrame(columns=["source_dataset", "source_sheet", "source_column", "origin_id", "store_name", "normalized_store_name"])
    unmatched = pd.concat(frames, ignore_index=True)
    unmatched = unmatched.drop_duplicates().sort_values(["source_dataset", "source_sheet", "store_name", "origin_id"])
    return unmatched


def build_kpi_summary(
    overview: dict[str, str],
    demand_summary: pd.DataFrame,
    clusters_summary: pd.DataFrame,
    trips: pd.DataFrame,
    driver_metrics: pd.DataFrame,
    unmatched: pd.DataFrame,
) -> pd.DataFrame:
    total_weekly_demand = int(demand_summary["employees"].sum()) if not demand_summary.empty else 0
    unique_demand_stores = int(demand_summary["store_name"].nunique()) if not demand_summary.empty else 0
    unique_trip_drives = int(trips["drive_id"].nunique()) if not trips.empty else 0
    routeable_trips = int(trips["routeable_trip"].sum()) if not trips.empty else 0
    total_route_distance = round(float(trips["route_distance_km"].sum()), 3) if not trips.empty else 0.0
    total_trip_minutes = round(float(trips["trip_duration_min"].sum()), 2) if not trips.empty else 0.0
    total_trip_overtime = round(float(driver_metrics["trip_minutes_over_9h"].sum()), 2) if not driver_metrics.empty else 0.0
    reported_overtime = round(float(driver_metrics["reported_overtime_hours"].fillna(0).sum() * 60), 2) if not driver_metrics.empty else 0.0

    rows = [
        ("pilot_total_stores_overview", overview.get("Total Stores", "")),
        ("pilot_vehicle_count_overview", overview.get("Vehicle No", "")),
        ("demand_rows", len(demand_summary)),
        ("total_weekly_employee_demand_events", total_weekly_demand),
        ("unique_routeable_demand_stores", unique_demand_stores),
        ("cluster_count", int(clusters_summary["cluster_id"].nunique()) if not clusters_summary.empty else 0),
        ("baseline_trip_count", int(len(trips))),
        ("routeable_baseline_trips", routeable_trips),
        ("baseline_drive_count", unique_trip_drives),
        ("total_baseline_trip_minutes", total_trip_minutes),
        ("avg_baseline_trip_minutes", round(float(trips["trip_duration_min"].mean()), 2) if not trips.empty else 0.0),
        ("total_baseline_route_distance_km", total_route_distance),
        ("drivers_over_9h_by_trip_minutes", int((driver_metrics["trip_minutes_over_9h"] > 0).sum()) if not driver_metrics.empty else 0),
        ("total_trip_minutes_over_9h", total_trip_overtime),
        ("reported_overtime_minutes_from_issues_sheet", reported_overtime),
        ("unique_unmatched_places", int(unmatched["store_name"].nunique()) if not unmatched.empty else 0),
        ("unmatched_place_occurrences", int(len(unmatched))),
    ]
    return pd.DataFrame(rows, columns=["metric", "value"])


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    overview = parse_overview()
    geo_lookup = build_geo_lookup()
    demand, shift_unmatched = parse_shift_workbook(geo_lookup)
    demand_summary = aggregate_demand(demand)
    trips, issues, route_unmatched = parse_bus_routes(geo_lookup)
    unmatched = build_unmatched([
        shift_unmatched.assign(source_dataset="Employee Shift data.xlsx") if not shift_unmatched.empty else shift_unmatched,
        route_unmatched,
    ])
    clustered_stores, clusters_summary = build_clusters(demand_summary, geo_lookup)
    driver_metrics = build_driver_metrics(trips, issues)
    kpi_summary = build_kpi_summary(overview, demand_summary, clusters_summary, trips, driver_metrics, unmatched)

    demand_summary.to_csv(OUTPUT_DIR / "demand_by_store_shift_window.csv", index=False)
    clustered_stores.to_csv(OUTPUT_DIR / "stores_with_clusters.csv", index=False)
    clusters_summary.to_csv(OUTPUT_DIR / "clusters_summary.csv", index=False)
    trips.to_csv(OUTPUT_DIR / "trip_routes.csv", index=False)
    driver_metrics.to_csv(OUTPUT_DIR / "driver_metrics.csv", index=False)
    unmatched.to_csv(OUTPUT_DIR / "unmatched_stores.csv", index=False)
    kpi_summary.to_csv(OUTPUT_DIR / "kpi_summary.csv", index=False)

    print("Prototype rebuilt from context/approach inputs.")
    print(f"Outputs written to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
