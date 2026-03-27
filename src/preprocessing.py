from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
import re

import pandas as pd

from data_loader import load_workbook_sheets_raw, read_xlsx_sheet_raw


DEPOT_NAME = "Mahboula Complex - Mix"
BUS_COUNT = 13
BUS_CAPACITY = 22
BUFFER_MIN = 30
TARGET_DUTY_MIN = 9 * 60
HARD_DUTY_SPAN_MIN = 10 * 60
EVENING_SEED_HOUR = 14
MAX_STOPS_PER_TRIP = 6
MAX_TRIP_DURATION_MIN = 300
WAVE_BUCKET_MIN = 30
PEAK_BIN_MIN = 15
AVG_SPEED_KMPH = 38.0
ROAD_FACTOR = 1.18
STOP_DWELL_MIN = 5
IN_EARLY_LIMIT_MIN = 30
IN_TARGET_LEAD_MIN = 15
OUT_WAIT_LIMIT_MIN = 40
MIXED_MAX_WAIT_MIN = 20
MIXED_MAX_ATTACH_MIN = 60
MIXED_MAX_DETOUR_KM = 6.0
REPAIR_SHIFT_OPTIONS_OUT = [10, 20, 30, 40]
REPAIR_SHIFT_OPTIONS_IN = [-15, 15, -30, 30]


@dataclass(frozen=True)
class GeoPoint:
    store_name: str
    store_id: int
    latitude: float
    longitude: float


def normalize_name(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip().casefold().replace("&", "and")
    text = re.sub(r"[()]", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def to_minutes(value: object) -> int | None:
    if pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime, time)):
        return value.hour * 60 + value.minute
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric < 0:
            return None
        fraction = numeric - int(numeric)
        total = round(fraction * 24 * 60) if numeric >= 1 else round(numeric * 24 * 60)
        return 0 if total == 1440 else total
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    for fmt in ("%H:%M:%S", "%I:%M %p", "%H:%M"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.hour * 60 + parsed.minute
        except ValueError:
            continue
    return None


def parse_duration_hours(value: object) -> float | None:
    if pd.isna(value):
        return None
    text = str(value).strip().lower().replace("hrs", "").replace("hr", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def excel_serial_to_timestamp(value: object) -> pd.Timestamp:
    if isinstance(value, pd.Timestamp):
        return value.normalize()
    if isinstance(value, datetime):
        return pd.Timestamp(value).normalize()
    numeric = float(value)
    return pd.Timestamp(datetime(1899, 12, 30) + pd.to_timedelta(numeric, unit="D")).normalize()


def load_overview_metrics(path: Path) -> dict[str, object]:
    details = read_xlsx_sheet_raw(path, "Details")
    pilot = details.iloc[:, 4:7].copy()
    pilot.columns = ["parameter", "value", "description"]
    pilot = pilot.iloc[1:].copy()
    pilot["parameter"] = pilot["parameter"].astype(str).str.strip()
    pilot = pilot[pilot["parameter"].ne("") & pilot["parameter"].ne("nan")]
    return {str(row["parameter"]): row["value"] for _, row in pilot.iterrows()}


def load_geocoordinates(path: Path) -> dict[str, GeoPoint]:
    sheets = load_workbook_sheets_raw(path)
    if not sheets:
        return {}
    geo = next(iter(sheets.values())).copy()
    geo.columns = geo.iloc[0]
    geo = geo.iloc[1:].copy()
    geo["Store ID"] = pd.to_numeric(geo["Store ID"], errors="coerce")
    geo["latitude"] = pd.to_numeric(geo["latitude"], errors="coerce")
    geo["longitude"] = pd.to_numeric(geo["longitude"], errors="coerce")
    geo = geo.dropna(subset=["Store Name", "Store ID", "latitude", "longitude"]).copy()

    lookup: dict[str, GeoPoint] = {}
    for _, row in geo.iterrows():
        point = GeoPoint(
            store_name=str(row["Store Name"]).strip(),
            store_id=int(row["Store ID"]),
            latitude=float(row["latitude"]),
            longitude=float(row["longitude"]),
        )
        lookup[normalize_name(point.store_name)] = point
    return lookup


def load_shift_workbook(path: Path) -> dict[str, pd.DataFrame]:
    return load_workbook_sheets_raw(path)


def build_strict_lookup(
    geo_lookup: dict[str, GeoPoint],
    shift_workbook: dict[str, pd.DataFrame],
) -> tuple[dict[str, GeoPoint], pd.DataFrame]:
    rows: list[dict[str, object]] = []
    for raw in shift_workbook.values():
        if raw.empty or len(raw) < 4:
            continue
        header = raw.iloc[2].tolist()
        body = raw.iloc[3:].copy()
        body.columns = header
        if "Store ID" not in body.columns or "Store Name" not in body.columns:
            continue
        tmp = body[["Store ID", "Store Name"]].dropna(subset=["Store ID", "Store Name"]).copy()
        tmp["Store ID"] = pd.to_numeric(tmp["Store ID"], errors="coerce")
        tmp = tmp.dropna(subset=["Store ID"]).copy()
        tmp["Store ID"] = tmp["Store ID"].astype(int)
        tmp["Store Name"] = tmp["Store Name"].astype(str).str.strip()
        tmp["norm_name"] = tmp["Store Name"].map(normalize_name)
        rows.extend(tmp.to_dict(orient="records"))

    shift_rows = pd.DataFrame(rows)
    grouped = (
        shift_rows.groupby("norm_name")
        .agg(
            shift_ids=("Store ID", lambda values: sorted(set(int(value) for value in values))),
            shift_names=("Store Name", lambda values: sorted(set(str(value) for value in values))),
        )
        .reset_index()
    )

    strict_lookup: dict[str, GeoPoint] = {}
    output_rows: list[dict[str, object]] = []
    for norm_name, point in geo_lookup.items():
        match = grouped[grouped["norm_name"] == norm_name]
        shift_ids = match["shift_ids"].iloc[0] if not match.empty else None
        strict_match = isinstance(shift_ids, list) and len(shift_ids) == 1 and shift_ids[0] == point.store_id
        output_rows.append(
            {
                "normalized_store_name": norm_name,
                "geo_store_name": point.store_name,
                "geo_store_id": point.store_id,
                "shift_store_names": None if match.empty else match["shift_names"].iloc[0],
                "shift_ids": shift_ids,
                "strict_match": strict_match,
            }
        )
        if strict_match:
            strict_lookup[norm_name] = point

    return strict_lookup, pd.DataFrame(output_rows)
