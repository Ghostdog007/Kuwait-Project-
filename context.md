# Context: Kuwait Pilot Employee Transportation Optimization

This document consolidates the current understanding of the Kuwait pilot employee transport problem, its data assets, and its operating constraints. It serves as the problem-definition companion to `Approaches/approach.md`.

<!-- SEARCH HOOK: CONTEXT INDEX -->
<!-- Fast jump labels in this file:
CONTEXT INDEX
PROBLEM SUMMARY
CURRENT PILOT STATUS
INPUTS MODEL
OUTPUTS MODEL
OPTIMIZATION PRIORITIES
OBJECTIVE STRUCTURE
KNOWN CONSTRAINTS
DATA ASSETS
ASSUMPTIONS
PROTOTYPE SCOPE
TRIP DESIGN
FLEET HEURISTIC
BEST VERSION ARCHITECTURE
DUTY HANDOFF
OVERTIME FOCUS
SERVICEABILITY POLICY
OPEN QUESTIONS
NEXT STEP
WORKING NOTES
UPDATE CHECKLIST
-->

## Problem Summary
<!-- SEARCH HOOK: PROBLEM SUMMARY -->
- Pilot scope only: employees live in accommodation and must be transported to and from pilot stores on fixed shift windows.
- The system is schedule-driven (metro-like): buses run trips and employees are assigned to trips.
- Trips may be `IN`, `OUT`, or `MIXED` when a bus drops inbound passengers and then opportunistically picks up shift-ended employees on the return path.
- Current routes are relatively fixed while demand and staffing vary.
- The optimization target is to design new trips from demand and constraints, not to preserve current trip shapes.
- Pain point: high driver overtime and idle/deadhead time.
- Goal: build a constraint-first pilot optimization pipeline covering demand estimation, routing, duty construction, and passenger assignment.
- Current prototype priority: keep the schedule within the 13-bus fleet, then maximize feasible service coverage within that hard fleet cap, then enforce driver freshness through morning/evening rotation slots, then reduce duty overtime without sacrificing served demand, then improve occupancy, then reduce deadhead and waiting where feasible.
- Current improvement direction: keep OR-Tools as the baseline trip constructor, then reduce the remaining gap between trip synthesis and scheduling by making `MIXED` construction, fragment pooling, and bottleneck repair more schedule-aware.
- Best-version direction: reduce the independence between trip synthesis and scheduling by moving toward schedule-aware trip construction, jsprit-style ruin-and-recreate fragment repair, OR-Tools-based `MIXED` return-leg insertion, rolling-horizon assignment, and joint bottleneck-window repair.

## Current Pilot Status
<!-- SEARCH HOOK: CURRENT PILOT STATUS -->
- The current prototype is pilot-only and should be interpreted against pilot demand, pilot fleet, and pilot overtime baselines only.
- The working fleet in the current prototype is 13 active buses unless the pilot scope is explicitly revised.
- Current modeled overtime is about 16.5 total hours across the pilot week, against a target of 10 total hours.
- The strongest remaining bottlenecks are concentrated around the 05:00 and 18:00 windows.
- Current unscheduled demand is no longer a broad week-long routing failure. The remaining gaps are mainly temporal conflicts (`duty_span_block`, `buffer_violation`) plus fragmented low-demand leftovers (`small_isolated_demand`) that need one more salvage-rebuild pass before being declared unserved.

## Inputs (Model)
<!-- SEARCH HOOK: INPUTS MODEL -->
From requirements and metadata:
- Fixed depot: accommodation (single start/end point per trip).
- Pilot store locations (geocoordinates) and store IDs.
- Employee information and weekly shift schedule by brand (April 5-11, 2026), including accommodation, store, role, and split-shift fields.
- Current pilot route execution logs and payroll/overtime summaries for calibration and benchmarking only.
- Pilot overview metrics for scale, fleet context, and operating assumptions.
- Resource counts: 13 buses, single vehicle type, 22 seats (max 25).
- Operational variables: driver availability; no traffic/festival modeling.

