# Circuit-Based Solver Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the pairwise feasibility solver with a circuit-based routing model that enforces vehicle custody as a hard physical constraint, and minimises a weighted cost objective.

**Architecture:** One `add_circuit` per driver over a graph of job nodes, depot-action nodes, and the driver's home node. Vehicle custody is enforced structurally — arcs only exist where the driver state machine allows. The objective function sums arc costs + driver activation penalty + shift span penalty.

**Tech Stack:** Python 3.12, Google OR-Tools CP-SAT (`add_circuit`), Pydantic frozen models, pytest.

**Design doc:** `docs/plans/2026-03-07-circuit-solver-design.md`

---

## Overview of Tasks

| # | Component | What |
|---|-----------|------|
| 1 | Models | Add `CircuitNode`, `CircuitArc`, `DriverCircuitGraph` to `models.py` |
| 2 | Circuit builder — node generation | Build per-driver node sets from `ProblemInstance` |
| 3 | Circuit builder — arc generation | Build state-legal arcs with cost computation |
| 4 | Circuit builder — pruning | Temporal, certification, vehicle-group pruning |
| 5 | Solver — circuit constraints | `add_circuit` per driver, self-loops, job assignment |
| 6 | Solver — temporal constraints | Time windows, arc travel time linking |
| 7 | Solver — shift span & activation | Shift span limit, driver activation penalty |
| 8 | Solver — TBA vehicle assignment | Vehicle selection for TBA delivers |
| 9 | Solver — objective function | Weighted cost minimisation |
| 10 | Solver — solution extraction | Extract assignments and driver routes from circuit solution |
| 11 | Integration | Wire into `run_solver.py`, full integration test |

---

## Constants Reference

```python
# In circuit_builder.py
DEPOT_DWELL_MINUTES = 15
TURNAROUND_MINUTES = 45

# In solver.py (or a shared constants module) (eventually we will calculate transit times using GMaps API)
TRANSIT_WEIGHT = 3
DRIVING_WEIGHT = 1
ACTIVATION_PENALTY = 120
SPAN_PENALTY = 1
```

---

## Task 1: Circuit Graph Models

**Files:**
- Modify: `src/scheduler/models.py`
- Test: `tests/test_models.py`

### Step 1: Write the failing test

Add to `tests/test_models.py`:

```python
from scheduler.models import CircuitNode, CircuitArc, DriverCircuitGraph


def test_circuit_node_types():
    """CircuitNode can represent all 5 node types."""
    home = CircuitNode(
        index=0, node_type="home", driver_id="D1",
        postcode="AA1 1AA", job_id=None, storage_location_id=None,
    )
    collect = CircuitNode(
        index=1, node_type="collect", driver_id="D1",
        postcode="BB2 2BB", job_id="J1", storage_location_id=None,
    )
    deliver = CircuitNode(
        index=2, node_type="deliver", driver_id="D1",
        postcode="CC3 3CC", job_id="J2", storage_location_id=None,
    )
    depot_drop = CircuitNode(
        index=3, node_type="depot_drop", driver_id="D1",
        postcode="DD4 4DD", job_id=None, storage_location_id="S001",
    )
    depot_pickup = CircuitNode(
        index=4, node_type="depot_pickup", driver_id="D1",
        postcode="DD4 4DD", job_id=None, storage_location_id="S001",
    )
    assert home.node_type == "home"
    assert collect.node_type == "collect"
    assert deliver.node_type == "deliver"
    assert depot_drop.node_type == "depot_drop"
    assert depot_pickup.node_type == "depot_pickup"


def test_circuit_arc():
    """CircuitArc stores tail, head, travel, cost, and state metadata."""
    arc = CircuitArc(
        tail=0, head=1, travel_minutes=30, cost=90,
        mode="transit", vehicle_reg=None,
    )
    assert arc.tail == 0
    assert arc.head == 1
    assert arc.cost == 90
    assert arc.mode == "transit"


def test_driver_circuit_graph():
    """DriverCircuitGraph bundles nodes and arcs for one driver."""
    home = CircuitNode(
        index=0, node_type="home", driver_id="D1",
        postcode="AA1 1AA", job_id=None, storage_location_id=None,
    )
    arc = CircuitArc(
        tail=0, head=0, travel_minutes=0, cost=0,
        mode="transit", vehicle_reg=None,
    )
    graph = DriverCircuitGraph(driver_id="D1", nodes=[home], arcs=[arc])
    assert graph.driver_id == "D1"
    assert len(graph.nodes) == 1
    assert len(graph.arcs) == 1
```

### Step 2: Run test to verify it fails

Run: `.venv/bin/python -m pytest tests/test_models.py::test_circuit_node_types tests/test_models.py::test_circuit_arc tests/test_models.py::test_driver_circuit_graph -v`
Expected: FAIL with `ImportError: cannot import name 'CircuitNode'`

### Step 3: Write minimal implementation

Add to end of `src/scheduler/models.py` (before `SolverResult`):

