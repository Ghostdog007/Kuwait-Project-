# Context: Kuwait Employee Transportation Optimization

This document consolidates the current understanding of the Kuwait employee transport problem, its data assets, and its operating constraints. It serves as the problem-definition companion to `Approaches/approach.md`.

## Problem Summary
- Employees live in accommodation and must be transported to and from stores on fixed shift windows.
- The system is schedule-driven (metro-like): buses run trips and employees are assigned to trips.
- Trips may be `IN`, `OUT`, or `MIXED` when a bus drops inbound passengers and then opportunistically picks up shift-ended employees on the return path.
- Current routes are relatively fixed while demand and staffing vary.
- The optimization target is to design new trips from demand and constraints, not to preserve current trip shapes.
- Pain point: high driver overtime and idle/deadhead time.
- Goal: build a constraint-first optimization pipeline covering demand estimation, routing, duty construction, and passenger assignment.
- Optimization priority in the implemented prototype should begin with fleet-feasible concurrency, then engineer legal and practical driver rotations, then reduce driver overtime, then preserve service coverage, then improve occupancy, then reduce deadhead and waiting where feasible.

## Inputs (Model)
From requirements and metadata:
- Fixed depot: accommodation (single start/end point per trip).
- Store locations (geocoordinates) and store IDs.
- Employee information and weekly shift schedule by brand (April 5-11, 2026), including accommodation, store, role, and split-shift fields.
- Current route execution logs and payroll/overtime summaries for calibration and benchmarking only.
- System overview metrics for scale, fleet context, and operating assumptions.
- Resource counts: 13 buses, single vehicle type, 22 seats (max 25).
- Operational variables: driver availability; no traffic/festival modeling.

## Outputs (Model)
- Optimized trip templates by time window and service direction.
- Bus and driver schedules, including legal buffers and split-shift handling where allowed.
- Store- and wave-level service plans derived from employee shift demand.
- Stop-level load and timing plans for validating `MIXED` trip feasibility.
- KPI comparison covering overtime, service coverage, occupancy, deadhead, waiting time, and on-time compliance.

## Optimization Priorities
- Primary objective: keep simultaneous active trips within the fixed 13-bus fleet limit.
- Secondary objective: engineer legal driver rotations, including broken shifts and handovers, so daily work is split into practical blocks rather than one long spread.
- Tertiary objective: minimize driver overtime across that fleet.
- Fourth objective: maximize feasible service coverage while respecting hard operating constraints.
- Fifth objective: increase occupancy by consolidating compatible demand and using `MIXED` return pickups where feasible.
- Sixth objective: reduce deadhead and passenger waiting without violating higher-priority goals.
- Practical interpretation: a fuller trip is only preferred if it does not materially worsen concurrency, duty spread, handover feasibility, overtime, coverage, or chaining feasibility.

## Objective Structure
- Hard constraints first: simultaneous fleet limit of 13 buses, seat capacity, trip start/end at accommodation, stop-level load feasibility, shift-time compatibility, trip-duration caps, and mandatory 30-45 minute buffer feasibility between chained trips.
- Soft objective hierarchy: regularize duty spans and handovers first, minimize overtime second, maximize feasible coverage/serviceability third, improve occupancy fourth, and reduce deadhead and waiting fifth.
- Modeling note: treat this as a lexicographic or strongly tiered penalty structure, not a loose weighted average that could trade fleet infeasibility, excessive duty spread, broken handovers, or overtime for fuller buses.
- Practical interpretation: if two solutions have similar occupancy but one creates peak-hour fleet overload, extreme duty spread, or illegal trip chaining, reject it even if the route looks geographically efficient.

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
- Long idle gaps should be treated as shift-break candidates rather than automatically stretched into one continuous duty.
- Late-night `OUT` waves should preferentially be served through evening rotations or handovers instead of being tacked onto already-long day duties.
- Max waiting time: 30-40 minutes (upper bound), to reduce overtime risk.
- Employees should arrive at pickup no earlier than 30 minutes before the scheduled bus trip (to avoid excessive waiting).
- Opportunistic pickup rule: after completing required inbound drops, a bus may collect outbound employees only if the pickup store is near the return path, the employees' shifts have ended or are within a small compatibility tolerance, and capacity remains available after earlier drops.
- Mixed trips must track onboard load after every stop; pickups cannot violate seat capacity at any point on the route.
- Mixed routing should reduce deadhead and improve occupancy without creating excessive detours or pushing driver hours beyond daily limits.
- Trip chaining and trip consolidation should be evaluated first by their effect on peak fleet concurrency, then by duty spread and overtime impact; occupancy gains are secondary unless concurrency, duty spread, and overtime are unchanged or improved.
- Borderline demand near overlapping duty windows should not be forced too early into a rigid time bucket if doing so removes a better chaining option.
- Some demand may naturally fit more than one duty window; assignment should remain flexible long enough to preserve better route-chaining opportunities.
- Current route logs should inspire feasible trip duration ranges, stop counts, and duty patterns, but they should not be treated as the trips the model must reproduce.

