# Integrated Approach: Kuwait Employee Transport Optimization

This document aligns with `context.md` and translates the problem definition into a practical, implementable optimization strategy. It treats the system as a scheduled shuttle network with accommodation as the fixed depot, strict operational constraints, and a primary focus on fleet-feasible scheduling followed by duty engineering before overtime reduction.

## 1) Problem Framing (Aligned to Context)
- Fixed start/end depot: accommodation (single start location).
- Trips are sequences of store stops and must return to depot.
- Routes are schedule-driven; employees are assigned to trips (not ad hoc routing).
- Goal: keep the designed schedule within the fixed 13-bus fleet, then reduce driver overtime, preserve feasible service coverage, improve occupancy, and reduce deadhead and idle time.
- No traffic or festival modeling; travel times are static with buffers.
- Current route logs are a baseline reference, not the target trip design.

## 2) Core Constraints (Hard or Near-Hard)
- Simultaneous active buses: max 13 in the pilot.
- Bus capacity: 22 seats, up to 25 max.
- Buffer between successive trips: 30-45 minutes.
- Trip duration target: average 2.5 hours (max 300 minutes in overview).
- Driver hours: target 9 hours, acceptable 8-10.
- Waiting time: 30-40 minutes max.
- Employees should not arrive more than 30 minutes early.
- Shifts: mostly 9-hour blocks, some 12-hour and broken shifts allowed.

## 2.1) Optimization Structure
- Hard constraints: simultaneous fleet limit, seat capacity, depot start/end, trip-duration caps, time-window feasibility, stop-level load feasibility on `MIXED` trips, and legal 30-45 minute buffers between chained trips.
- Objective hierarchy: satisfy the 13-bus fleet limit first, engineer practical rotations second, minimize overtime third, maximize feasible service coverage fourth, improve occupancy fifth, and reduce deadhead/waiting sixth.
- Implementation guidance: use a lexicographic or strongly tiered penalty structure so the solver does not trade fleet infeasibility, extreme duty spread, broken handovers, or overtime increases for fuller buses or slightly shorter routes. A trip must not be assigned to a duty slot that fails the driver-freshness test unless a formal rotation reset is performed.
- Practical rule: reject route patterns that look efficient geographically if they create peak-time fleet overload or make downstream bus/driver duties infeasible or excessively stretched.

## 3) Best-of-Approaches Architecture (Hybrid Pipeline)

Demand Estimation -> Peak Smoothing -> Capacity-Aware Clustering
-> Fleet-Aware Trip Construction -> Bus and Driver Scheduling
-> Repair Loop -> Service Validation -> Simulation and KPIs

Why this hybrid works:
- Clustering reduces combinatorial complexity while preserving geographic and temporal structure.
- Peak smoothing reduces obvious overload before the route constructor opens too many simultaneous trips.
- Fleet-aware routing enforces time windows, capacity, trip-level feasibility, and concurrency awareness.
- Scheduling ensures legal chaining, driver-hour limits, and buffers.
- Repair logic focuses compute on the bad parts of the solution instead of rebuilding the entire schedule after every conflict.
- Service validation guarantees that store-wave demand is covered at the required timing level.
- Simulation validates robustness without needing full traffic modeling.
- Current route logs remain useful as a benchmark and calibration signal, but they do not constrain the optimizer to reproduce existing trips.

## 4) Detailed Approach

### A) Demand Estimation (Lightweight ML or Deterministic)
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
Purpose: group stores into service zones that are both close and time-compatible.

Method:
- initial KMeans or DBSCAN on store geocoordinates
- refine using shift-window compatibility and capacity pressure

Rules:
- prevent clusters whose demand exceeds bus capacity in peak windows
- isolate sparse stores if they create infeasible routes
- avoid purely spatial clustering; nearby stores with incompatible demand waves should not be grouped just because they are geographically close
- preserve some flexibility for demand near overlapping shift boundaries instead of forcing it too early into one rigid time bucket

