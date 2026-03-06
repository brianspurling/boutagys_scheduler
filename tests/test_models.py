from datetime import date, time, datetime

from scheduler.models import (
    CertLevel, ActionType, ChainType, Location,
    StorageLocation, Driver, Vehicle, Job,
    DriverJobArc, VehicleJobArc, JobChainArc,
    TransitPair, TransitMatrix, HorizonConfig,
    ValidationIssue, ValidationReport,
    ProblemInstance, BuildResult,
)
import pytest


def test_cert_level_values():
    assert CertLevel.VAN == "van"
    assert CertLevel.VAN_TRUCK == "van_truck"


def test_action_type_values():
    assert ActionType.COLLECT == "collect"
    assert ActionType.DELIVER == "deliver"


def test_chain_type_values():
    assert ChainType.DRIVER_ONLY == "driver_only"
    assert ChainType.VEHICLE_DRIVER == "vehicle_driver"


def test_location_is_frozen():
    loc = Location(postcode="SW15 2SW", lat=51.4576, lon=-0.2289)
    assert loc.postcode == "SW15 2SW"
    assert loc.lat == 51.4576
    assert loc.lon == -0.2289
    with pytest.raises(Exception):
        loc.postcode = "X"


def test_storage_location():
    loc = Location(postcode="TW14 9DF", lat=51.4502, lon=-0.4084)
    sl = StorageLocation(
        location_id="S001",
        name="Feltham",
        location=loc,
        capacity=30,
        restricted_groups=set(),
    )
    assert sl.location_id == "S001"
    assert sl.capacity == 30
    assert sl.restricted_groups == set()


def test_driver():
    d = Driver(
        driver_id="D001",
        name="Jassim",
        home_location=Location(postcode="W2 1NY", lat=51.5154, lon=-0.1784),
        branch="PUTNEY",
        max_hours_per_day=600,
        certifications=CertLevel.VAN,
        can_overnight=True,
        unavailable_dates=frozenset(),
    )
    assert d.max_hours_per_day == 600
    assert d.certifications == CertLevel.VAN


def test_driver_with_unavailable_dates():
    d = Driver(
        driver_id="D003",
        name="Attila",
        home_location=Location(postcode="CV21 3DH", lat=52.3706, lon=-1.2634),
        branch="PUTNEY",
        max_hours_per_day=600,
        certifications=CertLevel.VAN,
        can_overnight=True,
        unavailable_dates=frozenset({date(2025, 12, 10)}),
    )
    assert date(2025, 12, 10) in d.unavailable_dates


def test_vehicle():
    v = Vehicle(
        reg="MK22EEA",
        group="V3",
        current_location=Location(postcode="TW14 9DF", lat=51.4502, lon=-0.4084),
        available_from=date(2025, 12, 8),
        available_from_t=0,
    )
    assert v.reg == "MK22EEA"
    assert v.available_from_t == 0


def test_job():
    j = Job(
        job_id="J001",
        book_no="#35937429",
        order_ref="NW94402872",
        rental_no="8073133",
        book_name="NATIONWIDE HIRE UK",
        book_status="ON HIRE",
        action=ActionType.COLLECT,
        scheduled_date=date(2025, 12, 8),
        scheduled_time=time(9, 0),
        scheduled_datetime=datetime(2025, 12, 8, 9, 0),
        time_offset_minutes=540,
        window_start_t=480,
        window_end_t=600,
        vehicle_reg="SM73ZRL",
        vehicle_group="V2",
        target_location=Location(postcode="TW11 8QA", lat=51.4264, lon=-0.3280),
        notes="",
    )
    assert j.action == ActionType.COLLECT
    assert j.vehicle_reg == "SM73ZRL"
    assert j.window_start_t == 480
    assert j.window_end_t == 600


def test_job_tba_vehicle():
    j = Job(
        job_id="J002",
        book_no="",
        order_ref="NW667AFF49",
        rental_no="",
        book_name="NATIONWIDE HIRE UK",
        book_status="BOOKING",
        action=ActionType.DELIVER,
        scheduled_date=date(2025, 12, 8),
        scheduled_time=time(9, 30),
        scheduled_datetime=datetime(2025, 12, 8, 9, 30),
        time_offset_minutes=570,
        window_start_t=510,
        window_end_t=630,
        vehicle_reg=None,
        vehicle_group="V2",
        target_location=Location(postcode="KT6 7NS", lat=51.3897, lon=-0.3000),
        notes="",
    )
    assert j.vehicle_reg is None


def test_driver_job_arc():
    arc = DriverJobArc(driver_id="D001", job_id="J001", deadhead_minutes=45)
    assert arc.deadhead_minutes == 45


def test_vehicle_job_arc():
    arc = VehicleJobArc(vehicle_reg="MK22EEA", job_id="J002", driving_minutes=30)
    assert arc.driving_minutes == 30


def test_job_chain_arc_driver_only():
    arc = JobChainArc(
        from_job_id="J001",
        to_job_id="J003",
        chain_type=ChainType.DRIVER_ONLY,
        travel_minutes=25,
        turnaround_minutes=0,
    )
    assert arc.turnaround_minutes == 0


def test_job_chain_arc_vehicle_driver():
    arc = JobChainArc(
        from_job_id="J001",
        to_job_id="J002",
        chain_type=ChainType.VEHICLE_DRIVER,
        travel_minutes=20,
        turnaround_minutes=45,
    )
    assert arc.turnaround_minutes == 45


def test_transit_matrix_get():
    matrix = TransitMatrix(entries={
        ("SW15 2SW", "TW14 9DF"): TransitPair(transit_minutes=55, driving_minutes=35),
    })
    loc_a = Location(postcode="SW15 2SW", lat=51.4576, lon=-0.2289)
    loc_b = Location(postcode="TW14 9DF", lat=51.4502, lon=-0.4084)
    pair = matrix.get(loc_a, loc_b)
    assert pair is not None
    assert pair.transit_minutes == 55
    assert pair.driving_minutes == 35
    assert matrix.get(loc_b, loc_a) is None


def test_transit_matrix_self_loop():
    """Same postcode should return zero-cost TransitPair without needing a dict entry."""
    matrix = TransitMatrix(entries={})
    loc = Location(postcode="SW15 2SW", lat=51.4576, lon=-0.2289)
    pair = matrix.get(loc, loc)
    assert pair is not None
    assert pair.transit_minutes == 0
    assert pair.driving_minutes == 0


def test_horizon_config():
    h = HorizonConfig(start_date=date(2025, 12, 8), num_days=5, t_max=7200)
    assert h.t_max == 5 * 1440


def test_validation_report_has_errors():
    report_clean = ValidationReport(issues=[], stats={"total_jobs": 10})
    assert not report_clean.has_errors

    report_bad = ValidationReport(
        issues=[ValidationIssue(severity="error", category="unknown_group", message="X", source_row=5)],
        stats={"total_jobs": 10},
    )
    assert report_bad.has_errors


def test_build_result_ok():
    report = ValidationReport(issues=[], stats={})
    result_none = BuildResult(instance=None, report=report)
    assert not result_none.ok
