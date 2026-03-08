"""Circuit-based CP-SAT solver with vehicle custody and objective function."""

from __future__ import annotations

import time as time_mod
from collections import defaultdict
from datetime import datetime, time, timedelta

from ortools.sat.python import cp_model

from scheduler.cert_table import driver_can_do_group
from scheduler.circuit_builder import build_driver_graph, TRANSIT_WEIGHT, DRIVING_WEIGHT
from scheduler.models import (
    ActionType, CertLevel, CircuitNode, DriverCircuitGraph, DriverRoute,
    HorizonConfig, Job, JobAssignment, ProblemInstance, RouteLeg, SolverResult,
)

ACTIVATION_PENALTY = 120
SPAN_PENALTY = 1


def _extract_driver_routes(
    solver: cp_model.CpSolver,
    driver_graphs: dict[str, DriverCircuitGraph],
    arc_vars: dict[str, dict[tuple[int, int], cp_model.IntVar]],
    arrival_time: dict[str, dict[int, cp_model.IntVar]],
    drivers_by_id: dict,
    jobs_by_id: dict,
    instance: ProblemInstance,
) -> list[DriverRoute]:
    """Extract driver routes from the solved circuit model."""
    routes: list[DriverRoute] = []

    for driver_id, graph in driver_graphs.items():
        driver = drivers_by_id[driver_id]

        # Find the active path by following arcs from home (node 0)
        active_arcs: dict[int, int] = {}  # tail -> head
        for (tail, head), var in arc_vars[driver_id].items():
            if tail != head and solver.value(var):
                active_arcs[tail] = head

        if not active_arcs:
            continue  # driver not used

        # Follow the path: home -> ... -> home
        path: list[int] = [0]
        current = 0
        visited_set = {0}
        while current in active_arcs:
            next_node = active_arcs[current]
            if next_node == 0:
                break  # back to home
            if next_node in visited_set:
                break  # safety
            path.append(next_node)
            visited_set.add(next_node)
            current = next_node

        if len(path) <= 1:
            continue  # no jobs visited

        # Build legs from path
        nodes_by_idx = {n.index: n for n in graph.nodes}
        arc_lookup = {(a.tail, a.head): a for a in graph.arcs}
        legs: list[RouteLeg] = []
        total_deadhead = 0

        for i in range(len(path)):
            tail_idx = path[i]
            head_idx = path[i + 1] if i + 1 < len(path) else 0  # last leg goes home
            tail_node = nodes_by_idx[tail_idx]
            head_node = nodes_by_idx[head_idx]
            arc = arc_lookup.get((tail_idx, head_idx))
            if arc is None:
                continue

            leg = RouteLeg(
                from_postcode=tail_node.postcode,
                to_postcode=head_node.postcode,
                mode=arc.mode,
                duration_minutes=arc.travel_minutes,
                job_id=head_node.job_id,
                vehicle_reg=arc.vehicle_reg,
            )
            legs.append(leg)

            if arc.mode == "transit":
                total_deadhead += arc.travel_minutes

        routes.append(DriverRoute(
            driver_id=driver_id,
            driver_name=driver.name,
            home_postcode=driver.home_location.postcode,
            legs=legs,
            deadhead_minutes_total=total_deadhead,
        ))

    return routes


