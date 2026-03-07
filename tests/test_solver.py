"""Unit tests for the CP-SAT solver using small synthetic ProblemInstance objects."""

from datetime import date, time, datetime
from pathlib import Path

from scheduler.models import (
    ActionType, CertLevel, Driver, DriverJobArc, HorizonConfig, Job,
    JobChainArc, Location, ProblemInstance, TransitMatrix, TransitPair,
    Vehicle, VehicleJobArc,
)
from scheduler.solver import solve

LOC_A = Location(postcode="AA1 1AA", lat=51.5, lon=-0.1)
LOC_B = Location(postcode="BB2 2BB", lat=51.6, lon=-0.2)
LOC_C = Location(postcode="CC3 3CC", lat=51.7, lon=-0.3)

HORIZON = HorizonConfig(start_date=date(2025, 12, 8), num_days=1, t_max=1440)

MATRIX = TransitMatrix(entries={
    ("AA1 1AA", "BB2 2BB"): TransitPair(transit_minutes=30, driving_minutes=20),
    ("BB2 2BB", "AA1 1AA"): TransitPair(transit_minutes=30, driving_minutes=20),
    ("AA1 1AA", "CC3 3CC"): TransitPair(transit_minutes=40, driving_minutes=25),
    ("CC3 3CC", "AA1 1AA"): TransitPair(transit_minutes=40, driving_minutes=25),
    ("BB2 2BB", "CC3 3CC"): TransitPair(transit_minutes=50, driving_minutes=30),
    ("CC3 3CC", "BB2 2BB"): TransitPair(transit_minutes=50, driving_minutes=30),
})


def _make_driver(driver_id: str, loc: Location = LOC_A) -> Driver:
    return Driver(
        driver_id=driver_id, name=driver_id, home_location=loc,
        branch="TEST", max_hours_per_day=600, certifications=CertLevel.VAN,
        can_overnight=True, unavailable_dates=frozenset(),
    )


def _make_job(
    job_id: str, loc: Location, window_start: int = 480, window_end: int = 600,
) -> Job:
    return Job(
        job_id=job_id, book_no=f"B{job_id}", order_ref="", rental_no="",
        book_name="", book_status="",
        action=ActionType.COLLECT, scheduled_date=date(2025, 12, 8),
        scheduled_time=time(9, 0), scheduled_datetime=datetime(2025, 12, 8, 9, 0),
        time_offset_minutes=540, window_start_t=window_start, window_end_t=window_end,
        vehicle_reg="VAN1", vehicle_group="V3",
        target_location=loc, notes="",
    )


def _make_tba_deliver(
    job_id: str, loc: Location, group: str = "V3",
    window_start: int = 480, window_end: int = 600,
) -> Job:
    return Job(
        job_id=job_id, book_no=f"B{job_id}", order_ref="", rental_no="",
        book_name="", book_status="",
        action=ActionType.DELIVER, scheduled_date=date(2025, 12, 8),
        scheduled_time=time(9, 0), scheduled_datetime=datetime(2025, 12, 8, 9, 0),
        time_offset_minutes=540, window_start_t=window_start, window_end_t=window_end,
        vehicle_reg=None, vehicle_group=group,
        target_location=loc, notes="",
    )


def _make_instance(
    drivers: list[Driver],
    jobs: list[Job],
    driver_job_arcs: list[DriverJobArc],
    job_chain_arcs: list[JobChainArc] | None = None,
    vehicles: list[Vehicle] | None = None,
    vehicle_job_arcs: list[VehicleJobArc] | None = None,
) -> ProblemInstance:
    return ProblemInstance(
        horizon=HORIZON, jobs=jobs, drivers=drivers,
        vehicles=vehicles or [],
        storage_locations=[], vehicle_group_certs={},
        transit_matrix=MATRIX,
        driver_job_arcs=driver_job_arcs,
        job_chain_arcs=job_chain_arcs or [],
        vehicle_job_arcs=vehicle_job_arcs or [],
    )


# --- Basic feasibility ---

def test_solve_basic_feasible():
    """Two non-overlapping jobs, one driver — should be FEASIBLE."""
    d1 = _make_driver("D1")
    j1 = _make_job("J1", LOC_B, window_start=480, window_end=540)
    j2 = _make_job("J2", LOC_B, window_start=600, window_end=660)
    arcs = [
        DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=30, return_deadhead_minutes=30),
        DriverJobArc(driver_id="D1", job_id="J2", deadhead_minutes=30, return_deadhead_minutes=30),
    ]
    chains = [
        JobChainArc(from_job_id="J1", to_job_id="J2", chain_type="driver_only",
                    travel_minutes=0, turnaround_minutes=0),
        JobChainArc(from_job_id="J2", to_job_id="J1", chain_type="driver_only",
                    travel_minutes=0, turnaround_minutes=0),
    ]
    result = solve(_make_instance([d1], [j1, j2], arcs, chains))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 2
    assert {a.job_id for a in result.assignments} == {"J1", "J2"}


