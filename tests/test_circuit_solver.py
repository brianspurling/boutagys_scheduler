"""Tests for the circuit-based solver."""

from datetime import date, time, datetime

from scheduler.models import (
    ActionType, CertLevel, Driver, HorizonConfig, Job,
    Location, ProblemInstance, StorageLocation, TransitMatrix, TransitPair,
    Vehicle,
)
from scheduler.circuit_solver import solve_circuit

LOC_HOME = Location(postcode="HH1 1HH", lat=51.5, lon=-0.1)
LOC_A = Location(postcode="AA1 1AA", lat=51.6, lon=-0.2)
LOC_B = Location(postcode="BB2 2BB", lat=51.7, lon=-0.3)
LOC_DEPOT = Location(postcode="DD4 4DD", lat=51.4, lon=0.0)

HORIZON = HorizonConfig(start_date=date(2025, 12, 8), num_days=1, t_max=1440)

MATRIX = TransitMatrix(entries={
    ("HH1 1HH", "AA1 1AA"): TransitPair(transit_minutes=30, driving_minutes=20),
    ("AA1 1AA", "HH1 1HH"): TransitPair(transit_minutes=30, driving_minutes=20),
    ("HH1 1HH", "BB2 2BB"): TransitPair(transit_minutes=40, driving_minutes=25),
    ("BB2 2BB", "HH1 1HH"): TransitPair(transit_minutes=40, driving_minutes=25),
    ("AA1 1AA", "BB2 2BB"): TransitPair(transit_minutes=50, driving_minutes=30),
    ("BB2 2BB", "AA1 1AA"): TransitPair(transit_minutes=50, driving_minutes=30),
    ("HH1 1HH", "DD4 4DD"): TransitPair(transit_minutes=20, driving_minutes=15),
    ("DD4 4DD", "HH1 1HH"): TransitPair(transit_minutes=20, driving_minutes=15),
    ("AA1 1AA", "DD4 4DD"): TransitPair(transit_minutes=25, driving_minutes=18),
    ("DD4 4DD", "AA1 1AA"): TransitPair(transit_minutes=25, driving_minutes=18),
    ("BB2 2BB", "DD4 4DD"): TransitPair(transit_minutes=35, driving_minutes=22),
    ("DD4 4DD", "BB2 2BB"): TransitPair(transit_minutes=35, driving_minutes=22),
})


def _make_driver(driver_id="D1", loc=LOC_HOME, max_hours=600):
    return Driver(
        driver_id=driver_id, name=driver_id, home_location=loc,
        branch="TEST", max_hours_per_day=max_hours, certifications=CertLevel.VAN,
        can_overnight=True, unavailable_dates=frozenset(),
    )


def _make_collect(job_id, loc, vehicle_reg="VAN1", group="V3",
                  earliest_departure_t=480, same_day_end_t=1439):
    return Job(
        job_id=job_id, book_no=f"B{job_id}", order_ref="", rental_no="",
        book_name="", book_status="",
        action=ActionType.COLLECT, scheduled_date=date(2025, 12, 8),
        scheduled_time=time(9, 0), scheduled_datetime=datetime(2025, 12, 8, 9, 0),
        time_offset_minutes=540,
        earliest_departure_t=earliest_departure_t,
        grace_end_t=earliest_departure_t + 120,
        same_day_start_t=0,
        same_day_end_t=same_day_end_t,
        deadline_t=None,
        vehicle_reg=vehicle_reg, vehicle_group=group,
        target_location=loc, notes="",
    )


def _make_deliver(job_id, loc, vehicle_reg="VAN1", group="V3",
                  deadline_t=600, same_day_start_t=0):
    return Job(
        job_id=job_id, book_no=f"B{job_id}", order_ref="", rental_no="",
        book_name="", book_status="",
        action=ActionType.DELIVER, scheduled_date=date(2025, 12, 8),
        scheduled_time=time(9, 0), scheduled_datetime=datetime(2025, 12, 8, 9, 0),
        time_offset_minutes=540,
        earliest_departure_t=None,
        grace_end_t=None,
        same_day_start_t=same_day_start_t,
        same_day_end_t=1439,
        deadline_t=deadline_t,
        vehicle_reg=vehicle_reg, vehicle_group=group,
        target_location=loc, notes="",
    )


def _make_storage(location_id="S001", loc=LOC_DEPOT):
    return StorageLocation(
        location_id=location_id, name="Depot", location=loc,
        capacity=20, restricted_groups=set(),
    )