## Outputs (Model)
<!-- SEARCH HOOK: OUTPUTS MODEL -->
- Optimized pilot trip templates by time window and service direction.
- Bus and driver schedules, including legal buffers and morning/evening rotation tagging.
- Store- and wave-level service plans derived from employee shift demand.
- Stop-level load and timing plans for validating `MIXED` trip feasibility.
- KPI comparison covering overtime, service coverage, occupancy, deadhead, waiting time, and on-time compliance.

## Employer Trip Representation
<!-- SEARCH HOOK: EMPLOYER TRIP REPRESENTATION -->
- Employer-facing trip identity is `Drive # + Trip ID`.
- `Drive #` is shown as `D1`, `D2`, ... (driver/day bucket).
- `Trip ID` is shown as `T1`, `T2`, ... and resets per drive/day.
- Trips are represented as lifecycle rows: `Trip Start` -> stop rows -> `Trip End`.
- Employer outputs should avoid raw internal optimizer IDs as primary identifiers.

## Output Contract (Lean)
<!-- SEARCH HOOK: OUTPUT CONTRACT -->
Default delivery is intentionally lean and should keep only:

In `prototype/output/`:
- `kpi_summary.csv`
- `baseline_staged_kpi_summary.csv`
- `unscheduled_trips.csv`

In `prototype/output/employer_format/`:
- `trips_per_day.xlsx`
- `employee_to_bus_mapping_per_day.xlsx`

Any extra intermediate/debug output should be treated as non-default and removed from the final delivery view.

## Optimization Priorities
<!-- SEARCH HOOK: OPTIMIZATION PRIORITIES -->
- Primary objective: keep simultaneous active trips within the fixed 13-bus fleet limit.
- Secondary objective: maximize feasible service coverage within that fleet and route every employee demand that can be served legally.
- Tertiary objective: engineer legal driver rotations through morning/evening slot assignment and handovers so one bus can be reused without forcing one continuous all-day duty.
- Fourth objective: minimize driver overtime across that covered solution.
- Fifth objective: increase occupancy by consolidating compatible demand and using `MIXED` return pickups where feasible.
- Sixth objective: reduce deadhead and passenger waiting without violating higher-priority goals.
- Practical interpretation: a fuller trip is only preferred if it does not materially worsen concurrency, duty spread, handover feasibility, overtime, coverage, or chaining feasibility.

## Objective Structure
<!-- SEARCH HOOK: OBJECTIVE STRUCTURE -->
- Hard constraints first: simultaneous fleet limit of 13 buses, seat capacity, trip start/end at accommodation, stop-level load feasibility, shift-time compatibility, trip-duration caps, and mandatory 30-45 minute buffer feasibility between chained trips.
- Soft objective hierarchy in the current prototype should be coverage-first after the hard fleet cap: maximize feasible coverage/serviceability first, regularize duty spans and slot freshness second, minimize overtime third, improve occupancy fourth, and reduce deadhead and waiting fifth.
- Modeling note: treat this as a lexicographic or strongly tiered penalty structure, not a loose weighted average that could trade fleet infeasibility, excessive duty spread, broken handovers, or overtime for fuller buses.
- Practical interpretation: if two solutions have similar occupancy but one creates peak-hour fleet overload, extreme duty spread, or illegal trip chaining, reject it even if the route looks geographically efficient.
- Best-practice interpretation: the strongest version of the pilot should not build trips first and schedule later in isolation; it should favor trips that are both route-feasible and likely to fit a real duty slot at the moment they are created.

