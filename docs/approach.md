# Integrated Approach: Kuwait Pilot Employee Transport Optimization

This document aligns with `context.md` and translates the pilot problem definition into a practical, implementable optimization strategy. It treats the system as a scheduled shuttle network with accommodation as the fixed depot, strict pilot operational constraints, and a primary focus on fleet-feasible coverage maximization under the hard 13-bus limit before overtime reduction.

<!-- SEARCH HOOK: APPROACH INDEX -->
<!-- Fast jump labels in this file:
APPROACH INDEX
PROBLEM FRAMING
CURRENT PILOT FOCUS
CORE CONSTRAINTS
OPTIMIZATION STRUCTURE
HYBRID PIPELINE
DEMAND ESTIMATION
CAPACITY AWARE CLUSTERING
PEAK PRESSURE
ORTOOLS ROUTE CONSTRUCTION
ROTATION AWARE SCHEDULING
COVERAGE FIRST PASS
OVERTIME IMPROVEMENT PASS
LIGHTWEIGHT RESCUE
BOTTLENECK REPAIR
SERVICE VALIDATION
SIMULATION KPIS
RECOMMENDED STARTING POINT
EXTENSIONS
FINAL RECOMMENDATION
-->

## 1) Problem Framing (Aligned to Context)
<!-- SEARCH HOOK: PROBLEM FRAMING -->
- Fixed start/end depot: accommodation (single start location).
- Pilot scope only: this approach is for the current Kuwait pilot, not full-market deployment.
- Trips are sequences of store stops and must return to depot.
- Routes are schedule-driven; employees are assigned to trips (not ad hoc routing).
- Goal: keep the designed schedule within the fixed 13-bus fleet, maximize feasible service coverage within that limit, then enforce rotation-aware duty assignment, reduce driver overtime without sacrificing served demand, improve occupancy, and reduce deadhead and idle time.
- No traffic or festival modeling; travel times are static with buffers.
- Current route logs are a baseline reference, not the target trip design.

## 1.1) Current Pilot Focus
<!-- SEARCH HOOK: CURRENT PILOT FOCUS -->
- The current prototype is already strong on the top constraints: no fleet breach, no duties over 10 hours, and materially improved overtime versus the pilot baseline.
- The main remaining gap is concentrated unscheduled demand in the 05:00 and 18:00 windows.
- Current evidence shows the remaining drop-off is a mix of temporal conflicts and fragmented leftovers, so the next improvements should focus on explicit split-duty resets for long midday breaks plus stronger reinsertion-based and cooperative salvage rebuilding rather than broad route redesign.
- The deeper structural issue is that trip synthesis and trip scheduling are still too independent; the best next architecture reduces that separation by using scheduling feedback during trip construction while keeping OR-Tools as the baseline route engine.

## 2) Core Constraints (Hard or Near-Hard)
<!-- SEARCH HOOK: CORE CONSTRAINTS -->
- Simultaneous active buses: max 13 in the pilot.
- Bus capacity: 22 seats, up to 25 max.
- Buffer between successive trips: 30-45 minutes.
- Trip duration target: average 2.5 hours (max 300 minutes in overview).
- Driver hours: target 9 hours, acceptable 8-10.
- Waiting time: 30-40 minutes max.
- Employees should not arrive more than 30 minutes early.
- Shifts: mostly 9-hour blocks, some 12-hour and broken shifts allowed.

## 2.1) Optimization Structure
<!-- SEARCH HOOK: OPTIMIZATION STRUCTURE -->
- Hard constraints: simultaneous fleet limit, seat capacity, depot start/end, trip-duration caps, time-window feasibility, stop-level load feasibility on `MIXED` trips, and legal 30-45 minute buffers between chained trips.
- Objective hierarchy: satisfy the 13-bus fleet limit first, maximize feasible service coverage second, engineer practical morning/evening rotations third, minimize overtime on the covered solution fourth, improve occupancy fifth, and reduce deadhead/waiting sixth.
- Implementation guidance: use a lexicographic or strongly tiered penalty structure so the solver does not trade fleet infeasibility, extreme duty spread, broken handovers, or overtime increases for fuller buses or slightly shorter routes. In the current prototype, a trip must not be assigned to a duty slot that fails the driver-freshness test.
- Practical rule: reject route patterns that look efficient geographically if they create peak-time fleet overload or make downstream bus/driver duties infeasible or excessively stretched.

