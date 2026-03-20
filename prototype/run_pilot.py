import math
import random
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "datasets"
SHIFT_DATA_PATH = DATA_DIR / "Employee Shift data.xlsx"
OUT_DIR = Path(__file__).resolve().parent / "output"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CAPACITY = 25
SPEED_KMPH = 40.0
DWELL_MIN_PER_STOP = 5
MAX_CLUSTER_TRIPS = 2  # allow clusters sized for roughly 2 busloads per window
MAX_K_PER_WINDOW = 6
KMEANS_ITERS = 12
RANDOM_SEED = 42


def normalize_name(val: str) -> str:
    if pd.isna(val):
        return ""
    return " ".join(str(val).strip().lower().split())


def parse_time(val):
    if pd.isna(val):
        return None
    if isinstance(val, pd.Timestamp):
        return val
    if hasattr(val, "hour") and hasattr(val, "minute"):
        return pd.Timestamp(2000, 1, 1, val.hour, val.minute)
    text = str(val).strip()
    if ":" in text:
        parsed = pd.to_datetime(text, format="%I:%M %p", errors="coerce")
    else:
        parsed = pd.to_datetime(text, format="%I%p", errors="coerce")
    if pd.isna(parsed):
        parsed = pd.to_datetime(text, errors="coerce")
    return parsed


def time_to_minutes(ts):
    return ts.hour * 60 + ts.minute


def minutes_to_time_str(minutes):
    minutes = int(round(minutes)) % (24 * 60)
    hour = minutes // 60
    minute = minutes % 60
    return pd.Timestamp(2000, 1, 1, hour, minute).strftime("%I:%M %p")