## Known Constraints and Notes
<!-- SEARCH HOOK: KNOWN CONSTRAINTS -->
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
- Broken shifts are allowed operationally, and the next stronger prototype step is to treat long legal midday gaps as explicit split-duty resets rather than always letting one duty span stretch across the whole day.
- Long idle gaps should not automatically stretch one duty across the whole day; the stronger version should let a driver or duty block sign off after the morning segment and restart later as a fresh legal block when the break is long enough.
- Late-night `OUT` waves should preferentially be served through evening rotations or handovers instead of being tacked onto already-long day duties.
- Max waiting time: 30-40 minutes (upper bound), to reduce overtime risk.
- Employees should arrive at pickup no earlier than 30 minutes before the scheduled bus trip (to avoid excessive waiting).
- Opportunistic pickup rule: after completing required inbound drops, a bus may collect outbound employees only if the pickup store is near the return path, the employees' shifts have ended or are within a small compatibility tolerance, and capacity remains available after earlier drops.
- Mixed trips must track onboard load after every stop; pickups cannot violate seat capacity at any point on the route.
- Mixed routing should reduce deadhead and improve occupancy without creating excessive detours or pushing driver hours beyond daily limits.
- In the current prototype, `MIXED` is still treated as a lightweight constructed option: an `IN` trip may absorb a nearby `OUT` trip on the return side when the timing gap, detour, and load profile remain feasible.
- The next target is to replace that lightweight compatibility screen with an OR-Tools-style local insertion model so return-leg pickups are optimized rather than only screened.
- Fragment pooling should be treated as a proper repair layer: leftover tiny stops should be removed from their failed fragment form, regrouped into denser salvage demand, cooperatively merged with nearby leftover fragments, and reinserted before they are treated as final uncovered demand.
- Trip chaining and trip consolidation should be evaluated first by their effect on peak fleet concurrency, then by duty spread and overtime impact; occupancy gains are secondary unless concurrency, duty spread, and overtime are unchanged or improved.
- Borderline demand near overlapping duty windows should not be forced too early into a rigid time bucket if doing so removes a better chaining option.
- Some demand may naturally fit more than one duty window; assignment should remain flexible long enough to preserve better route-chaining opportunities.
- Current route logs should inspire feasible trip duration ranges, stop counts, and duty patterns, but they should not be treated as the trips the model must reproduce.

## Data Assets (Metadata Summaries)
<!-- SEARCH HOOK: DATA ASSETS -->

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
<!-- SEARCH HOOK: ASSUMPTIONS -->
- Each row in trip datasets is a stop; trips are reconstructed by grouping on trip ID.
- Employees belong to accommodation locations and stores; transportation demand is aggregated from those relationships rather than assigned from a prebuilt itinerary file.
- Peak hours are derived from shift overlaps in the weekly schedule plus observed route activity.
- The system operates like a scheduled metro service, not ad hoc routes.
- Pilot travel distance/time uses geocoordinates with Haversine distance plus fixed speed and dwell assumptions; no external road-time API is used.
- Base `IN` and `OUT` routing is now OR-Tools-driven, but mixed routing is still heuristic and compatibility-based rather than a full pickup-delivery optimization over all possible pickup/drop combinations.
- Fragment repair is still lightweight. The next stronger version should behave more like a ruin-and-recreate reinsertion loop rather than a single narrow salvage retry.
- Pilot scope uses only stores that have valid coordinates in `Geocoordinates.xlsx`; unmatched stores are ignored for routing and KPI generation.

## Prototype Scope
<!-- SEARCH HOOK: PROTOTYPE SCOPE -->
- Prototype inputs should be limited to `Employee Shift data.xlsx`, `Bus Routes curent.xlsx`, `Geocoordinates.xlsx`, and `Kuwait Route Optimization - Overview.xlsx`.
- Weekly shift data is the source of store demand and time-window construction.
- Current bus route logs are the source of baseline references, observed duty patterns, and overtime calibration.
- Geocoordinates are the source of routeable store locations and distance computation.
- Stores without geocoordinates must be excluded from routing logic and logged explicitly for review.
- Prototype trips must be newly generated from demand waves, store compatibility, and operating constraints rather than copied from current route logs.
- Prototype scheduling must treat the fixed 13-bus concurrency limit as a hard feasibility rule, not just a KPI reported after schedule generation.
- Prototype scheduling must treat driver freshness as part of feasibility during assignment, not as a post-processing label added after trips are already chained.
- Prototype scheduling currently uses separate `morning` and `evening` duty slots per physical bus, and the next stronger step is to allow explicit split-duty resets inside a slot when a long midday break makes that legal and operationally realistic.
- The current prototype now uses OR-Tools to build the strongest implemented `IN` and `OUT` trip set, but it still remains partly staged because `MIXED` recovery and duty-aware repair are not yet fully integrated into that route-construction loop.
- The next implementation step is a two-phase scheduler: first maximize covered demand within the hard 13-bus limit, then run a coverage-preserving overtime improvement pass on the trips that were successfully assigned.
- This can still be implemented inside the current prototype structure because the route builder, scheduler, and repair passes are already separate enough to support stronger reinsertion logic without a full rewrite.

