# Context: Kuwait Employee Transportation Optimization

This document consolidates the current understanding of the problem, data, and constraints. It is optimized to support the integrated approach in `Approaches/approach.md`.

## Problem Summary
- Employees live in accommodation and must be transported to and from stores on fixed shift windows.
- The system is schedule-driven (metro-like): buses run trips and employees are assigned to trips.
- Current routes are relatively fixed while demand and staffing vary.
- Pain point: high driver overtime and idle/deadhead time.
- Goal: build a constraint-first optimization pipeline for demand, routing, scheduling, and assignment.

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
- Trip templates and optimized routes per time window.
- Bus and driver schedules (including buffers and split shifts).
- Employee-to-trip assignment tables.
- KPI comparison: overtime, occupancy, deadhead, waiting time, on-time compliance.

## Known Constraints and Notes
- Accommodation is the start/end anchor for the system.
- Trips are sequences of store stops; routes are grouped by trip ID.
- Overtime reported around 13 hours per driver in current system.
- Capacity and fleet size constraints must be respected.
- Scheduling must align with store shift times.
- Confirmed: 13 buses.
- Confirmed: single start location (employee accommodation). Each trip starts at this location, visits assigned stores, then returns to the start to complete the trip.
- Buffer time between successive trips for each bus: 30-45 minutes to allow for delays (hard constraint).
- Vehicle type: single type only, 22-seat capacity (can go up to 25 if crowded, never above 25).
- Trip duration target: average 2.5 hours per trip.
- Driver total driving hours: ideally 9 hours per day, with acceptable range 8-10 hours.
- Broken shifts allowed: a 9-hour workday can be split into a 4-hour shift and a 5-hour shift, with separate pickup/drop trips.
- Max waiting time: 30-40 minutes (upper bound), to reduce overtime risk.
- Employees should arrive at pickup no earlier than 30 minutes before the scheduled bus trip (to avoid excessive waiting).

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

## Open Questions / Gaps
- Confirm which week/brand tabs are in scope for modeling (pilot vs. full market).
- Validate shift data header structure and normalize wide format into long format.
- Resolve data quality issues in itinerary timing and route logs.

## Next Step (Approach-Ready)
This section is aligned with `Approaches/approach.md` (Section 5: Recommended Starting Point).
1. Normalize datasets into a unified schema (employees, stores, shifts, trips, itineraries).
2. Build demand tables by store and shift window (inbound/outbound).
3. Run capacity-aware clustering using geocoordinates plus time-window compatibility.
4. Solve VRPTW per cluster/time wave, then chain trips into driver schedules with buffers.
5. Assign employees to trips and validate constraints, then compute KPIs.

## Working Notes
- Visualize geocoordinates on a map to identify spatial clusters (e.g., south/central/north).
- Use inter-cluster travel time as a key driver for route structuring.
- Prospective idea: allow opportunistic pickups on return to accommodation if an employee's shift ends near the route after completing store stops.
- Note: clustering alone is insufficient due to fixed bus capacity and scheduling constraints.

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
