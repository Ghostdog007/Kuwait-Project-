# Tester & Examiner Walkthrough

This guide provides a step-by-step path to examine the **Kuwait Employee Transport Optimization** project.

---

## 1. Project Context
The goal is to optimize the transportation of hundreds of employees across 80+ stores in Kuwait using a limited fleet of **13 buses**. The system must handle:
- **Shift Timing**: Picking up employees for work (IN) and taking them home (OUT).
- **Hard Constraints**: 10-hour duty limits, 13-bus concurrency, and 14-seat bus capacity.
- **Employer Format**: Outputting schedules in the standard operational format (`D1/T1` naming).

---

## 2. Examination Path

### Step A: Understand the Constraints
Read **[docs/context.md](docs/context.md)**.
Focus on:
- The "Hard Operational Constraints" section.
- The "Priority Order" (Coverage first, then Overtime).

### Step B: Run the Pipeline
Execute the core solver:
```powershell
python prototype/run_pilot.py
```
**What to look for**:
- The console will show "Wave" processing (batching trips by time).
- It will summarize how many trips were successfully scheduled vs. rejected.
- Final outputs will appear in `prototype/output/`.

### Step C: Examine the Outputs
1. **KPI Summary**: Open `prototype/output/kpi_summary.csv`. Look at the `Utilization` and `Coverage` columns.
2. **Operational Schedule**: Open `prototype/output/employer_format/trips_per_day.xlsx`. This is what the bus drivers and dispatchers actually use.

### Step D: Interactive Map Visualization
This is the most powerful way to see the results.
1. **Ensure you have a Google Maps API Key** (optional, but recommended for road routes).
2. **Export data**: `python prototype/export_map_data.py`.
3. **Start a local server**: `python -m http.server 8090 --directory prototype/output`.
4. **Open in Browser**: `http://localhost:8090/trip_map.html`.
5. **Use the Selector**: Pick a Day -> Pick a Drive (D1-D13) -> Pick a Trip (T1-T4).
6. **Verify**: Click on stops to see employee names and scheduled vs. predicted times.

---

## 3. Core Logic Deep-Dive
If you want to review the code logic, open **[prototype/run_pilot.py](prototype/run_pilot.py)** and search for these key functions:
- `solve_wave_routes_ortools`: How routes are optimized using Google OR-Tools.
- `slot_is_feasible`: How duty timing and legality are checked.
- `apply_assignment`: How the system handles split duties and duty breaks.

---

## 4. Data Reference
- Raw input data is in **[datasets/](datasets/)**.
- Detailed explanations of each dataset's columns are in **[docs/data_dictionary/](docs/data_dictionary/)**.
- Supporting research and meeting minutes are in **[docs/references/](docs/references/)**.