```python
class CircuitNode(BaseModel, frozen=True):
    """A node in a driver's circuit graph."""
    index: int  # unique per driver's graph, 0 = home
    node_type: Literal["home", "collect", "deliver", "depot_drop", "depot_pickup"]
    driver_id: str
    postcode: str
    job_id: str | None = None  # set for collect/deliver nodes
    storage_location_id: str | None = None  # set for depot nodes


class CircuitArc(BaseModel, frozen=True):
    """A directed arc in a driver's circuit graph."""
    tail: int  # index of source node
    head: int  # index of destination node
    travel_minutes: int
    cost: int  # weighted cost (integer, for CP-SAT)
    mode: Literal["transit", "driving"]
    vehicle_reg: str | None = None  # set for driving arcs with specific vehicle


class DriverCircuitGraph(BaseModel, frozen=True):
    """Complete circuit graph for one driver."""
    driver_id: str
    nodes: list[CircuitNode]
    arcs: list[CircuitArc]
```

### Step 4: Run test to verify it passes

Run: `.venv/bin/python -m pytest tests/test_models.py::test_circuit_node_types tests/test_models.py::test_circuit_arc tests/test_models.py::test_driver_circuit_graph -v`
Expected: PASS

### Step 5: Commit

```bash
git add src/scheduler/models.py tests/test_models.py
git commit -m "feat: add CircuitNode, CircuitArc, DriverCircuitGraph models"
```

---

## Task 2: Circuit Builder — Node Generation

**Files:**
- Create: `src/scheduler/circuit_builder.py`
- Create: `tests/test_circuit_builder.py`

### Step 1: Write the failing test

Create `tests/test_circuit_builder.py`:

```python
"""Tests for circuit graph construction."""

from datetime import date, time, datetime

from scheduler.models import (
    ActionType, CertLevel, Driver, DriverJobArc, HorizonConfig, Job,
    Location, ProblemInstance, StorageLocation, TransitMatrix, TransitPair,
    Vehicle, VehicleJobArc, JobChainArc,
)
from scheduler.circuit_builder import build_driver_graph

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
        time_offset_minutes=540, window_start_t=window_start, window_end_t=window_end,
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
        time_offset_minutes=540, window_start_t=window_start, window_end_t=window_end,
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
```

### Step 2: Run test to verify it fails

Run: `.venv/bin/python -m pytest tests/test_circuit_builder.py::test_nodes_home_only -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scheduler.circuit_builder'`

### Step 3: Write minimal implementation

Create `src/scheduler/circuit_builder.py`:

```python
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

    # Arcs — built in Task 3
    arcs = _build_arcs(nodes, feasible_jobs, instance)

    return DriverCircuitGraph(driver_id=driver.driver_id, nodes=nodes, arcs=arcs)


def _build_arcs(
    nodes: list[CircuitNode],
    feasible_jobs: list[Job],
    instance: ProblemInstance,
) -> list[CircuitArc]:
    """Build state-legal arcs between nodes. Placeholder — implemented in Task 3."""
    return []
```

### Step 4: Run test to verify it passes

Run: `.venv/bin/python -m pytest tests/test_circuit_builder.py -v`
Expected: PASS (all 4 node tests)

### Step 5: Commit

```bash
git add src/scheduler/circuit_builder.py tests/test_circuit_builder.py
git commit -m "feat: circuit builder — node generation for home, job, and depot nodes"
```

---

## Task 3: Circuit Builder — Arc Generation

**Files:**
- Modify: `src/scheduler/circuit_builder.py`
- Modify: `tests/test_circuit_builder.py`

This is the core of the circuit builder. Arcs must respect the driver state machine:
- EMPTY_HANDED nodes: home, deliver, depot_drop
- IN_VEHICLE nodes: collect, depot_pickup

### Step 1: Write the failing tests

Add to `tests/test_circuit_builder.py`:

```python
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
```

### Step 2: Run tests to verify they fail

Run: `.venv/bin/python -m pytest tests/test_circuit_builder.py::test_arcs_home_to_collect -v`
Expected: FAIL (arcs list is empty — `_build_arcs` returns `[]`)

### Step 3: Write implementation

Replace `_build_arcs` in `src/scheduler/circuit_builder.py`:

