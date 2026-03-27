from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import pandas as pd

from preprocessing import (
    BUFFER_MIN,
    BUS_COUNT,
    EVENING_SEED_HOUR,
    HARD_DUTY_SPAN_MIN,
    MIXED_MAX_WAIT_MIN,
    REPAIR_SHIFT_OPTIONS_IN,
    REPAIR_SHIFT_OPTIONS_OUT,
    TARGET_DUTY_MIN,
)


@dataclass
class DutySlot:
    bus_id: int
    slot_type: str
    available_after: pd.Timestamp | None = None
    first_start: pd.Timestamp | None = None
    last_end: pd.Timestamp | None = None
    trip_ids: list[str] | None = None

    def __post_init__(self) -> None:
        if self.trip_ids is None:
            self.trip_ids = []


def init_slots(service_dates: list[str]) -> dict[tuple[str, int, str], DutySlot]:
    slots: dict[tuple[str, int, str], DutySlot] = {}
    for service_day in service_dates:
        for bus_id in range(1, BUS_COUNT + 1):
            slots[(service_day, bus_id, "morning")] = DutySlot(bus_id=bus_id, slot_type="morning")
            slots[(service_day, bus_id, "evening")] = DutySlot(bus_id=bus_id, slot_type="evening")
    return slots


def slot_preference(trip_type: str, start_dt: pd.Timestamp) -> list[str]:
    if trip_type == "OUT" or start_dt.hour >= EVENING_SEED_HOUR:
        return ["evening", "morning"]
    return ["morning", "evening"]


def slot_is_feasible(
    slot: DutySlot,
    trip: pd.Series,
    day_assignments: pd.DataFrame,
    desired_start: pd.Timestamp,
    latest_extension_min: int = 0,
) -> tuple[bool, pd.Timestamp | None, float]:
    earliest = pd.Timestamp(trip["earliest_start_dt"])
    latest = pd.Timestamp(trip["latest_start_dt"]) + timedelta(minutes=latest_extension_min)
    if slot.slot_type == "evening":
        earliest = max(earliest, pd.Timestamp(earliest.date()) + timedelta(hours=EVENING_SEED_HOUR))

    candidate_start = max(desired_start, earliest)
    if slot.available_after is not None:
        candidate_start = max(candidate_start, slot.available_after + timedelta(minutes=BUFFER_MIN))
    if candidate_start > latest:
        return False, None, 0.0

    candidate_end = candidate_start + timedelta(minutes=float(trip["trip_duration_min"]))
    projected_span = float(trip["trip_duration_min"])
    if slot.first_start is not None:
        projected_span = (candidate_end - slot.first_start).total_seconds() / 60.0
        if projected_span > HARD_DUTY_SPAN_MIN:
            return False, None, projected_span

    if not day_assignments.empty and "bus_id" in day_assignments.columns:
        for row in day_assignments[day_assignments["bus_id"] == slot.bus_id].itertuples(index=False):
            if not (
                candidate_end <= pd.Timestamp(row.planned_start_dt)
                or candidate_start >= pd.Timestamp(row.planned_end_dt)
            ):
                return False, None, projected_span
    return True, candidate_start, projected_span


def choose_slot_assignment(
    trip: pd.Series,
    slots: dict[tuple[str, int, str], DutySlot],
    assignment_rows: list[dict[str, object]],
    repair_mode: bool = False,
) -> tuple[tuple[str, int, str], pd.Timestamp, bool] | None:
    service_day = str(trip["service_date"])
    day_assignments = pd.DataFrame(assignment_rows)
    if not day_assignments.empty:
        day_assignments = day_assignments[day_assignments["service_date"] == service_day]

    deltas = [0]
    if repair_mode:
        deltas = REPAIR_SHIFT_OPTIONS_OUT if trip["trip_type"] == "OUT" else REPAIR_SHIFT_OPTIONS_IN
        deltas = [0] + deltas

    best_choice: tuple[tuple[str, int, str], pd.Timestamp, bool] | None = None
    best_score: tuple[float, float, float, int, str] | None = None
    preferred_slots = slot_preference(str(trip["trip_type"]), pd.Timestamp(trip["planned_start_dt"]))

    for slot_type in ("morning", "evening"):
        slot_penalty = 0 if slot_type == preferred_slots[0] else 5
        for bus_id in range(1, BUS_COUNT + 1):
            slot_key = (service_day, bus_id, slot_type)
            slot = slots[slot_key]
            for delta in deltas:
                desired_start = pd.Timestamp(trip["planned_start_dt"]) + timedelta(minutes=delta)
                latest_extension = max(0, delta)
                ok, start_dt, projected_span = slot_is_feasible(
                    slot,
                    trip,
                    day_assignments,
                    desired_start=desired_start,
                    latest_extension_min=latest_extension,
                )
                if not ok or start_dt is None:
                    continue

                delay = abs((start_dt - pd.Timestamp(trip["planned_start_dt"])).total_seconds()) / 60.0
                overtime_risk = max(0.0, projected_span - TARGET_DUTY_MIN)
                score = (slot_penalty + overtime_risk, delay, projected_span, bus_id, slot_type)
                if best_score is None or score < best_score:
                    best_score = score
                    best_choice = (slot_key, start_dt, delta != 0)
    return best_choice


