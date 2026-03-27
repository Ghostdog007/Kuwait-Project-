# Data Folder

This folder is the optional local data location for the new daily prototype in `Kuwait-Project-Aditya/`.

## What Was Implemented

A completely new prototype was built in:

- `Kuwait-Project-Aditya/src/`

It reimplements the logic of the existing weekly prototype in `prototype/run_pilot.py`, but changes the planning horizon to **daily processing**.

The new runner is:

- `Kuwait-Project-Aditya/src/run_daily.py`

It performs the following workflow:

1. Load the source Excel datasets
2. Build strict store matching
3. Generate weekly employee shift events
4. Build weekly store clusters once using weighted KMeans
5. Identify service dates
6. For each date, run:
   - daily demand generation
   - 30-minute wave aggregation
   - greedy trip construction
   - mixed-trip merge
   - bus assignment with morning/evening slots
   - duty calculation
   - daily KPI calculation
7. Save date-specific outputs to `Kuwait-Project-Aditya/outputs/`


## Dataset Discovery Logic

The daily prototype currently looks for the required Excel files in this order:

1. `Kuwait-Project-Aditya/data/`
2. `../Dataset_aditya/`
3. `../datasets/`

So the implementation works even if this folder is empty, as long as the files are available in one of the fallback locations.

## Notes

- The existing `prototype/` folder was not modified.
- The original weekly outputs were not changed.
- The new prototype uses the same core constraints and heuristics as the original implementation.
- Outputs produced by the new prototype are written to `Kuwait-Project-Aditya/outputs/`.

## Output Comparison vs Baseline Prototype

Compared with the original weekly outputs in `prototype/output/`, the new prototype changes the output structure and some final metrics.

### What did not change

These shared preprocessing outputs are effectively unchanged from the baseline:

- `strict_store_matches.csv`
- `stores_with_clusters.csv`
- `clusters_summary.csv`
- `unmatched_stores.csv`

This means the following parts of the logic remain the same:

- strict store matching
- routeable store set
- weekly weighted KMeans clustering
- unmatched store detection
- weekly demand base before daily scheduling

### Output structure changes

The baseline prototype writes one weekly set of files in `prototype/output/`.

The new prototype writes date-specific files in `Kuwait-Project-Aditya/outputs/`, for example:

- `2026-04-09_trip_routes.csv`
- `2026-04-09_trip_assignments.csv`
- `2026-04-09_driver_metrics.csv`
- `2026-04-09_kpi_summary.csv`
- `2026-04-09_unscheduled_trips.csv`

It also writes:

- `daily_kpi_summary_all_days.csv`

The new output folder does not recreate `baseline_overtime_reference.csv`, because the new implementation focuses on daily operational outputs rather than reproducing the original baseline calibration export.

### Aggregate behavioral changes vs baseline weekly prototype

When the daily outputs are aggregated back to a full-week view and compared with `prototype/output/kpi_summary.csv`, the following changes appear:

- Designed trips: `572` vs `566` baseline
- Scheduled trips: `503` vs `491` baseline
- Unscheduled trips: `69` vs `75` baseline
- Assigned passengers: `7653` vs `7565` baseline
- Coverage: `88.47%` vs `87.46%` baseline
- Avg occupancy: `63.09%` vs `63.87%` baseline
- Weighted avg occupancy: `63.09%` vs `63.87%` baseline
- Total route distance: `31450.145 km` vs `30704.278 km` baseline
- Max concurrent trips: `13` vs `13` baseline
- Duty count over 9h: `22` vs `26` baseline
- Duty count over 10h: `0` vs `0` baseline
- Total overtime: `757.58` minutes vs `988.52` baseline
- Max overtime: `56.99` minutes vs `58.68` baseline
- Rescued trips: `21` vs `18` baseline
- Handover trips: `206` vs `197` baseline

### Interpretation

The daily prototype performs better than the baseline weekly prototype on:

- total scheduled trips
- unscheduled trip reduction
- assigned passengers
- coverage
- total overtime
- long-duty count above 9 hours

The daily prototype is slightly worse on:

- average occupancy
- weighted occupancy
- total route distance

So the practical effect of daily planning is:

- better serviceability
- lower modeled overtime
- similar fleet concurrency control
- a small loss in consolidation efficiency

## Code Changes vs Baseline Prototype

The original prototype was implemented as one script:

- `prototype/run_pilot.py`

The new prototype is modularized into:

- `src/data_loader.py`
- `src/preprocessing.py`
- `src/demand_generation.py`
- `src/clustering.py`
- `src/trip_builder.py`
- `src/mixed_trip_builder.py`
- `src/scheduler.py`
- `src/duty_calculator.py`
- `src/kpi_calculator.py`
- `src/run_daily.py`

### Major code changes

1. Monolithic weekly script -> modular daily pipeline

- The baseline kept all logic in one file.
- The new prototype separates loading, preprocessing, demand generation, clustering, trip building, scheduling, duty calculation, and KPI calculation into dedicated files.

2. Weekly horizon -> daily execution loop

- The baseline builds and schedules across the whole week at once.
- The new version still builds weekly events and weekly clusters once, but then loops over each `service_date` and runs the downstream pipeline separately.

3. Dataset handling

- The baseline uses direct `pandas.read_excel(...)` reads from `datasets/`.
- The new version adds dataset path discovery and a workbook XML reader so it can work from:
  - `Kuwait-Project-Aditya/data/`
  - `../Dataset_aditya/`
  - `../datasets/`

4. Excel date handling

- The new version explicitly converts Excel serial dates into real timestamps during shift-event extraction.
- This was needed because the new workbook reader does not rely on `openpyxl` or `pandas.read_excel`.

5. KPI design

- The baseline `build_kpis()` mixes operational KPIs with overview metrics and baseline workbook references.
- The new version computes daily operational KPIs only, then combines them in `daily_kpi_summary_all_days.csv`.

6. Empty-day and empty-file safeguards

- The new code adds safe handling for empty frames and per-day outputs.
- The baseline assumes one full weekly run and does not need as many empty guards.

### What stayed the same in code logic

The following core modeling logic was intentionally preserved:

- store-name normalization
- strict store-name + store-ID matching
- `IN` and `OUT` event generation from shift starts and ends
- 30-minute wave aggregation
- weighted KMeans clustering
- nearest-neighbor stop sequencing
- greedy trip construction
- heuristic mixed-trip merging
- morning/evening slot scheduling
- 30-minute buffer logic
- hard 10-hour duty span blocking
- overtime = duty span above 9 hours
- limited repair by timing shifts

### Bottom line

The new code is not a new optimization method.

It is the same heuristic prototype logic reorganized into a cleaner module structure and changed from:

- one weekly planning run

to:

- repeated daily planning runs using weekly clusters and weekly event extraction as shared inputs

## Run Command

From inside `Kuwait-Project-Aditya/`, run:

```bash
python src/run_daily.py
```
