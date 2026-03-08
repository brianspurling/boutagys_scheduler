"""Tests for circuit graph construction."""

from datetime import date, time, datetime

from scheduler.models import (
    ActionType, CertLevel, Driver, DriverJobArc, HorizonConfig, Job,
    Location, ProblemInstance, StorageLocation, TransitMatrix, TransitPair,
    Vehicle, VehicleJobArc, JobChainArc,
)
from scheduler.circuit_builder import (
    build_driver_graph, DEPOT_DWELL_MINUTES, TURNAROUND_MINUTES,
    TRANSIT_WEIGHT, DRIVING_WEIGHT,
)

LOC_HOME = Location(postcode="HH1 1HH", lat=51.5, lon=-0.1)
LOC_A = Location(postcode="AA1 1AA", lat=51.6, lon=-0.2)
LOC_B = Location(postcode="BB2 2BB", lat=51.7, lon=-0.3)
LOC_DEPOT = Location(postcode="DD4 4DD", lat=51.4, lon=0.0)

HORIZON = HorizonConfig(start_date=date(2025, 12, 8), num_days=1, t_max=1440)

MATRIX = TransitMatrix(entries={
    ("HH1 1HH", "AA1 1AA"): TransitPair(transit_minutes=30, driving_minutes=20),
    ("AA1 1AA", "HH1 1HH"): TransitPair(transit_minutes=30, driving_minutes=20),
    ("HH1 1HH", "BB2 2BB"): TransitPair(transit_minutes=40, driving_minutes=25),
    ("BB2 2BB", "HH1 1HH"): TransitPair(transit_minutes=40, driving_minutes=25),
    ("AA1 1AA", "BB2 2BB"): TransitPair(transit_minutes=50, driving_minutes=30),
    ("BB2 2BB", "AA1 1AA"): TransitPair(transit_minutes=50, driving_minutes=30),
    ("HH1 1HH", "DD4 4DD"): TransitPair(transit_minutes=20, driving_minutes=15),
    ("DD4 4DD", "HH1 1HH"): TransitPair(transit_minutes=20, driving_minutes=15),
    ("AA1 1AA", "DD4 4DD"): TransitPair(transit_minutes=25, driving_minutes=18),
    ("DD4 4DD", "AA1 1AA"): TransitPair(transit_minutes=25, driving_minutes=18),
    ("BB2 2BB", "DD4 4DD"): TransitPair(transit_minutes=35, driving_minutes=22),
    ("DD4 4DD", "BB2 2BB"): TransitPair(transit_minutes=35, driving_minutes=22),
})


def _make_driver(driver_id="D1", loc=LOC_HOME):
    return Driver(
        driver_id=driver_id, name=driver_id, home_location=loc,
        branch="TEST", max_hours_per_day=600, certifications=CertLevel.VAN,
        can_overnight=True, unavailable_dates=frozenset(),
    )


def _make_collect(job_id, loc, vehicle_reg="VAN1", group="V3",
                  window_start=480, window_end=600):
    return Job(
        job_id=job_id, book_no=f"B{job_id}", order_ref="", rental_no="",
        book_name="", book_status="",
        action=ActionType.COLLECT, scheduled_date=date(2025, 12, 8),
        scheduled_time=time(9, 0), scheduled_datetime=datetime(2025, 12, 8, 9, 0),
        time_offset_minutes=540,
        earliest_departure_t=window_start,
        grace_end_t=window_end,
        same_day_start_t=0,
        same_day_end_t=1439,
        deadline_t=None,
        vehicle_reg=vehicle_reg, vehicle_group=group,
        target_location=loc, notes="",
    )