## Data Assets (Metadata Summaries)

### 1) Bus Routes (current)
File: `Metadata/Bus_Routes_current_description.md`
- Sheet `Bus Route Details` logs individual trip events (arrival/departure/stop).
- Sheet `Issues - Bus Route` summarizes schedule vs payment metrics for drivers.
- Trips are bounded by `Trip Start` and `Trip End` for a given trip number.
- Includes driver info, vehicle capacity, store details, stop timing, and operational notes.
- Used to reconstruct actual routes and analyze execution and payroll discrepancies.

### 2) Employee Information and Weekly Shift Schedule
File: `Metadata/Employee_shift_data_desciption.md`
- Employee records include accommodation, store, brand, and role information.
- Repeating daily shift columns provide primary and split-shift timing for the week in scope.
- Used to derive demand waves, shift compatibility, accommodation-to-store relationships, and candidate inbound/outbound service windows.

### 3) Store Geocoordinates
File: `Metadata/Geocordinates_decription.md`
- Store ID, name, latitude/longitude (WGS84).
- Supports distance calculations, clustering, and routing.
- Use Haversine distances unless projecting coordinates.

### 4) System Overview
File: `Metadata/Kuwait_Route_optimization_Overview.md`
- Summary metrics for stores, employees, routes, accommodations, and constraints.
- Provides scale and context across datasets.

## Assumptions (Current)
- Each row in trip datasets is a stop; trips are reconstructed by grouping on trip ID.
- Employees belong to accommodation locations and stores; transportation demand is aggregated from those relationships rather than assigned from a prebuilt itinerary file.
- Peak hours are derived from shift overlaps in the weekly schedule plus observed route activity.
- The system operates like a scheduled metro service, not ad hoc routes.
- Pilot travel distance/time uses geocoordinates with Haversine distance plus fixed speed and dwell assumptions; no external road-time API is used.
- Mixed routing is heuristic and compatibility-based, not a full exact optimization over all possible pickup/drop combinations.
- Pilot scope uses only stores that have valid coordinates in `Geocoordinates.xlsx`; unmatched stores are ignored for routing and KPI generation.

## Prototype Scope
- Prototype inputs should be limited to `Employee Shift data.xlsx`, `Bus Routes curent.xlsx`, `Geocoordinates.xlsx`, and `Kuwait Route Optimization - Overview.xlsx`.
- Weekly shift data is the source of store demand and time-window construction.
- Current bus route logs are the source of baseline references, observed duty patterns, and overtime calibration.
- Geocoordinates are the source of routeable store locations and distance computation.
- Stores without geocoordinates must be excluded from routing logic and logged explicitly for review.
- Prototype trips must be newly generated from demand waves, store compatibility, and operating constraints rather than copied from current route logs.
- Prototype scheduling must treat the fixed 13-bus concurrency limit as a hard feasibility rule, not just a KPI reported after schedule generation.
- Prototype scheduling must treat driver freshness as part of feasibility during assignment, not as a post-processing label added after trips are already chained.

## Trip Design Approach
- Build demand from `Employee Shift data.xlsx` at the store-wave level: each shift start creates inbound demand and each shift end creates outbound demand.
- Restrict routing to stores that pass the strict `Store Name` plus `Store ID` match between `Employee Shift data.xlsx` and `Geocoordinates.xlsx`.
- Group routeable stores by both geography and time compatibility so trips are built around realistic waves rather than historical route IDs.
- Aggregate demand into short sliding or rolling time windows so peak pressure is visible before trips are opened.
- Shift soft demand into adjacent feasible windows when doing so preserves employee waiting tolerance and helps keep simultaneous bus demand within fleet capacity.
- Generate new candidate trips from scratch for each wave using a fleet-aware construction heuristic:
  - `IN` trips carry employees from accommodation to stores before shift start.
  - `OUT` trips collect employees from stores after shift end and return to accommodation.
  - `MIXED` trips are allowed only when inbound drops create free capacity and outbound pickups remain near the return path without violating timing.
- Size each trip using hard operating limits: vehicle capacity, trip duration cap, waiting tolerance, maximum practical stop count, and the requirement that opening the trip should not force active fleet concurrency above 13 unless no feasible alternative exists.
- During assignment, every candidate bus-trip match must also pass a freshness check: if attaching the trip would push that duty beyond its practical span, the trip must trigger a rotation reset or be assigned elsewhere.
- Use current route logs only to calibrate realistic trip characteristics such as typical duration bands, common stop density, and plausible duty spacing.
- After trip generation, chain the new trips into bus and driver duties with 30-45 minute buffers and measure overtime on those designed duties, not on the raw current schedule.
- If the first-pass design still breaches the 13-bus limit, run a destroy-and-repair loop that targets the worst overlap windows, removes weak trips, and re-inserts that demand through merging, staggering, or mixed-trip conversion.
- If the first-pass duties remain over-stretched, run a duty-repair pass that:
  - detects spreads above 10-11 hours,
  - splits duties around long gaps,
  - seeds fresh evening rotations for late `OUT` waves,
  - and retries unscheduled work through small departure shifts within tolerance.

