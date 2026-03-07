"""Output formatters: console summary and CSV export."""

from __future__ import annotations

import csv
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