def _make_deliver(job_id, loc, vehicle_reg="VAN1", group="V3",
                  window_start=480, window_end=600):
    return Job(
        job_id=job_id, book_no=f"B{job_id}", order_ref="", rental_no="",
        book_name="", book_status="",
        action=ActionType.DELIVER, scheduled_date=date(2025, 12, 8),
        scheduled_time=time(9, 0), scheduled_datetime=datetime(2025, 12, 8, 9, 0),
        time_offset_minutes=540,
        earliest_departure_t=None,
        grace_end_t=None,
        same_day_start_t=0,
        same_day_end_t=window_end,
        deadline_t=window_end,
        vehicle_reg=vehicle_reg, vehicle_group=group,
        target_location=loc, notes="",
    )


def _make_storage(location_id="S001", loc=LOC_DEPOT):
    return StorageLocation(
        location_id=location_id, name="Depot", location=loc,
        capacity=20, restricted_groups=set(),
    )


def _make_instance(drivers, jobs, storage_locations=None):
    """Minimal ProblemInstance for circuit builder tests."""
    return ProblemInstance(
        horizon=HORIZON, jobs=jobs, drivers=drivers,
        vehicles=[], storage_locations=storage_locations or [],
        vehicle_group_certs={"V3": CertLevel.VAN},
        transit_matrix=MATRIX,
        driver_job_arcs=[], job_chain_arcs=[], vehicle_job_arcs=[],
    )


# --- Node generation ---

def test_nodes_home_only():
    """Driver with no feasible jobs gets just a home node."""
    d = _make_driver()
    graph = build_driver_graph(d, [], [], _make_instance([d], []))
    assert len(graph.nodes) == 1
    assert graph.nodes[0].node_type == "home"
    assert graph.nodes[0].index == 0


def test_nodes_one_collect():
    """One collect job produces: home + collect node."""
    d = _make_driver()
    j = _make_collect("J1", LOC_A)
    graph = build_driver_graph(d, [j], [], _make_instance([d], [j]))
    node_types = {n.node_type for n in graph.nodes}
    assert "home" in node_types
    assert "collect" in node_types
    assert len(graph.nodes) == 2


def test_nodes_with_depot():
    """With a storage location, depot_drop and depot_pickup nodes are created."""
    d = _make_driver()
    j = _make_collect("J1", LOC_A)
    depot = _make_storage()
    graph = build_driver_graph(d, [j], [depot], _make_instance([d], [j], [depot]))
    node_types = {n.node_type for n in graph.nodes}
    assert "depot_drop" in node_types
    assert "depot_pickup" in node_types
    # home + collect + depot_drop + depot_pickup = 4
    assert len(graph.nodes) == 4


def test_nodes_collect_and_deliver():
    """One collect + one deliver produces: home + collect + deliver."""
    d = _make_driver()
    j1 = _make_collect("J1", LOC_A)
    j2 = _make_deliver("J2", LOC_B)
    graph = build_driver_graph(d, [j1, j2], [], _make_instance([d], [j1, j2]))
    node_types = [n.node_type for n in graph.nodes]
    assert node_types.count("home") == 1
    assert node_types.count("collect") == 1
    assert node_types.count("deliver") == 1


# --- Arc generation: state-legal connections ---

def test_arcs_home_to_collect():
    """HOME (empty) -> COLLECT (empty->vehicle): transit arc exists."""
    d = _make_driver()
    j = _make_collect("J1", LOC_A)
    graph = build_driver_graph(d, [j], [], _make_instance([d], [j]))
    home_idx = 0
    collect_idx = [n.index for n in graph.nodes if n.node_type == "collect"][0]
    arcs_home_to_collect = [a for a in graph.arcs if a.tail == home_idx and a.head == collect_idx]
    assert len(arcs_home_to_collect) == 1
    assert arcs_home_to_collect[0].mode == "transit"
    assert arcs_home_to_collect[0].travel_minutes == 30  # HH1->AA1 transit