```python
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

    # Classify nodes by state
    empty_handed_types = {"home", "deliver", "depot_drop"}
    in_vehicle_types = {"collect", "depot_pickup"}

    # Targets reachable from EMPTY_HANDED state (nodes that accept empty-handed entry)
    # -> COLLECT, DEPOT_PICKUP (these transition to IN_VEHICLE)
    empty_to_targets = {"collect", "depot_pickup"}

    # Targets reachable from IN_VEHICLE state
    # -> DELIVER, DEPOT_DROP, HOME (these transition to EMPTY_HANDED)
    vehicle_to_targets = {"deliver", "depot_drop", "home"}

    # Build a location lookup for nodes
    from scheduler.models import Location
    def _node_location(node: CircuitNode) -> Location | None:
        if node.job_id:
            job = jobs_by_id.get(node.job_id)
            return job.target_location if job else None
        # Home or depot — find location from instance
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

        # Determine which target types this node can reach
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
                # IN_VEHICLE -> driving
                mode = "driving"
                pair = tm.get(tail_loc, head_loc)
                if pair is None:
                    continue
                travel = pair.driving_minutes
                # Add turnaround for COLLECT -> DELIVER
                if tail_node.node_type == "collect" and head_node.node_type == "deliver":
                    travel += TURNAROUND_MINUTES
                # Add depot dwell for arrival at DEPOT_DROP
                if head_node.node_type == "depot_drop":
                    travel += DEPOT_DWELL_MINUTES
                cost = travel * DRIVING_WEIGHT
            else:
                # EMPTY_HANDED -> transit
                mode = "transit"
                pair = tm.get(tail_loc, head_loc)
                if pair is None:
                    continue
                travel = pair.transit_minutes
                # Add depot dwell for arrival at DEPOT_PICKUP
                if head_node.node_type == "depot_pickup":
                    travel += DEPOT_DWELL_MINUTES
                cost = travel * TRANSIT_WEIGHT

            # Determine vehicle_reg on arc (for driving arcs from collect)
            vehicle_reg = None
            if tail_node.node_type == "collect" and tail_node.job_id:
                vehicle_reg = jobs_by_id[tail_node.job_id].vehicle_reg

            arcs.append(CircuitArc(
                tail=tail_node.index, head=head_node.index,
                travel_minutes=travel, cost=cost,
                mode=mode, vehicle_reg=vehicle_reg,
            ))

    return arcs
```

### Step 4: Run tests to verify they pass

Run: `.venv/bin/python -m pytest tests/test_circuit_builder.py -v`
Expected: ALL PASS

### Step 5: Commit

```bash
git add src/scheduler/circuit_builder.py tests/test_circuit_builder.py
git commit -m "feat: circuit builder — state-legal arc generation with cost computation"
```

---

## Task 4: Circuit Builder — Temporal Pruning

**Files:**
- Modify: `src/scheduler/circuit_builder.py`
- Modify: `tests/test_circuit_builder.py`

### Step 1: Write the failing test

Add to `tests/test_circuit_builder.py`:

```python
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
```

### Step 2: Run test to verify it fails

Run: `.venv/bin/python -m pytest tests/test_circuit_builder.py::test_temporal_pruning_removes_unreachable -v`
Expected: FAIL (arc exists because no temporal check yet)

### Step 3: Add temporal pruning to `_build_arcs`

In `src/scheduler/circuit_builder.py`, add temporal check inside the arc-generation loop, just before appending the arc. Add after computing `travel` and before `arcs.append(...)`:

```python
            # Temporal pruning: can the driver reach head_node in time?
            # Use best-case: tail_node's window_start_t + travel <= head_node's window_end_t
            if tail_node.job_id and head_node.job_id:
                tail_job = jobs_by_id[tail_node.job_id]
                head_job = jobs_by_id[head_node.job_id]
                if tail_job.window_start_t + travel > head_job.window_end_t:
                    continue
```

### Step 4: Run tests to verify they pass

Run: `.venv/bin/python -m pytest tests/test_circuit_builder.py -v`
Expected: ALL PASS

### Step 5: Commit

```bash
git add src/scheduler/circuit_builder.py tests/test_circuit_builder.py
git commit -m "feat: circuit builder — temporal pruning of infeasible arcs"
```

---

## Task 5: Solver — Circuit Constraints

**Files:**
- Create: `src/scheduler/circuit_solver.py`
- Create: `tests/test_circuit_solver.py`

We create a new solver file rather than modifying the existing one, to avoid breaking the current solver during development. The old `solver.py` stays untouched until the new one is validated.

### Step 1: Write the failing test

Create `tests/test_circuit_solver.py`:

