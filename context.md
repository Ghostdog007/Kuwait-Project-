# Context: Kuwait Employee Transportation Optimization

This document consolidates the current understanding of the Kuwait employee transport problem, its data assets, and its operating constraints. It serves as the problem-definition companion to `Approaches/approach.md`.

## Problem Summary
- Employees live in accommodation and must be transported to and from stores on fixed shift windows.
- The system is schedule-driven (metro-like): buses run trips and employees are assigned to trips.
- Trips may be `IN`, `OUT`, or `MIXED` when a bus drops inbound passengers and then opportunistically picks up shift-ended employees on the return path.
- Current routes are relatively fixed while demand and staffing vary.
- Pain point: high driver overtime and idle/deadhead time.
- Goal: build a constraint-first optimization pipeline covering demand estimation, routing, duty construction, and passenger assignment.
- Optimization priority: reduce driver overtime first, then preserve service coverage, then improve occupancy, then reduce deadhead and waiting where feasible.

## Inputs (Model)
From requirements and metadata:
- Fixed depot: accommodation (single start/end point per trip).
- Store locations (geocoordinates) and store IDs.
- Employee master data with accommodation and store mapping.
- Weekly shift schedule by brand (April 5-11, 2026) with shift start/end and split shift fields.
- Standard shift assignment data with employee, store, and standard shift start/end times.
- Current route execution logs and itinerary history for calibration.
- Resource counts: 13 buses, single vehicle type, 22 seats (max 25).
- Operational variables: driver availability; no traffic/festival modeling.

## Outputs (Model)
- Optimized trip templates by time window and service direction.
- Bus and driver schedules, including legal buffers and split-shift handling where allowed.
- Employee-to-trip assignment tables.
- Stop-level load and timing plans for validating `MIXED` trip feasibility.
- KPI comparison covering overtime, service coverage, occupancy, deadhead, waiting time, and on-time compliance.

## Optimization Priorities
- Primary objective: minimize driver overtime across the fixed 13-driver fleet.
- Secondary objective: maximize feasible service coverage while respecting hard operating constraints.
- Tertiary objective: increase occupancy by consolidating compatible demand and using `MIXED` return pickups where feasible.
- Fourth objective: reduce deadhead and passenger waiting without violating higher-priority goals.
- Practical interpretation: a fuller trip is only preferred if it does not materially worsen overtime, reduce coverage, or break chaining feasibility.

## Objective Structure
- Hard constraints first: fleet size, seat capacity, trip start/end at accommodation, stop-level load feasibility, shift-time compatibility, trip-duration caps, and mandatory 30-45 minute buffer feasibility between chained trips.
- Soft objective hierarchy: minimize overtime first, then maximize feasible coverage/serviceability, then improve occupancy, then reduce deadhead and waiting.
- Modeling note: treat this as a lexicographic or strongly tiered penalty structure, not a loose weighted average that could trade overtime for fuller buses or reduced coverage.
- Practical interpretation: if two solutions have similar occupancy but one creates additional overtime or makes legal trip chaining impossible, reject it even if the route looks geographically efficient.

## Known Constraints and Notes
- Accommodation is the start/end anchor for the system.
- Trips are sequences of store stops; routes are grouped by trip ID.
- Overtime reported around 13 hours per driver in current system.
- Capacity and fleet size constraints must be respected.
- Scheduling must align with store shift times.
- Confirmed: 13 buses.
- Confirmed: single start location (employee accommodation). Each trip starts at this location, visits assigned stores, then returns to the start to complete the trip.
- Allowed trip modes: `IN`, `OUT`, and `MIXED` when timing and capacity make opportunistic pickup feasible.
- Buffer time between successive trips for each bus: 30-45 minutes to allow for delays (hard constraint).
- Vehicle type: single type only, 22-seat capacity (can go up to 25 if crowded, never above 25).
- Trip duration target: average 2.5 hours per trip.
- Driver total driving hours: ideally 9 hours per day, with acceptable range 8-10 hours.
- Broken shifts allowed: a 9-hour workday can be split into a 4-hour shift and a 5-hour shift, with separate pickup/drop trips.
- Max waiting time: 30-40 minutes (upper bound), to reduce overtime risk.
- Employees should arrive at pickup no earlier than 30 minutes before the scheduled bus trip (to avoid excessive waiting).
- Opportunistic pickup rule: after completing required inbound drops, a bus may collect outbound employees only if the pickup store is near the return path, the employees' shifts have ended or are within a small compatibility tolerance, and capacity remains available after earlier drops.
- Mixed trips must track onboard load after every stop; pickups cannot violate seat capacity at any point on the route.
- Mixed routing should reduce deadhead and improve occupancy without creating excessive detours or pushing driver hours beyond daily limits.
- Trip chaining and trip consolidation should be evaluated mainly by their overtime impact; occupancy gains are secondary unless overtime is unchanged or improved.
- Borderline demand near overlapping duty windows should not be forced too early into a rigid time bucket if doing so removes a better chaining option.
- Some demand may naturally fit more than one duty window; assignment should remain flexible long enough to preserve better route-chaining opportunities.

