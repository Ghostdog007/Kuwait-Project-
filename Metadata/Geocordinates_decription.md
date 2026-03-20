## Dataset Specification: Store Geolocation Dataset(Geocordinates.xlsx)

### Overview

This dataset contains geographic coordinates for retail store locations. Each record represents a single store with a unique identifier and its GPS coordinates. The dataset can be used for spatial computations such as distance calculation, clustering, routing optimization, and geospatial visualization.

The dataset consists of **~83 rows**, where each row corresponds to one store.

---

# Schema

| Column Name  | Type    | Nullable | Description                                     |
| ------------ | ------- | -------- | ----------------------------------------------- |
| `store_name` | string  | No       | Human-readable name of the store or outlet      |
| `store_id`   | integer | No       | Unique identifier for the store                 |
| `latitude`   | float   | No       | Latitude coordinate in decimal degrees (WGS84)  |
| `longitude`  | float   | No       | Longitude coordinate in decimal degrees (WGS84) |

---

# Field Constraints

### store_id

* Must be **unique** for every record
* Used as the **primary identifier** of a store
* Integer values

### latitude

* Float value
* Valid range: **-90 ≤ latitude ≤ 90**

### longitude

* Float value
* Valid range: **-180 ≤ longitude ≤ 180**

### store_name

* String value
* Not guaranteed to be unique
* Used only for human-readable labeling

---

# Coordinate System

The dataset uses the **WGS84 geographic coordinate system**, which is the standard used by GPS systems.

Coordinates are expressed in **decimal degrees**.

Example:

```
latitude: 29.146545
longitude: 48.118341
```

---

# Example Record

```
store_name: "Mahboula Complex - Mix"
store_id: 2
latitude: 29.146545
longitude: 48.118341
```

---

# Assumptions

* Each row represents **one physical store location**
* There are **no duplicate store_id values**
* Coordinates represent **exact store locations**
* Stores are located within the **same geographic region**

---

# Typical Operations for Agents

The dataset may be used for:

1. **Distance calculations**

   * Haversine distance
   * Euclidean approximation

2. **Routing problems**

   * Traveling Salesman Problem (TSP)
   * Vehicle Routing Problem (VRP)

3. **Spatial clustering**

   * K-Means clustering
   * Density-based clustering (DBSCAN)

4. **Visualization**

   * Mapping store points
   * Heatmaps

5. **Graph construction**

   * Creating weighted graphs where nodes are stores and edges represent distances

---

# Important Notes for Implementations

* Distances should be computed using **Haversine formula** since coordinates are geographic.
* Do **not assume Euclidean distances unless converting coordinates to projected coordinates.**
* The dataset does **not include demand, traffic, or time windows**.

---

⚡ If you want, I can also give you a **much stronger version used in ML / optimization projects** (with **node definitions, distance matrix generation rules, depot assumptions, etc.**) which works **much better for routing algorithms like OR-Tools, RL, or metaheuristics**.

---

## Additional Metadata (Project Folder Context)

This folder contains foundational data for mapping store locations, managing employee information, and tracking bus routes. This data is intended for use by Kanishk Sharma and authorized project collaborators.

### Data Categories and Files

* **Geo Coordinates (Geocordinates.xlsx)**: A master list of store outlets, malls, and complexes with their unique IDs and GPS coordinates.
* **Employee Data**: Information regarding project staff and personnel.
* **Current Bus Routes**: Schedule and routing information for transportation logistics.

### Geocoordinates Dataset Schema (Business-Friendly)

| Field Name | Data Type        | Description                                                  |
| ---------- | ---------------- | ------------------------------------------------------------ |
| Store Name | String           | Name of the specific brand outlet or complex (e.g., KFC).     |
| Store ID   | Integer          | Unique identifier assigned to each location.                 |
| latitude   | Decimal / String | North/South GPS coordinate. Marked "Pending" if unavailable. |
| longitude  | Decimal / String | East/West GPS coordinate. Marked "Pending" if unavailable.   |

### Specific Handling and Business Rules

* **Mahboola Complex Management**:
  * Mahboola Complex 1 and Complex 2 are considered the same destination for routing and logistics purposes.
  * Note: They are geographically separated by approximately 5 minutes; this interval must be accounted for in transit calculations.

* **Store Exceptions**:
  * Commissary Chicken Tikka (ID: 1): Coordinates are currently undecided. Do not use these for mapping until the status is updated from "Pending."
