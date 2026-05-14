"""Export pipeline schedule data to JSON for the interactive trip map viewer.

Reads:
    - prototype/output/employer_format/trips_per_day.xlsx
    - prototype/output/employer_format/employee_to_bus_mapping_per_day.xlsx
    - datasets/Geocoordinates.xlsx
    - datasets/Employee Shift data.xlsx

Writes:
    - prototype/output/map_data.json
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[1]
DATASETS_DIR = BASE_DIR / "datasets"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
EMPLOYER_DIR = OUTPUT_DIR / "employer_format"

TRIPS_FILE = EMPLOYER_DIR / "trips_per_day.xlsx"
MAPPING_FILE = EMPLOYER_DIR / "employee_to_bus_mapping_per_day.xlsx"
GEO_FILE = DATASETS_DIR / "Geocoordinates.xlsx"
SHIFT_FILE = DATASETS_DIR / "Employee Shift data.xlsx"

DEPOT_NAME = "Mahboula Complex - Mix"


def load_geocoordinates() -> dict[int, dict]:
    """Load store geocoordinates keyed by Store ID."""
    geo = pd.read_excel(GEO_FILE)
    geo["Store ID"] = pd.to_numeric(geo["Store ID"], errors="coerce")
    geo["latitude"] = pd.to_numeric(geo["latitude"], errors="coerce")
    geo["longitude"] = pd.to_numeric(geo["longitude"], errors="coerce")
    geo = geo.dropna(subset=["Store Name", "Store ID", "latitude", "longitude"]).copy()
    lookup: dict[int, dict] = {}
    for _, row in geo.iterrows():
        sid = int(row["Store ID"])
        lookup[sid] = {
            "name": str(row["Store Name"]).strip(),
            "lat": float(row["latitude"]),
            "lng": float(row["longitude"]),
        }
    # Also add by name for depot lookup
    for _, row in geo.iterrows():
        name = str(row["Store Name"]).strip()
        if name == DEPOT_NAME:
            lookup["__depot__"] = {
                "name": name,
                "lat": float(row["latitude"]),
                "lng": float(row["longitude"]),
            }
    return lookup


def load_employee_names() -> dict[str, str]:
    """Build employee_code -> employee_name mapping from shift data."""
    workbook = pd.ExcelFile(SHIFT_FILE)
    names: dict[str, str] = {}
    for sheet in workbook.sheet_names:
        raw = workbook.parse(sheet, header=None)
        if raw.shape[0] < 4:
            continue
        header = raw.iloc[2].tolist()
        body = raw.iloc[3:].copy()
        body.columns = header
        if "EMPLOYEE CODE" not in body.columns or "EMPLOYEE NAME" not in body.columns:
            continue
        subset = body[["EMPLOYEE CODE", "EMPLOYEE NAME"]].dropna(subset=["EMPLOYEE CODE"])
        for _, row in subset.iterrows():
            code = str(row["EMPLOYEE CODE"]).strip()
            name = str(row["EMPLOYEE NAME"]).strip() if pd.notna(row["EMPLOYEE NAME"]) else ""
            if code and name and code not in names:
                names[code] = name
    return names


def parse_trips_sheet(df: pd.DataFrame, day: str, geo: dict[int, dict]) -> list[dict]:
    """Parse a single day's trips_per_day sheet into structured trip objects."""
    trips: list[dict] = []
    current_trip: dict | None = None

    for _, row in df.iterrows():
        event = str(row.get("Event", "")).strip()
        drive = str(row.get("Drive #", "")).strip()
        trip_id = str(row.get("Trip ID", "")).strip()

        if event == "Trip Start":
            current_trip = {
                "day": day,
                "drive": drive,
                "tripId": trip_id,
                "type": "IN",  # will be determined later
                "tripStart": str(row.get("Trip Start", "")).strip(),
                "tripEnd": str(row.get("Trip End", "")).strip(),
                "stops": [],
                "employees": [],
                "employeeCount": 0,
            }
        elif event == "Stop" and current_trip is not None:
            store_id = row.get("Store ID")
            store_id_int = int(store_id) if pd.notna(store_id) else None
            store_name = str(row.get("Store Name", "")).strip()
            pax = int(row.get("Passenger Count", 0)) if pd.notna(row.get("Passenger Count")) else 0
            sched_time = str(row.get("Time", "")).strip()

            # Get coordinates from geocoordinates
            geo_info = geo.get(store_id_int, {}) if store_id_int else {}
            current_trip["stops"].append({
                "storeId": str(store_id_int) if store_id_int else "",
                "name": store_name or geo_info.get("name", "Unknown"),
                "lat": geo_info.get("lat"),
                "lng": geo_info.get("lng"),
                "passengerCount": pax,
                "scheduledTime": sched_time,
            })
        elif event == "Trip End" and current_trip is not None:
            # Only keep trips that have at least one stop with coordinates
            valid_stops = [s for s in current_trip["stops"] if s.get("lat") and s.get("lng")]
            if valid_stops:
                current_trip["stops"] = valid_stops
                trips.append(current_trip)
            current_trip = None

    return trips