def test_solve_multi_driver():
    """Two jobs at distant locations, no chain arc — requires two drivers."""
    d1 = _make_driver("D1", LOC_A)
    d2 = _make_driver("D2", LOC_B)
    j1 = _make_job("J1", LOC_B, window_start=480, window_end=540)
    j2 = _make_job("J2", LOC_C, window_start=480, window_end=540)
    arcs = [
        DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=30, return_deadhead_minutes=30),
        DriverJobArc(driver_id="D1", job_id="J2", deadhead_minutes=40, return_deadhead_minutes=40),
        DriverJobArc(driver_id="D2", job_id="J1", deadhead_minutes=0, return_deadhead_minutes=0),
        DriverJobArc(driver_id="D2", job_id="J2", deadhead_minutes=50, return_deadhead_minutes=50),
    ]
    # No chain arcs — mutual exclusion per driver. Each driver can do at most 1.
    # With 2 jobs and 2 drivers, this is FEASIBLE.
    result = solve(_make_instance([d1, d2], [j1, j2], arcs, job_chain_arcs=[]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 2
    drivers_used = {a.driver_id for a in result.assignments}
    assert len(drivers_used) == 2


# --- Infeasibility ---

def test_solve_mutual_exclusion_no_chain_arc():
    """Two overlapping jobs, one driver, NO chain arc — INFEASIBLE.
    Mutual exclusion (x[d,i] + x[d,j] <= 1) conflicts with both-must-be-assigned."""
    d1 = _make_driver("D1")
    j1 = _make_job("J1", LOC_B, window_start=480, window_end=540)
    j2 = _make_job("J2", LOC_C, window_start=480, window_end=540)
    arcs = [
        DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=30, return_deadhead_minutes=30),
        DriverJobArc(driver_id="D1", job_id="J2", deadhead_minutes=40, return_deadhead_minutes=40),
    ]
    result = solve(_make_instance([d1], [j1, j2], arcs, job_chain_arcs=[]))
    assert result.status == "INFEASIBLE"
    assert result.assignments == []


def test_solve_deadhead_too_late():
    """Deadhead exceeds job window — INFEASIBLE."""
    d1 = _make_driver("D1")
    j1 = _make_job("J1", LOC_B, window_start=480, window_end=490)
    arcs = [
        DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=500, return_deadhead_minutes=30),
    ]
    result = solve(_make_instance([d1], [j1], arcs))
    assert result.status == "INFEASIBLE"


def test_solve_strict_order_enforced():
    """Chain arc only J1->J2, travel 50 min, windows too tight — INFEASIBLE."""
    d1 = _make_driver("D1")
    j1 = _make_job("J1", LOC_B, window_start=480, window_end=490)
    j2 = _make_job("J2", LOC_C, window_start=480, window_end=490)
    arcs = [
        DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=30, return_deadhead_minutes=30),
        DriverJobArc(driver_id="D1", job_id="J2", deadhead_minutes=40, return_deadhead_minutes=40),
    ]
    chains = [
        JobChainArc(from_job_id="J1", to_job_id="J2", chain_type="driver_only",
                    travel_minutes=50, turnaround_minutes=0),
    ]
    result = solve(_make_instance([d1], [j1, j2], arcs, chains))
    assert result.status == "INFEASIBLE"


# --- Disjunctive sequence ---

def test_solve_disjunctive_sequence():
    """Chain arcs in BOTH directions, wide windows — FEASIBLE, solver picks order."""
    d1 = _make_driver("D1")
    j1 = _make_job("J1", LOC_B, window_start=480, window_end=700)
    j2 = _make_job("J2", LOC_C, window_start=480, window_end=700)
    arcs = [
        DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=30, return_deadhead_minutes=30),
        DriverJobArc(driver_id="D1", job_id="J2", deadhead_minutes=40, return_deadhead_minutes=40),
    ]
    chains = [
        JobChainArc(from_job_id="J1", to_job_id="J2", chain_type="driver_only",
                    travel_minutes=50, turnaround_minutes=0),
        JobChainArc(from_job_id="J2", to_job_id="J1", chain_type="driver_only",
                    travel_minutes=50, turnaround_minutes=0),
    ]
    result = solve(_make_instance([d1], [j1, j2], arcs, chains))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 2
    starts = {a.job_id: a.start_time_t for a in result.assignments}
    gap = abs(starts["J1"] - starts["J2"])
    assert gap >= 50


# --- start_datetime extraction ---

