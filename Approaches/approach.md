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
-> Bus and Driver Scheduling -> Passenger Assignment -> Simulation and KPIs

Why this hybrid works:
- Clustering reduces combinatorial complexity while preserving geographic and temporal structure.
- VRPTW-style routing enforces time windows, capacity, and trip-level feasibility.
- Scheduling ensures legal chaining, driver-hour limits, and buffers.
- Passenger assignment guarantees service-level feasibility at the employee level.
- Simulation validates robustness without needing full traffic modeling.

## 4) Detailed Approach

### A) Demand Estimation (Lightweight ML or Deterministic)
Purpose: quantify how many employees need pickup/drop service for each store and shift window.

Inputs:
- `Employee_Shift_Assignment.xlsx`
- `Employee_Shift_data.xlsx`
- `passenger_itinerary_v11.xlsx`

Outputs:
- `demand_by_store_shift_window`
- peak time buckets for inbound and outbound waves

Practical default:
- deterministic aggregation by store and shift window (start/end)
- add confidence bands if historical data allows

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

### E) Passenger Assignment and Validation
Purpose: assign employees to trips and ensure policy compliance.

Checks:
- capacity at every stop (load tracking, not just total passengers)
- waiting time <= 30-40 minutes
- arrival not earlier than 30 minutes before shift
- trip duration and ride time limits
- explicit exception handling when full coverage is infeasible: extra trip creation, manual-review flag, or unserved-demand record with heavy penalty

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
Start with a deterministic pipeline that can run with current data:
1. Clean and unify datasets (trip IDs, store IDs, timestamps).
2. Build demand tables by store and shift window.
3. Perform capacity-aware clustering with both spatial and time-window compatibility.
4. Solve VRPTW per cluster/time wave and retain duty-feasibility outputs for scheduling.
5. Chain trips into bus/driver schedules with buffer rules and overtime-first logic.
6. Assign passengers, validate constraints, and surface infeasible or unserved demand explicitly.
7. Compare KPIs against current and `final_schedule_v11`.

## 6) Extensions (Phase 2+)
- Light ML demand forecasting for better peak estimates.
- Heuristic accelerators (GA, tabu search) for large-scale days.
- GNN or attention models for route proposal only (not core optimization).
- RL for disruption handling in real-time operations.

## Final Recommendation
Use a hybrid, constraint-first solution:

Demand Estimation -> Capacity-Aware Clustering -> VRPTW Routing
-> Bus and Driver Scheduling -> Passenger Assignment -> KPI Evaluation

This approach matches the data and constraints in `context.md`, directly targets overtime reduction while protecting coverage feasibility, and remains practical to implement with the current datasets.
