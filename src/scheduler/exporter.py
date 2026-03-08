"""Output formatters: console summary, CSV export, and JSON route export."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from scheduler.models import ProblemInstance, SolverResult


def print_schedule(result: SolverResult, instance: ProblemInstance) -> None:
    """Print a human-readable schedule to stdout."""
    print(f"\n=== Solver Status: {result.status} ===")
    print(f"Solve time: {result.solve_time_seconds:.3f}s")

    if not result.assignments:
        print("No assignments.")
        return

    jobs_by_id = {j.job_id: j for j in instance.jobs}
    drivers_by_id = {d.driver_id: d for d in instance.drivers}

    by_driver: dict[str, list] = defaultdict(list)
    for a in result.assignments:
        by_driver[a.driver_id].append(a)

    for driver_id in sorted(by_driver):
        driver = drivers_by_id[driver_id]
        assignments = sorted(by_driver[driver_id], key=lambda a: a.start_time_t)
        print(f"\n--- {driver.name} ({driver_id}) ---")
        for a in assignments:
            job = jobs_by_id[a.job_id]
            dt = a.start_datetime.strftime("%Y-%m-%d %H:%M")
            print(f"  [{dt}] {job.action.value.upper()} {job.vehicle_group} @ {job.target_location.postcode}")

    drivers_used = len(by_driver)
    print(f"\n--- Summary ---")
    print(f"Jobs assigned: {len(result.assignments)}")
    print(f"Drivers used: {drivers_used} / {len(instance.drivers)}")
    print(f"Solve time: {result.solve_time_seconds:.3f}s")


def export_csv(
    result: SolverResult,
    instance: ProblemInstance,
    input_csv_path: Path,
    output_csv_path: Path,
) -> None:
    """Write a copy of the input CSV with the Drivers column filled in."""
    if not result.assignments:
        return

    jobs_by_id = {j.job_id: j for j in instance.jobs}
    drivers_by_id = {d.driver_id: d for d in instance.drivers}
    assignment_by_job_id = {a.job_id: a for a in result.assignments}

    book_no_to_driver: dict[str, str] = {}
    for job_id, assignment in assignment_by_job_id.items():
        job = jobs_by_id[job_id]
        driver = drivers_by_id[assignment.driver_id]
        book_no_to_driver[job.book_no] = driver.name

    with open(input_csv_path, newline="") as fin:
        reader = csv.DictReader(fin)
        fieldnames = reader.fieldnames
        rows = list(reader)

    with open(output_csv_path, "w", newline="") as fout:
        writer = csv.DictWriter(fout, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            book_no = row.get("Book No.", "").strip()
            driver_name = book_no_to_driver.get(book_no, "")
            row["Drivers"] = driver_name
            writer.writerow(row)


def export_json(
    result: SolverResult,
    instance: ProblemInstance,
    output_json_path: Path,
) -> None:
    """Write a structured JSON file with full route data for the HTML report."""
    jobs_by_id = {j.job_id: j for j in instance.jobs}
    drivers_by_id = {d.driver_id: d for d in instance.drivers}

    # Build job lookup keyed by book_no for the report to cross-reference
    job_info = {}
    for j in instance.jobs:
        job_info[j.job_id] = {
            "job_id": j.job_id,
            "book_no": j.book_no,
            "action": j.action.value,
            "postcode": j.target_location.postcode,
            "vehicle_reg": j.vehicle_reg,
            "vehicle_group": j.vehicle_group,
            "scheduled_time": j.scheduled_time.strftime("%H:%M") if j.scheduled_time else None,
            "scheduled_date": j.scheduled_date.isoformat() if j.scheduled_date else None,
        }

    # Build assignment lookup: job_id -> start_datetime
    assignment_times = {
        a.job_id: a.start_datetime.strftime("%Y-%m-%d %H:%M")
        for a in result.assignments
    }

    routes_out = []
    for route in result.driver_routes:
        legs_out = []
        for leg in route.legs:
            leg_dict = {
                "from_postcode": leg.from_postcode,
                "to_postcode": leg.to_postcode,
                "mode": leg.mode,
                "duration_minutes": leg.duration_minutes,
                "job_id": leg.job_id,
                "vehicle_reg": leg.vehicle_reg,
            }
            if leg.depot_name:
                leg_dict["depot_name"] = leg.depot_name
            if leg.via_depot_postcode:
                leg_dict["via_depot"] = {
                    "postcode": leg.via_depot_postcode,
                    "transit_minutes": leg.via_depot_transit_minutes,
                    "driving_minutes": leg.via_depot_driving_minutes,
                }
            # Attach job details inline for convenience
            if leg.job_id and leg.job_id in job_info:
                leg_dict["job"] = job_info[leg.job_id]
                leg_dict["job"]["start_time"] = assignment_times.get(leg.job_id)
            legs_out.append(leg_dict)

        routes_out.append({
            "driver_id": route.driver_id,
            "driver_name": route.driver_name,
            "home_postcode": route.home_postcode,
            "deadhead_minutes_total": route.deadhead_minutes_total,
            "legs": legs_out,
        })

    output = {
        "status": result.status,
        "solve_time_seconds": result.solve_time_seconds,
        "horizon_start": instance.horizon.start_date.isoformat(),
        "jobs": job_info,
        "unassigned_job_ids": result.unassigned_job_ids,
        "driver_routes": routes_out,
    }

    with open(output_json_path, "w") as f:
        json.dump(output, f, indent=2)