def test_solve_start_datetime_correct():
    """Verify start_datetime is correctly derived from start_time_t and horizon."""
    d1 = _make_driver("D1")
    j1 = _make_job("J1", LOC_B, window_start=540, window_end=540)  # Exactly 09:00
    arcs = [DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=0, return_deadhead_minutes=30)]
    result = solve(_make_instance([d1], [j1], arcs, []))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    a = result.assignments[0]
    assert a.start_time_t == 540
    assert a.start_datetime == datetime(2025, 12, 8, 9, 0)


# --- Integration test ---

# --- Driver shift span ---

def test_solve_shift_span_within_limit():
    """One job, deadhead 30 + service 0 + return 30 = 60 min span.
    Driver max_hours_per_day=600. FEASIBLE."""
    d1 = _make_driver("D1")  # max_hours_per_day=600
    j1 = _make_job("J1", LOC_B, window_start=480, window_end=540)
    arcs = [DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=30, return_deadhead_minutes=30)]
    result = solve(_make_instance([d1], [j1], arcs, []))
    assert result.status in ("OPTIMAL", "FEASIBLE")


def test_solve_shift_span_exceeds_limit():
    """One job at LOC_B. Deadhead=30, return=30, job starts at 480.
    Shift span = (480 + 0 + 30) - (480 - 30) = 60 min.
    But if we set max_hours_per_day=50, the 60 min span exceeds it. INFEASIBLE."""
    d1 = Driver(
        driver_id="D1", name="D1", home_location=LOC_A,
        branch="TEST", max_hours_per_day=50, certifications=CertLevel.VAN,
        can_overnight=True, unavailable_dates=frozenset(),
    )
    j1 = _make_job("J1", LOC_B, window_start=480, window_end=540)
    arcs = [DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=30, return_deadhead_minutes=30)]
    result = solve(_make_instance([d1], [j1], arcs, []))
    assert result.status == "INFEASIBLE"


def test_solve_shift_span_two_jobs_feasible():
    """Two jobs, same location. D1 leaves at (480-30)=450, returns at (660+0+30)=690.
    Span=240 min. max_hours_per_day=600. FEASIBLE."""
    d1 = _make_driver("D1")
    j1 = _make_job("J1", LOC_B, window_start=480, window_end=540)
    j2 = _make_job("J2", LOC_B, window_start=600, window_end=660)
    arcs = [
        DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=30, return_deadhead_minutes=30),
        DriverJobArc(driver_id="D1", job_id="J2", deadhead_minutes=30, return_deadhead_minutes=30),
    ]
    chains = [
        JobChainArc(from_job_id="J1", to_job_id="J2", chain_type="driver_only",
                    travel_minutes=0, turnaround_minutes=0),
        JobChainArc(from_job_id="J2", to_job_id="J1", chain_type="driver_only",
                    travel_minutes=0, turnaround_minutes=0),
    ]
    result = solve(_make_instance([d1], [j1, j2], arcs, chains))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 2


def test_solve_shift_span_two_jobs_exceeds():
    """Two jobs spread far apart in time. J1@480, J2@1200 (8pm).
    Shift span: (1200 + 0 + 30) - (480 - 30) = 780 min.
    max_hours_per_day=600. INFEASIBLE for one driver — but 2 drivers available."""
    d1 = _make_driver("D1")
    d2 = _make_driver("D2")
    j1 = _make_job("J1", LOC_B, window_start=480, window_end=540)
    j2 = _make_job("J2", LOC_B, window_start=1200, window_end=1260)
    arcs = [
        DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=30, return_deadhead_minutes=30),
        DriverJobArc(driver_id="D1", job_id="J2", deadhead_minutes=30, return_deadhead_minutes=30),
        DriverJobArc(driver_id="D2", job_id="J1", deadhead_minutes=30, return_deadhead_minutes=30),
        DriverJobArc(driver_id="D2", job_id="J2", deadhead_minutes=30, return_deadhead_minutes=30),
    ]
    chains = [
        JobChainArc(from_job_id="J1", to_job_id="J2", chain_type="driver_only",
                    travel_minutes=0, turnaround_minutes=0),
        JobChainArc(from_job_id="J2", to_job_id="J1", chain_type="driver_only",
                    travel_minutes=0, turnaround_minutes=0),
    ]
    result = solve(_make_instance([d1, d2], [j1, j2], arcs, chains))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 2
    # Each driver should do exactly 1 job (can't combine due to shift limit)
    drivers_used = {a.driver_id for a in result.assignments}
    assert len(drivers_used) == 2


# --- TBA vehicle assignment ---

