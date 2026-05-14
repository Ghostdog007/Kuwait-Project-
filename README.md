# Kuwait Pilot Employee Transportation Optimization

Demand-driven employee shuttle optimization for Kuwait pilot operations.

The prototype builds and schedules employee transport trips under a hard 13-bus cap, then exports employer-facing daily schedules in the exact trip representation requested by operations (`Drive #` + `Trip ID` as `D1/T1`, `D1/T2`, ...).

---

## 🚀 Quick Start (Tester / Examiner)

If you are here to examine the project, please start with:
👉 **[WALKTHROUGH.md](WALKTHROUGH.md)**

It contains step-by-step instructions on how to run the pipeline, examine the logic, and use the interactive map visualizer.

---

## 📂 Project Structure

```
Kuwait Project/
├── prototype/              # Core implementation pipeline
│   ├── run_pilot.py        # Main optimization script
│   ├── export_map_data.py  # Map visualization data exporter
│   └── output/             # Generated schedules and reports
├── docs/                   # Documentation & References
│   ├── context.md          # Problem constraints & policy
│   ├── approach.md         # Implementation strategy
│   ├── data_dictionary/    # Column-level data descriptions
│   └── references/         # Background PDFs & Research
├── datasets/               # Input Excel files (Source of Truth)
└── archive/                # Historical/Stale files (Preserved)
```

## 🛠️ How To Run

1. **Setup Environment**:
   ```powershell
   # Create a .env in prototype/ folder (see .env.example)
   # Enter your Google Maps API key (optional for map viewer)
   ```

2. **Run Pipeline**:
   ```powershell
   python prototype/run_pilot.py
   ```
   This rebuilds routing+scheduling outputs and refreshes the KPI summaries.

3. **Visualize Results**:
   ```powershell
   # Generate map JSON
   python prototype/export_map_data.py
   
   # Serve and view
   python -m http.server 8090 --directory prototype/output
   # Navigate to http://localhost:8090/trip_map.html
   ```

## 📊 Output Contract

After each run, key outputs are maintained in `prototype/output/`:
1. `kpi_summary.csv`: Fleet utilization and coverage metrics.
2. `unscheduled_trips.csv`: Trips rejected due to constraints.
3. `employer_format/`: Professional-grade Excel schedules for operations.
4. `trip_map.html`: Interactive route visualization.

---

## 📖 Navigation

- **Problem Context**: [docs/context.md](docs/context.md)
- **Technical Approach**: [docs/approach.md](docs/approach.md)
- **Data Guide**: [docs/data_dictionary/](docs/data_dictionary/)
- **Core Engine**: [prototype/run_pilot.py](prototype/run_pilot.py)
