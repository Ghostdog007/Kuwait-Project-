from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
SCRIPTS_DIR = BACKEND_DIR / "scripts"
OUTPUT_DIR = REPO_ROOT / "prototype" / "output"

app = FastAPI(title="Kuwait Transport Prototype")


def _run_script(script_name: str) -> str:
    script_path = SCRIPTS_DIR / script_name
    if not script_path.exists():
        raise HTTPException(status_code=404, detail=f"Missing script: {script_name}")
    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"{script_name} failed:\n{result.stderr.strip() or result.stdout.strip()}",
        )
    return result.stdout.strip()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/run")
def run_pipeline() -> dict[str, str]:
    output = _run_script("run_pilot.py")
    return {"message": output}


@app.post("/export")
def export_map_data() -> dict[str, str]:
    output = _run_script("export_map_data.py")
    return {"message": output}


@app.get("/")
def home() -> FileResponse:
    index = OUTPUT_DIR / "trip_map.html"
    if not index.exists():
        raise HTTPException(
            status_code=404,
            detail="trip_map.html not found. Run /run and /export first.",
        )
    return FileResponse(index)


app.mount("/", StaticFiles(directory=str(OUTPUT_DIR), html=True), name="static-output")
