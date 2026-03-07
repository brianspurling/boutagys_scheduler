"""CP-SAT solver: bare-minimum feasible schedule."""

from __future__ import annotations

import time as time_mod
from collections import defaultdict
from datetime import datetime, time, timedelta

from ortools.sat.python import cp_model

from scheduler.models import (
    HorizonConfig, JobAssignment, ProblemInstance, SolverResult,
)

_SERVICE_TIME = 0


def _t_to_datetime(t: int, horizon: HorizonConfig) -> datetime:
    """Convert integer minutes from horizon start to a datetime."""
    day_offset, minutes_in_day = divmod(t, 1440)
    actual_date = horizon.start_date + timedelta(days=day_offset)
    actual_time = time(minutes_in_day // 60, minutes_in_day % 60)
    return datetime.combine(actual_date, actual_time)


def solve(instance: ProblemInstance, timeout_seconds: int = 300) -> SolverResult:
    """Build and solve the CP-SAT model. Returns SolverResult."""
    start_wall = time_mod.monotonic()

    model = cp_model.CpModel()
    jobs_by_id = {j.job_id: j for j in instance.jobs}

    # --- Index arcs ---
    # driver_id -> list of (job_id, deadhead_minutes, return_deadhead_minutes)
    driver_arcs: dict[str, list[tuple[str, int, int]]] = defaultdict(list)
    for arc in instance.driver_job_arcs:
        driver_arcs[arc.driver_id].append((arc.job_id, arc.deadhead_minutes, arc.return_deadhead_minutes))

    # job_id -> list of driver_ids that can serve it
    job_drivers: dict[str, list[str]] = defaultdict(list)
    for arc in instance.driver_job_arcs:
        job_drivers[arc.job_id].append(arc.driver_id)

    # Min-Time Arc Consolidation: for each directed pair, take the fastest
    # option across both chain types. DRIVER_ONLY uses transit_minutes
    # (turnaround is 0); VEHICLE_DRIVER uses driving_minutes + turnaround.
    chain_lookup: dict[tuple[str, str], int] = {}
    for arc in instance.job_chain_arcs:
        key = (arc.from_job_id, arc.to_job_id)
        effective_time = arc.travel_minutes + arc.turnaround_minutes
        if key not in chain_lookup or effective_time < chain_lookup[key]:
            chain_lookup[key] = effective_time

    # --- Variables ---
    # x[driver_id, job_id] = BoolVar: assignment
    x: dict[tuple[str, str], cp_model.IntVar] = {}
    # start[driver_id, job_id] = IntVar: service start time
    start: dict[tuple[str, str], cp_model.IntVar] = {}
    # interval[driver_id, job_id] = IntervalVar: optional service interval
    intervals: dict[str, list[cp_model.IntervalVar]] = defaultdict(list)

    for driver_id, arc_list in driver_arcs.items():
        for job_id, deadhead, return_dh in arc_list:
            job = jobs_by_id[job_id]
            x_var = model.new_bool_var(f"x_{driver_id}_{job_id}")
            x[driver_id, job_id] = x_var

            start_var = model.new_int_var(
                job.window_start_t, job.window_end_t,
                f"start_{driver_id}_{job_id}",
            )
            start[driver_id, job_id] = start_var

            interval_var = model.new_optional_fixed_size_interval_var(
                start_var, _SERVICE_TIME, x_var,
                f"interval_{driver_id}_{job_id}",
            )
            intervals[driver_id].append(interval_var)

    # --- Constraint 1: every job assigned to exactly one driver ---
    for job in instance.jobs:
        feasible_drivers = job_drivers.get(job.job_id, [])
        model.add_exactly_one([x[d, job.job_id] for d in feasible_drivers])

    # --- Constraint 2: no temporal overlap per driver ---
    for driver_id, driver_intervals in intervals.items():
        if len(driver_intervals) > 1:
            model.add_no_overlap(driver_intervals)

    # --- Constraint 3: physical travel between jobs (3 cases) ---
    for driver_id, arc_list in driver_arcs.items():
        job_ids = [job_id for job_id, _, _ in arc_list]
        for idx_a in range(len(job_ids)):
            for idx_b in range(idx_a + 1, len(job_ids)):
                ji = job_ids[idx_a]
                jj = job_ids[idx_b]

                has_i_to_j = (ji, jj) in chain_lookup
                has_j_to_i = (jj, ji) in chain_lookup

                if not has_i_to_j and not has_j_to_i:
                    # Case 1: no arc in either direction — mutual exclusion
                    model.add(x[driver_id, ji] + x[driver_id, jj] <= 1)

                elif has_i_to_j and not has_j_to_i:
                    # Case 2: only i->j — strict order
                    travel = chain_lookup[(ji, jj)]
                    model.add(
                        start[driver_id, jj] >= start[driver_id, ji] + _SERVICE_TIME + travel
                    ).only_enforce_if([x[driver_id, ji], x[driver_id, jj]])

                elif has_j_to_i and not has_i_to_j:
                    # Case 2: only j->i — strict order (reversed)
                    travel = chain_lookup[(jj, ji)]
                    model.add(
                        start[driver_id, ji] >= start[driver_id, jj] + _SERVICE_TIME + travel
                    ).only_enforce_if([x[driver_id, ji], x[driver_id, jj]])

                else:
                    # Case 3: both directions — disjunctive sequence
                    travel_ij = chain_lookup[(ji, jj)]
                    travel_ji = chain_lookup[(jj, ji)]
                    seq = model.new_bool_var(f"seq_{driver_id}_{ji}_{jj}")
                    model.add(
                        start[driver_id, jj] >= start[driver_id, ji] + _SERVICE_TIME + travel_ij
                    ).only_enforce_if([x[driver_id, ji], x[driver_id, jj], seq])
                    model.add(
                        start[driver_id, ji] >= start[driver_id, jj] + _SERVICE_TIME + travel_ji
                    ).only_enforce_if([x[driver_id, ji], x[driver_id, jj], seq.negated()])

    # --- Constraint 4: deadhead from home ---
    for driver_id, arc_list in driver_arcs.items():
        for job_id, deadhead, return_dh in arc_list:
            model.add(
                start[driver_id, job_id] >= deadhead
            ).only_enforce_if([x[driver_id, job_id]])

    # --- Solve ---
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = timeout_seconds
    status_code = solver.solve(model)

    status_map = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.UNKNOWN: "UNKNOWN",
    }
    status = status_map.get(status_code, "UNKNOWN")

    # --- Extract solution ---
    assignments: list[JobAssignment] = []
    if status in ("OPTIMAL", "FEASIBLE"):
        for (driver_id, job_id), x_var in x.items():
            if solver.value(x_var):
                start_t = solver.value(start[driver_id, job_id])
                assignments.append(JobAssignment(
                    job_id=job_id,
                    driver_id=driver_id,
                    start_time_t=start_t,
                    start_datetime=_t_to_datetime(start_t, instance.horizon),
                ))

    elapsed = time_mod.monotonic() - start_wall

    return SolverResult(
        status=status,
        solve_time_seconds=round(elapsed, 3),
        assignments=assignments,
        stats={
            "variables": len(x),
            "constraints": len(model.proto.constraints),
        },
    )