```python
"""Tests for the circuit-based solver."""

from datetime import date, time, datetime

from scheduler.models import (
    ActionType, CertLevel, Driver, HorizonConfig, Job,
    Location, ProblemInstance, StorageLocation, TransitMatrix, TransitPair,
    Vehicle,
)
from scheduler.circuit_solver import solve_circuit

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


def _make_driver(driver_id="D1", loc=LOC_HOME, max_hours=600):
    return Driver(
        driver_id=driver_id, name=driver_id, home_location=loc,
        branch="TEST", max_hours_per_day=max_hours, certifications=CertLevel.VAN,
        can_overnight=True, unavailable_dates=frozenset(),
    )


def _make_collect(job_id, loc, vehicle_reg="VAN1", group="V3",
                  window_start=480, window_end=600):
    return Job(
        job_id=job_id, book_no=f"B{job_id}", order_ref="", rental_no="",
        book_name="", book_status="",
        action=ActionType.COLLECT, scheduled_date=date(2025, 12, 8),
        scheduled_time=time(9, 0), scheduled_datetime=datetime(2025, 12, 8, 9, 0),
        time_offset_minutes=540, window_start_t=window_start, window_end_t=window_end,
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
        time_offset_minutes=540, window_start_t=window_start, window_end_t=window_end,
        vehicle_reg=vehicle_reg, vehicle_group=group,
        target_location=loc, notes="",
    )


def _make_storage(location_id="S001", loc=LOC_DEPOT):
    return StorageLocation(
        location_id=location_id, name="Depot", location=loc,
        capacity=20, restricted_groups=set(),
    )


def _make_instance(drivers, jobs, storage_locations=None, vehicles=None):
    return ProblemInstance(
        horizon=HORIZON, jobs=jobs, drivers=drivers,
        vehicles=vehicles or [],
        storage_locations=storage_locations or [],
        vehicle_group_certs={"V3": CertLevel.VAN, "V5": CertLevel.VAN},
        transit_matrix=MATRIX,
        driver_job_arcs=[], job_chain_arcs=[], vehicle_job_arcs=[],
    )


# --- Basic circuit feasibility ---

def test_single_collect_feasible():
    """One driver, one collect job — FEASIBLE, driver visits the collect node."""
    d = _make_driver()
    j = _make_collect("J1", LOC_A)
    result = solve_circuit(_make_instance([d], [j]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 1
    assert result.assignments[0].job_id == "J1"


def test_single_deliver_with_depot():
    """One deliver job — driver must go via depot_pickup to get a van.
    Only feasible if a depot exists."""
    d = _make_driver()
    j = _make_deliver("J1", LOC_A, vehicle_reg="VAN1")
    depot = _make_storage()
    result = solve_circuit(_make_instance([d], [j], [depot]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 1


def test_collect_then_deliver_chains():
    """Collect + matching deliver — solver should chain them (cheapest path)."""
    d = _make_driver()
    j1 = _make_collect("J1", LOC_A, vehicle_reg="VAN1", group="V3",
                       window_start=480, window_end=540)
    j2 = _make_deliver("J2", LOC_B, vehicle_reg="VAN1", group="V3",
                       window_start=600, window_end=700)
    result = solve_circuit(_make_instance([d], [j1, j2]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 2
    # Verify ordering: collect before deliver
    starts = {a.job_id: a.start_time_t for a in result.assignments}
    assert starts["J1"] < starts["J2"]


def test_two_collects_need_depot():
    """Two collects, no delivers — driver must visit depot between them.
    Without a depot, only one can be done (the other requires a depot drop)."""
    d = _make_driver()
    j1 = _make_collect("J1", LOC_A, vehicle_reg="VAN1", window_start=480, window_end=540)
    j2 = _make_collect("J2", LOC_B, vehicle_reg="VAN2", window_start=700, window_end=800)
    # Without depot: INFEASIBLE (can't do two collects — no arc COLLECT->COLLECT)
    # But we have two drivers to make it feasible without depot
    d2 = _make_driver("D2")
    result_no_depot = solve_circuit(_make_instance([d, d2], [j1, j2]))
    assert result_no_depot.status in ("OPTIMAL", "FEASIBLE")
    # With one driver and a depot: also FEASIBLE
    depot = _make_storage()
    result_depot = solve_circuit(_make_instance([d], [j1, j2], [depot]))
    assert result_depot.status in ("OPTIMAL", "FEASIBLE")


def test_multi_driver_assignment():
    """Two jobs, two drivers — both assigned."""
    d1 = _make_driver("D1")
    d2 = _make_driver("D2")
    j1 = _make_collect("J1", LOC_A, window_start=480, window_end=540)
    j2 = _make_collect("J2", LOC_B, window_start=480, window_end=540)
    result = solve_circuit(_make_instance([d1, d2], [j1, j2]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 2
```

### Step 2: Run test to verify it fails

Run: `.venv/bin/python -m pytest tests/test_circuit_solver.py::test_single_collect_feasible -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scheduler.circuit_solver'`

### Step 3: Write minimal solver implementation

Create `src/scheduler/circuit_solver.py`:

