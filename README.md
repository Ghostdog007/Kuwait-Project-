# Kuwait Pilot Employee Transportation Optimization

Demand-driven employee shuttle optimization for Kuwait pilot operations.

This project replaces legacy fixed-route planning with a coverage-first optimization pipeline that builds trips from actual weekly shift demand, routes them with OR-Tools, and schedules them under a hard 13-bus fleet cap.

## Current Best Version

The current mainline is the **coverage-first OR-Tools + split-duty scheduler**.

Authoritative KPI file:
- [baseline_staged_kpi_summary.csv](/d:/Sem%206/Kuwait%20Project/prototype/output/baseline_staged_kpi_summary.csv)

Current best staged baseline:
- Coverage: `99.39%`
- Designed trips: `474`
- Scheduled trips: `469`
- Unscheduled trips: `3`
- Assigned passengers: `8597`
- `MIXED` trips: `78`
- Max concurrent trips: `13`
- Fleet breaches: `0`
- Duties over `10h`: `0`
- Total overtime: `119.86 min`

Reported overtime baseline from current operations:
- `2235 min`

Modeled overtime improvement:
- `2235 -> 119.86 min`

## Objective Hierarchy

The project follows this priority order:

1. Keep the schedule within the hard `13`-bus limit.
2. Maximize legal employee coverage.
3. Preserve legal duty structure and keep duties under `10` hours.
4. Reduce overtime without sacrificing coverage.
5. Improve occupancy and reduce deadhead where possible.

If an experiment lowers overtime but also lowers coverage, it is **not** considered the better version.

## How The Prototype Works

The current pipeline is:

1. Build demand from weekly shift data.
   - Shift start creates `IN` demand.
   - Shift end creates `OUT` demand.
2. Strictly match stores using `Store Name + Store ID` and geocoordinates.
3. Group demand into time waves.
4. Use OR-Tools to build strong base `IN` and `OUT` routes from Mahboula depot.
5. Convert feasible return legs into `MIXED` trips when timing, detour, and load stay valid.
6. Run a custom coverage-first scheduler with:
   - hard `13`-bus limit
   - morning/evening slots
   - legal chaining
   - buffers
   - duty-span checks
   - split-duty reset for long midday gaps
7. Try repair before final rejection:
   - small timing shifts
   - donor swap
   - fragment salvage
   - stronger `MIXED` recovery
8. Run overtime cleanup only after the covered solution is fixed.

## Why This Version Works Best

The strongest gains came from:
- OR-Tools route construction for better trip grouping and stop order
- split-duty reset logic for long midday gaps
- coverage-first scheduling instead of overtime-first scheduling
- keeping repair and salvage inside the scheduling pipeline before demand is marked uncovered

At this point, the remaining gap to `100%` coverage is no longer a basic routing problem. It is a tight assignment/search problem involving a very small number of valid trips that fail due to constrained timing windows.

## Key Inputs

The prototype currently uses:
- `datasets/Employee Shift data.xlsx`
- `datasets/Bus Routes curent.xlsx`
- `datasets/Geocoordinates.xlsx`
- `datasets/Kuwait Route Optimization - Overview.xlsx`

## Key Outputs

Main outputs are written to:
- `prototype/output/`

Most important files:
- [baseline_staged_kpi_summary.csv](/d:/Sem%206/Kuwait%20Project/prototype/output/baseline_staged_kpi_summary.csv)
  - clean mainline KPI summary
- [kpi_summary.csv](/d:/Sem%206/Kuwait%20Project/prototype/output/kpi_summary.csv)
  - final run summary including later repair layers
- [trip_routes.csv](/d:/Sem%206/Kuwait%20Project/prototype/output/trip_routes.csv)
  - trip-level route output
- [trip_assignments.csv](/d:/Sem%206/Kuwait%20Project/prototype/output/trip_assignments.csv)
  - bus-slot assignments
- [unscheduled_trips.csv](/d:/Sem%206/Kuwait%20Project/prototype/output/unscheduled_trips.csv)
  - trips that could not be scheduled legally
- [unscheduled_trip_reason_summary.csv](/d:/Sem%206/Kuwait%20Project/prototype/output/unscheduled_trip_reason_summary.csv)
  - reason breakdown for uncovered demand
- [driver_metrics.csv](/d:/Sem%206/Kuwait%20Project/prototype/output/driver_metrics.csv)
  - duty spans and overtime

## How To Run

From the project root:

```powershell
python prototype/run_pilot.py
```

This rebuilds the prototype outputs from scratch.

## Project Navigation

Main project docs:
- [context.md](/d:/Sem%206/Kuwait%20Project/context.md)
  - problem definition, constraints, priorities, and current context
- [approach.md](/d:/Sem%206/Kuwait%20Project/Approaches/approach.md)
  - implementation strategy and pipeline design
- [run_pilot.py](/d:/Sem%206/Kuwait%20Project/prototype/run_pilot.py)
  - main prototype code

Fast search support is already built into all three:
- search `SEARCH HOOK` in [run_pilot.py](/d:/Sem%206/Kuwait%20Project/prototype/run_pilot.py)
- search `SEARCH HOOK` in [context.md](/d:/Sem%206/Kuwait%20Project/context.md)
- search `SEARCH HOOK` in [approach.md](/d:/Sem%206/Kuwait%20Project/Approaches/approach.md)

## Current Limitation

The mainline is already near full legal coverage.

The remaining uncovered demand is difficult because:
- the route set is already strong
- the remaining failures are real full trips, not weak fragments
- the schedule operates in a very tight feasible region
- small global scheduling changes tend to break more coverage than they rescue

That means future gains will likely come from stronger local search or exact neighborhood repair, not from broad heuristic changes.

## Mainline Rule

The current best version is the one with the **highest legal coverage**.

Experimental variants that improve overtime but reduce coverage should be treated as research branches, not as replacements for the mainline.
