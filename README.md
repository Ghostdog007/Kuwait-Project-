# Kuwait Pilot Employee Transportation Optimization

Demand-driven employee shuttle optimization for Kuwait pilot operations.

The prototype builds and schedules employee transport trips under a hard 13-bus cap, then exports employer-facing daily schedules using `Drive #` + `Trip ID` representation (`D1/T1`, `D1/T2`, ...).

## Quick Start (Tester / Examiner)

Start here:
- [WALKTHROUGH.md](/d:/Sem%206/Kuwait%20Project/WALKTHROUGH.md)

## Goals

1. Keep schedule feasible within hard `13`-bus concurrency.
2. Maximize legal employee coverage.
3. Keep duty legality and limit overtime.
4. Provide employer-ready daily route and mapping outputs in `D#/T#` format.

## Project Structure

```text
Kuwait Project/
|-- prototype/
|   |-- run_pilot.py
|   |-- export_map_data.py
|   `-- output/
|-- docs/
|   |-- context.md
|   |-- approach.md
|   |-- data_dictionary/
|   `-- references/
|-- datasets/
`-- archive/
```

## Inputs

Pipeline source files:

1. `datasets/Employee Shift data.xlsx`
2. `datasets/Bus Routes curent.xlsx`
3. `datasets/Geocoordinates.xlsx`
4. `datasets/Kuwait Route Optimization - Overview.xlsx`

## Routing and Scheduling Procedure

### 1) Demand Build
1. Build store-wave demand from shifts.
2. Shift start creates `IN` demand.
3. Shift end creates `OUT` demand.

### 2) Route Construction
1. Strictly match routeable stores using `Store Name + Store ID` against geocoordinates.
2. Build base trips with OR-Tools.
3. Allow feasible `MIXED` return-leg combinations when timing/load constraints hold.

### 3) Scheduling
1. Assign trips to buses under hard 13-bus cap.
2. Enforce buffer, chaining, and duty-span rules.
3. Run repair passes for blocked trips before final rejection.
4. Mark unresolved demand in `unscheduled_trips.csv`.

### 4) Employer Trip Representation
1. `Drive #` = `D1`, `D2`, ...
2. `Trip ID` = `T1`, `T2`, ... within each drive/day
3. Unique key = `Drive # + Trip ID` (for example `D1 T1`)
4. Trip lifecycle = `Trip Start` -> stop rows -> `Trip End`

## How to Run

1. Configure API key for map routing (optional but recommended):
   - Create `prototype/.env`
   - Add this line:
     - `GMAPS_API_KEY=YOUR_REAL_GOOGLE_MAPS_KEY`
   - You can copy from [`.env.example`](/d:/Sem%206/Kuwait%20Project/prototype/.env.example).
2. Run pipeline:

```powershell
python prototype/run_pilot.py
```

3. Generate wrapper/map analysis assets:

```powershell
python prototype/export_map_data.py
```

4. Serve map outputs:

```powershell
python -m http.server 8090 --directory prototype/output
```

Then open `http://localhost:8090/trip_map.html`.

API key behavior:
1. If `prototype/.env` has `GMAPS_API_KEY`, the wrapper injects it into `map_config.js`.
2. If missing, viewer still works for basic inspection, but road-accurate routing may be limited.

## Wrapper Analysis (What It Offers)

`prototype/export_map_data.py` is the analysis wrapper for map-based QA and stakeholder review.

It reads:
1. `prototype/output/employer_format/trips_per_day.xlsx`
2. `prototype/output/employer_format/employee_to_bus_mapping_per_day.xlsx`
3. geocoordinates and employee-name references from source datasets

It generates:
1. `prototype/output/map_data.json` (trip/stop payload)
2. `prototype/output/map_config.js` (runtime config for viewer)

Map viewer capabilities:
1. Day -> Drive -> Trip drill-down (`D#/T#` navigation).
2. Stop-level timeline for each trip (`Trip Start`, stops, `Trip End`).
3. Employee roster by trip for operational validation.
4. Road-accurate path rendering when Google Maps API key is present.
5. Fast manual checks for route ordering, timing windows, and trip coverage gaps.

## Output Contract (Lean)

After each run, only these files are kept.

In `prototype/output/`:
1. [kpi_summary.csv](/d:/Sem%206/Kuwait%20Project/prototype/output/kpi_summary.csv)
2. [baseline_staged_kpi_summary.csv](/d:/Sem%206/Kuwait%20Project/prototype/output/baseline_staged_kpi_summary.csv)
3. [unscheduled_trips.csv](/d:/Sem%206/Kuwait%20Project/prototype/output/unscheduled_trips.csv)

In `prototype/output/employer_format/`:
1. [trips_per_day.xlsx](/d:/Sem%206/Kuwait%20Project/prototype/output/employer_format/trips_per_day.xlsx)
2. [employee_to_bus_mapping_per_day.xlsx](/d:/Sem%206/Kuwait%20Project/prototype/output/employer_format/employee_to_bus_mapping_per_day.xlsx)

## Output Schemas

### `trips_per_day.xlsx`
One sheet per day.

Columns:
1. `Drive #`
2. `Trip ID`
3. `Time`
4. `Event` (`Trip Start`, `Stop`, `Trip End`)
5. `Location`
6. `Store ID`
7. `Store Name`
8. `Passenger Count`
9. `Trip Start`
10. `Trip End`

### `employee_to_bus_mapping_per_day.xlsx`
One sheet per day.

Columns:
1. `Drive #`
2. `Trip No`
3. `Trip ID`
4. `Trip Start`
5. `Trip End`
6. `Employee Count`
7. `Employees`
8. `Unmapped Seats`

## Documentation Links

1. [docs/context.md](/d:/Sem%206/Kuwait%20Project/docs/context.md)
2. [docs/approach.md](/d:/Sem%206/Kuwait%20Project/docs/approach.md)
3. [docs/data_dictionary/](/d:/Sem%206/Kuwait%20Project/docs/data_dictionary)
4. [prototype/run_pilot.py](/d:/Sem%206/Kuwait%20Project/prototype/run_pilot.py)