### B.1) Peak Smoothing (Before Final Trip Opening)
Purpose: prevent overloaded windows from producing globally impossible schedules.

Method:
- aggregate demand into short rolling or stepped windows such as 15 minutes
- estimate theoretical bus pressure as demand divided by effective bus capacity
- identify windows whose required bus count exceeds the fixed 13-bus fleet

Actions:
- shift soft demand to adjacent feasible windows within waiting tolerance
- delay low-priority outbound demand when doing so enables reuse of a recently freed bus
- keep records of any shifted demand so service quality remains measurable

### C) Fleet-Aware Trip Construction (Core Optimization Engine)
Purpose: generate new feasible trips for each cluster and time wave without exceeding practical fleet concurrency.

Model:
- nodes: accommodation + stores
- constraints: time windows, capacity, max stops, max trip duration, ride time, and peak concurrency feasibility
- objective: prefer trip patterns that keep bus concurrency within 13 first, then reduce overtime risk, then improve occupancy and deadhead performance within hard constraints

Notes:
- solve per cluster or per time wave for scalability, but score every accepted trip against the global concurrency profile
- use a greedy randomized construction heuristic by default; OR-Tools or MILP can still be used on smaller subproblems if needed
- emit duty-feasibility outputs for each trip: start/end times, duration, slack, stop-level load profile, and chaining compatibility
- do not treat driver-duty feasibility as purely downstream; routing should already prefer trips that can be chained legally with required buffers
- generate trips from scratch from store-wave demand rather than inheriting current trip IDs from the bus route logs
- use current route logs only to calibrate trip duration bands, stop density, and other realism checks

Trip construction logic:
- `IN`: group compatible pre-shift demand into accommodation-to-store trips.
- `OUT`: group compatible post-shift demand into store-to-accommodation trips.
- `MIXED`: actively seek return-path pickups when an inbound bus finishes near ready outbound demand and the combination reduces a separate bus movement.
- each candidate trip should be screened against hard limits before duty chaining: seat capacity, trip-duration cap, stop count, timing feasibility, and whether opening the trip worsens peak fleet overlap.
- if a candidate trip is locally feasible but would push active buses above 13, prefer one of three alternatives before accepting it:
  - merge into a fuller compatible trip
  - shift within tolerance
  - defer to repair as unresolved overload

### D) Bus and Driver Scheduling (Shift Optimization)
Purpose: chain trips into daily bus and driver duties with buffers.

Rules:
- 30-45 minute buffer between trips
- target 9 hours, penalize overtime beyond 9
- allow split shifts (4 + 5 hours)
- treat long gaps, for example 3+ hours, as shift-reset candidates instead of automatically stretching one duty across the whole day
- seed fresh evening rotations for late-night `OUT` waves before extending day duties
- treat the fleet as 13 physical buses but allow separate morning and evening duty slots on those buses when handover timing makes reuse feasible
- before attaching a trip to a slot, test whether the resulting duty span would exceed the practical threshold; if so, force a rotation reset or choose another slot
- reject trip pairings that are individually feasible but illegal when combined into a duty
- preserve visibility into why a trip cannot be chained: buffer violation, overtime spill, or shift-boundary mismatch

Outcome:
- daily bus schedules and driver rosters
- explicit reasons for rejected chains or overtime-heavy duties
- explicit split-shift recommendations when one bus can cover both a morning and evening block without treating them as one continuous driver spread
- explicit handover candidates where a late trip should move to a fresh evening rotation
- overtime metrics should be calculated on these designed duties, not on raw historical route logs

### E) Repair Loop (Large Neighborhood Search Style)
Purpose: repair the specific windows where a first-pass schedule still violates fleet or duty feasibility.