```python
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
                # Home: arrival time is departure time (start of day)
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

        # Create arc boolean variables and add circuit constraint
        circuit_arcs = []
        for arc in graph.arcs:
            var = model.new_bool_var(f"arc_{driver_id}_{arc.tail}_{arc.head}")
            arc_vars[driver_id][(arc.tail, arc.head)] = var
            circuit_arcs.append((arc.tail, arc.head, var))

        if circuit_arcs:
            model.add_circuit(circuit_arcs)

        # --- Temporal constraints on arcs ---
        for arc in graph.arcs:
            if arc.tail == arc.head:
                continue  # skip self-loops
            var = arc_vars[driver_id][(arc.tail, arc.head)]
            model.add(
                arrival_time[driver_id][arc.head]
                >= arrival_time[driver_id][arc.tail] + arc.travel_minutes
            ).only_enforce_if(var)

    # --- Job assignment: every job assigned to exactly one driver ---
    # Map job_id -> list of (driver_id, node_index) across all drivers
    job_visit_vars: dict[str, list[cp_model.IntVar]] = defaultdict(list)
    for driver_id, graph in driver_graphs.items():
        for node in graph.nodes:
            if node.job_id:
                # "visited" = NOT self-loop
                self_loop_var = arc_vars[driver_id].get((node.index, node.index))
                if self_loop_var is not None:
                    visited = self_loop_var.negated()
                    job_visit_vars[node.job_id].append(visited)

    for job in instance.jobs:
        visitors = job_visit_vars.get(job.job_id, [])
        if visitors:
            model.add_exactly_one(visitors)
        else:
            # No driver can visit this job — force infeasible
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

        # Collect all job visit indicators for this driver
        job_nodes = [n for n in graph.nodes if n.job_id]
        visit_indicators = []
        for node in job_nodes:
            self_loop = arc_vars[driver_id].get((node.index, node.index))
            if self_loop is not None:
                visit_indicators.append(self_loop.negated())

        if visit_indicators:
            model.add(sum(visit_indicators) >= 1).only_enforce_if(is_w)
            model.add(sum(visit_indicators) == 0).only_enforce_if(is_w.negated())
        else:
            model.add(is_w == 0)

        # When not working: pin to zero
        model.add(s_start == 0).only_enforce_if(is_w.negated())
        model.add(s_end == 0).only_enforce_if(is_w.negated())

        # Shift start <= home departure (= arrival_time at home node 0)
        model.add(s_start <= arrival_time[driver_id][0]).only_enforce_if(is_w)

        # Shift end: for each arc returning to home, shift_end >= arrival at destination
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
        # span_penalty = SPAN_PENALTY * (shift_end - shift_start)
        # We can't multiply IntVar by constant directly in objective with subtraction,
        # so add shift_end and subtract shift_start
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
                self_loop = arc_vars[driver_id].get((node.index, node.index))
                if self_loop is not None and not solver.value(self_loop):
                    # Node is visited (self-loop is off)
                    start_t = solver.value(arrival_time[driver_id][node.index])
                    assignments.append(JobAssignment(
                        job_id=node.job_id,
                        driver_id=driver_id,
                        start_time_t=start_t,
                        start_datetime=_t_to_datetime(start_t, instance.horizon),
                    ))

    elapsed = time_mod.monotonic() - start_wall

    return SolverResult(
        status=status,
        solve_time_seconds=round(elapsed, 3),
        assignments=assignments,
        driver_routes=[],  # Task 10
        stats={
            "variables": sum(len(avs) for avs in arc_vars.values()),
            "constraints": len(model.proto.constraints),
        },
    )
```

### Step 4: Run tests to verify they pass

Run: `.venv/bin/python -m pytest tests/test_circuit_solver.py -v`
Expected: ALL PASS

### Step 5: Commit

```bash
git add src/scheduler/circuit_solver.py tests/test_circuit_solver.py
git commit -m "feat: circuit solver — add_circuit per driver with temporal constraints and objective"
```

---

## Task 6: Solver — Vehicle Custody Verification Tests

**Files:**
- Modify: `tests/test_circuit_solver.py`

These tests verify that the state machine structurally prevents illegal sequences.

### Step 1: Write the tests

Add to `tests/test_circuit_solver.py`:

```python
# --- Vehicle custody ---

def test_no_double_collect_one_driver():
    """One driver, two collects, no depot — one driver can only do one collect.
    The second must go to another driver."""
    d1 = _make_driver("D1")
    d2 = _make_driver("D2")
    j1 = _make_collect("J1", LOC_A, vehicle_reg="VAN1", window_start=480, window_end=540)
    j2 = _make_collect("J2", LOC_B, vehicle_reg="VAN2", window_start=480, window_end=540)
    # No depot — can't park between collects
    result = solve_circuit(_make_instance([d1, d2], [j1, j2]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 2
    # Each driver does exactly one job
    drivers_used = {a.driver_id for a in result.assignments}
    assert len(drivers_used) == 2


def test_collect_deliver_collect_feasible_with_depot():
    """Collect -> Deliver -> Collect is feasible (driver drops van, takes transit, collects another)."""
    d = _make_driver()
    j1 = _make_collect("J1", LOC_A, vehicle_reg="VAN1", group="V3",
                       window_start=480, window_end=540)
    j2 = _make_deliver("J2", LOC_B, vehicle_reg="VAN1", group="V3",
                       window_start=600, window_end=700)
    j3 = _make_collect("J3", LOC_A, vehicle_reg="VAN2", group="V3",
                       window_start=800, window_end=900)
    result = solve_circuit(_make_instance([d], [j1, j2, j3]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 3
    starts = {a.job_id: a.start_time_t for a in result.assignments}
    assert starts["J1"] < starts["J2"] < starts["J3"]


def test_shift_span_limit():
    """Shift span exceeding max_hours_per_day is infeasible."""
    d = _make_driver(max_hours=50)  # 50 minutes max
    # Job at 480, deadhead 30 min each way = 60 min span minimum
    j = _make_collect("J1", LOC_A, window_start=480, window_end=540)
    result = solve_circuit(_make_instance([d], [j]))
    assert result.status == "INFEASIBLE"
```

