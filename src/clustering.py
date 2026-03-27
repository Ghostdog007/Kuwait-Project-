from __future__ import annotations

import math

import pandas as pd
from sklearn.cluster import KMeans

from preprocessing import BUS_CAPACITY, PEAK_BIN_MIN


def cluster_stores(events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if events.empty:
        return (
            pd.DataFrame(columns=["store_id", "store_name", "latitude", "longitude", "weekly_employee_events", "cluster_id"]),
            pd.DataFrame(columns=["cluster_id", "store_count", "weekly_employee_events"]),
        )

    stores = (
        events.groupby(["store_id", "store_name", "latitude", "longitude"], dropna=False)
        .size()
        .reset_index(name="weekly_employee_events")
    )
    cluster_count = max(1, min(len(stores), math.ceil(len(stores) / 14)))
    model = KMeans(n_clusters=cluster_count, random_state=42, n_init=10)
    stores["cluster_id"] = model.fit_predict(
        stores[["latitude", "longitude"]],
        sample_weight=stores["weekly_employee_events"],
    )
    summary = (
        stores.groupby("cluster_id")
        .agg(store_count=("store_name", "count"), weekly_employee_events=("weekly_employee_events", "sum"))
        .reset_index()
    )
    return stores, summary


def build_peak_pressure(demand: pd.DataFrame) -> pd.DataFrame:
    if demand.empty:
        return pd.DataFrame(columns=["peak_bin_dt", "direction", "employees", "theoretical_buses"])
    bins = demand.copy()
    bins["peak_bin_dt"] = bins["wave_dt"].dt.floor(f"{PEAK_BIN_MIN}min")
    summary = bins.groupby(["peak_bin_dt", "direction"], dropna=False)["employees"].sum().reset_index()
    summary["theoretical_buses"] = summary["employees"].apply(lambda value: math.ceil(value / BUS_CAPACITY))
    return summary
