import csv
from datetime import date, time, datetime
from pathlib import Path

from scheduler.models import (
    ActionType, CertLevel, Driver, HorizonConfig, Job, JobAssignment,
    Location, ProblemInstance, SolverResult, TransitMatrix,
    DriverJobArc, JobChainArc, VehicleJobArc,
)
from scheduler.exporter import print_schedule, export_csv


LOC_A = Location(postcode="AA1 1AA", lat=51.5, lon=-0.1)

INSTANCE = ProblemInstance(
    horizon=HorizonConfig(start_date=date(2025, 12, 8), num_days=1, t_max=1440),
    jobs=[
        Job(job_id="J1", book_no="B001", order_ref="", rental_no="",
            book_name="Smith", book_status="", action=ActionType.COLLECT,
            scheduled_date=date(2025, 12, 8), scheduled_time=time(9, 0),
            scheduled_datetime=datetime(2025, 12, 8, 9, 0),
            time_offset_minutes=540, window_start_t=480, window_end_t=600,
            vehicle_reg="VAN1", vehicle_group="V3", target_location=LOC_A, notes=""),
    ],
    drivers=[
        Driver(driver_id="D1", name="Alice", home_location=LOC_A,
               branch="TEST", max_hours_per_day=600, certifications=CertLevel.VAN,
               can_overnight=True, unavailable_dates=frozenset()),
    ],
    vehicles=[], storage_locations=[], vehicle_group_certs={},
    transit_matrix=TransitMatrix(entries={}),
    driver_job_arcs=[], job_chain_arcs=[], vehicle_job_arcs=[],
)


def test_print_schedule_runs(capsys):
    solver_result = SolverResult(
        status="FEASIBLE", solve_time_seconds=0.5,
        assignments=[
            JobAssignment(job_id="J1", driver_id="D1", start_time_t=540,
                          start_datetime=datetime(2025, 12, 8, 9, 0)),
        ],
        stats={"variables": 10, "constraints": 5},
    )
    print_schedule(solver_result, INSTANCE)
    captured = capsys.readouterr()
    assert "FEASIBLE" in captured.out
    assert "Alice" in captured.out
    assert "COLLECT" in captured.out
    assert "AA1 1AA" in captured.out


def test_print_schedule_infeasible(capsys):
    solver_result = SolverResult(
        status="INFEASIBLE", solve_time_seconds=0.1,
        assignments=[], stats={},
    )
    print_schedule(solver_result, INSTANCE)
    captured = capsys.readouterr()
    assert "INFEASIBLE" in captured.out


def test_export_csv(tmp_path):
    """Export a solved schedule to CSV. The Drivers column should be filled in."""
    input_csv = tmp_path / "bookings.csv"
    input_csv.write_text(
        "Book No.,Order ref:,Rental No.,Book Name,Book Status,"
        "Date,Time,Action,Reg No.,Supp'd Grp,Drivers,"
        "Delivery postcode,Collection postcode,Notes\n"
        "B001,,,,Confirmed,"
        "08/12/2025,09:00,Collect,VAN1,V3,,"
        "AA1 1AA,,\n"
        "B999,,,,Confirmed,"
        "08/12/2025,10:00,Deliver,VAN2,V3,,"
        "BB2 2BB,,\n"
    )
    solver_result = SolverResult(
        status="FEASIBLE", solve_time_seconds=0.5,
        assignments=[
            JobAssignment(job_id="J1", driver_id="D1", start_time_t=540,
                          start_datetime=datetime(2025, 12, 8, 9, 0)),
        ],
        stats={},
    )
    output_csv = tmp_path / "output.csv"
    export_csv(solver_result, INSTANCE, input_csv, output_csv)

    with open(output_csv) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert rows[0]["Drivers"] == "Alice"
    assert rows[1]["Drivers"] == ""