Destroy step:
- identify the highest-overlap bottleneck windows
- score trips in those windows by weak occupancy, poor chaining value, and redundancy with nearby trips
- score unscheduled trips and excessively long duties as repair targets too
- remove a small set of weak trips rather than rebuilding the full schedule

Repair step:
- reinsert removed demand by merging into compatible active trips
- stagger departures within waiting tolerance to reuse buses freed by earlier trips
- convert feasible `IN` plus `OUT` pairs into `MIXED` duties when that avoids launching another concurrent trip
- split over-stretched duties into separate morning and evening blocks when long idle gaps make that legal and practical
- use departure-window flexibility to rescue unscheduled trips if delaying them by 15-40 minutes allows a bus to complete its mandatory buffer and absorb the load
- attempt late-wave swaps by moving the final trip of a stretched duty onto a shorter or freshly seeded evening duty

Acceptance rule:
- always prefer repairs that reduce concurrency breaches
- among fleet-feasible repairs, prefer shorter duty spreads
- among equal duty-spread options, prefer lower overtime
- among equal overtime options, prefer higher coverage and occupancy

### F) Service Validation
Purpose: validate that routed trips cover required store-wave demand and remain policy-compliant.

Checks:
- capacity at every stop (load tracking, not just total passengers)
- waiting time <= 30-40 minutes
- arrival not earlier than 30 minutes before shift
- trip duration and ride time limits
- explicit exception handling when full coverage is infeasible: extra trip creation, manual-review flag, or unserved-demand record with heavy penalty
- unmatched stores without geocoordinates are excluded from routing and reported separately so coverage gaps are visible

### G) Simulation and KPI Evaluation
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
Start with a deterministic prototype that can run with current data:
1. Clean and unify the four active inputs: `Employee Shift data.xlsx`, `Bus Routes curent.xlsx`, `Geocoordinates.xlsx`, and `Kuwait Route Optimization - Overview.xlsx`.
2. Build demand tables by store and shift window from `Employee Shift data.xlsx`, then calibrate wave intensity against `Bus Routes curent.xlsx`.
3. Exclude stores without geocoordinates from route generation and log them in a separate unmatched-store output.
4. Extract calibration signals from `Bus Routes curent.xlsx` such as typical trip durations, practical stop counts, and baseline overtime.
5. Build short demand windows, estimate peak bus pressure, and smooth windows that clearly exceed the 13-bus fleet limit.
6. Perform capacity-aware clustering with both spatial and time-window compatibility.
7. Generate new `IN`, `OUT`, and allowed `MIXED` trips from cluster-level and wave-level demand using fleet-aware construction rules.
8. Chain those trips into bus/driver schedules with buffer rules, split-shift reset logic, evening-rotation seeding, and duty-aware staggering.
9. Run a repair loop on the worst concurrency windows, longest duty spreads, and unscheduled trips until the fleet-overlap profile stabilizes or explicit infeasibility remains.
10. Use departure-window flexibility to rescue unscheduled trips before classifying them as uncovered demand.
11. Run a dedicated duty-repair stage that splits stretched duties and swaps late-wave trips onto shorter or fresh evening duties.
12. Validate against shift timing, surface infeasible or unserved demand explicitly, and compare the designed schedule KPIs against the current route operation and overtime logs.

## 6) Extensions (Phase 2+)
- Light ML demand forecasting for better peak estimates.
- Heuristic accelerators (GA, tabu search) for large-scale days.
- GNN or attention models for route proposal only (not core optimization).
- RL for disruption handling in real-time operations.

## Final Recommendation
Use a hybrid, constraint-first solution:

Demand Estimation -> Peak Smoothing -> Capacity-Aware Clustering
-> Fleet-Aware Trip Construction -> Bus and Driver Scheduling
-> Repair Loop -> Service Validation -> KPI Evaluation

This approach matches the data and constraints in `context.md`, directly targets fleet-feasible schedules before overtime reduction, protects coverage feasibility, and remains practical to implement with the current datasets.
