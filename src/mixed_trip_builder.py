from __future__ import annotations

import json
from datetime import timedelta

import pandas as pd

from preprocessing import BUS_CAPACITY, GeoPoint, MAX_TRIP_DURATION_MIN, MIXED_MAX_ATTACH_MIN, MIXED_MAX_DETOUR_KM
from trip_builder import road_km, route_metrics_ordered


def decode_stop_data(stop_data_json: str) -> list[dict[str, object]]:
    return json.loads(stop_data_json) if isinstance(stop_data_json, str) and stop_data_json else []


def point_from_stop(stop: dict[str, object]) -> GeoPoint:
    return GeoPoint(
        store_name=str(stop["store_name"]),
        store_id=int(stop["store_id"]),
        latitude=float(stop["latitude"]),
        longitude=float(stop["longitude"]),
    )


def nearest_from_current(current: GeoPoint, stops: list[GeoPoint]) -> list[GeoPoint]:
    remaining = stops.copy()
    ordered: list[GeoPoint] = []
    while remaining:
        next_point = min(remaining, key=lambda point: road_km(current, point))
        ordered.append(next_point)
        remaining.remove(next_point)
        current = next_point
    return ordered


def build_mixed_candidates(base_trips: pd.DataFrame, depot: GeoPoint) -> pd.DataFrame:
    if base_trips.empty:
        return base_trips

    trips = base_trips.copy().sort_values(["planned_start_dt", "trip_type", "trip_id"]).reset_index(drop=True)
    used_out: set[str] = set()
    mixed_rows: list[dict[str, object]] = []

    for _, trip in trips.iterrows():
        if trip["trip_type"] != "IN":
            continue
        in_stops = decode_stop_data(trip.get("stop_data_json", ""))
        if not in_stops:
            continue

        in_points = [point_from_stop(stop) for stop in in_stops]
        in_end = pd.Timestamp(trip["planned_end_dt"])
        last_in = in_points[-1]
        candidates = trips[
            (trips["trip_type"] == "OUT")
            & (~trips["trip_id"].isin(used_out))
            & (trips["service_date"] == trip["service_date"])
        ].copy()
        if candidates.empty:
            continue

        best_idx = None
        best_score = None
        for idx, out_trip in candidates.iterrows():
            gap_min = (pd.Timestamp(out_trip["planned_start_dt"]) - in_end).total_seconds() / 60.0
            if gap_min < 0 or gap_min > MIXED_MAX_ATTACH_MIN:
                continue
            out_stops = decode_stop_data(out_trip.get("stop_data_json", ""))
            if not out_stops:
                continue

            out_points = [point_from_stop(stop) for stop in out_stops]
            first_leg = min(road_km(last_in, point) for point in out_points)
            if first_leg > MIXED_MAX_DETOUR_KM:
                continue

            out_order = nearest_from_current(last_in, out_points)
            combined_points = in_points + out_order
            distance, duration = route_metrics_ordered(depot, combined_points)
            if duration > MAX_TRIP_DURATION_MIN:
                continue

            peak_load = max(int(trip["peak_load"]), int(out_trip["peak_load"]))
            if peak_load > BUS_CAPACITY:
                continue

            score = (first_leg, gap_min, float(duration))
            if best_score is None or score < best_score:
                best_score = score
                best_idx = idx

        if best_idx is None:
            continue

        out_trip = trips.loc[best_idx]
        out_stops = decode_stop_data(out_trip.get("stop_data_json", ""))
        out_points = nearest_from_current(last_in, [point_from_stop(stop) for stop in out_stops])
        combined_points = in_points + out_points
        distance, duration = route_metrics_ordered(depot, combined_points)
        ordered_names = [point.store_name for point in combined_points]

        combined_trip = trip.to_dict()
        combined_trip["trip_type"] = "MIXED"
        combined_trip["direction"] = "MIXED"
        combined_trip["planned_end_dt"] = pd.Timestamp(trip["planned_start_dt"]) + timedelta(minutes=float(duration))
        combined_trip["trip_duration_min"] = round(float(duration), 2)
        combined_trip["route_distance_km"] = round(float(distance), 3)
        combined_trip["stop_count"] = len(combined_points)
        combined_trip["assigned_passengers"] = int(trip["assigned_passengers"]) + int(out_trip["assigned_passengers"])
        combined_trip["peak_load"] = max(int(trip["peak_load"]), int(out_trip["peak_load"]))
        combined_trip["occupancy_pct"] = round((combined_trip["peak_load"] / BUS_CAPACITY) * 100, 2)
        combined_trip["store_sequence"] = " -> ".join(ordered_names)
        combined_trip["store_passenger_plan"] = (
            f"{trip['store_passenger_plan']} || RETURN || {out_trip['store_passenger_plan']}"
        )
        combined_trip["stop_data_json"] = json.dumps(in_stops + out_stops, default=str)
        mixed_rows.append(combined_trip)

        used_out.add(str(out_trip["trip_id"]))
        trips.loc[trips["trip_id"] == trip["trip_id"], "trip_type"] = "MIXED_USED"

    keep = trips[(trips["trip_type"] != "MIXED_USED") & (~trips["trip_id"].isin(used_out))].copy()
    if mixed_rows:
        keep = pd.concat([keep, pd.DataFrame(mixed_rows)], ignore_index=True)
    return keep.sort_values(["planned_start_dt", "trip_type", "trip_id"]).reset_index(drop=True)
