# Data Folder

This folder is the optional local data location for the new daily prototype in `Kuwait-Project-Aditya/`.

## What Was Implemented

A completely new prototype was built in:

- `Kuwait-Project-Aditya/src/`

It reimplements the logic of the existing weekly prototype in `prototype/run_pilot.py`, but changes the planning horizon to **daily processing**.

The new runner is:

- `Kuwait-Project-Aditya/src/run_daily.py`

It performs the following workflow:

1. Load the source Excel datasets
2. Build strict store matching
3. Generate weekly employee shift events
4. Build weekly store clusters once using weighted KMeans
5. Identify service dates
6. For each date, run:
   - daily demand generation
   - 30-minute wave aggregation
   - greedy trip construction
   - mixed-trip merge
   - bus assignment with morning/evening slots
   - duty calculation
   - daily KPI calculation
7. Save date-specific outputs to `Kuwait-Project-Aditya/outputs/`


## Dataset Discovery Logic

The daily prototype currently looks for the required Excel files in this order:

1. `Kuwait-Project-Aditya/data/`
2. `../Dataset_aditya/`
3. `../datasets/`

So the implementation works even if this folder is empty, as long as the files are available in one of the fallback locations.

## Notes

- The existing `prototype/` folder was not modified.
- The original weekly outputs were not changed.
- The new prototype uses the same core constraints and heuristics as the original implementation.
- Outputs produced by the new prototype are written to `Kuwait-Project-Aditya/outputs/`.

## Run Command

From inside `Kuwait-Project-Aditya/`, run:

```bash
python src/run_daily.py
```