## Trip Design Approach
<!-- SEARCH HOOK: TRIP DESIGN -->
- Build demand from `Employee Shift data.xlsx` at the store-wave level: each shift start creates inbound demand and each shift end creates outbound demand.
- Restrict routing to stores that pass the strict `Store Name` plus `Store ID` match between `Employee Shift data.xlsx` and `Geocoordinates.xlsx`.
- Group routeable stores by geography; keep time compatibility visible through wave-level demand buckets rather than inherited route IDs.
- Aggregate demand into short time windows so peak pressure is visible before trips are opened.
- Current prototype uses peak pressure as a trip-opening signal, preferring start times and wider trip groupings that consume less scarce peak-slot budget.
- Current prototype uses OR-Tools as the main route-construction engine for `IN` and `OUT` batches, with Mahboula as both start and end depot.
- Generate new candidate trips from scratch for each wave using fleet-aware construction logic:
  - `IN` trips carry employees from accommodation to stores before shift start.
  - `OUT` trips collect employees from stores after shift end and return to accommodation.
  - `MIXED` trips are built opportunistically by pairing a feasible `IN` trip with a nearby `OUT` return opportunity when the bus can absorb that return demand without breaking time or load limits.
- For `IN` and `OUT`, OR-Tools decides which stores belong together and in what order, subject to capacity, duration, and depot-return requirements.
- For `MIXED`, the current prototype only applies a heuristic compatibility pass after base route construction; the next step is an OR-Tools-based local insertion step on the return leg.
- For fragment recovery, the next step is to pool failed micro-fragments across nearby time windows, cooperatively merge them into denser leftover trips, and reinsert them into existing or newly rebuilt salvage trips before final rejection.
- Size each trip using hard operating limits: vehicle capacity, trip duration cap, waiting tolerance, maximum practical stop count, and the requirement that opening the trip should not force active fleet concurrency above 13 unless no feasible alternative exists.
- Before opening a new narrow trip in a crowded window, try to widen a compatible trip by adding nearby demand rather than consuming another peak-time slot.
- During assignment, every candidate bus-trip match must also pass a freshness check: if attaching the trip would push that duty beyond its practical span, the trip must be assigned to another slot or remain unscheduled.
- Use current route logs only to calibrate realistic trip characteristics such as typical duration bands, common stop density, and plausible duty spacing.
- After trip generation, chain the new trips into bus and driver duties with 30-minute buffers and measure overtime on those designed duties, not on the raw current schedule.
- Current prototype scheduling should be interpreted as two-stage: first assign as many trips as possible within the hard 13-bus and 10-hour duty rules, then improve the resulting covered schedule to reduce overtime without dropping already-served demand.
- Before a trip is finally marked unserved, the strongest near-term version should also pool tiny leftover stop fragments back into salvage demand and try one more denser rebuild pass.