## 3) Best-of-Approaches Architecture (Hybrid Pipeline)
<!-- SEARCH HOOK: HYBRID PIPELINE -->

Demand Estimation -> Peak Pressure Measurement -> Capacity-Aware Clustering
-> OR-Tools Route Construction -> Coverage-First Scheduling
-> Coverage-Preserving Overtime Improvement
-> OR-Tools-Assisted Mixed Insertion -> Bottleneck-Window Repair
-> Service Validation -> Simulation and KPIs

Why this hybrid works:
- Clustering reduces combinatorial complexity while preserving geographic and temporal structure.
- Peak-pressure measurement shows where overload is likely before the route constructor opens too many simultaneous trips.
- OR-Tools route construction enforces depot-return routing, capacity, trip-level feasibility, and stronger stop grouping/order than the earlier greedy builder.
- Coverage-first scheduling ensures the fleet is used to serve as much demand as possible before overtime becomes the dominant optimization target.
- Coverage-preserving overtime improvement then cleans the covered solution without allowing the solver to gain a nicer duty profile by dropping hard-to-serve trips.
- OR-Tools-assisted mixed insertion is the next missing bridge: it should test whether a scheduled inbound route can absorb nearby outbound demand on the return leg without breaking load, time, or duty feasibility.
- Fragment pooling should become a proper coverage-recovery layer: leftover tiny stops should be regrouped and reinserted instead of only being retried once in narrow salvage form.
- Bottleneck-window repair focuses effort on the real problem windows instead of disturbing the whole pilot week.
- Service validation guarantees that store-wave demand is covered at the required timing level.
- Simulation validates robustness without needing full traffic modeling.
- Current route logs remain useful as a benchmark and calibration signal, but they do not constrain the optimizer to reproduce existing trips.

## 4) Detailed Approach

### A) Demand Estimation (Lightweight ML or Deterministic)
<!-- SEARCH HOOK: DEMAND ESTIMATION -->
Purpose: quantify how many employees need pickup/drop service for each store and shift window.

Inputs:
- `Employee_Shift_data.xlsx`
- `Bus Routes curent.xlsx`
- `Kuwait Route Optimization - Overview.xlsx`

Outputs:
- `demand_by_store_shift_window`
- peak time buckets for inbound and outbound waves

Practical default:
- deterministic aggregation from the weekly shift schedule by store and shift window (start/end, including split shifts)
- calibrate or sanity-check wave sizes against observed route activity in `Bus Routes curent.xlsx`
- use the overview file for scale checks, fleet counts, and pilot-scope consistency
- exclude stores without geocoordinates from route generation and log them as unmatched inputs for review

### B) Capacity-Aware Clustering (Geospatial + Time Window)
<!-- SEARCH HOOK: CAPACITY AWARE CLUSTERING -->
Purpose: group stores into service zones that are both close and time-compatible.

Method:
- initial KMeans or DBSCAN on store geocoordinates
- refine using shift-window compatibility and capacity pressure

Rules:
- prevent clusters whose demand exceeds bus capacity in peak windows
- isolate sparse stores if they create infeasible routes
- avoid purely spatial clustering; nearby stores with incompatible demand waves should not be grouped just because they are geographically close
- preserve some flexibility for demand near overlapping shift boundaries instead of forcing it too early into one rigid time bucket

### B.1) Peak Pressure Measurement (Before Final Trip Opening)
<!-- SEARCH HOOK: PEAK PRESSURE -->
Purpose: expose overloaded windows before trips are finalized.

Method:
- aggregate demand into short rolling or stepped windows such as 15 minutes
- estimate theoretical bus pressure as demand divided by effective bus capacity
- identify windows whose required bus count exceeds the fixed 13-bus fleet

Actions:
- measure whether theoretical bus need is already close to or above the 13-bus cap
- use this pressure signal to judge whether trip opening and later scheduling are likely to be feasible
- use that pressure signal to prefer less congested candidate start times when a trip can legally move within tolerance
- future extension: shift soft demand more aggressively across adjacent feasible windows before trip opening