def test_arcs_home_to_depot_pickup():
    """HOME (empty) -> DEPOT_PICKUP (empty->vehicle): transit arc exists."""
    d = _make_driver()
    j = _make_collect("J1", LOC_A)
    depot = _make_storage()
    graph = build_driver_graph(d, [j], [depot], _make_instance([d], [j], [depot]))
    home_idx = 0
    pickup_idx = [n.index for n in graph.nodes if n.node_type == "depot_pickup"][0]
    arcs = [a for a in graph.arcs if a.tail == home_idx and a.head == pickup_idx]
    assert len(arcs) == 1
    assert arcs[0].mode == "transit"
    # travel = transit HH1->DD4 (20) + dwell (15) = 35 total travel
    assert arcs[0].travel_minutes == 20 + DEPOT_DWELL_MINUTES


def test_no_arc_home_to_deliver():
    """HOME -> DELIVER is not created (driver is empty-handed, needs a van first)."""
    d = _make_driver()
    j = _make_deliver("J1", LOC_A)
    graph = build_driver_graph(d, [j], [], _make_instance([d], [j]))
    home_idx = 0
    deliver_idx = [n.index for n in graph.nodes if n.node_type == "deliver"][0]
    arcs = [a for a in graph.arcs if a.tail == home_idx and a.head == deliver_idx]
    assert len(arcs) == 0


def test_arcs_collect_to_deliver_matching():
    """COLLECT (vehicle) -> DELIVER (vehicle->empty): driving arc for matching group."""
    d = _make_driver()
    j1 = _make_collect("J1", LOC_A, vehicle_reg="VAN1", group="V3")
    j2 = _make_deliver("J2", LOC_B, vehicle_reg="VAN1", group="V3")
    graph = build_driver_graph(d, [j1, j2], [], _make_instance([d], [j1, j2]))
    collect_idx = [n.index for n in graph.nodes if n.node_type == "collect"][0]
    deliver_idx = [n.index for n in graph.nodes if n.node_type == "deliver"][0]
    arcs = [a for a in graph.arcs if a.tail == collect_idx and a.head == deliver_idx]
    assert len(arcs) == 1
    assert arcs[0].mode == "driving"
    # travel = driving AA1->BB2 (30) + turnaround (45)
    assert arcs[0].travel_minutes == 30 + TURNAROUND_MINUTES


def test_no_arc_collect_to_collect():
    """COLLECT -> COLLECT is never created (driver is IN_VEHICLE, can't pick up another)."""
    d = _make_driver()
    j1 = _make_collect("J1", LOC_A)
    j2 = _make_collect("J2", LOC_B)
    graph = build_driver_graph(d, [j1, j2], [], _make_instance([d], [j1, j2]))
    collect_indices = [n.index for n in graph.nodes if n.node_type == "collect"]
    for ci in collect_indices:
        for cj in collect_indices:
            if ci != cj:
                arcs = [a for a in graph.arcs if a.tail == ci and a.head == cj]
                assert len(arcs) == 0, f"Illegal COLLECT->COLLECT arc found: {ci}->{cj}"


def test_no_arc_deliver_to_deliver():
    """DELIVER -> DELIVER is never created (driver is EMPTY, needs van first)."""
    d = _make_driver()
    j1 = _make_deliver("J1", LOC_A)
    j2 = _make_deliver("J2", LOC_B)
    graph = build_driver_graph(d, [j1, j2], [], _make_instance([d], [j1, j2]))
    deliver_indices = [n.index for n in graph.nodes if n.node_type == "deliver"]
    for di in deliver_indices:
        for dj in deliver_indices:
            if di != dj:
                arcs = [a for a in graph.arcs if a.tail == di and a.head == dj]
                assert len(arcs) == 0