def test_solve_tba_depot_vehicle():
    """TBA deliver job with a matching depot vehicle — FEASIBLE."""
    d1 = _make_driver("D1")
    j1 = _make_tba_deliver("J1", LOC_B)
    v1 = Vehicle(reg="VAN1", group="V3", current_location=LOC_A,
                 available_from=date(2025, 12, 8), available_from_t=0)
    arcs = [DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=30, return_deadhead_minutes=30)]
    v_arcs = [VehicleJobArc(vehicle_reg="VAN1", job_id="J1", driving_minutes=30, earliest_arrival_t=30)]
    result = solve(_make_instance([d1], [j1], arcs, [], [v1], v_arcs))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 1


def test_solve_tba_no_vehicle_infeasible():
    """TBA deliver job with no depot vehicle and no chain — INFEASIBLE."""
    d1 = _make_driver("D1")
    j1 = _make_tba_deliver("J1", LOC_B)
    arcs = [DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=30, return_deadhead_minutes=30)]
    # No vehicles, no vehicle arcs, no VEHICLE_DRIVER chains
    result = solve(_make_instance([d1], [j1], arcs, [], [], []))
    assert result.status == "INFEASIBLE"


def test_solve_tba_vehicle_driver_chain():
    """TBA deliver served by VEHICLE_DRIVER chain from a collect — no depot vehicle needed."""
    d1 = _make_driver("D1")
    # Collect job (has a reg) at LOC_B
    j_collect = Job(
        job_id="JC", book_no="BC", order_ref="", rental_no="",
        book_name="", book_status="",
        action=ActionType.COLLECT, scheduled_date=date(2025, 12, 8),
        scheduled_time=time(9, 0), scheduled_datetime=datetime(2025, 12, 8, 9, 0),
        time_offset_minutes=540, window_start_t=480, window_end_t=540,
        vehicle_reg="VAN1", vehicle_group="V3",
        target_location=LOC_B, notes="",
    )
    # TBA deliver at LOC_C — same group, no reg
    j_deliver = _make_tba_deliver("JD", LOC_C, group="V3", window_start=600, window_end=700)

    arcs = [
        DriverJobArc(driver_id="D1", job_id="JC", deadhead_minutes=30, return_deadhead_minutes=30),
        DriverJobArc(driver_id="D1", job_id="JD", deadhead_minutes=40, return_deadhead_minutes=40),
    ]
    chains = [
        # DRIVER_ONLY arc (for Constraint 3 sequencing)
        JobChainArc(from_job_id="JC", to_job_id="JD", chain_type="driver_only",
                    travel_minutes=50, turnaround_minutes=0),
        # VEHICLE_DRIVER arc: collect VAN1 at LOC_B, deliver at LOC_C
        JobChainArc(from_job_id="JC", to_job_id="JD", chain_type="vehicle_driver",
                    travel_minutes=30, turnaround_minutes=45),
    ]
    # No depot vehicles — the van comes from the collect chain
    result = solve(_make_instance([d1], [j_collect, j_deliver], arcs, chains, [], []))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 2


def test_solve_tba_depot_vehicle_one_each():
    """Two TBA jobs, one depot vehicle — one must get vehicle, other needs a chain.
    Without a chain for the second, INFEASIBLE."""
    d1 = _make_driver("D1")
    d2 = _make_driver("D2")
    j1 = _make_tba_deliver("J1", LOC_B, window_start=480, window_end=540)
    j2 = _make_tba_deliver("J2", LOC_C, window_start=480, window_end=540)
    v1 = Vehicle(reg="VAN1", group="V3", current_location=LOC_A,
                 available_from=date(2025, 12, 8), available_from_t=0)
    arcs = [
        DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=30, return_deadhead_minutes=30),
        DriverJobArc(driver_id="D1", job_id="J2", deadhead_minutes=40, return_deadhead_minutes=40),
        DriverJobArc(driver_id="D2", job_id="J1", deadhead_minutes=30, return_deadhead_minutes=30),
        DriverJobArc(driver_id="D2", job_id="J2", deadhead_minutes=40, return_deadhead_minutes=40),
    ]
    # Only one depot vehicle, for J1 only
    v_arcs = [VehicleJobArc(vehicle_reg="VAN1", job_id="J1", driving_minutes=30, earliest_arrival_t=30)]
    # No chains — J2 has no van source. INFEASIBLE.
    result = solve(_make_instance([d1, d2], [j1, j2], arcs, [], [v1], v_arcs))
    assert result.status == "INFEASIBLE"


# --- Integration test ---

def test_solve_real_sample_data():
    """Integration: build from real CSVs and solve. Must find a feasible schedule."""
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

    solver_result = solve(inst, timeout_seconds=60)
    assert solver_result.status in ("OPTIMAL", "FEASIBLE"), (
        f"Solver returned {solver_result.status} on sample data"
    )
    assert len(solver_result.assignments) == len(inst.jobs)
    assigned_job_ids = {a.job_id for a in solver_result.assignments}
    expected_job_ids = {j.job_id for j in inst.jobs}
    assert assigned_job_ids == expected_job_ids