### C) OR-Tools Route Construction (Core Optimization Engine)
<!-- SEARCH HOOK: ORTOOLS ROUTE CONSTRUCTION -->
Purpose: generate strong base `IN` and `OUT` trips for each cluster and time wave before those trips are handed to the custom bus-duty scheduler.

Model:
- nodes: accommodation + stores
- constraints: time windows, capacity, max stops, max trip duration, ride time, and peak concurrency feasibility
- objective: prefer trip patterns that keep bus concurrency within 13 first, then reduce expected duty-span and buffer risk, then improve occupancy and deadhead performance within hard constraints

Notes:
- solve per cluster or per time wave for scalability, but score every accepted trip against the global concurrency profile and the current expected bus-duty landscape
- use OR-Tools as the default route constructor for `IN` and `OUT` batches; keep MILP or deeper exact models only as future extensions for smaller subproblems if needed
- emit duty-feasibility outputs for each trip: start/end times, duration, slack, stop-level load profile, and chaining compatibility
- do not treat driver-duty feasibility as purely downstream; routing should already prefer trips that can be chained legally with required buffers and lower expected scheduling cost
- generate trips from scratch from store-wave demand rather than inheriting current trip IDs from the bus route logs
- use current route logs only to calibrate trip duration bands, stop density, and other realism checks
- best-version direction: move toward a rolling-horizon constructor where accepted trips update the current fleet state before the next wave is built

Trip construction logic:
- `IN`: group compatible pre-shift demand into accommodation-to-store trips.
- `OUT`: group compatible post-shift demand into store-to-accommodation trips.
- `MIXED`: current prototype only tests simple `IN` plus nearby `OUT` pairings heuristically after base route construction.
- Next target for `MIXED`: run a local OR-Tools-style return-leg insertion model that tries to insert outbound pickups into the tail of an already-constructed inbound trip, subject to employee readiness, detour, stop-level load, duration, and downstream duty feasibility.
- Fragment repair target: move toward a jsprit-style ruin-and-recreate idea where failed small fragments are pooled, then reinserted into existing routes or denser salvage trips before final rejection.
- each candidate trip should be screened against hard limits before duty chaining: seat capacity, trip-duration cap, stop count, timing feasibility, and whether opening the trip worsens peak fleet overlap.
- if a candidate trip is locally feasible but would push active buses above 13, prefer a fuller compatible trip pattern or a slightly shifted start time during construction before letting scheduling absorb the conflict later
- if two candidate trips are similar geographically, prefer the one that is more likely to fit a real bus slot without causing downstream buffer or duty-span blocks

### D) Rotation-Aware Scheduling
<!-- SEARCH HOOK: ROTATION AWARE SCHEDULING -->
Purpose: chain trips into daily bus duties with buffers while approximating fresh driver rotations.

Rules:
- 30-45 minute buffer between trips
- target 9 hours, penalize overtime beyond 9
- approximate split shifts through separate `morning` and `evening` duty slots on each physical bus, then upgrade that approximation by allowing a long legal midday gap to reset a duty block inside the scheduler
- prefer evening slots for late `OUT` work and trips starting after the evening seed hour
- test both slot types around the boundary and choose the legal slot that gives the cleaner duty profile rather than relying on a rigid cutoff alone
- before attaching a trip to a slot, test whether the resulting duty span would exceed the practical threshold; if so, reject that slot
- reject trip pairings that are individually feasible but illegal when combined into a duty
- preserve visibility into why a trip cannot be chained: buffer violation, freshness block, or fleet overlap on the same physical bus

Outcome:
- daily bus schedules and driver rosters
- explicit reasons for rejected chains or overtime-heavy duties
- explicit morning/evening rotation tags showing how one bus is reused
- delayed-trip rescue flags for outbound trips shifted within tolerance
- overtime metrics should be calculated on these designed duties, not on raw historical route logs

### D.1) Coverage-First Scheduling Pass
<!-- SEARCH HOOK: COVERAGE FIRST PASS -->
Purpose: maximize covered demand under the hard 13-bus limit before optimizing overtime.

