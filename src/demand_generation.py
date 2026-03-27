from __future__ import annotations

from datetime import timedelta

import pandas as pd

from preprocessing import GeoPoint, WAVE_BUCKET_MIN, excel_serial_to_timestamp, normalize_name, to_minutes


def extract_shift_events(
    shift_workbook: dict[str, pd.DataFrame],
    strict_lookup: dict[str, GeoPoint],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    event_rows: list[dict[str, object]] = []
    unmatched_rows: list[dict[str, object]] = []

    for sheet_name, raw in shift_workbook.items():
        if raw.empty or len(raw) < 4:
            continue
        date_row = raw.iloc[1].tolist()
        header_row = raw.iloc[2].tolist()
        body = raw.iloc[3:].copy()
        body.columns = header_row

        for row_idx, row in body.iterrows():
            store_name = "" if pd.isna(row.get("Store Name")) else str(row.get("Store Name")).strip()
            store_id = pd.to_numeric(row.get("Store ID"), errors="coerce")
            if not store_name:
                continue

            norm_name = normalize_name(store_name)
            point = strict_lookup.get(norm_name)
            employee_code = str(row.get("EMPLOYEE CODE", row_idx)).strip()
            if point is None or pd.isna(store_id) or int(store_id) != point.store_id:
                unmatched_rows.append(
                    {
                        "source_dataset": "Employee Shift data.xlsx",
                        "source_sheet": sheet_name,
                        "source_column": "Store Name",
                        "origin_id": employee_code,
                        "store_name": store_name,
                        "normalized_store_name": norm_name,
                        "source_store_id": "" if pd.isna(store_id) else int(store_id),
                        "reason": "no_strict_name_id_match",
                    }
                )
                continue

            for start_col in range(8, len(header_row), 4):
                if start_col + 3 >= len(header_row):
                    break
                base_date = date_row[start_col]
                if pd.isna(base_date):
                    continue
                base_date = excel_serial_to_timestamp(base_date)
                for shift_slot, start_idx, end_idx in ((1, start_col, start_col + 1), (2, start_col + 2, start_col + 3)):
                    start_min = to_minutes(row.iloc[start_idx])
                    end_min = to_minutes(row.iloc[end_idx])
                    if start_min is None or end_min is None:
                        continue
                    shift_start = base_date + timedelta(minutes=start_min)
                    shift_end = base_date + timedelta(minutes=end_min)
                    if end_min < start_min:
                        shift_end += timedelta(days=1)

                    common = {
                        "employee_code": employee_code,
                        "store_id": point.store_id,
                        "store_name": point.store_name,
                        "latitude": point.latitude,
                        "longitude": point.longitude,
                        "shift_slot": shift_slot,
                    }
                    event_rows.append(
                        {
                            **common,
                            "direction": "IN",
                            "event_dt": shift_start,
                            "event_date": shift_start.date().isoformat(),
                        }
                    )
                    event_rows.append(
                        {
                            **common,
                            "direction": "OUT",
                            "event_dt": shift_end,
                            "event_date": shift_end.date().isoformat(),
                        }
                    )

    return pd.DataFrame(event_rows), pd.DataFrame(unmatched_rows)


def aggregate_store_waves(events: pd.DataFrame, stores_with_clusters: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(
            columns=[
                "event_date",
                "direction",
                "wave_dt",
                "store_id",
                "store_name",
                "latitude",
                "longitude",
                "cluster_id",
                "employees",
                "wave_label",
            ]
        )
    demand = events.merge(stores_with_clusters[["store_id", "cluster_id"]], on="store_id", how="left")
    demand["wave_dt"] = demand["event_dt"].dt.floor(f"{WAVE_BUCKET_MIN}min")
    grouped = (
        demand.groupby(
            ["event_date", "direction", "wave_dt", "store_id", "store_name", "latitude", "longitude", "cluster_id"],
            dropna=False,
        )
        .size()
        .reset_index(name="employees")
    )
    grouped["wave_label"] = grouped["wave_dt"].dt.strftime("%Y-%m-%d %H:%M")
    return grouped.sort_values(["wave_dt", "direction", "store_name"]).reset_index(drop=True)