def test_arcs_collect_to_depot_drop():
    """COLLECT (vehicle) -> DEPOT_DROP (vehicle->empty): driving arc."""
    d = _make_driver()
    j = _make_collect("J1", LOC_A)
    depot = _make_storage()
    graph = build_driver_graph(d, [j], [depot], _make_instance([d], [j], [depot]))
    collect_idx = [n.index for n in graph.nodes if n.node_type == "collect"][0]
    drop_idx = [n.index for n in graph.nodes if n.node_type == "depot_drop"][0]
    arcs = [a for a in graph.arcs if a.tail == collect_idx and a.head == drop_idx]
    assert len(arcs) == 1
    assert arcs[0].mode == "driving"
    # travel = driving AA1->DD4 (18) + dwell (15)
    assert arcs[0].travel_minutes == 18 + DEPOT_DWELL_MINUTES


def test_arcs_deliver_to_home():
    """DELIVER (empty) -> HOME (empty): transit arc."""
    d = _make_driver()
    j = _make_deliver("J1", LOC_A)
    graph = build_driver_graph(d, [j], [], _make_instance([d], [j]))
    deliver_idx = [n.index for n in graph.nodes if n.node_type == "deliver"][0]
    home_idx = 0
    arcs = [a for a in graph.arcs if a.tail == deliver_idx and a.head == home_idx]
    assert len(arcs) == 1
    assert arcs[0].mode == "transit"


def test_arcs_collect_to_home_driving():
    """COLLECT (vehicle) -> HOME: driving arc (end of day with van)."""
    d = _make_driver()
    j = _make_collect("J1", LOC_A)
    graph = build_driver_graph(d, [j], [], _make_instance([d], [j]))
    collect_idx = [n.index for n in graph.nodes if n.node_type == "collect"][0]
    home_idx = 0
    arcs = [a for a in graph.arcs if a.tail == collect_idx and a.head == home_idx]
    assert len(arcs) == 1
    assert arcs[0].mode == "driving"


def test_arcs_depot_drop_to_collect():
    """DEPOT_DROP (empty) -> COLLECT (empty->vehicle): transit arc."""
    d = _make_driver()
    j = _make_collect("J1", LOC_A)
    depot = _make_storage()
    graph = build_driver_graph(d, [j], [depot], _make_instance([d], [j], [depot]))
    drop_idx = [n.index for n in graph.nodes if n.node_type == "depot_drop"][0]
    collect_idx = [n.index for n in graph.nodes if n.node_type == "collect"][0]
    arcs = [a for a in graph.arcs if a.tail == drop_idx and a.head == collect_idx]
    assert len(arcs) == 1
    assert arcs[0].mode == "transit"


def test_arcs_depot_drop_to_depot_pickup():
    """DEPOT_DROP (empty) -> DEPOT_PICKUP (empty->vehicle): transit arc (same or different depot)."""
    d = _make_driver()
    j = _make_collect("J1", LOC_A)  # need at least one job for a non-trivial graph
    depot = _make_storage()
    graph = build_driver_graph(d, [j], [depot], _make_instance([d], [j], [depot]))
    drop_idx = [n.index for n in graph.nodes if n.node_type == "depot_drop"][0]
    pickup_idx = [n.index for n in graph.nodes if n.node_type == "depot_pickup"][0]
    arcs = [a for a in graph.arcs if a.tail == drop_idx and a.head == pickup_idx]
    assert len(arcs) == 1
    assert arcs[0].mode == "transit"


def test_arcs_depot_pickup_to_deliver():
    """DEPOT_PICKUP (vehicle) -> DELIVER (vehicle->empty): driving arc."""
    d = _make_driver()
    j = _make_deliver("J1", LOC_A)
    depot = _make_storage()
    graph = build_driver_graph(d, [j], [depot], _make_instance([d], [j], [depot]))
    pickup_idx = [n.index for n in graph.nodes if n.node_type == "depot_pickup"][0]
    deliver_idx = [n.index for n in graph.nodes if n.node_type == "deliver"][0]
    arcs = [a for a in graph.arcs if a.tail == pickup_idx and a.head == deliver_idx]
    assert len(arcs) == 1
    assert arcs[0].mode == "driving"