## Data Assets (Metadata Summaries)

### 1) Bus Routes (current)
File: `Metadata/Bus_Routes_current_description.md`
- Sheet `Bus Route Details` logs individual trip events (arrival/departure/stop).
- Sheet `Issues - Bus Route` summarizes schedule vs payment metrics for drivers.
- Trips are bounded by `Trip Start` and `Trip End` for a given trip number.
- Includes driver info, vehicle capacity, store details, stop timing, and operational notes.
- Used to reconstruct actual routes and analyze execution and payroll discrepancies.

### 2) Employee Shift Assignments
File: `Metadata/Employee_shift_assignment.md`
- Standard shift schedule per employee and store (brand + location).
- Includes employee number/name, store name, and standard shift start/end times (AM/PM).
- Used for baseline staffing windows, shift timing, and allocation.

### 3) Employee Information and Weekly Shift Schedule
File: `Metadata/Employee_shift_data_desciption.md`
- Weekly shift schedule context for April 5-11, 2026 across multiple brands (Wimpy, BR, TGIF, KFC, Hardees, CT, KK).
- Tabs represent brands; headers are multi-row (labels, dates, then core columns).
- Columns A-H include employee and store metadata; columns I-AJ hold repeated daily shift start/end patterns (including split shifts).
- Used to map employees to accommodation/stores and derive shift windows by date.

### 4) Passenger Itinerary
File: `Metadata/passenger_itinerary_description.md`
- Each row is one employee's daily commute plan tied to their shift.
- Contains shift start/end plus two transport legs (bus number, direction, boarding/drop-off times).
- Used to align employee schedules with inbound/outbound bus trips and validate timing coverage.

### 5) Final Schedule (v11)
File: `Metadata/final_shedule_v11_description.md`
- Each row is a stop within a trip in the finalized schedule.
- Defines planned route sequences and timing.
- Useful for benchmarking and constraints.

### 6) Store Geocoordinates
File: `Metadata/Geocordinates_decription.md`
- Store ID, name, latitude/longitude (WGS84).
- Supports distance calculations, clustering, and routing.
- Use Haversine distances unless projecting coordinates.

### 7) System Overview
File: `Metadata/Kuwait_Route_optimization_Overview.md`
- Summary metrics for stores, employees, routes, accommodations, and constraints.
- Provides scale and context across datasets.

## Assumptions (Current)
- Each row in trip datasets is a stop; trips are reconstructed by grouping on trip ID.
- Employees belong to accommodation locations and stores; transportation is between these.
- Peak hours are derived from shift overlaps and itinerary volumes.
- The system operates like a scheduled metro service, not ad hoc routes.
- Pilot travel distance/time uses geocoordinates with Haversine distance plus fixed speed and dwell assumptions; no external road-time API is used.
- Mixed routing is heuristic and compatibility-based, not a full exact optimization over all possible pickup/drop combinations.
- Pilot scope uses only stores that have valid coordinates in `Geocoordinates.xlsx`; unmatched stores are ignored for routing and KPI generation.

## Duty-Feasibility Handoff
- Routing should output more than store sequences. Each generated trip should carry start time, end time, duration, slack, stop-level load profile, and compatibility markers for chaining into a legal bus/driver duty.
- Trip generation should expose whether a trip can be followed by another trip while preserving the required 30-45 minute buffer.
- `MIXED` trips should retain enough stop-level timing detail to verify that opportunistic pickups do not create infeasible downstream duties.
- Scheduling should be allowed to reject or penalize trips that are route-feasible in isolation but create overtime or illegal buffers when chained.

