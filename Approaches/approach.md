# Integrated Approach: Kuwait Employee Transport Optimization

This document aligns with `context.md` and translates the problem definition into a practical, implementable optimization strategy. It treats the system as a scheduled shuttle network with accommodation as the fixed depot, strict operational constraints, and a primary focus on reducing driver overtime.

## 1) Problem Framing (Aligned to Context)
- Fixed start/end depot: accommodation (single start location).
- Trips are sequences of store stops and must return to depot.
- Routes are schedule-driven; employees are assigned to trips (not ad hoc routing).
- Goal: reduce driver overtime, preserve feasible service coverage, improve occupancy, and reduce deadhead and idle time.
- No traffic or festival modeling; travel times are static with buffers.

## 2) Core Constraints (Hard or Near-Hard)
- Bus capacity: 22 seats, up to 25 max.
- Buffer between successive trips: 30-45 minutes.
- Trip duration target: average 2.5 hours (max 300 minutes in overview).
- Driver hours: target 9 hours, acceptable 8-10.
- Waiting time: 30-40 minutes max.
- Employees should not arrive more than 30 minutes early.
- Shifts: mostly 9-hour blocks, some 12-hour and broken shifts allowed.

## 2.1) Optimization Structure
- Hard constraints: seat capacity, depot start/end, trip-duration caps, time-window feasibility, stop-level load feasibility on `MIXED` trips, and legal 30-45 minute buffers between chained trips.
- Objective hierarchy: minimize overtime first, maximize feasible service coverage second, improve occupancy third, and reduce deadhead/waiting fourth.
- Implementation guidance: use a lexicographic or strongly tiered penalty structure so the solver does not trade overtime increases for fuller buses or slightly shorter routes.
- Practical rule: reject route patterns that look efficient geographically if they make downstream bus/driver duties infeasible.

## 3) Best-of-Approaches Architecture (Hybrid Pipeline)

Demand Estimation -> Capacity-Aware Clustering -> VRPTW Routing
-> Bus and Driver Scheduling -> Service Validation -> Simulation and KPIs

Why this hybrid works:
- Clustering reduces combinatorial complexity while preserving geographic and temporal structure.
- VRPTW-style routing enforces time windows, capacity, and trip-level feasibility.
- Scheduling ensures legal chaining, driver-hour limits, and buffers.
- Service validation guarantees that store-wave demand is covered at the required timing level.
- Simulation validates robustness without needing full traffic modeling.

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

### C) VRPTW Routing (Core Optimization Engine)
Purpose: generate feasible trips for each cluster and time wave.

Model:
- nodes: accommodation + stores
- constraints: time windows, capacity, max stops, max trip duration, ride time
- objective: prefer trip patterns that reduce overtime risk first, then improve occupancy and deadhead performance within hard constraints

Notes:
- solve per cluster or per time wave for scalability
- use OR-Tools as default; MILP only for smaller instances
- emit duty-feasibility outputs for each trip: start/end times, duration, slack, stop-level load profile, and chaining compatibility
- do not treat driver-duty feasibility as purely downstream; routing should already prefer trips that can be chained legally with required buffers

### D) Bus and Driver Scheduling (Shift Optimization)
Purpose: chain trips into daily bus and driver duties with buffers.

Rules:
- 30-45 minute buffer between trips
- target 9 hours, penalize overtime beyond 9
- allow split shifts (4 + 5 hours)
- reject trip pairings that are individually feasible but illegal when combined into a duty
- preserve visibility into why a trip cannot be chained: buffer violation, overtime spill, or shift-boundary mismatch

Outcome:
- daily bus schedules and driver rosters
- explicit reasons for rejected chains or overtime-heavy duties

### E) Service Validation
Purpose: validate that routed trips cover required store-wave demand and remain policy-compliant.

Checks:
- capacity at every stop (load tracking, not just total passengers)
- waiting time <= 30-40 minutes
- arrival not earlier than 30 minutes before shift
- trip duration and ride time limits
- explicit exception handling when full coverage is infeasible: extra trip creation, manual-review flag, or unserved-demand record with heavy penalty
- unmatched stores without geocoordinates are excluded from routing and reported separately so coverage gaps are visible

### F) Simulation and KPI Evaluation
Purpose: stress-test the schedule and quantify improvement.

KPIs:
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
4. Reconstruct baseline trip patterns and driver duties from `Bus Routes curent.xlsx`.
5. Perform capacity-aware clustering with both spatial and time-window compatibility.
6. Solve VRPTW per cluster or time wave and retain duty-feasibility outputs for scheduling.
7. Chain trips into bus/driver schedules with buffer rules and overtime-first logic.
8. Validate against shift timing, surface infeasible or unserved demand explicitly, and compare KPIs against the current route operation and overtime logs.

## 6) Extensions (Phase 2+)
- Light ML demand forecasting for better peak estimates.
- Heuristic accelerators (GA, tabu search) for large-scale days.
- GNN or attention models for route proposal only (not core optimization).
- RL for disruption handling in real-time operations.

## Final Recommendation
Use a hybrid, constraint-first solution:

Demand Estimation -> Capacity-Aware Clustering -> VRPTW Routing
-> Bus and Driver Scheduling -> Service Validation -> KPI Evaluation

This approach matches the data and constraints in `context.md`, directly targets overtime reduction while protecting coverage feasibility, and remains practical to implement with the current datasets.