Rules:
- keep the 13-bus cap and hard duty cap non-negotiable
- when multiple legal slot choices exist, prefer the choice that preserves schedulability and demand coverage before preferring the lowest overtime placement
- process the trip set in a coverage-oriented order so higher-value trips are not crowded out by locally cleaner but lower-coverage assignments
- keep blocked trips in a repair queue rather than treating them as final failures on first rejection
- if a bus has a long enough legal midday gap, allow the next trip to start a fresh split-duty block instead of forcing one continuous duty span

### D.2) Coverage-Preserving Overtime Improvement Pass
<!-- SEARCH HOOK: OVERTIME IMPROVEMENT PASS -->
Purpose: improve duty quality after the covered trip set is frozen.

Rules:
- do not drop already-served trips
- try reassignment, slot changes, and small legal time shifts only if coverage stays unchanged
- accept a move only if it reduces total overtime, long-duty count, or duty span without violating fleet or duty hard constraints

### E) Lightweight Rescue Logic
<!-- SEARCH HOOK: LIGHTWEIGHT RESCUE -->
Purpose: recover some blocked pilot trips without breaking the fleet or freshness rules.

Current logic:
- when a trip cannot be assigned immediately, retry assignment with a small set of legal timing shifts
- prefer simple recoveries first: better slot choice, allowed departure shift, then re-assignment
- keep unscheduled trips explicit when no slot passes buffer, freshness, and physical bus overlap checks
- emit a rejection-cause breakdown so blocked trips can be grouped into `buffer_violation`, `duty_span_block`, `slot_exhausted`, or `small_isolated_demand`

Future extension:
- add a targeted bottleneck-window repair loop for the 05:00 and 18:00 peaks before attempting full LNS
- add slot-donor swaps and stronger `MIXED` recovery for blocked outbound trips in those windows
- let that stronger mixed recovery reuse the OR-Tools route engine locally, instead of relying only on post-hoc heuristics
- pool `small_isolated_demand` leftovers into a salvage-demand table and run one more integrated rebuild pass before final rejection
- extend that salvage pass into a true reinsertion loop: regroup fragments, try insertion into existing trips, cooperatively merge nearby leftovers into denser retry trips, then build salvage trips only for what still cannot be absorbed

### E.1) Best-Version Bottleneck Repair
<!-- SEARCH HOOK: BOTTLENECK REPAIR -->
Purpose: fix the remaining independence between trip creation and scheduling by letting the repair stage modify both trip timing and trip placement inside the true bottleneck windows.

Best-version logic:
- work only on high-pressure windows such as 05:00 and 18:00
- test donor swaps, slot reassignments, targeted `MIXED` conversions, and small legal time shifts together rather than one at a time in isolation
- accept a repair only if it preserves the 13-bus cap and all hard duty limits
- keep employee service timing valid when any donor or shifted trip is modified

### F) Service Validation
<!-- SEARCH HOOK: SERVICE VALIDATION -->
Purpose: validate that routed trips cover required store-wave demand and remain policy-compliant.

Checks:
- capacity at every stop (load tracking, not just total passengers)
- waiting time <= 30-40 minutes
- arrival not earlier than 30 minutes before shift
- trip duration and ride time limits
- explicit exception handling when full coverage is infeasible: extra trip creation, manual-review flag, or unserved-demand record with heavy penalty
- unmatched stores without geocoordinates are excluded from routing and reported separately so coverage gaps are visible

### G) Simulation and KPI Evaluation
<!-- SEARCH HOOK: SIMULATION KPIS -->
Purpose: stress-test the schedule and quantify improvement.

KPIs:
- peak simultaneous active trips
- fleet-limit breach count / magnitude
- long-duty count and average duty spread
- rescued-trip count and handover count
- driver overtime hours
- service coverage / unserved demand count
- bus occupancy percentage
- deadhead time/distance
- employee waiting and ride time
- on-time compliance
- duty-chaining rejection count or reason breakdown

