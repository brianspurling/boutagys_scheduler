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
    drivers_by_id = {d.driver_id: d for d in instance.drivers}

    # --- Index arcs ---
    # driver_id -> list of (job_id, deadhead_minutes, return_deadhead_minutes)
    driver_arcs: dict[str, list[tuple[str, int, int]]] = defaultdict(list)
    for arc in instance.driver_job_arcs:
        driver_arcs[arc.driver_id].append((arc.job_id, arc.deadhead_minutes, arc.return_deadhead_minutes))

    # job_id -> list of driver_ids that can serve it
    job_drivers: dict[str, list[str]] = defaultdict(list)
    for arc in instance.driver_job_arcs:
        job_drivers[arc.job_id].append(arc.driver_id)

    # VEHICLE_DRIVER chain index: built BEFORE min-time consolidation
    # which loses chain_type info
    vd_pairs: set[tuple[str, str]] = set()
    for arc in instance.job_chain_arcs:
        if arc.chain_type == "vehicle_driver":
            vd_pairs.add((arc.from_job_id, arc.to_job_id))

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

    seq_vars: dict[tuple[str, str, str], cp_model.IntVar] = {}

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
                    seq_vars[driver_id, ji, jj] = seq
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

    # --- Constraint 5: driver shift span ---
    is_working: dict[str, cp_model.IntVar] = {}
    shift_start: dict[str, cp_model.IntVar] = {}
    shift_end: dict[str, cp_model.IntVar] = {}

    for driver_id, arc_list in driver_arcs.items():
        driver = drivers_by_id[driver_id]
        t_max = instance.horizon.t_max

        is_w = model.new_bool_var(f"is_working_{driver_id}")
        s_start = model.new_int_var(0, t_max, f"shift_start_{driver_id}")
        s_end = model.new_int_var(0, t_max, f"shift_end_{driver_id}")
        is_working[driver_id] = is_w
        shift_start[driver_id] = s_start
        shift_end[driver_id] = s_end

        # Link is_working to assignments
        all_x = [x[driver_id, job_id] for job_id, _, _ in arc_list]
        model.add(sum(all_x) >= 1).only_enforce_if(is_w)
        model.add(sum(all_x) == 0).only_enforce_if(is_w.negated())

        # When not working: pin to zero
        model.add(s_start == 0).only_enforce_if(is_w.negated())
        model.add(s_end == 0).only_enforce_if(is_w.negated())

        # When working: shift_start <= departure, shift_end >= return
        for job_id, deadhead, return_dh in arc_list:
            model.add(
                s_start <= start[driver_id, job_id] - deadhead
            ).only_enforce_if(x[driver_id, job_id])
            model.add(
                s_end >= start[driver_id, job_id] + _SERVICE_TIME + return_dh
            ).only_enforce_if(x[driver_id, job_id])

        # Shift span constraint: scale by num_days for multi-day horizons.
        # In a multi-day horizon drivers can work across multiple days;
        # per-day granularity will be tightened once overnight-stay
        # modelling is in place.
        span_limit = driver.max_hours_per_day * instance.horizon.num_days
        model.add(s_end - s_start <= span_limit).only_enforce_if(is_w)

    # --- Constraint 6: TBA vehicle assignment ---
    tba_job_ids = {j.job_id for j in instance.jobs if j.vehicle_reg is None}

    # y[vehicle_reg, job_id] = BoolVar: depot vehicle assignment
    y: dict[tuple[str, str], cp_model.IntVar] = {}
    # vd_active[driver_id, from_job_id, to_job_id] = BoolVar
    vd_active: dict[tuple[str, str, str], cp_model.IntVar] = {}

    # Create y variables for depot vehicle -> TBA job arcs
    for arc in instance.vehicle_job_arcs:
        y_var = model.new_bool_var(f"y_{arc.vehicle_reg}_{arc.job_id}")
        y[arc.vehicle_reg, arc.job_id] = y_var

    # Create vd_active variables for VEHICLE_DRIVER chains into TBA jobs
    for (ji, jj) in vd_pairs:
        if jj not in tba_job_ids:
            continue
        # For each driver that can do both jobs
        drivers_for_i = set(job_drivers.get(ji, []))
        drivers_for_j = set(job_drivers.get(jj, []))
        common_drivers = drivers_for_i & drivers_for_j

        for driver_id in common_drivers:
            vda = model.new_bool_var(f"vd_active_{driver_id}_{ji}_{jj}")
            vd_active[driver_id, ji, jj] = vda

            has_i_to_j = (ji, jj) in chain_lookup
            has_j_to_i = (jj, ji) in chain_lookup

            if has_i_to_j and not has_j_to_i:
                # Strict order: vd_active iff both assigned to same driver
                model.add_bool_and([x[driver_id, ji], x[driver_id, jj]]).only_enforce_if(vda)
                model.add_bool_or([x[driver_id, ji].negated(), x[driver_id, jj].negated()]).only_enforce_if(vda.negated())
            elif has_i_to_j and has_j_to_i:
                # Disjunctive: vd_active iff both assigned AND i-before-j
                # Look up seq var — key is (driver_id, ji, jj) or (driver_id, jj, ji)
                if (driver_id, ji, jj) in seq_vars:
                    seq_v = seq_vars[driver_id, ji, jj]
                    model.add_bool_and([x[driver_id, ji], x[driver_id, jj], seq_v]).only_enforce_if(vda)
                    model.add_bool_or([x[driver_id, ji].negated(), x[driver_id, jj].negated(), seq_v.negated()]).only_enforce_if(vda.negated())
                elif (driver_id, jj, ji) in seq_vars:
                    seq_v = seq_vars[driver_id, jj, ji]
                    # seq_v=1 means jj-before-ji, so negated means ji-before-jj
                    model.add_bool_and([x[driver_id, ji], x[driver_id, jj], seq_v.negated()]).only_enforce_if(vda)
                    model.add_bool_or([x[driver_id, ji].negated(), x[driver_id, jj].negated(), seq_v]).only_enforce_if(vda.negated())

    # Rule 1: exactly one van source per TBA job
    for job_id in tba_job_ids:
        van_sources = []
        # Depot vehicles
        for (v_reg, j_id) in y:
            if j_id == job_id:
                van_sources.append(y[v_reg, j_id])
        # VEHICLE_DRIVER chains
        for (di, ji, jj) in vd_active:
            if jj == job_id:
                van_sources.append(vd_active[di, ji, jj])
        if van_sources:
            model.add_exactly_one(van_sources)
        else:
            # No van source at all — force infeasible
            false_var = model.new_bool_var(f"infeasible_{job_id}")
            model.add(false_var == 1)
            model.add(false_var == 0)

    # Rule 2: each depot vehicle assigned to at most one TBA job
    from collections import defaultdict as _dd
    vehicle_assignments: dict[str, list] = _dd(list)
    for (v_reg, j_id) in y:
        vehicle_assignments[v_reg].append(y[v_reg, j_id])
    for v_reg, assigned in vehicle_assignments.items():
        if len(assigned) > 1:
            model.add(sum(assigned) <= 1)

    # Rule 3: temporal link — depot vehicle must arrive before job starts
    for arc in instance.vehicle_job_arcs:
        for d_id in job_drivers.get(arc.job_id, []):
            model.add(
                start[d_id, arc.job_id] >= arc.earliest_arrival_t
            ).only_enforce_if([y[arc.vehicle_reg, arc.job_id], x[d_id, arc.job_id]])

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
