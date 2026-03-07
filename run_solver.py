#!/usr/bin/env python3
"""Run the full pipeline: build problem, solve, print schedule, export CSV."""

from datetime import date
from pathlib import Path

from scheduler.builder import ProblemBuilder
from scheduler.solver import solve
from scheduler.exporter import print_schedule, export_csv, export_json

ROOT = Path(__file__).resolve().parent
REF = ROOT / "ref-data"
INPUT = ROOT / "input"
OUTPUT = ROOT / "output"


def main():
    # Build
    print("Building problem instance...")
    result = (
        ProblemBuilder(horizon_start=date(2025, 12, 8), num_days=5)
        .load_postcode_coords(REF / "postcode_coords.csv")
        .load_storage_locations(REF / "storage_locations.csv")
        .load_drivers(REF / "drivers.csv")
        .load_vehicles(REF / "vehicle_inventory.csv")
        .load_bookings(INPUT / "sample_bookings_data.csv")
        .build()
    )
    if not result.ok:
        print("BUILD FAILED:")
        for issue in result.report.issues:
            if issue.severity == "error":
                print(f"  {issue.message}")
        return

    inst = result.instance
    print(f"Built: {len(inst.jobs)} jobs, {len(inst.drivers)} drivers, "
          f"{len(inst.driver_job_arcs)} driver-job arcs, "
          f"{len(inst.job_chain_arcs)} chain arcs")

    # Solve
    print("\nSolving...")
    solver_result = solve(inst, timeout_seconds=300)

    # Print
    print_schedule(solver_result, inst)

    # Export CSV
    if solver_result.status in ("OPTIMAL", "FEASIBLE"):
        OUTPUT.mkdir(exist_ok=True)
        output_path = OUTPUT / "schedule.csv"
        export_csv(solver_result, inst, INPUT / "sample_bookings_data.csv", output_path)
        print(f"\nCSV exported to: {output_path}")
        json_path = OUTPUT / "schedule.json"
        export_json(solver_result, inst, json_path)
        print(f"JSON exported to: {json_path}")


if __name__ == "__main__":
    main()