def duration_minutes(start, end):
    if end < start:
        end = end + pd.Timedelta(days=1)
    return int((end - start).total_seconds() // 60)


def time_to_str(val):
    if pd.isna(val):
        return None
    if isinstance(val, pd.Timestamp):
        return val.strftime("%I:%M %p")
    if hasattr(val, "hour") and hasattr(val, "minute"):
        return pd.Timestamp(2000, 1, 1, val.hour, val.minute).strftime("%I:%M %p")
    return str(val)


def load_shift_data_weekly():
    xl = pd.ExcelFile(SHIFT_DATA_PATH)
    rows = []
    for sheet in xl.sheet_names:
        df = pd.read_excel(SHIFT_DATA_PATH, sheet_name=sheet, header=None)
        if df.shape[0] < 4:
            continue

        header_labels = df.iloc[0, 8:36].tolist()
        header_dates = df.iloc[1, 8:36].tolist()
        base_cols = df.iloc[2, 0:8].tolist()

        data = df.iloc[3:].copy()
        data.columns = base_cols + list(range(8, 36))

        for _, row in data.iterrows():
            employee_number = row.get("EMPLOYEE CODE")
            employee_name = row.get("EMPLOYEE NAME")
            store_name = row.get("Store Name")
            brand = row.get("Brand")

            if pd.isna(employee_number) or pd.isna(store_name):
                continue

            for offset in range(0, 28, 4):
                date_val = header_dates[offset]
                start_1 = row[8 + offset]
                end_1 = row[8 + offset + 1]
                start_2 = row[8 + offset + 2]
                end_2 = row[8 + offset + 3]

                if pd.notna(start_1) and pd.notna(end_1):
                    rows.append(
                        {
                            "employee_number": employee_number,
                            "employee_name": employee_name,
                            "store_name": store_name,
                            "brand": brand,
                            "shift_date": pd.to_datetime(date_val).date()
                            if pd.notna(date_val)
                            else None,
                            "shift_start": time_to_str(start_1),
                            "shift_end": time_to_str(end_1),
                        }
                    )

                if pd.notna(start_2) and pd.notna(end_2):
                    rows.append(
                        {
                            "employee_number": employee_number,
                            "employee_name": employee_name,
                            "store_name": store_name,
                            "brand": brand,
                            "shift_date": pd.to_datetime(date_val).date()
                            if pd.notna(date_val)
                            else None,
                            "shift_start": time_to_str(start_2),
                            "shift_end": time_to_str(end_2),
                        }
                    )

    return pd.DataFrame(rows)


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def weighted_kmeans(points, weights, k):
    if k <= 1 or len(points) == 1:
        return [0] * len(points)

    rng = random.Random(RANDOM_SEED)
    centroids = [points[i] for i in rng.sample(range(len(points)), k)]

    for _ in range(KMEANS_ITERS):
        clusters = [[] for _ in range(k)]
        for idx, (lat, lon) in enumerate(points):
            distances = [haversine_km(lat, lon, c[0], c[1]) for c in centroids]
            nearest = distances.index(min(distances))
            clusters[nearest].append(idx)

        new_centroids = []
        for cluster in clusters:
            if not cluster:
                new_centroids.append(points[rng.randrange(len(points))])
                continue
            total_w = sum(weights[i] for i in cluster)
            lat = sum(points[i][0] * weights[i] for i in cluster) / total_w
            lon = sum(points[i][1] * weights[i] for i in cluster) / total_w
            new_centroids.append((lat, lon))
        centroids = new_centroids

    assignments = []
    for lat, lon in points:
        distances = [haversine_km(lat, lon, c[0], c[1]) for c in centroids]
        assignments.append(distances.index(min(distances)))
    return assignments


def pick_depot(geo_df):
    candidates = geo_df[geo_df["store_name_norm"].str.contains("mahboula")]
    if not candidates.empty:
        acc = candidates[candidates["store_name_norm"].str.contains("acc|accommodation|complex")]
        if not acc.empty:
            return acc.iloc[0]
        return candidates.iloc[0]
    return geo_df.iloc[0]


def build_trips(store_group, depot, window_type, window_time_str):
    stores = store_group.copy()
    stores["distance_km"] = stores.apply(
        lambda r: haversine_km(depot["latitude"], depot["longitude"], r["latitude"], r["longitude"]),
        axis=1,
    )
    stores = stores.sort_values("distance_km")

    trips = []
    current_trip = []
    current_load = 0

    for _, row in stores.iterrows():
        store_demand = int(row["demand"])
        while store_demand > 0:
            remaining = CAPACITY - current_load
            if remaining == 0:
                trips.append(current_trip)
                current_trip = []
                current_load = 0
                remaining = CAPACITY
            take = min(remaining, store_demand)
            entry = row.copy()
            entry["assigned_demand"] = take
            current_trip.append(entry)
            current_load += take
            store_demand -= take

            if current_load == CAPACITY:
                trips.append(current_trip)
                current_trip = []
                current_load = 0

    if current_trip:
        trips.append(current_trip)

    trip_rows = []
    for i, trip in enumerate(trips, start=1):
        trip_df = pd.DataFrame(trip)
        stop_count = len(trip_df)
        route_distance = 0.0
        last_lat = depot["latitude"]
        last_lon = depot["longitude"]
        for _, stop in trip_df.iterrows():
            route_distance += haversine_km(last_lat, last_lon, stop["latitude"], stop["longitude"])
            last_lat = stop["latitude"]
            last_lon = stop["longitude"]
        route_distance += haversine_km(last_lat, last_lon, depot["latitude"], depot["longitude"])

        travel_minutes = (route_distance / SPEED_KMPH) * 60
        duration_min = int(travel_minutes + stop_count * DWELL_MIN_PER_STOP)

        window_time = parse_time(window_time_str)
        if window_time is None or pd.isna(window_time):
            trip_start = None
            trip_end = None
        else:
            window_minutes = time_to_minutes(window_time)
            if window_type == "IN":
                trip_end_minutes = window_minutes
                trip_start_minutes = window_minutes - duration_min
            else:
                trip_start_minutes = window_minutes
                trip_end_minutes = window_minutes + duration_min
            trip_start = minutes_to_time_str(trip_start_minutes)
            trip_end = minutes_to_time_str(trip_end_minutes)

        trip_id = f"{window_type}_{window_time_str.replace(':','').replace(' ','')}_C{trip_df.iloc[0]['cluster_id']}_T{i}"
        trip_rows.append(
            {
                "trip_id": trip_id,
                "cluster_id": trip_df.iloc[0]["cluster_id"],
                "window_type": window_type,
                "window_time": window_time_str,
                "store_sequence": " | ".join(trip_df["store_name"].tolist()),
                "store_count": stop_count,
                "passenger_count": int(trip_df["assigned_demand"].sum()),
                "capacity": CAPACITY,
                "route_distance_km": round(route_distance, 2),
                "trip_duration_min": duration_min,
                "trip_start_time": trip_start,
                "trip_end_time": trip_end,
            }
        )

    return trip_rows


def main():
    # Load datasets
    shift_df = load_shift_data_weekly()
    geo_df = pd.read_excel(DATA_DIR / "Geocoordinates.xlsx", sheet_name="Sheet1")
    shift_df["store_name_norm"] = shift_df["store_name"].map(normalize_name)
    shift_df["shift_start_ts"] = shift_df["shift_start"].map(parse_time)
    shift_df["shift_end_ts"] = shift_df["shift_end"].map(parse_time)
    shift_df["shift_duration_min"] = shift_df.apply(
        lambda r: duration_minutes(r["shift_start_ts"], r["shift_end_ts"])
        if pd.notna(r["shift_start_ts"]) and pd.notna(r["shift_end_ts"])
        else None,
        axis=1,
    )

    # Expand to inbound/outbound windows
    inbound = shift_df.copy()
    inbound["window_type"] = "IN"
    inbound["window_time"] = inbound["shift_start"]

    outbound = shift_df.copy()
    outbound["window_type"] = "OUT"
    outbound["window_time"] = outbound["shift_end"]

    windows_df = pd.concat([inbound, outbound], ignore_index=True)

    demand_df = (
        windows_df.groupby(["store_name", "store_name_norm", "window_type", "window_time"], dropna=False)
        .agg(demand=("employee_number", "count"))
        .reset_index()
    )

    geo_df = geo_df.rename(
        columns={
            "Store Name": "store_name",
            "Store ID": "store_id",
            "latitude": "latitude",
            "longitude": "longitude",
        }
    )
    geo_df["latitude"] = pd.to_numeric(geo_df["latitude"], errors="coerce")
    geo_df["longitude"] = pd.to_numeric(geo_df["longitude"], errors="coerce")
    geo_df["store_name_norm"] = geo_df["store_name"].map(normalize_name)

    demand_geo = demand_df.merge(geo_df, on="store_name_norm", how="left", suffixes=("", "_geo"))
    unmatched = demand_geo[demand_geo["latitude"].isna()][
        ["store_name", "store_name_norm", "window_type", "window_time", "demand"]
    ]

    matched = demand_geo.dropna(subset=["latitude", "longitude"]).copy()
    demand_matched = matched[
        ["store_name", "store_name_norm", "window_type", "window_time", "demand"]
    ].copy()

    # Geo + time-window clustering (per window) using weighted k-means
    cluster_ids = []
    global_cluster = 1
    for (window_type, window_time), group in matched.groupby(["window_type", "window_time"]):
        points = list(zip(group["latitude"].tolist(), group["longitude"].tolist()))
        weights = group["demand"].tolist()
        total_demand = sum(weights)
        k = max(1, math.ceil(total_demand / (CAPACITY * MAX_CLUSTER_TRIPS)))
        k = min(k, MAX_K_PER_WINDOW, len(points))

        assignments = weighted_kmeans(points, weights, k)
        for idx, (_, row) in enumerate(group.iterrows()):
            cluster_ids.append(
                {
                    "index": row.name,
                    "cluster_id": global_cluster + assignments[idx],
                }
            )
        global_cluster += k

    cluster_df = pd.DataFrame(cluster_ids).set_index("index")
    matched = matched.join(cluster_df, how="left")
    matched["cluster_id"] = matched["cluster_id"].fillna(1).astype(int)

    # Choose depot
    depot = pick_depot(geo_df)

    # Build trips
    trip_rows = []
    for (window_type, window_time, cluster_id), group in matched.groupby(
        ["window_type", "window_time", "cluster_id"]
    ):
        trip_rows.extend(build_trips(group, depot, window_type, window_time))

    trips_df = pd.DataFrame(trip_rows)

    # Passenger assignment stub
    assignment_rows = []
    trips_lookup = {}
    if not trips_df.empty:
        for _, trip in trips_df.iterrows():
            trips_lookup.setdefault(
                (trip["window_type"], trip["window_time"], trip["cluster_id"]), []
            ).append(trip)

    matched_employees = windows_df.merge(
        matched[["store_name_norm", "cluster_id"]].drop_duplicates(),
        on="store_name_norm",
        how="left",
    )

    for _, row in matched_employees.iterrows():
        key = (row["window_type"], row["window_time"], row["cluster_id"])
        trip_list = trips_lookup.get(key, [])
        if not trip_list:
            continue
        assigned_trip = trip_list[0]["trip_id"]
        assignment_rows.append(
            {
                "employee_number": row["employee_number"],
                "employee_name": row["employee_name"],
                "store_name": row["store_name"],
                "window_type": row["window_type"],
                "window_time": row["window_time"],
                "trip_id": assigned_trip,
            }
        )

    assignment_df = pd.DataFrame(assignment_rows)

    # KPI summary
    if trips_df.empty:
        kpi_df = pd.DataFrame()
    else:
        trips_df["occupancy"] = trips_df["passenger_count"] / trips_df["capacity"]
        kpi_df = pd.DataFrame(
            [
                {
                    "total_trips": int(trips_df["trip_id"].count()),
                    "avg_occupancy": float(trips_df["occupancy"].mean()),
                    "avg_distance_km": float(trips_df["route_distance_km"].mean()),
                    "avg_duration_min": float(trips_df["trip_duration_min"].mean()),
                }
            ]
        )

    # Outputs
    demand_matched.to_csv(OUT_DIR / "demand_by_store_window.csv", index=False)
    matched[["store_name", "store_id", "latitude", "longitude", "cluster_id"]].drop_duplicates().to_csv(
        OUT_DIR / "stores_with_clusters.csv", index=False
    )
    trips_df.to_csv(OUT_DIR / "trips_stub.csv", index=False)
    assignment_df.to_csv(OUT_DIR / "passenger_assignment_stub.csv", index=False)
    if not kpi_df.empty:
        kpi_df.to_csv(OUT_DIR / "kpi_summary.csv", index=False)
    unmatched.to_csv(OUT_DIR / "unmatched_stores.csv", index=False)

    summary = {
        "employees": int(shift_df.shape[0]),
        "stores": int(demand_matched["store_name_norm"].nunique()),
        "windows": int(demand_matched.shape[0]),
        "windows_total": int(demand_df.shape[0]),
        "trips": int(trips_df.shape[0]),
        "unmatched_store_windows": int(unmatched.shape[0]),
        "depot": depot["store_name"],
    }
    pd.DataFrame([summary]).to_csv(OUT_DIR / "run_summary.csv", index=False)


if __name__ == "__main__":
    main()
