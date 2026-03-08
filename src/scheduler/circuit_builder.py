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
    """Build state-legal arcs between nodes.

    State machine:
      EMPTY_HANDED nodes: home, deliver, depot_drop
      IN_VEHICLE nodes: collect, depot_pickup

    From EMPTY_HANDED: can go to COLLECT or DEPOT_PICKUP (transit)
    From IN_VEHICLE: can go to DELIVER, DEPOT_DROP, or HOME (driving)
    """
    arcs: list[CircuitArc] = []
    jobs_by_id = {j.job_id: j for j in feasible_jobs}
    tm = instance.transit_matrix

    empty_handed_types = {"home", "deliver", "depot_drop"}
    in_vehicle_types = {"collect", "depot_pickup"}
    empty_to_targets = {"collect", "depot_pickup", "home"}
    vehicle_to_targets = {"deliver", "depot_drop", "home"}

    def _node_location(node: CircuitNode):
        if node.job_id:
            job = jobs_by_id.get(node.job_id)
            return job.target_location if job else None
        if node.node_type == "home":
            for d in instance.drivers:
                if d.driver_id == node.driver_id:
                    return d.home_location
        if node.node_type in ("depot_drop", "depot_pickup"):
            for sl in instance.storage_locations:
                if sl.location_id == node.storage_location_id:
                    return sl.location
        return None

    for tail_node in nodes:
        # Self-loop for skippable nodes (everything except home)
        if tail_node.node_type != "home":
            arcs.append(CircuitArc(
                tail=tail_node.index, head=tail_node.index,
                travel_minutes=0, cost=0, mode="transit",
            ))

        tail_loc = _node_location(tail_node)
        if tail_loc is None:
            continue

        if tail_node.node_type in empty_handed_types:
            allowed_targets = empty_to_targets
        elif tail_node.node_type in in_vehicle_types:
            allowed_targets = vehicle_to_targets
        else:
            continue

        for head_node in nodes:
            if head_node.index == tail_node.index:
                continue
            if head_node.node_type not in allowed_targets:
                continue

            head_loc = _node_location(head_node)
            if head_loc is None:
                continue

            # Vehicle group matching for COLLECT -> DELIVER
            if tail_node.node_type == "collect" and head_node.node_type == "deliver":
                tail_job = jobs_by_id[tail_node.job_id]
                head_job = jobs_by_id[head_node.job_id]
                if tail_job.vehicle_group != head_job.vehicle_group:
                    continue
                # Reg compatibility: deliver must be TBA or same reg
                if head_job.vehicle_reg is not None and tail_job.vehicle_reg != head_job.vehicle_reg:
                    continue

            # Determine mode and travel time
            if tail_node.node_type in in_vehicle_types:
                mode = "driving"
                pair = tm.get(tail_loc, head_loc)
                if pair is None:
                    continue
                travel = pair.driving_minutes
                if tail_node.node_type == "collect" and head_node.node_type == "deliver":
                    travel += TURNAROUND_MINUTES
                if head_node.node_type == "depot_drop":
                    travel += DEPOT_DWELL_MINUTES
                cost = travel * DRIVING_WEIGHT
            else:
                mode = "transit"
                pair = tm.get(tail_loc, head_loc)
                if pair is None:
                    continue
                travel = pair.transit_minutes
                if head_node.node_type == "depot_pickup":
                    travel += DEPOT_DWELL_MINUTES
                cost = travel * TRANSIT_WEIGHT

            # Temporal pruning: can the driver reach head_node in time?
            if tail_node.job_id and head_node.job_id:
                tail_job = jobs_by_id[tail_node.job_id]
                head_job = jobs_by_id[head_node.job_id]
                if tail_job.window_start_t + travel > head_job.window_end_t:
                    continue

            # vehicle_reg on arc (for driving arcs from collect)
            vehicle_reg = None
            if tail_node.node_type == "collect" and tail_node.job_id:
                vehicle_reg = jobs_by_id[tail_node.job_id].vehicle_reg

            arcs.append(CircuitArc(
                tail=tail_node.index, head=head_node.index,
                travel_minutes=travel, cost=cost,
                mode=mode, vehicle_reg=vehicle_reg,
            ))

    return arcs
