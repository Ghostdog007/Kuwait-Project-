from __future__ import annotations

import pandas as pd

from preprocessing import BUS_CAPACITY


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


def build_daily_kpis(
    service_date: str,
    demand: pd.DataFrame,
    scheduled: pd.DataFrame,
    assignments: pd.DataFrame,
    duties: pd.DataFrame,
    unscheduled: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, object]]:
    total_demand_events = int(demand["employees"].sum()) if not demand.empty else 0
    assigned_passengers = int(scheduled["assigned_passengers"].sum()) if not scheduled.empty else 0
    total_offered_seats = int(len(scheduled) * BUS_CAPACITY)
    occupied_seats = float(scheduled["peak_load"].sum()) if not scheduled.empty else 0.0
    avg_occupancy_pct = float(scheduled["occupancy_pct"].mean()) if not scheduled.empty else 0.0
    weighted_avg_occupancy_pct = (occupied_seats / total_offered_seats) * 100 if total_offered_seats else 0.0
    max_concurrent_trips = compute_max_concurrent(assignments)
    total_route_distance_km = float(scheduled["route_distance_km"].sum()) if not scheduled.empty else 0.0
    duty_count = int(len(duties))
    duty_count_over_9h = int((duties["overtime_min"] > 0).sum()) if not duties.empty else 0
    duty_count_over_10h = int(duties["over_10h_flag"].sum()) if not duties.empty else 0
    total_overtime_minutes = float(duties["overtime_min"].sum()) if not duties.empty else 0.0
    max_overtime_minutes = float(duties["overtime_min"].max()) if not duties.empty else 0.0
    rescued_trip_count = int(assignments["rescued_by_delay"].sum()) if not assignments.empty else 0
    handover_trip_count = int(assignments["handover_flag"].sum()) if not assignments.empty else 0

    metrics = {
        "service_date": service_date,
        "total_demand_events": total_demand_events,
        "assigned_passengers": assigned_passengers,
        "coverage_pct": round((assigned_passengers / total_demand_events) * 100, 2) if total_demand_events else 0.0,
        "scheduled_trip_count": int(len(scheduled)),
        "unscheduled_trip_count": int(len(unscheduled)),
        "avg_occupancy_pct": round(avg_occupancy_pct, 2),
        "weighted_avg_occupancy_pct": round(weighted_avg_occupancy_pct, 2),
        "max_concurrent_trips": max_concurrent_trips,
        "total_route_distance_km": round(total_route_distance_km, 3),
        "duty_count": duty_count,
        "duty_count_over_9h": duty_count_over_9h,
        "duty_count_over_10h": duty_count_over_10h,
        "total_overtime_minutes": round(total_overtime_minutes, 2),
        "max_overtime_minutes": round(max_overtime_minutes, 2),
        "rescued_trip_count": rescued_trip_count,
        "handover_trip_count": handover_trip_count,
    }
    kpi_df = pd.DataFrame({"metric": list(metrics.keys()), "value": list(metrics.values())})
    return kpi_df, metrics
