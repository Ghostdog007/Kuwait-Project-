from __future__ import annotations

from pathlib import Path

import pandas as pd

from clustering import build_peak_pressure, cluster_stores
from data_loader import discover_dataset_paths
from demand_generation import aggregate_store_waves, extract_shift_events
from duty_calculator import build_duties
from kpi_calculator import build_daily_kpis
from mixed_trip_builder import build_mixed_candidates
from preprocessing import DEPOT_NAME, build_strict_lookup, load_geocoordinates, load_overview_metrics, load_shift_workbook, normalize_name
from scheduler import add_mixed_labels, schedule_with_rotation_reset
from trip_builder import build_base_trips


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    outputs_dir = project_root / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    dataset_paths = discover_dataset_paths(project_root)
    overview = load_overview_metrics(dataset_paths.overview)
    geo_lookup = load_geocoordinates(dataset_paths.geocoordinates)
    shift_workbook = load_shift_workbook(dataset_paths.shift_data)
    strict_lookup, strict_matches = build_strict_lookup(geo_lookup, shift_workbook)
    weekly_events, unmatched = extract_shift_events(shift_workbook, strict_lookup)
    stores_with_clusters, clusters_summary = cluster_stores(weekly_events)

    depot = geo_lookup.get(normalize_name(DEPOT_NAME))
    if depot is None:
        raise RuntimeError(f"Depot '{DEPOT_NAME}' not found in geocoordinates.")

    strict_matches.to_csv(outputs_dir / "strict_store_matches.csv", index=False)
    stores_with_clusters.to_csv(outputs_dir / "stores_with_clusters.csv", index=False)
    clusters_summary.to_csv(outputs_dir / "clusters_summary.csv", index=False)
    unmatched.to_csv(outputs_dir / "unmatched_stores.csv", index=False)

    all_daily_metrics: list[dict[str, object]] = []
    service_dates = sorted(weekly_events["event_date"].astype(str).unique())

    for service_date in service_dates:
        daily_events = weekly_events[weekly_events["event_date"].astype(str) == service_date].copy()
        daily_demand = aggregate_store_waves(daily_events, stores_with_clusters)
        daily_peak_pressure = build_peak_pressure(daily_demand)
        designed_trips = build_base_trips(daily_demand, depot)
        designed_trips = build_mixed_candidates(designed_trips, depot)
        scheduled, assignments, unscheduled = schedule_with_rotation_reset(designed_trips)
        scheduled = add_mixed_labels(scheduled, assignments)
        duties = build_duties(assignments)
        daily_kpis, daily_metric_row = build_daily_kpis(
            service_date=service_date,
            demand=daily_demand,
            scheduled=scheduled,
            assignments=assignments,
            duties=duties,
            unscheduled=unscheduled,
        )
        all_daily_metrics.append(daily_metric_row)

        daily_demand.to_csv(outputs_dir / f"{service_date}_demand_by_store_shift_window.csv", index=False)
        daily_peak_pressure.to_csv(outputs_dir / f"{service_date}_peak_pressure_summary.csv", index=False)
        designed_trips.to_csv(outputs_dir / f"{service_date}_designed_trips_raw.csv", index=False)
        scheduled.to_csv(outputs_dir / f"{service_date}_trip_routes.csv", index=False)
        assignments.to_csv(outputs_dir / f"{service_date}_trip_assignments.csv", index=False)
        duties.to_csv(outputs_dir / f"{service_date}_driver_metrics.csv", index=False)
        unscheduled.to_csv(outputs_dir / f"{service_date}_unscheduled_trips.csv", index=False)
        daily_kpis.to_csv(outputs_dir / f"{service_date}_kpi_summary.csv", index=False)

        print(f"Date: {service_date}")
        print(f"Total Demand: {daily_metric_row['total_demand_events']}")
        print(f"Trips Designed: {len(designed_trips)}")
        print(f"Trips Scheduled: {daily_metric_row['scheduled_trip_count']}")
        print(f"Unscheduled Trips: {daily_metric_row['unscheduled_trip_count']}")
        print(f"Avg Occupancy: {daily_metric_row['avg_occupancy_pct']}")
        print(f"Total Overtime: {daily_metric_row['total_overtime_minutes']}")
        print()

    pd.DataFrame(all_daily_metrics).sort_values("service_date").to_csv(
        outputs_dir / "daily_kpi_summary_all_days.csv",
        index=False,
    )

    print("Daily prototype complete.")
    print(f"Shared overview vehicle count: {overview.get('Vehicle No', '')}")
    print(f"Strict matched stores: {int(strict_matches['strict_match'].sum()) if not strict_matches.empty else 0}")
    print(f"Outputs written to: {outputs_dir}")


if __name__ == "__main__":
    main()