## Fleet-Constrained Heuristic
<!-- SEARCH HOOK: FLEET HEURISTIC -->
- Current construction phase: use OR-Tools for base `IN` and `OUT` route construction inside time-compatible batches, then pass those routes into the custom scheduler.
- Peak control phase: compute theoretical bus pressure in short time windows and use that pressure as a budget signal when choosing start times and whether to open another trip.
- Rotation phase: treat the 13 physical buses as supporting separate morning and evening duty slots, with freshness checks controlling when a bus can be reused by a fresh evening duty.
- Rescue phase: allow limited delay-based rescue and retry for blocked trips within waiting tolerance when that helps fit the trip into an available slot.
- Salvage phase: pool `small_isolated_demand` leftovers back into denser same-wave or nearby-wave demand, then run a cooperative merge pass on those leftovers before declaring them permanently uncovered.
- Reinsertion phase: after pooling fragments, try to reinsert them using a ruin-and-recreate style repair sequence rather than only one narrow salvage attempt.
- Acceptance rule: prefer solutions that keep concurrency within 13 first, then maximize covered demand, then keep duty spans under control, then reduce overtime without losing coverage, then improve occupancy.
- Future extension: add a full destroy-and-repair / LNS stage for overloaded windows and unscheduled trips after the current greedy repair baseline is stable.

## Best-Version Architecture
<!-- SEARCH HOOK: BEST VERSION ARCHITECTURE -->
- The best practical version for this pilot is a schedule-aware rolling-horizon optimizer rather than a fully independent route-first pipeline.
- In that version, each candidate trip is scored not only by route quality but also by expected scheduling cost, including peak-window pressure, buffer fit, duty-span impact, and handover compatibility.
- Trip generation and bus assignment should proceed in time order so earlier accepted trips update the live fleet state before later trips are constructed.
- Bottleneck windows such as 05:00 and 18:00 should then receive a local repair pass that is allowed to shift, swap, merge, or convert trips to `MIXED` while preserving the fleet cap and duty legality.
- The strongest near-term version should keep OR-Tools for base route consolidation and add OR-Tools-style local pickup insertion for `MIXED` return-leg recovery instead of treating mixed routing as a separate lightweight heuristic.
- The strongest near-term version should also separate solving into two phases: coverage maximization under the hard 13-bus cap first, then overtime improvement on the fixed covered-trip set.
- A practical near-term design is therefore: OR-Tools for base routes, explicit split-duty resets for long midday gaps, stronger reinsertion-based fragment pooling, cooperative merge rebuilding for leftover demand, stronger return-leg `MIXED` insertion, then coverage-preserving overtime cleanup.
- This best-version direction keeps the pilot implementable while reducing the current independence between trip synthesis and downstream scheduling.

## Duty-Feasibility Handoff
<!-- SEARCH HOOK: DUTY HANDOFF -->
- Routing should output more than store sequences. Each generated trip should carry start time, end time, duration, slack, stop-level load profile, and compatibility markers for chaining into a legal bus/driver duty.
- Trip generation should expose whether a trip can be followed by another trip while preserving the required 30-45 minute buffer.
- `MIXED` trips should retain enough stop-level timing detail to verify that opportunistic pickups do not create infeasible downstream duties.
- Scheduling should be allowed to reject or penalize trips that are route-feasible in isolation but create overtime or illegal buffers when chained.
- Scheduling should surface peak concurrency by time window so fleet usage can be compared against the 13-bus cap.
- Scheduling should explicitly distinguish physical bus reuse from driver continuity: a bus ID may stay in service across the day, but the current prototype represents driver resets through separate morning/evening duty slots.
- Scheduling should emit enough timing detail to explain why a trip was accepted, delayed, or blocked by buffer or freshness limits.

## Overtime Reduction Focus
<!-- SEARCH HOOK: OVERTIME FOCUS -->
- To move from roughly 16.5 total overtime hours toward the 10-hour pilot target, the next gains should come from first maximizing coverage under the hard 13-bus cap and then reducing `duty_span_block` and `buffer_violation` without dropping already-served demand, especially in the concentrated 05:00 and 18:00 bottleneck windows.
- The highest-value pilot repairs are:
  - targeted start-time shifting within allowed tolerance for 05:00 and 18:00 trips,
  - stronger reassignment across morning/evening slots before dropping a trip,
  - targeted `MIXED` recovery for blocked outbound demand when an inbound return can absorb it,
  - salvage rebuilding of tiny leftover fragments into fuller retriable trips,
  - slot-donor or late-wave swap logic when one scheduled trip can move slightly and free a legal placement for a blocked trip.
