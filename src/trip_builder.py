from __future__ import annotations

import json
import math
from datetime import timedelta

import pandas as pd

from preprocessing import (
    AVG_SPEED_KMPH,
    BUS_CAPACITY,
    BUS_COUNT,
    GeoPoint,
    IN_EARLY_LIMIT_MIN,
    IN_TARGET_LEAD_MIN,
    MAX_STOPS_PER_TRIP,
    MAX_TRIP_DURATION_MIN,
    OUT_WAIT_LIMIT_MIN,
    PEAK_BIN_MIN,
    ROAD_FACTOR,
    STOP_DWELL_MIN,
    WAVE_BUCKET_MIN,
)


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
    if demand.empty:
        return pd.DataFrame(
            columns=[
                "trip_id",
                "trip_type",
                "direction",
                "service_date",
                "cluster_id",
                "requested_wave_dt",
                "requested_wave_label",
                "earliest_start_dt",
                "latest_start_dt",
                "planned_start_dt",
                "planned_end_dt",
                "trip_duration_min",
                "route_distance_km",
                "stop_count",
                "peak_load",
                "assigned_passengers",
                "occupancy_pct",
                "store_sequence",
                "store_passenger_plan",
                "stop_data_json",
            ]
        )

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
            candidates["wave_gap"] = candidates["wave_dt"].apply(
                lambda value: abs((pd.Timestamp(value) - seed_wave).total_seconds()) / 60.0
            )
            candidates["distance"] = [road_km(seed_point, point_from_row(candidates.loc[idx])) for idx in candidates.index]
            candidates = candidates.sort_values(
                ["wave_gap", "distance", "remaining", "store_name"],
                ascending=[True, True, False, True],
            )

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
            planned_start = choose_start_with_pressure(
                requested_start,
                earliest_start,
                latest_start,
                duration,
                activity_counts,
            )
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
                    "store_passenger_plan": " | ".join(
                        f"{row['store_name']} ({int(row['allocated_passengers'])})" for row in selected_rows
                    ),
                    "stop_data_json": json.dumps(selected_rows, default=str),
                }
            )
            trip_counter += 1

    return pd.DataFrame(trip_rows).sort_values(["planned_start_dt", "trip_type", "trip_id"]).reset_index(drop=True)