def test_arcs_deliver_to_collect():
    """DELIVER (empty) -> COLLECT (empty->vehicle): transit arc."""
    d = _make_driver()
    j1 = _make_deliver("J1", LOC_A)
    j2 = _make_collect("J2", LOC_B)
    graph = build_driver_graph(d, [j1, j2], [], _make_instance([d], [j1, j2]))
    deliver_idx = [n.index for n in graph.nodes if n.node_type == "deliver"][0]
    collect_idx = [n.index for n in graph.nodes if n.node_type == "collect"][0]
    arcs = [a for a in graph.arcs if a.tail == deliver_idx and a.head == collect_idx]
    assert len(arcs) == 1
    assert arcs[0].mode == "transit"


def test_self_loop_on_job_nodes():
    """Every job node has a self-loop arc (for skipping). Home does NOT."""
    d = _make_driver()
    j = _make_collect("J1", LOC_A)
    graph = build_driver_graph(d, [j], [], _make_instance([d], [j]))
    # Self-loop on collect node
    collect_idx = [n.index for n in graph.nodes if n.node_type == "collect"][0]
    self_loops = [a for a in graph.arcs if a.tail == collect_idx and a.head == collect_idx]
    assert len(self_loops) == 1
    assert self_loops[0].cost == 0
    # No self-loop on home
    home_loops = [a for a in graph.arcs if a.tail == 0 and a.head == 0]
    assert len(home_loops) == 0


def test_self_loop_on_depot_nodes():
    """Depot nodes also get self-loops."""
    d = _make_driver()
    j = _make_collect("J1", LOC_A)
    depot = _make_storage()
    graph = build_driver_graph(d, [j], [depot], _make_instance([d], [j], [depot]))
    for n in graph.nodes:
        if n.node_type in ("depot_drop", "depot_pickup"):
            self_loops = [a for a in graph.arcs if a.tail == n.index and a.head == n.index]
            assert len(self_loops) == 1


def test_collect_deliver_group_mismatch_no_arc():
    """COLLECT -> DELIVER with different vehicle groups: no arc."""
    d = _make_driver()
    j1 = _make_collect("J1", LOC_A, vehicle_reg="VAN1", group="V3")
    j2 = _make_deliver("J2", LOC_B, vehicle_reg="VAN2", group="V5")
    graph = build_driver_graph(d, [j1, j2], [], _make_instance([d], [j1, j2]))
    collect_idx = [n.index for n in graph.nodes if n.node_type == "collect"][0]
    deliver_idx = [n.index for n in graph.nodes if n.node_type == "deliver"][0]
    arcs = [a for a in graph.arcs if a.tail == collect_idx and a.head == deliver_idx]
    assert len(arcs) == 0


def test_collect_deliver_reg_mismatch_no_arc():
    """COLLECT reg=VAN1 -> DELIVER reg=VAN2 (specific, different): no arc."""
    d = _make_driver()
    j1 = _make_collect("J1", LOC_A, vehicle_reg="VAN1", group="V3")
    j2 = _make_deliver("J2", LOC_B, vehicle_reg="VAN2", group="V3")
    graph = build_driver_graph(d, [j1, j2], [], _make_instance([d], [j1, j2]))
    collect_idx = [n.index for n in graph.nodes if n.node_type == "collect"][0]
    deliver_idx = [n.index for n in graph.nodes if n.node_type == "deliver"][0]
    arcs = [a for a in graph.arcs if a.tail == collect_idx and a.head == deliver_idx]
    assert len(arcs) == 0