- Lower-priority pilot work includes general low-occupancy consolidation, because the current main overtime driver is temporal duty fit rather than average trip duration alone.

## Serviceability Policy
<!-- SEARCH HOOK: SERVICEABILITY POLICY -->
- Full employee coverage is the target, but the model should explicitly handle infeasible demand rather than assuming every request can always be served.
- If demand cannot be assigned within hard timing, capacity, or duty constraints, the system should surface the exception clearly rather than hiding it inside an invalid route.
- Allowed fallback actions should be explicit in implementation: create an extra trip if feasible, flag for manual review, or record the demand as unserved with a very large penalty for KPI reporting.
- Coverage shortfalls should be reported separately from overtime so that a solution does not appear successful merely because it dropped hard-to-serve demand.
- If full legal coverage is not achievable within 13 buses and the hard duty cap, the model should prove that by exhausting repair and reassignment options before reporting residual unserved demand.

## Open Questions / Gaps
<!-- SEARCH HOOK: OPEN QUESTIONS -->
- Confirm which week/brand tabs are in scope for modeling (pilot vs. full market).
- Resolve data quality issues in itinerary timing and route logs.
- Set the final compatibility tolerance for mixed pickups (for example, how many minutes after shift end a bus may wait or how much detour is acceptable).
- Validate whether mixed trips should prioritize occupancy gain, overtime reduction, or waiting-time control when those objectives conflict.
- Define the exact optimization structure to use in implementation: lexicographic solve, staged solve, or hard constraints plus tiered penalties.
- Decide how much flexibility to preserve for demand near overlapping shift boundaries before assigning it to a fixed time wave.

## Next Step (Approach-Ready)
<!-- SEARCH HOOK: NEXT STEP -->
This section is aligned with `Approaches/approach.md` (Section 5: Recommended Starting Point).
1. Normalize datasets into a unified schema (employees, stores, shifts, trips, overtime summaries).
2. Build store- and wave-level demand from the weekly shift schedule, including split-shift handling where present.
3. Filter pilot scope to stores with valid geocoordinates and log unmatched stores separately for review.
4. Use current route execution logs only to calibrate reasonable trip duration, stop sequencing, and driver-duty patterns for the new design.
5. Run capacity-aware clustering using geocoordinates plus time-window compatibility, avoiding purely spatial clusters that ignore demand timing.
6. Smooth overloaded demand windows within allowed waiting tolerances before final trip opening so the 13-bus fleet limit remains achievable.
7. Generate new `IN`, `OUT`, and conditionally `MIXED` trips from scratch for each cluster or time wave using fleet-aware construction rules.
8. Run a coverage-first assignment pass that tries to place as many trips as possible into the 13-bus schedule using legal buffers, soft slot testing, hard freshness checks, and physical bus reuse rules.
9. Convert feasible `IN` plus nearby `OUT` pairs into `MIXED` candidates when that removes a separate return trip without breaking trip limits and improves covered demand.
10. Run a greedy repair pass on blocked trips using small timing shifts, slot donor logic, and simple re-assignment before classifying the demand as unscheduled.
11. Pool `small_isolated_demand` leftovers back into a salvage-demand table, cooperatively merge nearby leftover fragments, and run one more denser build-and-schedule pass before declaring those fragments unserved.
12. Freeze the covered trip set and run an overtime-improvement pass that is only allowed to reduce duty stress without reducing covered demand.
13. Validate waiting, capacity, and timing constraints against the weekly shift schedule, surface any infeasible or unserved demand explicitly, then compute KPIs with fleet-feasibility and coverage reported before overtime.
14. Evolve the prototype toward a rolling-horizon schedule-aware constructor so future trips are created with live knowledge of available buses, active duties, and bottleneck-window pressure.

## Working Notes
<!-- SEARCH HOOK: WORKING NOTES -->
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
<!-- SEARCH HOOK: UPDATE CHECKLIST -->

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
