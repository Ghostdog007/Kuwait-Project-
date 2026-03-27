from __future__ import annotations

import pandas as pd

from preprocessing import HARD_DUTY_SPAN_MIN, TARGET_DUTY_MIN


def build_duties(assignments: pd.DataFrame) -> pd.DataFrame:
    if assignments.empty:
        return pd.DataFrame(
            columns=[
                "duty_id",
                "bus_id",
                "service_date",
                "rotation_tag",
                "first_trip_start_dt",
                "last_trip_end_dt",
                "trip_count",
                "trip_minutes",
                "avg_occupancy_pct",
                "rescued_trip_count",
                "handover_trip_count",
                "duty_span_min",
                "overtime_min",
                "over_10h_flag",
            ]
        )

    duty_rows: list[dict[str, object]] = []
    duty_counter = 1
    for (service_day, bus_id, rotation_tag), group in assignments.groupby(
        ["service_date", "bus_id", "rotation_tag"],
        dropna=False,
    ):
        group = group.sort_values("planned_start_dt")
        first_start = pd.Timestamp(group["planned_start_dt"].min())
        last_end = pd.Timestamp(group["planned_end_dt"].max())
        duty_rows.append(
            {
                "duty_id": f"DUTY_{duty_counter:04d}",
                "bus_id": bus_id,
                "service_date": service_day,
                "rotation_tag": rotation_tag,
                "first_trip_start_dt": first_start,
                "last_trip_end_dt": last_end,
                "trip_count": int(len(group)),
                "trip_minutes": float(group["trip_duration_min"].sum()),
                "avg_occupancy_pct": float(group["occupancy_pct"].mean()),
                "rescued_trip_count": int(group["rescued_by_delay"].sum()),
                "handover_trip_count": int(group["handover_flag"].sum()),
            }
        )
        duty_counter += 1

    duties = pd.DataFrame(duty_rows).sort_values(["first_trip_start_dt", "bus_id"]).reset_index(drop=True)
    duties["duty_span_min"] = (
        pd.to_datetime(duties["last_trip_end_dt"]) - pd.to_datetime(duties["first_trip_start_dt"])
    ).dt.total_seconds() / 60.0
    duties["overtime_min"] = (duties["duty_span_min"] - TARGET_DUTY_MIN).clip(lower=0)
    duties["over_10h_flag"] = duties["duty_span_min"] > HARD_DUTY_SPAN_MIN
    return duties