def infer_trip_type(trips: list[dict]) -> None:
    """Infer trip type (IN/OUT/MIXED) from timing patterns.

    Heuristic: if scheduled stop times are before the trip midpoint → IN,
    if after → OUT. If mixed pattern → MIXED.
    The employer trip file does not carry a type column, but the original
    pipeline schedule does.  We use a simple time heuristic here.
    """

    def time_to_minutes(t: str) -> int | None:
        t = t.strip().upper()
        for fmt in ("%I:%M %p", "%H:%M"):
            try:
                from datetime import datetime
                parsed = datetime.strptime(t, fmt)
                return parsed.hour * 60 + parsed.minute
            except ValueError:
                continue
        return None

    for trip in trips:
        start_min = time_to_minutes(trip["tripStart"])
        end_min = time_to_minutes(trip["tripEnd"])
        if start_min is None or end_min is None:
            trip["type"] = "IN"
            continue

        # Handle overnight trips
        if end_min < start_min:
            end_min += 24 * 60

        # Check stop times relative to trip window
        stop_times = [time_to_minutes(s["scheduledTime"]) for s in trip["stops"]]
        stop_times = [t for t in stop_times if t is not None]
        if not stop_times:
            trip["type"] = "IN"
            continue

        # Adjust overnight stop times
        stop_times = [t + 24 * 60 if t < start_min else t for t in stop_times]

        mid = (start_min + end_min) / 2
        before_mid = sum(1 for t in stop_times if t <= mid)
        after_mid = sum(1 for t in stop_times if t > mid)

        if before_mid > 0 and after_mid > 0:
            trip["type"] = "MIXED"
        elif before_mid > after_mid:
            trip["type"] = "IN"
        else:
            trip["type"] = "OUT"


def attach_employees(trips: list[dict], mapping_sheets: dict[str, pd.DataFrame], employee_names: dict[str, str]) -> None:
    """Attach employee codes and names to trips from the bus mapping data."""
    for day, df in mapping_sheets.items():
        day_trips = [t for t in trips if t["day"] == day]
        for _, row in df.iterrows():
            drive = str(row.get("Drive #", "")).strip()
            trip_id = str(row.get("Trip ID", "")).strip()
            employees_str = str(row.get("Employees", "")).strip()
            employee_count = int(row.get("Employee Count", 0)) if pd.notna(row.get("Employee Count")) else 0

            # Find matching trip
            for trip in day_trips:
                if trip["drive"] == drive and trip["tripId"] == trip_id:
                    codes = [c.strip() for c in employees_str.split(",") if c.strip() and not c.strip().startswith("UNMAPPED")]
                    trip["employees"] = [
                        {"code": c, "name": employee_names.get(c, "")}
                        for c in codes
                    ]
                    trip["employeeCount"] = employee_count
                    break


def load_api_key() -> str:
    """Read GMAPS_API_KEY from prototype/.env file."""
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        print(f"Warning: {env_path} not found. Create it with GMAPS_API_KEY=your_key")
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == "GMAPS_API_KEY":
            return value.strip()
    return ""


def build_index(trips: list[dict]) -> dict:
    """Build a day -> drives -> trips index for the cascading selector."""
    index: dict[str, dict[str, list[str]]] = {}
    for trip in trips:
        day = trip["day"]
        drive = trip["drive"]
        trip_id = trip["tripId"]
        if day not in index:
            index[day] = {}
        if drive not in index[day]:
            index[day][drive] = []
        if trip_id not in index[day][drive]:
            index[day][drive].append(trip_id)
    # Sort drives and trips naturally
    for day in index:
        sorted_drives: dict[str, list[str]] = {}
        for drive in sorted(index[day], key=lambda d: int(d[1:]) if d[1:].isdigit() else 0):
            sorted_drives[drive] = sorted(index[day][drive], key=lambda t: int(t[1:]) if t[1:].isdigit() else 0)
        index[day] = sorted_drives
    return index


def main() -> None:
    print("Loading geocoordinates...")
    geo = load_geocoordinates()

    print("Loading employee names...")
    employee_names = load_employee_names()

    print("Loading trips_per_day.xlsx...")
    trips_sheets = pd.read_excel(TRIPS_FILE, sheet_name=None)

    print("Loading employee_to_bus_mapping_per_day.xlsx...")
    mapping_sheets = pd.read_excel(MAPPING_FILE, sheet_name=None)

    # Get depot location
    depot_info = geo.get("__depot__", {"name": DEPOT_NAME, "lat": 29.146545, "lng": 48.118341})

    # Build store lookup for JSON (keyed by string store ID)
    stores: dict[str, dict] = {}
    for sid, info in geo.items():
        if sid == "__depot__":
            continue
        stores[str(sid)] = info

    # Parse all trips
    all_trips: list[dict] = []
    days: list[str] = sorted(trips_sheets.keys())
    for day in days:
        day_trips = parse_trips_sheet(trips_sheets[day], day, geo)
        all_trips.extend(day_trips)

    print(f"Parsed {len(all_trips)} trips across {len(days)} days")

    # Infer trip types
    infer_trip_type(all_trips)

    # Attach employees
    attach_employees(all_trips, mapping_sheets, employee_names)

    # Build cascading index
    index = build_index(all_trips)

    # Build output
    output = {
        "depot": depot_info,
        "stores": stores,
        "days": days,
        "index": index,
        "totalTrips": len(all_trips),
        "trips": all_trips,
    }

    output_path = OUTPUT_DIR / "map_data.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # Write API key config
    api_key = load_api_key()
    config_path = OUTPUT_DIR / "map_config.js"
    config_path.write_text(
        f'// Auto-generated by export_map_data.py - do not edit manually\n'
        f'window.GMAPS_API_KEY = "{api_key}";\n',
        encoding="utf-8",
    )

    print(f"Exported {len(all_trips)} trips to {output_path}")
    print(f"Config written to {config_path}")
    if api_key and api_key != "YOUR_API_KEY_HERE":
        print(f"API key loaded from .env (starts with {api_key[:8]}...)")
    else:
        print("Warning: No valid API key found. Edit prototype/.env and re-run.")
    print(f"Days: {days}")
    print(f"Stores with coordinates: {len(stores)}")
    print(f"Employee names resolved: {len(employee_names)}")


if __name__ == "__main__":
    main()