## 5) Recommended Starting Point (Phase 1)
<!-- SEARCH HOOK: RECOMMENDED STARTING POINT -->
Start with a deterministic prototype that can run with current data:
1. Clean and unify the four active inputs: `Employee Shift data.xlsx`, `Bus Routes curent.xlsx`, `Geocoordinates.xlsx`, and `Kuwait Route Optimization - Overview.xlsx`.
2. Build demand tables by store and shift window from `Employee Shift data.xlsx`, then calibrate wave intensity against `Bus Routes curent.xlsx`.
3. Exclude stores without geocoordinates from route generation and log them in a separate unmatched-store output.
4. Extract calibration signals from `Bus Routes curent.xlsx` such as typical trip durations, practical stop counts, and baseline overtime.
5. Build short demand windows and estimate peak bus pressure against the 13-bus fleet limit.
6. Perform capacity-aware clustering with both spatial and time-window compatibility.
7. Generate new `IN` and `OUT` trips from cluster-level and wave-level demand using OR-Tools route construction rules, then add `MIXED` only through a validated return-leg compatibility step.
8. Use peak-pressure signals to prefer wider trips and less congested legal start times before final scheduling.
9. Run a coverage-first assignment pass into morning/evening bus slots with buffer rules, soft slot-boundary testing, and hard freshness checks.
10. Use lightweight repair with small timing shifts and re-assignment attempts before classifying trips as uncovered demand.
11. Pool `small_isolated_demand` leftovers into a salvage-demand table, cooperatively merge nearby leftovers into denser retry demand, and run one more build-and-schedule pass before treating them as final uncovered demand.
12. Freeze the covered trip set, then run a coverage-preserving overtime improvement pass over those assigned trips.
13. Inspect unscheduled-trip rejection causes and focus the next repair pass on the dominant pilot bottlenecks, especially 05:00 and 18:00.
14. Evolve the prototype toward a rolling-horizon trip constructor so later trips are built with live knowledge of active duties, available buses, and likely bottleneck conflicts.
15. Validate against shift timing, surface infeasible or unserved demand explicitly, and compare the designed schedule KPIs against the current route operation and overtime logs.

Implementation note:
- This should be integrated into the current prototype rather than rebuilt from scratch, because the existing OR-Tools route builder, custom scheduler, fragment salvage outputs, and repair passes already provide the right extension points for split-duty resets, stronger reinsertion logic, and cooperative leftover merging.

## 6) Extensions (Phase 2+)
<!-- SEARCH HOOK: EXTENSIONS -->
- Light ML demand forecasting for better peak estimates.
- Heuristic accelerators (GA, tabu search) for large-scale days.
- GNN or attention models for route proposal only (not core optimization).
- RL for disruption handling in real-time operations.

## Final Recommendation
<!-- SEARCH HOOK: FINAL RECOMMENDATION -->
Use a hybrid, constraint-first solution:

Demand Estimation -> Peak Pressure Measurement -> Capacity-Aware Clustering
-> OR-Tools Route Construction -> Rotation-Aware Scheduling
-> OR-Tools-Assisted Mixed Insertion -> Bottleneck-Window Repair
-> Service Validation -> KPI Evaluation

This approach matches the data and constraints in `context.md`, directly targets fleet-feasible schedules before overtime reduction, protects coverage feasibility, and points the prototype toward a stronger schedule-aware architecture without requiring a full exact solver.

## Delivery Schema (Employer-Facing)
<!-- SEARCH HOOK: DELIVERY SCHEMA -->
Final delivery should prioritize employer readability over raw optimizer internals.

Trip and schedule representation:

1. Use `Drive #` (`D1`, `D2`, ...) and `Trip ID` (`T1`, `T2`, ...) as the primary trip key.
2. Reset trip sequence per drive/day.
3. Represent each trip as lifecycle events: `Trip Start`, stop rows, `Trip End`.

Lean default output set:

1. `prototype/output/kpi_summary.csv`
2. `prototype/output/baseline_staged_kpi_summary.csv`
3. `prototype/output/unscheduled_trips.csv`
4. `prototype/output/employer_format/trips_per_day.xlsx`
5. `prototype/output/employer_format/employee_to_bus_mapping_per_day.xlsx`

Implementation policy:

1. Keep the optimization core intact.
2. Evolve exports incrementally to match stakeholder format.
3. Avoid full rewrites when the requirement is mainly schema/presentation alignment.