def _t_to_datetime(t: int, horizon: HorizonConfig) -> datetime:
    day_offset, minutes_in_day = divmod(t, 1440)
    actual_date = horizon.start_date + timedelta(days=day_offset)
    actual_time = time(minutes_in_day // 60, minutes_in_day % 60)
    return datetime.combine(actual_date, actual_time)


def _feasible_jobs_for_driver(
    driver, jobs: list[Job], instance: ProblemInstance,
) -> list[Job]:
    """Filter jobs this driver can physically reach and is certified for."""
    result = []
    for job in jobs:
        cert_level = instance.vehicle_group_certs.get(job.vehicle_group)
        if cert_level is None:
            continue
        if not driver_can_do_group(driver.certifications, job.vehicle_group):
            continue
        if job.scheduled_date in driver.unavailable_dates:
            continue
        pair = instance.transit_matrix.get(driver.home_location, job.target_location)
        if pair is None:
            continue
        if pair.transit_minutes > job.window_end_t:
            continue
        result.append(job)
    return result


def solve_circuit(
    instance: ProblemInstance, timeout_seconds: int = 300,
) -> SolverResult:
    """Build and solve the circuit-based CP-SAT model."""
    start_wall = time_mod.monotonic()
    model = cp_model.CpModel()

    jobs_by_id = {j.job_id: j for j in instance.jobs}
    drivers_by_id = {d.driver_id: d for d in instance.drivers}

    # --- Build per-driver circuit graphs ---
    driver_graphs: dict[str, DriverCircuitGraph] = {}
    for driver in instance.drivers:
        feasible_jobs = _feasible_jobs_for_driver(driver, instance.jobs, instance)
        graph = build_driver_graph(
            driver, feasible_jobs, instance.storage_locations, instance,
        )
        driver_graphs[driver.driver_id] = graph

    # --- Circuit variables ---
    # arc_vars[driver_id][(tail, head)] = BoolVar
    arc_vars: dict[str, dict[tuple[int, int], cp_model.IntVar]] = {}
    # arrival_time[driver_id][node_index] = IntVar
    arrival_time: dict[str, dict[int, cp_model.IntVar]] = {}

    t_max = instance.horizon.t_max

    for driver_id, graph in driver_graphs.items():
        arc_vars[driver_id] = {}
        arrival_time[driver_id] = {}

        # Create arrival time variables for each node
        for node in graph.nodes:
            if node.node_type == "home":
                arrival_time[driver_id][node.index] = model.new_int_var(
                    0, t_max, f"arrival_{driver_id}_{node.index}",
                )
            elif node.job_id:
                job = jobs_by_id[node.job_id]
                arrival_time[driver_id][node.index] = model.new_int_var(
                    job.window_start_t, job.window_end_t,
                    f"arrival_{driver_id}_{node.index}",
                )
            else:
                # Depot nodes
                arrival_time[driver_id][node.index] = model.new_int_var(
                    0, t_max, f"arrival_{driver_id}_{node.index}",
                )

        # Step 1: populate arc_vars dict (home self-loop first, then graph arcs)
        # Home self-loop: required by add_circuit when driver does no work
        arc_vars[driver_id][(0, 0)] = model.new_bool_var(f"arc_{driver_id}_0_0")
        for arc in graph.arcs:
            arc_vars[driver_id][(arc.tail, arc.head)] = model.new_bool_var(
                f"arc_{driver_id}_{arc.tail}_{arc.head}"
            )

        # Step 2: collect all arc vars into circuit_arcs in one pass
        circuit_arcs = [
            (u, v, var) for (u, v), var in arc_vars[driver_id].items()
        ]
        model.add_circuit(circuit_arcs)

        # --- Temporal constraints on arcs ---
        # Skip self-loops and arcs returning to home: home arrival_time is
        # departure time (not return), so arcs back to home are handled
        # via shift_end, not arrival_time propagation.
        for arc in graph.arcs:
            if arc.tail == arc.head:
                continue  # self-loops: no time propagation
            if arc.head == 0:
                continue  # arcs to home: return time tracked via s_end
            var = arc_vars[driver_id][(arc.tail, arc.head)]
            model.add(
                arrival_time[driver_id][arc.head]
                >= arrival_time[driver_id][arc.tail] + arc.travel_minutes
            ).only_enforce_if(var)

    # --- Job assignment: every job visited by exactly one driver ---
    # For each job node j: sum(incoming arcs to j) - self_loop_j == 1
    # i.e. exactly one real arc enters j (not the self-loop skip arc)
    # Collect per-job: list of (driver_id, node_index, self_loop_var)
    job_node_info: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for driver_id, graph in driver_graphs.items():
        for node in graph.nodes:
            if node.job_id:
                job_node_info[node.job_id].append((driver_id, node.index))

    for job in instance.jobs:
        infos = job_node_info.get(job.job_id, [])
        if not infos:
            # No driver graph contains this job — force infeasible
            false_var = model.new_bool_var(f"infeasible_{job.job_id}")
            model.add(false_var == 1)
            model.add(false_var == 0)
            continue

        # Sum of (incoming real arcs) across all drivers = 1
        # incoming real = all arcs with head==node_index except the self-loop
        visit_terms = []
        for driver_id, node_idx in infos:
            incoming = [
                arc_vars[driver_id][(u, v)]
                for (u, v) in arc_vars[driver_id]
                if v == node_idx and u != node_idx
            ]
            visit_terms.extend(incoming)

        if visit_terms:
            model.add(sum(visit_terms) == 1)
        else:
            false_var = model.new_bool_var(f"infeasible_{job.job_id}")
            model.add(false_var == 1)
            model.add(false_var == 0)

    # --- Shift span constraint ---
    is_working: dict[str, cp_model.IntVar] = {}
    shift_start_var: dict[str, cp_model.IntVar] = {}
    shift_end_var: dict[str, cp_model.IntVar] = {}

    for driver_id, graph in driver_graphs.items():
        driver = drivers_by_id[driver_id]
        is_w = model.new_bool_var(f"is_working_{driver_id}")
        s_start = model.new_int_var(0, t_max, f"shift_start_{driver_id}")
        s_end = model.new_int_var(0, t_max, f"shift_end_{driver_id}")
        is_working[driver_id] = is_w
        shift_start_var[driver_id] = s_start
        shift_end_var[driver_id] = s_end

        job_nodes = [n for n in graph.nodes if n.job_id]

        # is_working is directly equivalent to home self-loop being OFF
        home_sl = arc_vars[driver_id][(0, 0)]
        model.add(home_sl == 1).only_enforce_if(is_w.negated())
        model.add(home_sl == 0).only_enforce_if(is_w)

        # When not working: pin to zero
        model.add(s_start == 0).only_enforce_if(is_w.negated())
        model.add(s_end == 0).only_enforce_if(is_w.negated())

        # Shift start == home departure time
        model.add(s_start == arrival_time[driver_id][0]).only_enforce_if(is_w)

        # Shift end: for each arc returning to home
        home_idx = 0
        for arc in graph.arcs:
            if arc.head == home_idx and arc.tail != home_idx:
                var = arc_vars[driver_id][(arc.tail, arc.head)]
                model.add(
                    s_end >= arrival_time[driver_id][arc.tail] + arc.travel_minutes
                ).only_enforce_if(var)

        # For all visited job nodes, shift_end >= arrival
        for node in job_nodes:
            self_loop = arc_vars[driver_id].get((node.index, node.index))
            if self_loop is not None:
                model.add(
                    s_end >= arrival_time[driver_id][node.index]
                ).only_enforce_if(self_loop.negated())

        span_limit = driver.max_hours_per_day * instance.horizon.num_days
        model.add(s_end - s_start <= span_limit).only_enforce_if(is_w)

    # --- Objective function ---
    objective_terms = []

    # Arc costs
    for driver_id, graph in driver_graphs.items():
        for arc in graph.arcs:
            if arc.tail == arc.head:
                continue  # self-loops have 0 cost
            if arc.cost > 0:
                var = arc_vars[driver_id][(arc.tail, arc.head)]
                objective_terms.append(arc.cost * var)

    # Activation penalty
    for driver_id in driver_graphs:
        objective_terms.append(ACTIVATION_PENALTY * is_working[driver_id])

    # Span penalty
    for driver_id in driver_graphs:
        objective_terms.append(SPAN_PENALTY * shift_end_var[driver_id])
        objective_terms.append(-SPAN_PENALTY * shift_start_var[driver_id])

    if objective_terms:
        model.minimize(sum(objective_terms))

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
        for driver_id, graph in driver_graphs.items():
            for node in graph.nodes:
                if not node.job_id:
                    continue
                # Node visited = any incoming non-self-loop arc is selected
                incoming = [
                    arc_vars[driver_id][(u, v)]
                    for (u, v) in arc_vars[driver_id]
                    if v == node.index and u != node.index
                ]
                if any(solver.value(arc) for arc in incoming):
                    start_t = solver.value(arrival_time[driver_id][node.index])
                    assignments.append(JobAssignment(
                        job_id=node.job_id,
                        driver_id=driver_id,
                        start_time_t=start_t,
                        start_datetime=_t_to_datetime(start_t, instance.horizon),
                    ))

    driver_routes: list[DriverRoute] = []
    if status in ("OPTIMAL", "FEASIBLE"):
        driver_routes = _extract_driver_routes(
            solver, driver_graphs, arc_vars, arrival_time,
            drivers_by_id, jobs_by_id, instance,
        )

    elapsed = time_mod.monotonic() - start_wall

    return SolverResult(
        status=status,
        solve_time_seconds=round(elapsed, 3),
        assignments=assignments,
        driver_routes=driver_routes,
        stats={
            "variables": sum(len(avs) for avs in arc_vars.values()),
            "constraints": len(model.proto.constraints),
        },
    )
