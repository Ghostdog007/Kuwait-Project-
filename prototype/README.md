# Pilot Prototype

This prototype follows the pipeline described in `context.md` (Phase 1) and produces a lightweight, end-to-end output using the current datasets.

## What It Does

1. Normalizes shift assignment data (inbound/outbound windows).
2. Builds demand tables by store and shift window.
3. Joins geocoordinates and applies simple capacity-aware clustering.
4. Generates trip stubs (depot -> stores -> depot) with rough duration estimates.
5. Assigns employees to trips (stub assignment).
6. Produces KPI summaries for quick validation.

## Inputs

- `datasets/Employee Shift data.xlsx`
- `datasets/Geocoordinates.xlsx`

## Outputs

Written to `prototype/output/`:

- `demand_by_store_window.csv`
- `stores_with_clusters.csv`
- `trips_stub.csv`
- `passenger_assignment_stub.csv`
- `kpi_summary.csv`
- `unmatched_stores.csv`
- `run_summary.csv`

## Assumptions (Pilot)

- Capacity is fixed at 25.
- Speed is assumed at 40 km/h; 5 minutes dwell per stop.
- Depot is chosen as the first Mahboula location in geocoordinates (fallback: first row).
- Clustering is geo + time-window weighted k-means (k sized by demand).
- Trip times are approximated around shift windows, not full VRPTW.

## Run

```bash
python prototype/run_pilot.py
```