## Serviceability Policy
- Full employee coverage is the target, but the model should explicitly handle infeasible demand rather than assuming every request can always be served.
- If demand cannot be assigned within hard timing, capacity, or duty constraints, the system should surface the exception clearly rather than hiding it inside an invalid route.
- Allowed fallback actions should be explicit in implementation: create an extra trip if feasible, flag for manual review, or record the demand as unserved with a very large penalty for KPI reporting.
- Coverage shortfalls should be reported separately from overtime so that a solution does not appear successful merely because it dropped hard-to-serve demand.

## Open Questions / Gaps
- Confirm which week/brand tabs are in scope for modeling (pilot vs. full market).
- Resolve data quality issues in itinerary timing and route logs.
- Set the final compatibility tolerance for mixed pickups (for example, how many minutes after shift end a bus may wait or how much detour is acceptable).
- Validate whether mixed trips should prioritize occupancy gain, overtime reduction, or waiting-time control when those objectives conflict.
- Define the exact optimization structure to use in implementation: lexicographic solve, staged solve, or hard constraints plus tiered penalties.
- Decide how much flexibility to preserve for demand near overlapping shift boundaries before assigning it to a fixed time wave.

## Next Step (Approach-Ready)
This section is aligned with `Approaches/approach.md` (Section 5: Recommended Starting Point).
1. Normalize datasets into a unified schema (employees, stores, shifts, trips, itineraries).
2. Filter pilot scope to stores with valid geocoordinates and build demand tables by store and shift window (inbound/outbound).
3. Run capacity-aware clustering using geocoordinates plus time-window compatibility, avoiding purely spatial clusters that ignore demand timing.
4. Solve routing per cluster or time wave with support for `IN`, `OUT`, and `MIXED` trip construction, preferring changes that reduce total required driver duty time and emitting duty-feasibility information for chaining.
5. Chain trips into bus and driver schedules with legal buffers, stop-level load tracking, and opportunistic pickup checks, treating overtime as the main penalty.
6. Assign employees to trips, validate waiting, capacity, and timing constraints, surface any infeasible or unserved demand explicitly, then compute KPIs with overtime reported first.

## Working Notes
- Visualize geocoordinates on a map to identify spatial clusters (e.g., south/central/north).
- Use inter-cluster travel time as a key driver for route structuring.
- Smart-routing target: allow opportunistic pickups on the return to accommodation if a shift-ended employee is near the bus path after inbound drops are completed.
- Mixed routing should be evaluated as a capacity-recovery mechanism: inbound drops free seats, then nearby outbound pickups can fill those seats on the return leg.
- Mixed routing should only be accepted when detour, employee readiness, stop-level seat feasibility, and downstream duty compatibility all remain acceptable.
- Consolidation rule of thumb: remove or absorb low-value trips when doing so lowers total duty hours, even if occupancy gains are only moderate.
- Occupancy improvement is desirable, but not at the cost of adding extra duties or extending too many drivers past the 9-hour target.
- Store-level stop times matter because mixed routing depends on whether a bus reaches a pickup point after the employee is actually ready.
- Note: clustering alone is insufficient due to fixed bus capacity and scheduling constraints; geographic closeness without time compatibility can produce poor route groups.

## Update Checklist (with Smoke Tests)

Use this when updating any metadata file or summary in this document. Run the smoke test before moving to the next checklist item.

1. Update the dataset summary block in `context.md`.
Smoke test: Confirm the dataset block still matches the latest metadata file title, scope, and core fields.

2. Update the Inputs (Model) section if the dataset affects modeling inputs.
Smoke test: Cross-check that any new or removed fields are reflected in Inputs without contradicting the metadata.

3. Update Constraints and Notes if the dataset introduces or changes constraints.
Smoke test: Verify no constraint conflicts with the metadata or other constraints.

4. Update Assumptions or Open Questions if any uncertainty was introduced.
Smoke test: Ensure any new uncertainty is explicitly captured and is not presented as a confirmed fact.

5. Update Next Step (Approach-Ready) if the pipeline needs adjustment.
Smoke test: Verify the steps still align with `Approaches/approach.md` and do not reference outdated data.