## Fleet-Constrained Heuristic
- Construction phase: use a greedy randomized adaptive search style approach that seeds urgent trips first and then inserts nearby compatible demand only when capacity, timing, duration, and fleet concurrency remain feasible.
- Peak control phase: compute theoretical bus pressure in each short time window and proactively smooth overloaded windows before the main routing step.
- Repair phase: apply a large neighborhood search style loop to the worst bottleneck windows by removing low-efficiency trips and re-inserting their demand through fuller trips, shifted departures, `MIXED` conversions, or split-shift duty resets.
- Duty-splitting phase: identify long gaps between trips and treat them as opportunities to end one duty and begin another, especially when doing so prevents a 13-15 hour spread from being counted as one driver day.
- Rotation phase: try late-wave handovers by assigning late `OUT` trips to fresh evening duties instead of extending day duties past practical limits.
- Slot-allocation phase: treat the 13 physical buses as supporting separate morning and evening duty slots, with handover logic controlling when a fresh evening driver can reuse the same bus.
- Acceptance rule: prefer solutions that reduce concurrency breaches first, then reduce duty spread, then reduce overtime, then improve coverage and occupancy.

## Duty-Feasibility Handoff
- Routing should output more than store sequences. Each generated trip should carry start time, end time, duration, slack, stop-level load profile, and compatibility markers for chaining into a legal bus/driver duty.
- Trip generation should expose whether a trip can be followed by another trip while preserving the required 30-45 minute buffer.
- `MIXED` trips should retain enough stop-level timing detail to verify that opportunistic pickups do not create infeasible downstream duties.
- Scheduling should be allowed to reject or penalize trips that are route-feasible in isolation but create overtime or illegal buffers when chained.
- Scheduling should also surface peak concurrency by time window so trip construction and repair can see exactly where the fleet limit is being breached.
- Scheduling should also emit long-gap markers so the duty builder can split a stretched day into separate morning and evening blocks when policy allows.
- Scheduling should emit handover candidates for late trips so the repair stage can attempt a fresh evening rotation before extending a day duty into overtime.
- Scheduling should explicitly distinguish physical bus reuse from driver continuity: a bus ID may stay in service across the day, but the driver attached to that bus must be allowed to reset at a planned handover.

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
1. Normalize datasets into a unified schema (employees, stores, shifts, trips, overtime summaries).
2. Build store- and wave-level demand from the weekly shift schedule, including split-shift handling where present.
3. Filter pilot scope to stores with valid geocoordinates and log unmatched stores separately for review.
4. Use current route execution logs only to calibrate reasonable trip duration, stop sequencing, and driver-duty patterns for the new design.
5. Run capacity-aware clustering using geocoordinates plus time-window compatibility, avoiding purely spatial clusters that ignore demand timing.
6. Smooth overloaded demand windows within allowed waiting tolerances before final trip opening so the 13-bus fleet limit remains achievable.
7. Generate new `IN`, `OUT`, and conditionally `MIXED` trips from scratch for each cluster or time wave using fleet-aware construction rules.
8. Chain those designed trips into bus and driver schedules with legal buffers, stop-level load tracking, opportunistic pickup checks, and explicit split-shift reset logic when long idle gaps are available.
9. Run a destroy-and-repair loop on bottleneck windows and unscheduled trips until concurrency, duty spread, overtime, or explicit infeasibility stabilizes.
10. Run a duty-repair pass that splits stretched duties, seeds fresh evening rotations, and swaps late trips away from already-long day duties when feasible.
11. Use waiting tolerance to rescue unscheduled trips where a short departure shift allows an existing bus to finish its buffer and absorb the work.
12. Validate waiting, capacity, and timing constraints against the weekly shift schedule, surface any infeasible or unserved demand explicitly, then compute KPIs with fleet-feasibility, duty regularity, and overtime reported first.

## Working Notes
- Visualize geocoordinates on a map to identify spatial clusters (e.g., south/central/north).
- Use inter-cluster travel time as a key driver for route structuring.
- Smart-routing target: allow opportunistic pickups on the return to accommodation if a shift-ended employee is near the bus path after inbound drops are completed.
- Mixed routing should be evaluated as a capacity-recovery mechanism: inbound drops free seats, then nearby outbound pickups can fill those seats on the return leg.
- Mixed routing should only be accepted when detour, employee readiness, stop-level seat feasibility, and downstream duty compatibility all remain acceptable.
- Consolidation rule of thumb: remove or absorb low-value trips when doing so lowers peak fleet usage and total duty hours, even if occupancy gains are only moderate.
- Occupancy improvement is desirable, but not at the cost of exceeding the 13-bus limit, adding extra duties, or extending too many drivers past the 9-hour target.
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