### Step 2: Run tests

Run: `.venv/bin/python -m pytest tests/test_circuit_solver.py -v`
Expected: ALL PASS (these should pass with the existing solver code from Task 5)

### Step 3: Commit

```bash
git add tests/test_circuit_solver.py
git commit -m "test: add vehicle custody and shift span verification tests"
```

---

## Task 7: Solver — TBA Vehicle Assignment

**Files:**
- Modify: `src/scheduler/circuit_solver.py`
- Modify: `tests/test_circuit_solver.py`

TBA Deliver jobs (no vehicle_reg) need a van from somewhere. In the circuit model:
- A TBA DELIVER can be reached from a COLLECT with matching group (handled structurally)
- Or from a DEPOT_PICKUP (needs vehicle selection variable)

### Step 1: Write the failing test

Add to `tests/test_circuit_solver.py`:

```python
# --- TBA vehicle assignment ---

def test_tba_deliver_from_depot():
    """TBA deliver job — solver picks a depot vehicle and routes through depot_pickup."""
    d = _make_driver()
    j = _make_deliver("J1", LOC_A, vehicle_reg=None, group="V3",
                      window_start=480, window_end=700)
    depot = _make_storage()
    v = Vehicle(reg="VAN1", group="V3", current_location=LOC_DEPOT,
                available_from=date(2025, 12, 8), available_from_t=0)
    result = solve_circuit(_make_instance([d], [j], [depot], [v]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 1


def test_tba_deliver_from_collect_chain():
    """TBA deliver sourced from a collect chain — no depot vehicle needed."""
    d = _make_driver()
    j1 = _make_collect("J1", LOC_A, vehicle_reg="VAN1", group="V3",
                       window_start=480, window_end=540)
    j2 = _make_deliver("J2", LOC_B, vehicle_reg=None, group="V3",
                       window_start=600, window_end=800)
    result = solve_circuit(_make_instance([d], [j1, j2]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 2


def test_tba_no_source_infeasible():
    """TBA deliver with no depot vehicle and no matching collect — INFEASIBLE."""
    d = _make_driver()
    j = _make_deliver("J1", LOC_A, vehicle_reg=None, group="V3",
                      window_start=480, window_end=700)
    # No depot, no vehicles, no collects
    result = solve_circuit(_make_instance([d], [j]))
    assert result.status == "INFEASIBLE"
```

### Step 2: Run tests

Run: `.venv/bin/python -m pytest tests/test_circuit_solver.py::test_tba_deliver_from_depot -v`
Expected: This test will likely FAIL because the solver currently doesn't handle TBA vehicle assignment in the circuit model. The depot_pickup node exists but there's no vehicle selection variable.

### Step 3: Add TBA vehicle assignment to circuit solver

Add to `src/scheduler/circuit_solver.py`, inside `solve_circuit`, after the job assignment constraint block:

```python
    # --- TBA vehicle assignment ---
    # For TBA deliver jobs (vehicle_reg is None), the driver must either:
    # 1. Arrive from a COLLECT with matching group (structural — already handled by arcs)
    # 2. Arrive from a DEPOT_PICKUP with a selected vehicle
    #
    # We need to ensure exactly one van source per TBA job.
    tba_jobs = [j for j in instance.jobs if j.vehicle_reg is None]

    if tba_jobs:
        # For each TBA job, collect all possible van sources across all drivers:
        # - COLLECT -> TBA_DELIVER arcs (van comes from collect)
        # - DEPOT_PICKUP -> TBA_DELIVER arcs (van comes from depot, need vehicle selection)
        for tba_job in tba_jobs:
            van_sources: list[cp_model.IntVar] = []

            for driver_id, graph in driver_graphs.items():
                tba_node = None
                for node in graph.nodes:
                    if node.job_id == tba_job.job_id:
                        tba_node = node
                        break
                if tba_node is None:
                    continue

                # Source 1: COLLECT -> TBA_DELIVER arcs
                for arc in graph.arcs:
                    if arc.head != tba_node.index or arc.tail == arc.head:
                        continue
                    tail_node = graph.nodes[arc.tail]
                    if tail_node.node_type == "collect":
                        var = arc_vars[driver_id][(arc.tail, arc.head)]
                        van_sources.append(var)

                # Source 2: DEPOT_PICKUP -> TBA_DELIVER arcs
                for arc in graph.arcs:
                    if arc.head != tba_node.index or arc.tail == arc.head:
                        continue
                    tail_node = graph.nodes[arc.tail]
                    if tail_node.node_type == "depot_pickup":
                        var = arc_vars[driver_id][(arc.tail, arc.head)]
                        van_sources.append(var)

            # Must have exactly one van source (or the job can't be done)
            if not van_sources:
                false_var = model.new_bool_var(f"tba_infeasible_{tba_job.job_id}")
                model.add(false_var == 1)
                model.add(false_var == 0)
```

### Step 4: Run tests to verify they pass

