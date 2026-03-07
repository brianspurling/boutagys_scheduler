from pathlib import Path
from datetime import date

from scheduler.builder import ProblemBuilder

ROOT = Path(__file__).resolve().parent.parent
INPUT = ROOT / "input"
REF = ROOT / "ref-data"


def _build():
    return (
        ProblemBuilder(horizon_start=date(2025, 12, 8), num_days=5)
        .load_postcode_coords(REF / "postcode_coords.csv")
        .load_storage_locations(REF / "storage_locations.csv")
        .load_drivers(REF / "drivers.csv")
        .load_vehicles(REF / "vehicle_inventory.csv")
        .load_bookings(INPUT / "sample_bookings_data.csv")
        .build()
    )


def test_builder_loads_and_builds():
    result = _build()
    assert result.ok
    inst = result.instance
    assert inst is not None
    assert len(inst.drivers) == 20
    assert len(inst.storage_locations) == 3
    assert len(inst.vehicles) > 0
    assert len(inst.jobs) > 0


def test_builder_time_offsets():
    result = _build()
    inst = result.instance
    day1_9am_jobs = [
        j for j in inst.jobs
        if j.scheduled_date == date(2025, 12, 8)
        and j.scheduled_time is not None
        and j.scheduled_time.hour == 9
        and j.scheduled_time.minute == 0
    ]
    assert len(day1_9am_jobs) > 0
    for j in day1_9am_jobs:
        assert j.time_offset_minutes == 540


def test_builder_time_windows():
    result = _build()
    for j in result.instance.jobs:
        assert j.window_start_t < j.window_end_t, f"Job {j.job_id} has invalid window"


def test_builder_vehicle_available_from_t():
    result = _build()
    for v in result.instance.vehicles:
        if v.available_from <= date(2025, 12, 8):
            assert v.available_from_t == 0
        else:
            assert v.available_from_t > 0


def test_builder_validation_report_stats():
    result = _build()
    assert "total_jobs" in result.report.stats
    assert "total_drivers" in result.report.stats
    assert "total_vehicles" in result.report.stats


def test_builder_no_unknown_vehicle_group_errors():
    result = _build()
    group_errors = [
        i for i in result.report.issues if i.category == "unknown_vehicle_group"
    ]
    assert len(group_errors) == 0


def test_builder_has_arcs():
    result = _build()
    inst = result.instance
    assert len(inst.driver_job_arcs) > 0
    assert len(inst.job_chain_arcs) > 0
    assert isinstance(inst.vehicle_job_arcs, list)


def test_builder_arc_stats():
    result = _build()
    assert "driver_job_arcs" in result.report.stats
    assert "job_chain_arcs" in result.report.stats
    assert "vehicle_job_arcs" in result.report.stats


def test_builder_no_excluded_jobs_in_instance():
    result = _build()
    inst = result.instance
    arc_job_ids = {arc.job_id for arc in inst.driver_job_arcs}
    for j in inst.jobs:
        assert j.job_id in arc_job_ids, f"Job {j.job_id} has no driver arcs but is in instance"
