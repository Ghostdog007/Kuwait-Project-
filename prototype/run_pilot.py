from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[1]
DATASETS_DIR = BASE_DIR / "datasets"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"

GEO_FILE = DATASETS_DIR / "Geocoordinates.xlsx"
FINAL_SCHEDULE_FILE = DATASETS_DIR / "final_schedule_v11.xlsx"
BUS_ROUTES_FILE = DATASETS_DIR / "Bus Routes curent.xlsx"
SHIFT_ASSIGNMENT_FILE = DATASETS_DIR / "Employee_Shift_Assignment.xlsx"
SHIFT_DATA_FILE = DATASETS_DIR / "Employee Shift data.xlsx"
ITINERARY_FILE = DATASETS_DIR / "passenger_itinerary_v11.xlsx"

BUS_CAPACITY = 22
MAX_CAPACITY = 25
TARGET_DRIVER_MINUTES = 9 * 60
ASSUMED_SPEED_KMPH = 35.0


@dataclass(frozen=True)
class GeoPoint:
    canonical_name: str
    store_id: str
    latitude: float
    longitude: float


ALIASES = {
    "hardees sabah al salem block 1": "Hardees - Sabah Al Salem Block",
    "krispy kreme alyia and ghalyia towers": "Krispy Kreme Alyia Ghalyia Tower",
    "krispy kreme khiran hybrid outlet": "Krispy Kreme - Khiran Hybrid O",
    "krispy kreme khiran square mall": "Krispy Kreme - Khiran Square M",
    "krispy kreme mangaf sultan center": "Krispy Kreme Mangaf Sultan Centr",
    "krispy kreme sabah al salem block 1": "Krispy Kreme - Sabah Al Salem",
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


def build_geo_lookup() -> dict[str, GeoPoint]:
    geo = pd.read_excel(GEO_FILE)
    geo["latitude"] = pd.to_numeric(geo["latitude"], errors="coerce")
    geo["longitude"] = pd.to_numeric(geo["longitude"], errors="coerce")
    geo = geo.dropna(subset=["Store Name", "latitude", "longitude"]).copy()

    lookup: dict[str, GeoPoint] = {}
    for row in geo.itertuples(index=False):
        point = GeoPoint(
            canonical_name=str(row._0).strip(),
            store_id="" if pd.isna(row._1) else str(int(row._1)) if float(row._1).is_integer() else str(row._1),
            latitude=float(row.latitude),
            longitude=float(row.longitude),
        )
        lookup[normalize_name(point.canonical_name)] = point
    return lookup


def resolve_store(name: str, geo_lookup: dict[str, GeoPoint]) -> GeoPoint | None:
    key = normalize_name(name)
    if not key:
        return None
    if key in geo_lookup:
        return geo_lookup[key]
    alias = ALIASES.get(key)
    if alias:
        return geo_lookup.get(normalize_name(alias))
    return None


def parse_time_to_minutes(value: object) -> int | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    try:
        parsed = datetime.strptime(text, "%I:%M %p")
    except ValueError:
        return None
    return parsed.hour * 60 + parsed.minute


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    lat1_r, lon1_r, lat2_r, lon2_r = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def parse_trip_stops(text: object) -> list[str]:
    if pd.isna(text):
        return []
    raw = str(text).strip()
    if not raw:
        return []
    if "->" in raw:
        return [part.strip() for part in raw.split("->") if part.strip()]

    parsed: list[str] = []
    for token in raw.split("),"):
        cleaned = token.strip().rstrip(",")
        cleaned = re.sub(r"\s*\(In:.*$", "", cleaned).strip()
        if cleaned:
            parsed.append(cleaned)
    return parsed


def split_multi_store_cell(value: object) -> list[str]:
    if pd.isna(value):
        return []
    raw = str(value).strip()
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def collect_unmatched_records(geo_lookup: dict[str, GeoPoint]) -> pd.DataFrame:
    records: list[dict[str, object]] = []

    def append_record(source_dataset: str, source_sheet: str, source_column: str, origin_id: str, store_name: str) -> None:
        if not store_name:
            return
        if resolve_store(store_name, geo_lookup) is not None:
            return
        records.append(
            {
                "source_dataset": source_dataset,
                "source_sheet": source_sheet,
                "source_column": source_column,
                "origin_id": origin_id,
                "store_name": store_name,
                "normalized_store_name": normalize_name(store_name),
            }
        )

    assignment = pd.read_excel(SHIFT_ASSIGNMENT_FILE)
    for idx, row in assignment.iterrows():
        append_record(
            "Employee_Shift_Assignment.xlsx",
            "Sheet1",
            "STORE_NAME",
            str(row.get("EMPLOYEE_NUMBER", idx)),
            str(row.get("STORE_NAME", "")).strip(),
        )

    itinerary = pd.read_excel(ITINERARY_FILE)
    for idx, row in itinerary.iterrows():
        append_record(
            "passenger_itinerary_v11.xlsx",
            "Sheet1",
            "Store",
            str(row.get("Employee ID", idx)),
            str(row.get("Store", "")).strip(),
        )

    final_schedule = pd.read_excel(FINAL_SCHEDULE_FILE)
    for row in final_schedule.itertuples(index=False):
        for stop in parse_trip_stops(row.Stops):
            append_record(
                "final_schedule_v11.xlsx",
                "Sheet1",
                "Stops",
                str(row._1),
                stop,
            )

    bus_routes = pd.read_excel(BUS_ROUTES_FILE, sheet_name="Bus Route Details")
    for idx, row in bus_routes.iterrows():
        trip_id = row.get("Trip ID", row.get("Trip No", idx))
        for stop in split_multi_store_cell(row.get("Store Name")):
            append_record(
                "Bus Routes curent.xlsx",
                "Bus Route Details",
                "Store Name",
                str(trip_id),
                stop,
            )

    shift_workbook = pd.ExcelFile(SHIFT_DATA_FILE)
    for sheet in shift_workbook.sheet_names:
        raw = shift_workbook.parse(sheet, header=None)
        if raw.shape[0] < 3:
            continue
        header = raw.iloc[2].tolist()
        body = raw.iloc[3:].copy()
        body.columns = header
        if "Store Name" not in body.columns:
            continue
        for idx, row in body.iterrows():
            append_record(
                "Employee Shift data.xlsx",
                sheet,
                "Store Name",
                str(row.get("EMPLOYEE CODE", idx)),
                str(row.get("Store Name", "")).strip(),
            )

    unmatched = pd.DataFrame(records)
    if unmatched.empty:
        return unmatched
    unmatched = unmatched.drop_duplicates().sort_values(
        ["source_dataset", "source_sheet", "source_column", "store_name", "origin_id"]
    )
    return unmatched


def build_trip_routes(geo_lookup: dict[str, GeoPoint]) -> tuple[pd.DataFrame, pd.DataFrame]:
    final_schedule = pd.read_excel(FINAL_SCHEDULE_FILE).copy()
    route_rows: list[dict[str, object]] = []
    unmatched_rows: list[dict[str, object]] = []

    for row in final_schedule.itertuples(index=False):
        original_stops = parse_trip_stops(row.Stops)
        matched_points: list[GeoPoint] = []
        unmatched_count = 0

        for seq, stop_name in enumerate(original_stops, start=1):
            point = resolve_store(stop_name, geo_lookup)
            if point is None:
                unmatched_count += 1
                unmatched_rows.append(
                    {
                        "source_dataset": "final_schedule_v11.xlsx",
                        "source_sheet": "Sheet1",
                        "source_column": "Stops",
                        "origin_id": str(row._1),
                        "store_name": stop_name,
                        "normalized_store_name": normalize_name(stop_name),
                        "trip_id": str(row._1),
                        "stop_sequence": seq,
                    }
                )
                continue
            matched_points.append(point)

        route_km = 0.0
        for prev, curr in zip(matched_points, matched_points[1:]):
            route_km += haversine_km(prev.latitude, prev.longitude, curr.latitude, curr.longitude)

        estimated_route_minutes = 0.0 if route_km == 0 else (route_km / ASSUMED_SPEED_KMPH) * 60.0
        start_min = parse_time_to_minutes(row._4)
        end_min = parse_time_to_minutes(row._5)
        if start_min is not None and end_min is not None and end_min < start_min:
            end_min += 24 * 60

        route_rows.append(
            {
                "bus_id": row._0,
                "trip_id": str(row._1),
                "trip_type": row.Type,
                "shift_time": row._3,
                "trip_start_time": row._4,
                "trip_end_time": row._5,
                "scheduled_trip_minutes": float(row._6),
                "scheduled_deadhead_minutes": float(row._7),
                "mission_passengers": float(row._9),
                "original_stop_count": len(original_stops),
                "matched_stop_count": len(matched_points),
                "unmatched_stop_count": unmatched_count,
                "routeable_trip": len(matched_points) >= 1,
                "fully_matched_trip": unmatched_count == 0,
                "routed_store_sequence": " -> ".join(point.canonical_name for point in matched_points),
                "route_distance_km": round(route_km, 3),
                "estimated_route_minutes": round(estimated_route_minutes, 2),
                "start_min": start_min,
                "end_min": end_min,
            }
        )

    trip_routes = pd.DataFrame(route_rows)
    unmatched_trip_stops = pd.DataFrame(unmatched_rows)
    return trip_routes, unmatched_trip_stops


def build_driver_metrics(trip_routes: pd.DataFrame) -> pd.DataFrame:
    metrics: list[dict[str, object]] = []
    for bus_id, group in trip_routes.groupby("bus_id"):
        total_trip_minutes = float(group["scheduled_trip_minutes"].sum())
        overtime_minutes = max(total_trip_minutes - TARGET_DRIVER_MINUTES, 0.0)
        route_km = float(group["route_distance_km"].sum())
        routeable_trips = int(group["routeable_trip"].sum())

        metrics.append(
            {
                "bus_id": int(bus_id),
                "trip_count": int(len(group)),
                "routeable_trip_count": routeable_trips,
                "scheduled_trip_minutes": round(total_trip_minutes, 2),
                "avg_trip_minutes": round(total_trip_minutes / len(group), 2),
                "overtime_minutes_over_9h": round(overtime_minutes, 2),
                "route_distance_km": round(route_km, 3),
                "mission_passengers": int(group["mission_passengers"].sum()),
            }
        )

    return pd.DataFrame(metrics).sort_values("bus_id")


def build_kpi_summary(
    trip_routes: pd.DataFrame,
    driver_metrics: pd.DataFrame,
    unmatched_all: pd.DataFrame,
) -> pd.DataFrame:
    total_trips = len(trip_routes)
    routeable_trips = int(trip_routes["routeable_trip"].sum())
    fully_matched_trips = int(trip_routes["fully_matched_trip"].sum())
    total_original_stops = int(trip_routes["original_stop_count"].sum())
    total_matched_stops = int(trip_routes["matched_stop_count"].sum())
    total_unmatched_trip_stops = int(trip_routes["unmatched_stop_count"].sum())
    stop_match_rate = 0.0 if total_original_stops == 0 else 100.0 * total_matched_stops / total_original_stops

    summary_rows = [
        ("total_trips", total_trips),
        ("routeable_trips", routeable_trips),
        ("fully_matched_trips", fully_matched_trips),
        ("trips_with_unmatched_stops", int((trip_routes["unmatched_stop_count"] > 0).sum())),
        ("total_original_trip_stops", total_original_stops),
        ("total_routed_trip_stops", total_matched_stops),
        ("total_unmatched_trip_stops", total_unmatched_trip_stops),
        ("trip_stop_match_rate_pct", round(stop_match_rate, 2)),
        ("total_route_distance_km", round(float(trip_routes["route_distance_km"].sum()), 3)),
        ("avg_route_distance_km_per_trip", round(float(trip_routes["route_distance_km"].mean()), 3)),
        ("total_scheduled_trip_minutes", round(float(trip_routes["scheduled_trip_minutes"].sum()), 2)),
        ("avg_scheduled_trip_minutes", round(float(trip_routes["scheduled_trip_minutes"].mean()), 2)),
        ("total_mission_passengers", int(trip_routes["mission_passengers"].sum())),
        ("buses_in_schedule", int(driver_metrics["bus_id"].nunique())),
        ("buses_over_9h_by_trip_minutes", int((driver_metrics["overtime_minutes_over_9h"] > 0).sum())),
        ("total_overtime_minutes_over_9h", round(float(driver_metrics["overtime_minutes_over_9h"].sum()), 2)),
        ("max_bus_overtime_minutes_over_9h", round(float(driver_metrics["overtime_minutes_over_9h"].max()), 2)),
        ("unique_unmatched_places_all_datasets", 0 if unmatched_all.empty else int(unmatched_all["store_name"].nunique())),
        ("unmatched_place_occurrences_all_datasets", int(len(unmatched_all))),
        ("assumed_speed_kmph", ASSUMED_SPEED_KMPH),
        ("seating_capacity_target", BUS_CAPACITY),
        ("absolute_capacity_ceiling", MAX_CAPACITY),
    ]

    return pd.DataFrame(summary_rows, columns=["metric", "value"])


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    geo_lookup = build_geo_lookup()

    unmatched_all = collect_unmatched_records(geo_lookup)
    trip_routes, unmatched_trip_stops = build_trip_routes(geo_lookup)
    driver_metrics = build_driver_metrics(trip_routes)
    kpi_summary = build_kpi_summary(trip_routes, driver_metrics, unmatched_all)

    if not unmatched_trip_stops.empty:
        trip_specific = unmatched_trip_stops[[
            "source_dataset",
            "source_sheet",
            "source_column",
            "origin_id",
            "trip_id",
            "stop_sequence",
            "store_name",
            "normalized_store_name",
        ]]
        unmatched_all = pd.concat([unmatched_all, trip_specific], ignore_index=True, sort=False)

    unmatched_all.to_csv(OUTPUT_DIR / "unmatched_stores.csv", index=False)
    trip_routes.to_csv(OUTPUT_DIR / "trip_routes.csv", index=False)
    driver_metrics.to_csv(OUTPUT_DIR / "driver_metrics.csv", index=False)
    kpi_summary.to_csv(OUTPUT_DIR / "kpi_summary.csv", index=False)

    print("Prototype run complete.")
    print(f"Trip routes: {OUTPUT_DIR / 'trip_routes.csv'}")
    print(f"Driver metrics: {OUTPUT_DIR / 'driver_metrics.csv'}")
    print(f"Unmatched stores: {OUTPUT_DIR / 'unmatched_stores.csv'}")
    print(f"KPI summary: {OUTPUT_DIR / 'kpi_summary.csv'}")


if __name__ == "__main__":
    main()
