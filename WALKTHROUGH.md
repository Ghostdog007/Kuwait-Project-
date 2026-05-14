# Tester and Examiner Walkthrough

This guide is for a new reviewer (human or model) to run the project, verify outputs, and use the wrapper for analysis.

## 1) What This Project Does

The pipeline optimizes employee transport schedules for a pilot operation in Kuwait.

Key operating constraints:
1. Hard fleet cap: `13` concurrent buses.
2. Bus capacity: standard `22` seats (up to `25` max operational tolerance).
3. Duty legality and buffer constraints.
4. Employer-facing trip naming: `Drive #` + `Trip ID` (`D1/T1`, `D1/T2`, ...).

Primary objective order:
1. Feasible schedule under hard constraints.
2. Maximize legal coverage.
3. Reduce overtime without losing covered demand.

## 2) Inputs You Need

Source files in `datasets/`:
1. `Employee Shift data.xlsx`
2. `Bus Routes curent.xlsx`
3. `Geocoordinates.xlsx`
4. `Kuwait Route Optimization - Overview.xlsx`

## 3) Run the Core Pipeline

From repo root:

```powershell
python prototype/run_pilot.py
```

Expected result:
1. Trip design + scheduling complete.
2. Lean outputs refreshed in `prototype/output` and `prototype/output/employer_format`.

## 4) Verify Final Outputs

Core outputs:
1. `prototype/output/kpi_summary.csv`
2. `prototype/output/baseline_staged_kpi_summary.csv`
3. `prototype/output/unscheduled_trips.csv`

Employer outputs:
1. `prototype/output/employer_format/trips_per_day.xlsx`
2. `prototype/output/employer_format/employee_to_bus_mapping_per_day.xlsx`

Quick checks:
1. `trips_per_day.xlsx` should be day-wise sheets.
2. Trip identifiers should be in `D#/T#` style.
3. `employee_to_bus_mapping_per_day.xlsx` should map employees to the same `D#/T#` trip structure.

## 5) Run the Wrapper for Analysis

The wrapper builds analysis assets for interactive route validation.

Run:

```powershell
python prototype/export_map_data.py
```

Generates:
1. `prototype/output/map_data.json`
2. `prototype/output/map_config.js`

## 6) Open the Interactive Viewer

Serve the output folder:

```powershell
python -m http.server 8090 --directory prototype/output
```

Open:
`http://localhost:8090/trip_map.html`

Optional:
1. Add Google Maps key in `prototype/.env` (template: `prototype/.env.example`).
2. With key present, road routes are rendered more accurately.

## 7) What the Wrapper Offers for Analysis

1. Cascading selection flow:
   - Day -> Drive -> Trip
2. Trip timeline visibility:
   - `Trip Start`, stop sequence, `Trip End`
3. Stop-level metadata:
   - location, store ID/name, passenger counts
4. Employee mapping overlay by trip:
   - quick validation of assignment completeness
5. QA use cases:
   - detect odd stop ordering
   - inspect timing tightness
   - spot unscheduled/under-covered patterns for specific drives or days

## 8) Where to Read More

1. `README.md` for architecture and output contract.
2. `docs/context.md` for constraints and policy.
3. `docs/approach.md` for optimization strategy.
4. `docs/data_dictionary/` for dataset column meanings.
