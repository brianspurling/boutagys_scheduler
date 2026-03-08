from datetime import date, time, datetime

from scheduler.arcs import compute_driver_job_arcs, compute_vehicle_job_arcs, compute_job_chain_arcs
from scheduler.models import (
    ActionType, CertLevel, ChainType, Driver, Job,
    Location, TransitMatrix, TransitPair, Vehicle,
)
from scheduler.cert_table import VEHICLE_GROUP_CERTS

LOC_A = Location(postcode="SW15 2SW", lat=51.4576, lon=-0.2289)
LOC_B = Location(postcode="TW14 9DF", lat=51.4502, lon=-0.4084)
LOC_C = Location(postcode="SE10 0EF", lat=51.4826, lon=0.0077)

MATRIX = TransitMatrix(entries={
    ("SW15 2SW", "TW14 9DF"): TransitPair(transit_minutes=55, driving_minutes=35),
    ("TW14 9DF", "SW15 2SW"): TransitPair(transit_minutes=55, driving_minutes=35),
    ("SW15 2SW", "SE10 0EF"): TransitPair(transit_minutes=70, driving_minutes=45),
    ("SE10 0EF", "SW15 2SW"): TransitPair(transit_minutes=70, driving_minutes=45),
    ("TW14 9DF", "SE10 0EF"): TransitPair(transit_minutes=80, driving_minutes=50),
    ("SE10 0EF", "TW14 9DF"): TransitPair(transit_minutes=80, driving_minutes=50),
})


def _make_driver(driver_id: str, cert: CertLevel, loc: Location, unavail=frozenset()) -> Driver:
    return Driver(
        driver_id=driver_id, name="Test", home_location=loc,
        branch="PUTNEY", max_hours_per_day=600, certifications=cert,
        can_overnight=True, unavailable_dates=unavail,
    )


def _make_job(
    job_id: str, action: ActionType, group: str, loc: Location,
    sched_date: date = date(2025, 12, 8),
    window_start: int = 480, window_end: int = 600,
    vehicle_reg: str | None = None,
) -> Job:
    is_collect = (action == ActionType.COLLECT)
    return Job(
        job_id=job_id, book_no="", order_ref="", rental_no="",
        book_name="", book_status="",
        action=action, scheduled_date=sched_date,
        scheduled_time=time(9, 0), scheduled_datetime=datetime(2025, 12, 8, 9, 0),
        time_offset_minutes=540,
        earliest_departure_t=window_start if is_collect else None,
        grace_end_t=window_end if is_collect else None,
        same_day_start_t=window_start,
        same_day_end_t=window_end,
        deadline_t=None if is_collect else window_end,
        vehicle_reg=vehicle_reg, vehicle_group=group,
        target_location=loc, notes="",
    )


# --- DriverJobArc ---

def test_driver_job_arc_basic():
    driver = _make_driver("D001", CertLevel.VAN, LOC_A)
    job = _make_job("J001", ActionType.COLLECT, "V3", LOC_B)
    arcs = compute_driver_job_arcs([driver], [job], MATRIX, VEHICLE_GROUP_CERTS)
    assert len(arcs) == 1
    assert arcs[0].deadhead_minutes == 55
    assert arcs[0].return_deadhead_minutes == 55


def test_driver_job_arc_cert_mismatch():
    driver = _make_driver("D001", CertLevel.VAN, LOC_A)
    job = _make_job("J001", ActionType.COLLECT, "C.F4", LOC_B)
    arcs = compute_driver_job_arcs([driver], [job], MATRIX, VEHICLE_GROUP_CERTS)
    assert len(arcs) == 0


def test_driver_job_arc_unavailable():
    driver = _make_driver("D001", CertLevel.VAN, LOC_A, unavail=frozenset({date(2025, 12, 8)}))
    job = _make_job("J001", ActionType.COLLECT, "V3", LOC_B)
    arcs = compute_driver_job_arcs([driver], [job], MATRIX, VEHICLE_GROUP_CERTS)
    assert len(arcs) == 0


def test_driver_job_arc_too_far():
    """If deadhead exceeds the job's absolute window_end_t, arc should be pruned."""
    driver = _make_driver("D001", CertLevel.VAN, LOC_A)
    # Window ends at minute 50 — but deadhead is 55 minutes, so driver can't arrive in time
    job = _make_job("J001", ActionType.COLLECT, "V3", LOC_B, window_start=0, window_end=50)
    arcs = compute_driver_job_arcs([driver], [job], MATRIX, VEHICLE_GROUP_CERTS)
    assert len(arcs) == 0


# --- VehicleJobArc ---

def test_vehicle_job_arc_basic():
    vehicle = Vehicle(
        reg="MK22EEA", group="V3", current_location=LOC_B,
        available_from=date(2025, 12, 8), available_from_t=0,
    )
    job = _make_job("J001", ActionType.DELIVER, "V3", LOC_A, vehicle_reg=None)
    arcs = compute_vehicle_job_arcs([vehicle], [job], MATRIX)
    assert len(arcs) == 1
    assert arcs[0].driving_minutes == 35
    assert arcs[0].earliest_arrival_t == 35


