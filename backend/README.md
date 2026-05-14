# Backend

Python backend and pipeline scripts (Railway-ready).

Structure:
- `app/app.py` FastAPI entrypoint
- `scripts/run_pilot.py` optimizer pipeline
- `scripts/export_map_data.py` wrapper exporter
- `requirements.txt`

Run locally from repo root:

```powershell
pip install -r backend/requirements.txt
uvicorn backend.app.app:app --host 0.0.0.0 --port 8000
```
