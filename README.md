# Kuwait Pilot Employee Transportation Optimization

Demand-driven employee shuttle optimization for Kuwait pilot operations.

The prototype builds and schedules employee transport trips under a hard 13-bus cap, then exports employer-facing daily schedules in the exact trip representation requested by operations (`Drive #` + `Trip ID` as `D1/T1`, `D1/T2`, ...).

## Goals

Priority order:

1. Keep schedule feasible within hard `13`-bus concurrency.
2. Maximize legal employee coverage.
3. Keep duty legality and limit overtime.
4. Provide employer-ready daily route and mapping outputs in `D#/T#` format.

## Inputs

The pipeline reads:

1. `datasets/Employee Shift data.xlsx`
2. `datasets/Bus Routes curent.xlsx`
3. `datasets/Geocoordinates.xlsx`
4. `datasets/Kuwait Route Optimization - Overview.xlsx`

## Routing And Scheduling Procedure

### 1) Demand Build

1. Build store-wave demand from shifts.
2. Shift start creates `IN` demand.
3. Shift end creates `OUT` demand.

### 2) Route Construction

1. Strictly match routeable stores using `Store Name + Store ID` against geocoordinates.
2. Build base trips with OR-Tools.
3. Allow feasible `MIXED` return-leg combinations when timing/load constraints hold.

### 3) Scheduling

1. Assign trips to buses with hard 13-bus cap.
2. Enforce buffer, chaining, and duty-span rules.
3. Run repair passes for blocked trips before final rejection.
4. Mark unresolved demand in `unscheduled_trips.csv`.

### 4) Employer Trip Representation

Employer files do not depend on raw internal trip IDs for primary identification.

Trip identity is represented as:

1. `Drive #` = `D1`, `D2`, ...
2. `Trip ID` = `T1`, `T2`, ... within each drive/day
3. Unique key = `Drive # + Trip ID` (for example `D1 T1`)

Trip lifecycle in employer route output:

1. `Trip Start` at Mahboula accommodation
2. Stop rows
3. `Trip End` at Mahboula accommodation

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

One sheet per day (currently derived from shift week window).

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

### KPI Files

1. `kpi_summary.csv`: final run KPI view.
2. `baseline_staged_kpi_summary.csv`: staged baseline KPI view.
3. `unscheduled_trips.csv`: demand/trips not legally placed.

## How To Run

From project root:

```powershell
python prototype/run_pilot.py
```

This rebuilds routing+scheduling outputs and refreshes the lean output contract above.

## Project Navigation

1. [context.md](/d:/Sem%206/Kuwait%20Project/context.md): problem constraints, data, policy.
2. [Approaches/approach.md](/d:/Sem%206/Kuwait%20Project/Approaches/approach.md): implementation strategy.
3. [prototype/run_pilot.py](/d:/Sem%206/Kuwait%20Project/prototype/run_pilot.py): executable pipeline.