def test_vehicle_job_arc_group_mismatch():
    vehicle = Vehicle(
        reg="MK22EEA", group="V5", current_location=LOC_B,
        available_from=date(2025, 12, 8), available_from_t=0,
    )
    job = _make_job("J001", ActionType.DELIVER, "V3", LOC_A, vehicle_reg=None)
    arcs = compute_vehicle_job_arcs([vehicle], [job], MATRIX)
    assert len(arcs) == 0


def test_vehicle_job_arc_only_tba_jobs():
    vehicle = Vehicle(
        reg="MK22EEA", group="V3", current_location=LOC_B,
        available_from=date(2025, 12, 8), available_from_t=0,
    )
    job = _make_job("J001", ActionType.DELIVER, "V3", LOC_A, vehicle_reg="EXISTING")
    arcs = compute_vehicle_job_arcs([vehicle], [job], MATRIX)
    assert len(arcs) == 0


def test_vehicle_job_arc_skips_non_tba_in_mixed_list():
    vehicle = Vehicle(
        reg="MK22EEA", group="V3", current_location=LOC_B,
        available_from=date(2025, 12, 8), available_from_t=0,
    )
    job_tba = _make_job("J001", ActionType.DELIVER, "V3", LOC_A, vehicle_reg=None)
    job_assigned = _make_job("J002", ActionType.DELIVER, "V3", LOC_A, vehicle_reg="VAN456")
    arcs = compute_vehicle_job_arcs([vehicle], [job_tba, job_assigned], MATRIX)
    assert len(arcs) == 1
    assert arcs[0].job_id == "J001"


# --- JobChainArc ---

def test_job_chain_arc_driver_only():
    job_a = _make_job("J001", ActionType.COLLECT, "V3", LOC_A, window_start=480, window_end=540)
    job_b = _make_job("J002", ActionType.COLLECT, "V5", LOC_B, window_start=600, window_end=720)
    arcs = compute_job_chain_arcs([job_a, job_b], MATRIX)
    driver_only = [a for a in arcs if a.chain_type == ChainType.DRIVER_ONLY]
    assert len(driver_only) >= 1
    arc = [a for a in driver_only if a.from_job_id == "J001" and a.to_job_id == "J002"][0]
    assert arc.travel_minutes == 55
    assert arc.turnaround_minutes == 0


def test_job_chain_arc_vehicle_driver_tba():
    job_a = _make_job("J001", ActionType.COLLECT, "V3", LOC_A, window_start=480, window_end=540, vehicle_reg="VAN123")
    job_b = _make_job("J002", ActionType.DELIVER, "V3", LOC_B, window_start=600, window_end=720, vehicle_reg=None)
    arcs = compute_job_chain_arcs([job_a, job_b], MATRIX)
    vd_arcs = [a for a in arcs if a.chain_type == ChainType.VEHICLE_DRIVER]
    assert len(vd_arcs) == 1
    assert vd_arcs[0].travel_minutes == 35
    assert vd_arcs[0].turnaround_minutes == 45


def test_job_chain_arc_vehicle_driver_same_reg():
    job_a = _make_job("J001", ActionType.COLLECT, "V3", LOC_A, window_start=480, window_end=540, vehicle_reg="VAN123")
    job_b = _make_job("J002", ActionType.DELIVER, "V3", LOC_B, window_start=600, window_end=720, vehicle_reg="VAN123")
    arcs = compute_job_chain_arcs([job_a, job_b], MATRIX)
    vd_arcs = [a for a in arcs if a.chain_type == ChainType.VEHICLE_DRIVER]
    assert len(vd_arcs) == 1


def test_job_chain_arc_vehicle_driver_different_reg():
    job_a = _make_job("J001", ActionType.COLLECT, "V3", LOC_A, window_start=480, window_end=540, vehicle_reg="VAN123")
    job_b = _make_job("J002", ActionType.DELIVER, "V3", LOC_B, window_start=600, window_end=720, vehicle_reg="VAN456")
    arcs = compute_job_chain_arcs([job_a, job_b], MATRIX)
    vd_arcs = [a for a in arcs if a.chain_type == ChainType.VEHICLE_DRIVER]
    assert len(vd_arcs) == 0


def test_job_chain_arc_vehicle_driver_group_mismatch():
    job_a = _make_job("J001", ActionType.COLLECT, "V3", LOC_A, window_start=480, window_end=540)
    job_b = _make_job("J002", ActionType.DELIVER, "V5", LOC_B, window_start=600, window_end=720)
    arcs = compute_job_chain_arcs([job_a, job_b], MATRIX)
    vd_arcs = [a for a in arcs if a.chain_type == ChainType.VEHICLE_DRIVER]
    assert len(vd_arcs) == 0


def test_job_chain_arc_temporally_impossible():
    job_a = _make_job("J001", ActionType.COLLECT, "V3", LOC_A, window_start=700, window_end=720)
    job_b = _make_job("J002", ActionType.COLLECT, "V3", LOC_B, window_start=700, window_end=720)
    arcs = compute_job_chain_arcs([job_a, job_b], MATRIX)
    a_to_b = [a for a in arcs if a.from_job_id == "J001" and a.to_job_id == "J002"]
    assert len(a_to_b) == 0