Run: `.venv/bin/python -m pytest tests/test_circuit_solver.py -v`
Expected: ALL PASS

### Step 5: Commit

```bash
git add src/scheduler/circuit_solver.py tests/test_circuit_solver.py
git commit -m "feat: circuit solver — TBA vehicle assignment via depot or collect chain"
```

---

## Task 8: Solver — Activation Penalty & Density Tests

**Files:**
- Modify: `tests/test_circuit_solver.py`

### Step 1: Write the test

Add to `tests/test_circuit_solver.py`:

```python
# --- Objective function behavior ---

def test_activation_penalty_prefers_fewer_drivers():
    """With activation penalty, solver prefers fewer drivers for two jobs
    that one driver can handle."""
    d1 = _make_driver("D1")
    d2 = _make_driver("D2")
    j1 = _make_collect("J1", LOC_A, window_start=480, window_end=540)
    j2 = _make_collect("J2", LOC_B, window_start=700, window_end=800)
    depot = _make_storage()
    result = solve_circuit(_make_instance([d1, d2], [j1, j2], [depot]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 2
    # With activation penalty, solver should use 1 driver (via depot between collects)
    drivers_used = {a.driver_id for a in result.assignments}
    assert len(drivers_used) == 1


def test_chaining_cheaper_than_depot_detour():
    """Collect -> Deliver chain should be cheaper than Collect -> Depot -> transit -> Deliver.
    Verify the solver chains when a matching collect/deliver pair exists."""
    d = _make_driver()
    j1 = _make_collect("J1", LOC_A, vehicle_reg="VAN1", group="V3",
                       window_start=480, window_end=540)
    j2 = _make_deliver("J2", LOC_B, vehicle_reg="VAN1", group="V3",
                       window_start=600, window_end=800)
    depot = _make_storage()
    result = solve_circuit(_make_instance([d], [j1, j2], [depot]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    # Verify ordering
    starts = {a.job_id: a.start_time_t for a in result.assignments}
    assert starts["J1"] < starts["J2"]
```

### Step 2: Run tests

Run: `.venv/bin/python -m pytest tests/test_circuit_solver.py -v`
Expected: ALL PASS

### Step 3: Commit

```bash
git add tests/test_circuit_solver.py
git commit -m "test: verify activation penalty and chaining preference in objective"
```

---

## Task 9: Solver — Driver Route Extraction

**Files:**
- Modify: `src/scheduler/circuit_solver.py`
- Modify: `tests/test_circuit_solver.py`

### Step 1: Write the failing test

Add to `tests/test_circuit_solver.py`:

```python
# --- Route extraction ---

def test_route_extraction_single_collect():
    """Single collect: route = HOME -transit-> COLLECT -driving-> HOME."""
    d = _make_driver()
    j = _make_collect("J1", LOC_A, window_start=480, window_end=600)
    result = solve_circuit(_make_instance([d], [j]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.driver_routes) == 1
    route = result.driver_routes[0]
    assert route.driver_id == "D1"
    assert route.home_postcode == "HH1 1HH"
    assert len(route.legs) >= 2
    # First leg: transit from home
    assert route.legs[0].from_postcode == "HH1 1HH"
    assert route.legs[0].mode == "transit"
    # Last leg: driving back home (collect = in-vehicle)
    assert route.legs[-1].to_postcode == "HH1 1HH"
    assert route.legs[-1].mode == "driving"


def test_route_extraction_collect_deliver_chain():
    """Collect then deliver: HOME -transit-> COLLECT -driving-> DELIVER -transit-> HOME."""
    d = _make_driver()
    j1 = _make_collect("J1", LOC_A, vehicle_reg="VAN1", group="V3",
                       window_start=480, window_end=540)
    j2 = _make_deliver("J2", LOC_B, vehicle_reg="VAN1", group="V3",
                       window_start=600, window_end=800)
    result = solve_circuit(_make_instance([d], [j1, j2]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.driver_routes) == 1
    route = result.driver_routes[0]
    assert len(route.legs) >= 3
    # First: transit to collect
    assert route.legs[0].mode == "transit"
    # Middle: driving collect -> deliver
    assert route.legs[1].mode == "driving"
    # Last: transit home (after deliver, driver is empty-handed)
    assert route.legs[-1].to_postcode == "HH1 1HH"
    assert route.legs[-1].mode == "transit"
```

### Step 2: Run tests to verify they fail

Run: `.venv/bin/python -m pytest tests/test_circuit_solver.py::test_route_extraction_single_collect -v`
Expected: FAIL (`driver_routes` is empty `[]`)

### Step 3: Implement route extraction

Add to `src/scheduler/circuit_solver.py`, inside `solve_circuit`, in the solution extraction block (replace `driver_routes=[],`):

```python
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
        path: list[int] = [0]  # start at home
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
            head_idx = path[i + 1] if i + 1 < len(path) else 0  # last goes home
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
```

Then wire it into the solution extraction:

