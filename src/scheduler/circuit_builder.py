"""Circuit graph construction: builds per-driver graphs for the circuit-based solver."""

from __future__ import annotations

from scheduler.models import (
    ActionType, CircuitArc, CircuitNode, Driver, DriverCircuitGraph,
    Job, ProblemInstance, StorageLocation,
)

DEPOT_DWELL_MINUTES = 15
TURNAROUND_MINUTES = 45
TRANSIT_WEIGHT = 3
DRIVING_WEIGHT = 1

# Node state machine:
# EMPTY_HANDED nodes: home, deliver, depot_drop
# IN_VEHICLE nodes: collect, depot_pickup
_EMPTY_HANDED = {"home", "deliver", "depot_drop"}
_IN_VEHICLE = {"collect", "depot_pickup"}


def build_driver_graph(
    driver: Driver,
    feasible_jobs: list[Job],
    storage_locations: list[StorageLocation],
    instance: ProblemInstance,
) -> DriverCircuitGraph:
    """Build a circuit graph for one driver.

    Args:
        driver: The driver this graph is for.
        feasible_jobs: Jobs this driver is certified and temporally able to reach.
        storage_locations: All depot/storage locations.
        instance: The full problem instance (for transit matrix access).

    Returns:
        DriverCircuitGraph with nodes and state-legal arcs.
    """
    nodes: list[CircuitNode] = []
    idx = 0

    # Node 0 is always HOME
    home_node = CircuitNode(
        index=idx, node_type="home", driver_id=driver.driver_id,
        postcode=driver.home_location.postcode,
    )
    nodes.append(home_node)
    idx += 1

    # Job nodes
    for job in feasible_jobs:
        node_type = "collect" if job.action == ActionType.COLLECT else "deliver"
        nodes.append(CircuitNode(
            index=idx, node_type=node_type, driver_id=driver.driver_id,
            postcode=job.target_location.postcode, job_id=job.job_id,
        ))
        idx += 1

    # Depot nodes (one drop + one pickup per storage location)
    for sl in storage_locations:
        nodes.append(CircuitNode(
            index=idx, node_type="depot_drop", driver_id=driver.driver_id,
            postcode=sl.location.postcode, storage_location_id=sl.location_id,
        ))
        idx += 1
        nodes.append(CircuitNode(
            index=idx, node_type="depot_pickup", driver_id=driver.driver_id,
            postcode=sl.location.postcode, storage_location_id=sl.location_id,
        ))
        idx += 1

    arcs = _build_arcs(nodes, feasible_jobs, instance)

    return DriverCircuitGraph(driver_id=driver.driver_id, nodes=nodes, arcs=arcs)


def _build_arcs(
    nodes: list[CircuitNode],
    feasible_jobs: list[Job],
    instance: ProblemInstance,
) -> list[CircuitArc]:
    """Build state-legal arcs between nodes based on driver custody state machine."""
    matrix = instance.transit_matrix
    job_by_id = {j.job_id: j for j in feasible_jobs}
    arcs: list[CircuitArc] = []

    for tail_node in nodes:
        for head_node in nodes:
            if tail_node.index == head_node.index:
                continue  # self-loops handled by solver, not here

            arc = _try_build_arc(tail_node, head_node, job_by_id, matrix)
            if arc is not None:
                arcs.append(arc)

    return arcs


def _try_build_arc(
    tail: CircuitNode,
    head: CircuitNode,
    job_by_id: dict[str, Job],
    matrix,
) -> CircuitArc | None:
    """Return an arc if the state transition is legal, else None."""
    from scheduler.models import Location, TransitPair

    tail_type = tail.node_type
    head_type = head.node_type

    # Determine which postcode to look up travel from
    tail_postcode = tail.postcode
    head_postcode = head.postcode

    # --- State machine: legal transitions ---
    # EMPTY_HANDED -> collect: transit to pick up the van
    if tail_type in _EMPTY_HANDED and head_type == "collect":
        pair = matrix.entries.get((tail_postcode, head_postcode))
        if pair is None:
            return None
        travel = pair.transit_minutes
        cost = travel * TRANSIT_WEIGHT
        return CircuitArc(
            tail=tail.index, head=head.index,
            travel_minutes=travel, cost=cost,
            mode="transit",
        )

    # EMPTY_HANDED -> depot_pickup: transit to depot to pick up a van (+ dwell)
    if tail_type in _EMPTY_HANDED and head_type == "depot_pickup":
        # No self-depot-pickup-from-depot-drop-same-depot unless different depot
        pair = matrix.entries.get((tail_postcode, head_postcode))
        if pair is None and tail_postcode != head_postcode:
            return None
        if pair is None:
            # same postcode (same depot): zero travel + dwell
            travel = DEPOT_DWELL_MINUTES
        else:
            travel = pair.transit_minutes + DEPOT_DWELL_MINUTES
        cost = travel * TRANSIT_WEIGHT
        return CircuitArc(
            tail=tail.index, head=head.index,
            travel_minutes=travel, cost=cost,
            mode="transit",
        )

    # IN_VEHICLE -> deliver: driving the van to delivery (+ turnaround)
    if tail_type in _IN_VEHICLE and head_type == "deliver":
        pair = matrix.entries.get((tail_postcode, head_postcode))
        if pair is None:
            return None
        travel = pair.driving_minutes + TURNAROUND_MINUTES
        cost = travel * DRIVING_WEIGHT
        return CircuitArc(
            tail=tail.index, head=head.index,
            travel_minutes=travel, cost=cost,
            mode="driving",
        )

    # IN_VEHICLE -> depot_drop: driving van to depot (+ dwell)
    if tail_type in _IN_VEHICLE and head_type == "depot_drop":
        pair = matrix.entries.get((tail_postcode, head_postcode))
        if pair is None and tail_postcode != head_postcode:
            return None
        if pair is None:
            travel = DEPOT_DWELL_MINUTES
        else:
            travel = pair.driving_minutes + DEPOT_DWELL_MINUTES
        cost = travel * DRIVING_WEIGHT
        return CircuitArc(
            tail=tail.index, head=head.index,
            travel_minutes=travel, cost=cost,
            mode="driving",
        )

    # IN_VEHICLE -> home: driving van home (end of day with van)
    if tail_type in _IN_VEHICLE and head_type == "home":
        pair = matrix.entries.get((tail_postcode, head_postcode))
        if pair is None:
            return None
        travel = pair.driving_minutes
        cost = travel * DRIVING_WEIGHT
        return CircuitArc(
            tail=tail.index, head=head.index,
            travel_minutes=travel, cost=cost,
            mode="driving",
        )

    # EMPTY_HANDED -> home: transit home (end of day without van)
    if tail_type in _EMPTY_HANDED and head_type == "home":
        # depot_drop -> home is transit
        pair = matrix.entries.get((tail_postcode, head_postcode))
        if pair is None and tail_postcode != head_postcode:
            return None
        if pair is None:
            travel = 0
        else:
            travel = pair.transit_minutes
        cost = travel * TRANSIT_WEIGHT
        return CircuitArc(
            tail=tail.index, head=head.index,
            travel_minutes=travel, cost=cost,
            mode="transit",
        )

    # No legal transition
    return None