def schedule_with_rotation_reset(base_trips: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if base_trips.empty:
        empty_assignments = pd.DataFrame(
            columns=[
                "trip_id",
                "trip_type",
                "service_date",
                "bus_id",
                "rotation_tag",
                "planned_start_dt",
                "planned_end_dt",
                "trip_duration_min",
                "occupancy_pct",
                "assigned_passengers",
                "rescued_by_delay",
                "handover_flag",
            ]
        )
        empty_unscheduled = pd.DataFrame(
            columns=["trip_id", "trip_type", "requested_wave_label", "reason", "assigned_passengers", "peak_load"]
        )
        return base_trips.copy(), empty_assignments, empty_unscheduled

    trips = base_trips.copy().sort_values(["planned_start_dt", "peak_load", "trip_id"], ascending=[True, False, True])
    trips = trips.reset_index(drop=True)
    service_dates = sorted(trips["service_date"].astype(str).unique())
    slots = init_slots(service_dates)
    scheduled_rows: list[dict[str, object]] = []
    assignment_rows: list[dict[str, object]] = []
    unscheduled_trips: list[pd.Series] = []

    for _, trip in trips.iterrows():
        best_choice = choose_slot_assignment(trip, slots, assignment_rows, repair_mode=False)
        if best_choice is None:
            unscheduled_trips.append(trip)
            continue

        slot_key, start_dt, rescued = best_choice
        service_day, bus_id, slot_type = slot_key
        end_dt = pd.Timestamp(start_dt) + timedelta(minutes=float(trip["trip_duration_min"]))
        slot = slots[slot_key]
        if slot.first_start is None:
            slot.first_start = pd.Timestamp(start_dt)
        slot.available_after = end_dt
        slot.last_end = end_dt
        slot.trip_ids.append(str(trip["trip_id"]))

        trip_dict = trip.to_dict()
        trip_dict["service_date"] = service_day
        trip_dict["planned_start_dt"] = pd.Timestamp(start_dt)
        trip_dict["planned_end_dt"] = end_dt
        trip_dict["rescued_by_delay"] = rescued
        trip_dict["rotation_tag"] = slot_type
        scheduled_rows.append(trip_dict)

        assignment_rows.append(
            {
                "trip_id": trip["trip_id"],
                "trip_type": trip["trip_type"],
                "service_date": service_day,
                "bus_id": bus_id,
                "rotation_tag": slot_type,
                "planned_start_dt": pd.Timestamp(start_dt),
                "planned_end_dt": end_dt,
                "trip_duration_min": float(trip["trip_duration_min"]),
                "occupancy_pct": float(trip["occupancy_pct"]),
                "assigned_passengers": int(trip["assigned_passengers"]),
                "rescued_by_delay": rescued,
                "handover_flag": slot_type == "evening",
            }
        )

    final_unscheduled_rows: list[dict[str, object]] = []
    for trip in unscheduled_trips:
        best_choice = choose_slot_assignment(trip, slots, assignment_rows, repair_mode=True)
        if best_choice is None:
            final_unscheduled_rows.append(
                {
                    "trip_id": trip["trip_id"],
                    "trip_type": trip["trip_type"],
                    "requested_wave_label": trip["requested_wave_label"],
                    "reason": "fleet_or_freshness_block",
                    "assigned_passengers": int(trip["assigned_passengers"]),
                    "peak_load": int(trip["peak_load"]),
                }
            )
            continue

        slot_key, start_dt, rescued = best_choice
        service_day, bus_id, slot_type = slot_key
        end_dt = pd.Timestamp(start_dt) + timedelta(minutes=float(trip["trip_duration_min"]))
        slot = slots[slot_key]
        if slot.first_start is None:
            slot.first_start = pd.Timestamp(start_dt)
        slot.available_after = end_dt
        slot.last_end = end_dt
        slot.trip_ids.append(str(trip["trip_id"]))

        trip_dict = trip.to_dict()
        trip_dict["service_date"] = service_day
        trip_dict["planned_start_dt"] = pd.Timestamp(start_dt)
        trip_dict["planned_end_dt"] = end_dt
        trip_dict["rescued_by_delay"] = rescued
        trip_dict["rotation_tag"] = slot_type
        scheduled_rows.append(trip_dict)

        assignment_rows.append(
            {
                "trip_id": trip["trip_id"],
                "trip_type": trip["trip_type"],
                "service_date": service_day,
                "bus_id": bus_id,
                "rotation_tag": slot_type,
                "planned_start_dt": pd.Timestamp(start_dt),
                "planned_end_dt": end_dt,
                "trip_duration_min": float(trip["trip_duration_min"]),
                "occupancy_pct": float(trip["occupancy_pct"]),
                "assigned_passengers": int(trip["assigned_passengers"]),
                "rescued_by_delay": rescued,
                "handover_flag": slot_type == "evening",
            }
        )

    scheduled = pd.DataFrame(scheduled_rows).sort_values(["planned_start_dt", "trip_id"]).reset_index(drop=True)
    assignments = pd.DataFrame(assignment_rows).sort_values(["planned_start_dt", "bus_id"]).reset_index(drop=True)
    unscheduled = pd.DataFrame(final_unscheduled_rows)
    return scheduled, assignments, unscheduled


def add_mixed_labels(scheduled: pd.DataFrame, assignments: pd.DataFrame) -> pd.DataFrame:
    if scheduled.empty or assignments.empty:
        return scheduled
    updated = scheduled.copy()
    for _, group in assignments.sort_values(["bus_id", "planned_start_dt"]).groupby(["service_date", "bus_id"], dropna=False):
        rows = list(group.itertuples(index=False))
        for prev, curr in zip(rows, rows[1:]):
            if prev.trip_type != "IN" or curr.trip_type != "OUT":
                continue
            gap_min = (pd.Timestamp(curr.planned_start_dt) - pd.Timestamp(prev.planned_end_dt)).total_seconds() / 60.0
            if 0 <= gap_min <= MIXED_MAX_WAIT_MIN:
                updated.loc[updated["trip_id"] == prev.trip_id, "trip_type"] = "MIXED"
    return updated