def _make_instance(drivers, jobs, storage_locations=None, vehicles=None):
    return ProblemInstance(
        horizon=HORIZON, jobs=jobs, drivers=drivers,
        vehicles=vehicles or [],
        storage_locations=storage_locations or [],
        vehicle_group_certs={"V3": CertLevel.VAN, "V5": CertLevel.VAN},
        transit_matrix=MATRIX,
        driver_job_arcs=[], job_chain_arcs=[], vehicle_job_arcs=[],
    )


def _solve(instance):
    """Solve with a short timeout suitable for unit tests."""
    return solve_circuit(instance, timeout_seconds=5)


# --- Basic circuit feasibility ---

def test_single_collect_feasible():
    """One driver, one collect job — FEASIBLE, driver visits the collect node."""
    d = _make_driver()
    j = _make_collect("J1", LOC_A)
    result = _solve(_make_instance([d], [j]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 1
    assert result.assignments[0].job_id == "J1"


def test_single_deliver_with_depot():
    """One deliver job — driver must go via depot_pickup to get a van.
    Only feasible if a depot exists."""
    d = _make_driver()
    j = _make_deliver("J1", LOC_A, vehicle_reg="VAN1")
    depot = _make_storage()
    result = _solve(_make_instance([d], [j], [depot]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 1


def test_collect_then_deliver_chains():
    """Collect + matching deliver — solver should chain them (cheapest path)."""
    d = _make_driver()
    j1 = _make_collect("J1", LOC_A, vehicle_reg="VAN1", group="V3",
                       earliest_departure_t=480, same_day_end_t=1439)
    j2 = _make_deliver("J2", LOC_B, vehicle_reg="VAN1", group="V3",
                       deadline_t=700)
    result = _solve(_make_instance([d], [j1, j2]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 2
    # Verify ordering: collect before deliver
    starts = {a.job_id: a.start_time_t for a in result.assignments}
    assert starts["J1"] < starts["J2"]


def test_two_collects_need_depot():
    """Two collects, no delivers — driver must visit depot between them.
    Without a depot, only one can be done (the other requires a depot drop)."""
    d = _make_driver()
    j1 = _make_collect("J1", LOC_A, vehicle_reg="VAN1", earliest_departure_t=480)
    j2 = _make_collect("J2", LOC_B, vehicle_reg="VAN2", earliest_departure_t=700)
    # Without depot: INFEASIBLE (can't do two collects — no arc COLLECT->COLLECT)
    # But we have two drivers to make it feasible without depot
    d2 = _make_driver("D2")
    result_no_depot = _solve(_make_instance([d, d2], [j1, j2]))
    assert result_no_depot.status in ("OPTIMAL", "FEASIBLE")
    # With one driver and a depot: also FEASIBLE
    depot = _make_storage()
    result_depot = _solve(_make_instance([d], [j1, j2], [depot]))
    assert result_depot.status in ("OPTIMAL", "FEASIBLE")


def test_multi_driver_assignment():
    """Two jobs, two drivers — both assigned."""
    d1 = _make_driver("D1")
    d2 = _make_driver("D2")
    j1 = _make_collect("J1", LOC_A, earliest_departure_t=480)
    j2 = _make_collect("J2", LOC_B, earliest_departure_t=480)
    result = _solve(_make_instance([d1, d2], [j1, j2]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 2


# --- Vehicle custody ---

def test_no_double_collect_one_driver():
    """One driver, two collects, no depot — one driver can only do one collect.
    The second must go to another driver."""
    d1 = _make_driver("D1")
    d2 = _make_driver("D2")
    j1 = _make_collect("J1", LOC_A, vehicle_reg="VAN1", earliest_departure_t=480)
    j2 = _make_collect("J2", LOC_B, vehicle_reg="VAN2", earliest_departure_t=480)
    # No depot — can't park between collects
    result = _solve(_make_instance([d1, d2], [j1, j2]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 2
    # Each driver does exactly one job
    drivers_used = {a.driver_id for a in result.assignments}
    assert len(drivers_used) == 2


def test_collect_deliver_collect_feasible_with_depot():
    """Collect -> Deliver -> Collect is feasible (driver drops van, takes transit, collects another)."""
    d = _make_driver()
    j1 = _make_collect("J1", LOC_A, vehicle_reg="VAN1", group="V3",
                       earliest_departure_t=480)
    j2 = _make_deliver("J2", LOC_B, vehicle_reg="VAN1", group="V3",
                       deadline_t=700)
    j3 = _make_collect("J3", LOC_A, vehicle_reg="VAN2", group="V3",
                       earliest_departure_t=800)
    result = _solve(_make_instance([d], [j1, j2, j3]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 3
    starts = {a.job_id: a.start_time_t for a in result.assignments}
    assert starts["J1"] < starts["J2"] < starts["J3"]


def test_shift_span_limit():
    """Shift span exceeding max_hours_per_day forces job to be unassigned."""
    d = _make_driver(max_hours=40)  # 40 minutes max
    # Job at 480: transit out=30min, return driving=20min → min span=50 > 40
    j = _make_collect("J1", LOC_A, earliest_departure_t=480)
    result = _solve(_make_instance([d], [j]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 0
    assert "J1" in result.unassigned_job_ids


# --- TBA vehicle assignment ---

def test_tba_deliver_from_depot():
    """TBA deliver job — solver picks a depot vehicle and routes through depot_pickup."""
    d = _make_driver()
    j = _make_deliver("J1", LOC_A, vehicle_reg=None, group="V3",
                      deadline_t=700)
    depot = _make_storage()
    v = Vehicle(reg="VAN1", group="V3", current_location=LOC_DEPOT,
                available_from=date(2025, 12, 8), available_from_t=0)
    result = _solve(_make_instance([d], [j], [depot], [v]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 1


def test_tba_deliver_from_collect_chain():
    """TBA deliver sourced from a collect chain — no depot vehicle needed."""
    d = _make_driver()
    j1 = _make_collect("J1", LOC_A, vehicle_reg="VAN1", group="V3",
                       earliest_departure_t=480)
    j2 = _make_deliver("J2", LOC_B, vehicle_reg=None, group="V3",
                       deadline_t=800)
    result = _solve(_make_instance([d], [j1, j2]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 2


def test_tba_no_source_infeasible():
    """TBA deliver with no depot vehicle and no matching collect — left unassigned."""
    d = _make_driver()
    j = _make_deliver("J1", LOC_A, vehicle_reg=None, group="V3",
                      deadline_t=700)
    # No depot, no vehicles, no collects
    result = _solve(_make_instance([d], [j]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 0
    assert "J1" in result.unassigned_job_ids


# --- Objective function behavior ---

def test_activation_penalty_prefers_fewer_drivers():
    """With activation penalty, solver prefers fewer drivers for two jobs
    that one driver can handle."""
    d1 = _make_driver("D1")
    d2 = _make_driver("D2")
    j1 = _make_collect("J1", LOC_A, earliest_departure_t=480)
    j2 = _make_collect("J2", LOC_B, earliest_departure_t=700)
    depot = _make_storage()
    result = _solve(_make_instance([d1, d2], [j1, j2], [depot]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 2
    # With activation penalty, solver should use 1 driver (via depot between collects)
    drivers_used = {a.driver_id for a in result.assignments}
    assert len(drivers_used) == 1


# --- Route extraction ---

def test_route_extraction_single_collect():
    """Single collect: route = HOME -transit-> COLLECT -driving-> HOME."""
    d = _make_driver()
    j = _make_collect("J1", LOC_A, earliest_departure_t=480)
    result = _solve(_make_instance([d], [j]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.driver_routes) == 1
    route = result.driver_routes[0]
    assert route.driver_id == "D1"
    assert route.home_postcode == "HH1 1HH"
    assert len(route.legs) >= 2
    # First leg: transit from home
    assert route.legs[0].from_postcode == "HH1 1HH"
    assert route.legs[0].mode == "transit"
    # Last leg: driving back home (collect = in-vehicle)
    assert route.legs[-1].to_postcode == "HH1 1HH"
    assert route.legs[-1].mode == "driving"


def test_route_extraction_collect_deliver_chain():
    """Collect then deliver: HOME -transit-> COLLECT -driving-> DELIVER -transit-> HOME."""
    d = _make_driver()
    j1 = _make_collect("J1", LOC_A, vehicle_reg="VAN1", group="V3",
                       earliest_departure_t=480)
    j2 = _make_deliver("J2", LOC_B, vehicle_reg="VAN1", group="V3",
                       deadline_t=800)
    result = _solve(_make_instance([d], [j1, j2]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.driver_routes) == 1
    route = result.driver_routes[0]
    assert len(route.legs) >= 3
    # First: transit to collect
    assert route.legs[0].mode == "transit"
    # Middle: driving collect -> deliver
    assert route.legs[1].mode == "driving"
    # Last: transit home (after deliver, driver is empty-handed)
    assert route.legs[-1].to_postcode == "HH1 1HH"
    assert route.legs[-1].mode == "transit"


def test_chaining_cheaper_than_depot_detour():
    """Collect -> Deliver chain should be cheaper than Collect -> Depot -> transit -> Deliver.
    Verify the solver assigns both jobs when a matching collect/deliver pair exists."""
    d = _make_driver()
    # Force J1 to be done before J2 by setting earliest_departure_t=480 and
    # making J2 only reachable after J1 via deadline_t that is well after J1 can complete.
    j1 = _make_collect("J1", LOC_A, vehicle_reg="VAN1", group="V3",
                       earliest_departure_t=480)
    j2 = _make_deliver("J2", LOC_B, vehicle_reg="VAN1", group="V3",
                       deadline_t=800)
    depot = _make_storage()
    result = _solve(_make_instance([d], [j1, j2], [depot]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    # Both jobs should be assigned (chaining is possible)
    assert len(result.assignments) == 2


# --- Integration test ---

def test_circuit_solver_real_sample_data():
    """Integration: build from real CSVs and solve with circuit solver."""
    from pathlib import Path
    from collections import defaultdict
    from scheduler.builder import ProblemBuilder

    ROOT = Path(__file__).resolve().parent.parent
    result = (
        ProblemBuilder(horizon_start=date(2025, 12, 8), num_days=5)
        .load_postcode_coords(ROOT / "ref-data" / "postcode_coords.csv")
        .load_storage_locations(ROOT / "ref-data" / "storage_locations.csv")
        .load_drivers(ROOT / "ref-data" / "drivers.csv")
        .load_vehicles(ROOT / "ref-data" / "vehicle_inventory.csv")
        .load_bookings(ROOT / "input" / "sample_bookings_data.csv")
        .build()
    )
    assert result.ok
    inst = result.instance

    solver_result = solve_circuit(inst, timeout_seconds=120)
    assert solver_result.status in ("OPTIMAL", "FEASIBLE"), (
        f"Circuit solver returned {solver_result.status} on sample data"
    )

    # Assigned + unassigned must cover all jobs exactly once
    assigned_job_ids = {a.job_id for a in solver_result.assignments}
    unassigned_job_ids = set(solver_result.unassigned_job_ids)
    all_job_ids = {j.job_id for j in inst.jobs}
    assert assigned_job_ids | unassigned_job_ids == all_job_ids
    assert assigned_job_ids & unassigned_job_ids == set()

    # Most jobs should be assigned (unassigned indicates genuinely infeasible jobs)
    assert len(solver_result.assignments) > 0
    if solver_result.unassigned_job_ids:
        print(f"\nUnassigned jobs ({len(solver_result.unassigned_job_ids)}): {solver_result.unassigned_job_ids}")

    # Verify routes exist for used drivers
    assert len(solver_result.driver_routes) > 0


# --- Asymmetric time semantics ---

def test_collect_hard_floor_respected():
    """Driver arrives early but cannot depart before earliest_departure_t."""
    d = _make_driver()  # 30min transit to LOC_A
    # earliest_departure_t=600 (10:00). Driver can reach in 30min from t=0.
    j = _make_collect("J1", LOC_A, earliest_departure_t=600)
    result = _solve(_make_instance([d], [j]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 1
    # Service must not start before the hard floor
    assert result.assignments[0].start_time_t >= 600


def test_collect_within_grace_is_assigned():
    """Collect job within grace period is assigned without issue."""
    d = _make_driver()
    j = _make_collect("J1", LOC_A, earliest_departure_t=0)  # grace ends at 120
    result = _solve(_make_instance([d], [j]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 1


def test_deliver_early_arrival_is_assigned():
    """Deliver job where driver arrives before deadline is assigned."""
    d = _make_driver()
    j = _make_deliver("J1", LOC_A, deadline_t=400)  # driver arrives in ~30min, well before 400
    depot = _make_storage()
    v = Vehicle(reg="VAN1", group="V3", current_location=LOC_DEPOT,
                available_from=date(2025, 12, 8), available_from_t=0)
    result = _solve(_make_instance([d], [j], [depot], [v]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 1