def test_collect_to_tba_deliver_same_group():
    """COLLECT reg=VAN1, group=V3 -> TBA DELIVER group=V3: arc exists."""
    d = _make_driver()
    j1 = _make_collect("J1", LOC_A, vehicle_reg="VAN1", group="V3")
    j2 = _make_deliver("J2", LOC_B, vehicle_reg=None, group="V3")
    graph = build_driver_graph(d, [j1, j2], [], _make_instance([d], [j1, j2]))
    collect_idx = [n.index for n in graph.nodes if n.node_type == "collect"][0]
    deliver_idx = [n.index for n in graph.nodes if n.node_type == "deliver"][0]
    arcs = [a for a in graph.arcs if a.tail == collect_idx and a.head == deliver_idx]
    assert len(arcs) == 1


def test_arc_cost_transit():
    """Transit arc cost = travel_minutes * TRANSIT_WEIGHT."""
    d = _make_driver()
    j = _make_collect("J1", LOC_A)
    graph = build_driver_graph(d, [j], [], _make_instance([d], [j]))
    home_idx = 0
    collect_idx = [n.index for n in graph.nodes if n.node_type == "collect"][0]
    arc = [a for a in graph.arcs if a.tail == home_idx and a.head == collect_idx][0]
    # HH1->AA1 transit = 30 min, cost = 30 * TRANSIT_WEIGHT(3) = 90
    assert arc.cost == 30 * TRANSIT_WEIGHT


def test_arc_cost_driving():
    """Driving arc cost = travel_minutes * DRIVING_WEIGHT (travel includes turnaround if applicable)."""
    d = _make_driver()
    j1 = _make_collect("J1", LOC_A, vehicle_reg="VAN1", group="V3")
    j2 = _make_deliver("J2", LOC_B, vehicle_reg="VAN1", group="V3")
    graph = build_driver_graph(d, [j1, j2], [], _make_instance([d], [j1, j2]))
    collect_idx = [n.index for n in graph.nodes if n.node_type == "collect"][0]
    deliver_idx = [n.index for n in graph.nodes if n.node_type == "deliver"][0]
    arc = [a for a in graph.arcs if a.tail == collect_idx and a.head == deliver_idx][0]
    # driving AA1->BB2 = 30, turnaround = 45, total travel = 75
    # cost = 75 * DRIVING_WEIGHT(1) = 75
    assert arc.cost == (30 + TURNAROUND_MINUTES) * DRIVING_WEIGHT


# --- Temporal pruning ---

def test_temporal_pruning_removes_unreachable():
    """Arc from job at t=480 to job at t=490 with 50 min travel: pruned (480+50 > 490)."""
    d = _make_driver()
    j1 = _make_collect("J1", LOC_A, window_start=480, window_end=480)
    j2 = _make_deliver("J2", LOC_B, vehicle_reg="VAN1", group="V3",
                       window_start=490, window_end=490)
    graph = build_driver_graph(d, [j1, j2], [], _make_instance([d], [j1, j2]))
    collect_idx = [n.index for n in graph.nodes if n.node_type == "collect"][0]
    deliver_idx = [n.index for n in graph.nodes if n.node_type == "deliver"][0]
    # driving 30 + turnaround 45 = 75 min travel. 480 + 75 = 555 > 490. Pruned.
    arcs = [a for a in graph.arcs if a.tail == collect_idx and a.head == deliver_idx]
    assert len(arcs) == 0


def test_temporal_pruning_keeps_reachable():
    """Arc from job at t=480 to job at t=600 with 75 min travel: kept (480+75 <= 600)."""
    d = _make_driver()
    j1 = _make_collect("J1", LOC_A, window_start=480, window_end=480)
    j2 = _make_deliver("J2", LOC_B, vehicle_reg="VAN1", group="V3",
                       window_start=555, window_end=700)
    graph = build_driver_graph(d, [j1, j2], [], _make_instance([d], [j1, j2]))
    collect_idx = [n.index for n in graph.nodes if n.node_type == "collect"][0]
    deliver_idx = [n.index for n in graph.nodes if n.node_type == "deliver"][0]
    arcs = [a for a in graph.arcs if a.tail == collect_idx and a.head == deliver_idx]
    assert len(arcs) == 1