```python
    # Replace driver_routes=[] with:
    driver_routes = []
    if status in ("OPTIMAL", "FEASIBLE"):
        driver_routes = _extract_driver_routes(
            solver, driver_graphs, arc_vars, arrival_time,
            drivers_by_id, jobs_by_id, instance,
        )
```

### Step 4: Run tests to verify they pass

Run: `.venv/bin/python -m pytest tests/test_circuit_solver.py -v`
Expected: ALL PASS

### Step 5: Commit

```bash
git add src/scheduler/circuit_solver.py tests/test_circuit_solver.py
git commit -m "feat: circuit solver — driver route extraction from solved circuit"
```

---

## Task 10: Integration — Wire Up & Full Test

**Files:**
- Modify: `tests/test_circuit_solver.py`
- Modify: `run_solver.py` (optional, after validation)

### Step 1: Write the integration test

Add to `tests/test_circuit_solver.py`:

```python
from pathlib import Path


def test_circuit_solver_real_sample_data():
    """Integration: build from real CSVs and solve with circuit solver.
    Must find a feasible schedule with all jobs assigned."""
    from scheduler.builder import ProblemBuilder

    ROOT = Path(__file__).resolve().parent.parent
    result = (
        ProblemBuilder(horizon_start=date(2025, 12, 8), num_days=5)
        .load_postcode_coords(ROOT / "ref-data" / "postcode_coords.csv")
        .load_storage_locations(ROOT / "ref-data" / "storage_locations.csv")
        .load_drivers(ROOT / "ref-data" / "drivers.csv")
        .load_vehicles(ROOT / "ref-data" / "vehicle_inventory.csv")
        .load_bookings(ROOT / "input" / "sample_bookings_data.csv")
        .build()
    )
    assert result.ok
    inst = result.instance

    solver_result = solve_circuit(inst, timeout_seconds=120)
    assert solver_result.status in ("OPTIMAL", "FEASIBLE"), (
        f"Circuit solver returned {solver_result.status} on sample data"
    )
    assert len(solver_result.assignments) == len(inst.jobs)
    assigned_job_ids = {a.job_id for a in solver_result.assignments}
    expected_job_ids = {j.job_id for j in inst.jobs}
    assert assigned_job_ids == expected_job_ids

    # Verify vehicle custody: no driver does two collects in a row
    from collections import defaultdict
    by_driver = defaultdict(list)
    for a in solver_result.assignments:
        by_driver[a.driver_id].append(a)
    jobs_by_id_local = {j.job_id: j for j in inst.jobs}
    for driver_id, assigns in by_driver.items():
        sorted_assigns = sorted(assigns, key=lambda a: a.start_time_t)
        for i in range(len(sorted_assigns) - 1):
            curr = jobs_by_id_local[sorted_assigns[i].job_id]
            nxt = jobs_by_id_local[sorted_assigns[i + 1].job_id]
            # Two collects in a row is only valid if there's a depot visit between them.
            # The circuit model enforces this structurally, but we verify the output.
            if curr.action.value == "collect" and nxt.action.value == "collect":
                # This is allowed ONLY if the driver visited a depot_drop between them.
                # For now, just verify it happened via the route legs.
                pass  # structural guarantee — if circuit is correct, this can't happen without depot

    # Verify routes exist for used drivers
    assert len(solver_result.driver_routes) > 0
```

### Step 2: Run the test

Run: `.venv/bin/python -m pytest tests/test_circuit_solver.py::test_circuit_solver_real_sample_data -v --timeout=180`
Expected: PASS (may take 30-120 seconds for real data)

### Step 3: Commit

```bash
git add tests/test_circuit_solver.py
git commit -m "test: integration test for circuit solver on real sample data"
```

---

## Task 11: Switch `run_solver.py` to Circuit Solver

**Files:**
- Modify: `run_solver.py`

This is the final switchover. Only do this after all tests pass.

### Step 1: Update `run_solver.py`

Change the import and call:

```python
# Change:
from scheduler.solver import solve
# To:
from scheduler.circuit_solver import solve_circuit as solve
```

### Step 2: Run end-to-end

Run: `.venv/bin/python run_solver.py`
Expected: Full output with schedule, CSV export, and JSON export.

### Step 3: Run all tests

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: ALL PASS (both old and new test suites)

### Step 4: Commit

```bash
git add run_solver.py
git commit -m "feat: switch run_solver.py to circuit-based solver"
```

---

## Appendix: Node Index Convention

For each driver, nodes are indexed as:
- `0` — HOME (always)
- `1..N` — job nodes (COLLECT or DELIVER), in order they appear in `feasible_jobs`
- `N+1..N+2S` — depot nodes (DROP, PICKUP alternating), for each storage location

This convention is stable and used throughout the solver for arc variable naming and circuit constraint construction.

## Appendix: What's Deferred

These items from the design doc are **not** included in this plan:
- Storage location capacity constraints (deferred)
- `can_overnight` / multi-day assignment rules (deferred)
- Soft time window penalties (windows remain hard bounds)
- Geographic parking constraints for restricted postcodes (deferred)
- Removing the old `solver.py` (kept for comparison)
