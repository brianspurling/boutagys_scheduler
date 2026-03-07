# Bare-Minimum Feasible Solver — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a CP-SAT solver that finds any feasible schedule assigning every job to exactly one driver, respecting time windows and physical travel constraints.

**Architecture:** Boolean arc variables with optional service intervals. Physical travel enforced via pre-computed `JobChainArc` list (3 cases: mutual exclusion, strict order, disjunctive sequence). Standalone `solve(instance) -> SolverResult` function. Console + CSV output.

**Tech Stack:** Python 3.12+, Pydantic v2, Google OR-Tools CP-SAT, pytest.

**Design doc:** `docs/plans/2026-03-07-bare-minimum-solver-design.md`

**Project root:** `/Users/Shared/_code/boutagys_scheduler`

---

## Task 0: Add ortools dependency

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add ortools to dependencies**

In `pyproject.toml`, add `"ortools>=9.9"` to the `dependencies` list:

```toml
[project]
name = "boutagys-scheduler"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.0",
    "ortools>=9.9",
]
```

**Step 2: Install**

Run: `source .venv/bin/activate && pip install -e ".[dev]"`
Expected: Clean install with ortools available.

**Step 3: Verify import works**

Run: `python3 -c "from ortools.sat.python import cp_model; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "deps: add ortools for CP-SAT solver"
```

---

## Task 1: Add JobAssignment and SolverResult models

**Files:**
- Modify: `src/scheduler/models.py` (add after `BuildResult` class, around line 153)
- Test: `tests/test_models.py`

**Step 1: Write the failing test**

Add to `tests/test_models.py`:

```python
from scheduler.models import JobAssignment, SolverResult

def test_job_assignment():
    a = JobAssignment(
        job_id="J001",
        driver_id="D001",
        start_time_t=540,
        start_datetime=datetime(2025, 12, 8, 9, 0),
    )
    assert a.job_id == "J001"
    assert a.start_time_t == 540
    assert a.start_datetime == datetime(2025, 12, 8, 9, 0)


def test_solver_result_feasible():
    r = SolverResult(
        status="FEASIBLE",
        solve_time_seconds=1.23,
        assignments=[
            JobAssignment(job_id="J001", driver_id="D001", start_time_t=540,
                          start_datetime=datetime(2025, 12, 8, 9, 0)),
        ],
        stats={"variables": 100, "constraints": 50},
    )
    assert r.status == "FEASIBLE"
    assert len(r.assignments) == 1


def test_solver_result_infeasible():
    r = SolverResult(
        status="INFEASIBLE",
        solve_time_seconds=0.5,
        assignments=[],
        stats={},
    )
    assert r.assignments == []
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_models.py::test_job_assignment tests/test_models.py::test_solver_result_feasible tests/test_models.py::test_solver_result_infeasible -v`
Expected: FAIL with `ImportError: cannot import name 'JobAssignment'`

**Step 3: Write minimal implementation**

Add to `src/scheduler/models.py` after the `BuildResult` class:

```python
class JobAssignment(BaseModel, frozen=True):
    job_id: str
    driver_id: str
    start_time_t: int
    start_datetime: datetime


class SolverResult(BaseModel, frozen=True):
    status: str
    solve_time_seconds: float
    assignments: list[JobAssignment]
    stats: dict[str, int]
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_models.py -v`
Expected: All pass (existing + 3 new).

**Step 5: Commit**

```bash
git add src/scheduler/models.py tests/test_models.py
git commit -m "feat: add JobAssignment and SolverResult models"
```

---

## Task 2: Solver — basic feasibility (Constraints 1 & 2 only)

Build the solver with just assignment + no-overlap. This won't be physically correct yet (teleportation bug), but it proves the CP-SAT wiring works before adding the harder Constraint 3.

**Files:**
- Create: `src/scheduler/solver.py`
- Create: `tests/test_solver.py`

**Context:**
- The solver consumes `ProblemInstance` from `src/scheduler/models.py`
- `ProblemInstance.driver_job_arcs` is a `list[DriverJobArc]` with `(driver_id, job_id, deadhead_minutes)`
- `ProblemInstance.jobs` is a `list[Job]` where each job has `window_start_t`, `window_end_t`
- `ProblemInstance.horizon` has `start_date`, `num_days`, `t_max`
- The solver must return `SolverResult` with `JobAssignment` objects

**Step 1: Write the failing test**

Create `tests/test_solver.py`:

```python
"""Unit tests for the CP-SAT solver using small synthetic ProblemInstance objects."""

from datetime import date, time, datetime

from scheduler.models import (
    ActionType, CertLevel, Driver, DriverJobArc, HorizonConfig, Job,
    JobChainArc, Location, ProblemInstance, StorageLocation, TransitMatrix,
    TransitPair, VehicleJobArc,
)
from scheduler.solver import solve

LOC_A = Location(postcode="AA1 1AA", lat=51.5, lon=-0.1)
LOC_B = Location(postcode="BB2 2BB", lat=51.6, lon=-0.2)
LOC_C = Location(postcode="CC3 3CC", lat=51.7, lon=-0.3)

HORIZON = HorizonConfig(start_date=date(2025, 12, 8), num_days=1, t_max=1440)

MATRIX = TransitMatrix(entries={
    ("AA1 1AA", "BB2 2BB"): TransitPair(transit_minutes=30, driving_minutes=20),
    ("BB2 2BB", "AA1 1AA"): TransitPair(transit_minutes=30, driving_minutes=20),
    ("AA1 1AA", "CC3 3CC"): TransitPair(transit_minutes=40, driving_minutes=25),
    ("CC3 3CC", "AA1 1AA"): TransitPair(transit_minutes=40, driving_minutes=25),
    ("BB2 2BB", "CC3 3CC"): TransitPair(transit_minutes=50, driving_minutes=30),
    ("CC3 3CC", "BB2 2BB"): TransitPair(transit_minutes=50, driving_minutes=30),
})


def _make_driver(driver_id: str, loc: Location = LOC_A) -> Driver:
    return Driver(
        driver_id=driver_id, name=driver_id, home_location=loc,
        branch="TEST", max_hours_per_day=600, certifications=CertLevel.VAN,
        can_overnight=True, unavailable_dates=frozenset(),
    )


def _make_job(
    job_id: str, loc: Location, window_start: int = 480, window_end: int = 600,
) -> Job:
    return Job(
        job_id=job_id, book_no=f"B{job_id}", order_ref="", rental_no="",
        book_name="", book_status="",
        action=ActionType.COLLECT, scheduled_date=date(2025, 12, 8),
        scheduled_time=time(9, 0), scheduled_datetime=datetime(2025, 12, 8, 9, 0),
        time_offset_minutes=540, window_start_t=window_start, window_end_t=window_end,
        vehicle_reg="VAN1", vehicle_group="V3",
        target_location=loc, notes="",
    )


def _make_instance(
    drivers: list[Driver],
    jobs: list[Job],
    driver_job_arcs: list[DriverJobArc],
    job_chain_arcs: list[JobChainArc] | None = None,
) -> ProblemInstance:
    return ProblemInstance(
        horizon=HORIZON, jobs=jobs, drivers=drivers, vehicles=[],
        storage_locations=[], vehicle_group_certs={},
        transit_matrix=MATRIX,
        driver_job_arcs=driver_job_arcs,
        job_chain_arcs=job_chain_arcs or [],
        vehicle_job_arcs=[],
    )


def test_solve_basic_feasible():
    """Two non-overlapping jobs, one driver — should be FEASIBLE."""
    d1 = _make_driver("D1")
    j1 = _make_job("J1", LOC_B, window_start=480, window_end=540)
    j2 = _make_job("J2", LOC_B, window_start=600, window_end=660)
    arcs = [
        DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=30),
        DriverJobArc(driver_id="D1", job_id="J2", deadhead_minutes=30),
    ]
    # Chain arc: J1->J2 feasible (same location, zero travel)
    chains = [
        JobChainArc(from_job_id="J1", to_job_id="J2", chain_type="driver_only",
                    travel_minutes=0, turnaround_minutes=0),
        JobChainArc(from_job_id="J2", to_job_id="J1", chain_type="driver_only",
                    travel_minutes=0, turnaround_minutes=0),
    ]
    result = solve(_make_instance([d1], [j1, j2], arcs, chains))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 2
    assert {a.job_id for a in result.assignments} == {"J1", "J2"}


def test_solve_multi_driver():
    """Three jobs, two drivers — solver must split work."""
    d1 = _make_driver("D1", LOC_A)
    d2 = _make_driver("D2", LOC_B)
    j1 = _make_job("J1", LOC_B, window_start=480, window_end=540)
    j2 = _make_job("J2", LOC_B, window_start=480, window_end=540)
    j3 = _make_job("J3", LOC_B, window_start=480, window_end=540)
    arcs = [
        DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=30),
        DriverJobArc(driver_id="D1", job_id="J2", deadhead_minutes=30),
        DriverJobArc(driver_id="D1", job_id="J3", deadhead_minutes=30),
        DriverJobArc(driver_id="D2", job_id="J1", deadhead_minutes=0),
        DriverJobArc(driver_id="D2", job_id="J2", deadhead_minutes=0),
        DriverJobArc(driver_id="D2", job_id="J3", deadhead_minutes=0),
    ]
    # All at same location, all overlapping — no chain arcs between them
    # means mutual exclusion per driver. Need 2 drivers for 3 overlapping jobs.
    result = solve(_make_instance([d1, d2], [j1, j2, j3], arcs))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 3
    drivers_used = {a.driver_id for a in result.assignments}
    assert len(drivers_used) == 2  # Both drivers must be used
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_solver.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scheduler.solver'`

**Step 3: Write minimal implementation**

Create `src/scheduler/solver.py`:

```python
"""CP-SAT solver: bare-minimum feasible schedule."""

from __future__ import annotations

import time as time_mod
from collections import defaultdict
from datetime import datetime, time, timedelta

from ortools.sat.python import cp_model

from scheduler.models import (
    ChainType, HorizonConfig, JobAssignment, ProblemInstance, SolverResult,
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
    # driver_id -> list of (job_id, deadhead_minutes)
    driver_arcs: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for arc in instance.driver_job_arcs:
        driver_arcs[arc.driver_id].append((arc.job_id, arc.deadhead_minutes))

    # job_id -> list of driver_ids that can serve it
    job_drivers: dict[str, list[str]] = defaultdict(list)
    for arc in instance.driver_job_arcs:
        job_drivers[arc.job_id].append(arc.driver_id)

    # Chain arc lookup: (from_job_id, to_job_id) -> JobChainArc (DRIVER_ONLY only)
    chain_lookup: dict[tuple[str, str], int] = {}
    for arc in instance.job_chain_arcs:
        if arc.chain_type == ChainType.DRIVER_ONLY:
            chain_lookup[(arc.from_job_id, arc.to_job_id)] = arc.travel_minutes

    # --- Variables ---
    # x[driver_id, job_id] = BoolVar: assignment
    x: dict[tuple[str, str], cp_model.IntVar] = {}
    # start[driver_id, job_id] = IntVar: service start time
    start: dict[tuple[str, str], cp_model.IntVar] = {}
    # interval[driver_id, job_id] = IntervalVar: optional service interval
    intervals: dict[str, list[cp_model.IntervalVar]] = defaultdict(list)

    for driver_id, arc_list in driver_arcs.items():
        for job_id, deadhead in arc_list:
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
        job_ids = [job_id for job_id, _ in arc_list]
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
        for job_id, deadhead in arc_list:
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
            "constraints": model.proto.constraints.__len__(),
        },
    )
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_solver.py -v`
Expected: All pass.

**Step 5: Commit**

```bash
git add src/scheduler/solver.py tests/test_solver.py
git commit -m "feat: add CP-SAT solver with assignment, overlap, travel, and deadhead constraints"
```

---

## Task 3: Solver — infeasibility and deadhead tests

Add tests that verify the solver correctly returns INFEASIBLE when physics are violated, and that deadhead from home is enforced.

**Files:**
- Modify: `tests/test_solver.py`

**Step 1: Write the failing tests**

Add to `tests/test_solver.py`:

```python
def test_solve_mutual_exclusion_no_chain_arc():
    """Two overlapping jobs, one driver, NO chain arc between them — INFEASIBLE.
    Without a chain arc, the solver adds mutual exclusion (x[d,i] + x[d,j] <= 1),
    but Constraint 1 requires both assigned. With only 1 driver, this is impossible."""
    d1 = _make_driver("D1")
    j1 = _make_job("J1", LOC_B, window_start=480, window_end=540)
    j2 = _make_job("J2", LOC_C, window_start=480, window_end=540)
    arcs = [
        DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=30),
        DriverJobArc(driver_id="D1", job_id="J2", deadhead_minutes=40),
    ]
    # No chain arcs at all — Case 1 mutual exclusion kicks in
    result = solve(_make_instance([d1], [j1, j2], arcs, job_chain_arcs=[]))
    assert result.status == "INFEASIBLE"
    assert result.assignments == []


def test_solve_deadhead_too_late():
    """Driver's deadhead exceeds the job's time window — INFEASIBLE.
    Job window is [480, 490] but deadhead is 500 minutes. Constraint 4
    forces start >= 500, which violates the domain [480, 490]."""
    d1 = _make_driver("D1")
    j1 = _make_job("J1", LOC_B, window_start=480, window_end=490)
    arcs = [
        DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=500),
    ]
    result = solve(_make_instance([d1], [j1], arcs))
    assert result.status == "INFEASIBLE"


def test_solve_strict_order_enforced():
    """Two jobs, one driver, chain arc only in one direction (J1->J2).
    J1 at minute 480, J2 at minute 490 — but travel is 50 minutes.
    480 + 0 + 50 = 530 > 490 (J2.window_end). Should be INFEASIBLE."""
    d1 = _make_driver("D1")
    j1 = _make_job("J1", LOC_B, window_start=480, window_end=490)
    j2 = _make_job("J2", LOC_C, window_start=480, window_end=490)
    arcs = [
        DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=30),
        DriverJobArc(driver_id="D1", job_id="J2", deadhead_minutes=40),
    ]
    # Only J1->J2 arc, travel 50 minutes
    chains = [
        JobChainArc(from_job_id="J1", to_job_id="J2", chain_type="driver_only",
                    travel_minutes=50, turnaround_minutes=0),
    ]
    result = solve(_make_instance([d1], [j1, j2], arcs, chains))
    assert result.status == "INFEASIBLE"


def test_solve_disjunctive_sequence():
    """Two jobs with chain arcs in BOTH directions, wide windows.
    Should be FEASIBLE — solver picks an order."""
    d1 = _make_driver("D1")
    j1 = _make_job("J1", LOC_B, window_start=480, window_end=700)
    j2 = _make_job("J2", LOC_C, window_start=480, window_end=700)
    arcs = [
        DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=30),
        DriverJobArc(driver_id="D1", job_id="J2", deadhead_minutes=40),
    ]
    chains = [
        JobChainArc(from_job_id="J1", to_job_id="J2", chain_type="driver_only",
                    travel_minutes=50, turnaround_minutes=0),
        JobChainArc(from_job_id="J2", to_job_id="J1", chain_type="driver_only",
                    travel_minutes=50, turnaround_minutes=0),
    ]
    result = solve(_make_instance([d1], [j1, j2], arcs, chains))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 2
    # Verify ordering — one must start at least 50 minutes after the other
    starts = {a.job_id: a.start_time_t for a in result.assignments}
    gap = abs(starts["J1"] - starts["J2"])
    assert gap >= 50
```

**Step 2: Run tests to verify they pass**

Run: `pytest tests/test_solver.py -v`
Expected: All pass (2 existing + 4 new = 6 total).

**Step 3: Commit**

```bash
git add tests/test_solver.py
git commit -m "test: add infeasibility, deadhead, and disjunctive sequence solver tests"
```

---

## Task 4: Solver — start_datetime extraction test

Verify the solver correctly converts integer minutes back to datetimes.

**Files:**
- Modify: `tests/test_solver.py`

**Step 1: Write the failing test**

Add to `tests/test_solver.py`:

```python
def test_solve_start_datetime_correct():
    """Verify start_datetime is correctly derived from start_time_t and horizon."""
    d1 = _make_driver("D1")
    j1 = _make_job("J1", LOC_B, window_start=540, window_end=540)  # Exactly 09:00
    arcs = [DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=0)]
    chains = []
    result = solve(_make_instance([d1], [j1], arcs, chains))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    a = result.assignments[0]
    assert a.start_time_t == 540
    assert a.start_datetime == datetime(2025, 12, 8, 9, 0)
```

**Step 2: Run test to verify it passes**

Run: `pytest tests/test_solver.py::test_solve_start_datetime_correct -v`
Expected: PASS (implementation already handles this).

**Step 3: Commit**

```bash
git add tests/test_solver.py
git commit -m "test: add start_datetime extraction verification"
```

---

## Task 5: Integration test — solve real sample data

Run the solver on the full `ProblemInstance` from the sample bookings CSV and verify it finds a feasible solution.

**Files:**
- Modify: `tests/test_solver.py`

**Step 1: Write the integration test**

Add to `tests/test_solver.py`:

```python
from pathlib import Path
from scheduler.builder import ProblemBuilder

def test_solve_real_sample_data():
    """Integration: build from real CSVs and solve. Must find a feasible schedule."""
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

    from scheduler.solver import solve as solve_fn
    solver_result = solve_fn(inst, timeout_seconds=60)
    assert solver_result.status in ("OPTIMAL", "FEASIBLE"), (
        f"Solver returned {solver_result.status} on sample data"
    )
    assert len(solver_result.assignments) == len(inst.jobs)
    # Every job should appear exactly once
    assigned_job_ids = {a.job_id for a in solver_result.assignments}
    expected_job_ids = {j.job_id for j in inst.jobs}
    assert assigned_job_ids == expected_job_ids
```

**Step 2: Run test**

Run: `pytest tests/test_solver.py::test_solve_real_sample_data -v`
Expected: PASS (may take a few seconds to solve).

If this fails with INFEASIBLE, the constraint model or the arc pruning has a bug. Debug by checking `solver_result.stats` and the constraint count.

**Step 3: Commit**

```bash
git add tests/test_solver.py
git commit -m "test: add integration test solving real sample data"
```

---

## Task 6: Console output — print_schedule()

**Files:**
- Create: `src/scheduler/exporter.py`
- Create: `tests/test_exporter.py`

**Step 1: Write the failing test**

Create `tests/test_exporter.py`:

```python
from datetime import date, time, datetime

from scheduler.models import (
    ActionType, CertLevel, Driver, HorizonConfig, Job, JobAssignment,
    Location, ProblemInstance, SolverResult, StorageLocation, TransitMatrix,
    VehicleJobArc, DriverJobArc, JobChainArc,
)
from scheduler.exporter import print_schedule


LOC_A = Location(postcode="AA1 1AA", lat=51.5, lon=-0.1)

INSTANCE = ProblemInstance(
    horizon=HorizonConfig(start_date=date(2025, 12, 8), num_days=1, t_max=1440),
    jobs=[
        Job(job_id="J1", book_no="B001", order_ref="", rental_no="",
            book_name="Smith", book_status="", action=ActionType.COLLECT,
            scheduled_date=date(2025, 12, 8), scheduled_time=time(9, 0),
            scheduled_datetime=datetime(2025, 12, 8, 9, 0),
            time_offset_minutes=540, window_start_t=480, window_end_t=600,
            vehicle_reg="VAN1", vehicle_group="V3", target_location=LOC_A, notes=""),
    ],
    drivers=[
        Driver(driver_id="D1", name="Alice", home_location=LOC_A,
               branch="TEST", max_hours_per_day=600, certifications=CertLevel.VAN,
               can_overnight=True, unavailable_dates=frozenset()),
    ],
    vehicles=[], storage_locations=[], vehicle_group_certs={},
    transit_matrix=TransitMatrix(entries={}),
    driver_job_arcs=[], job_chain_arcs=[], vehicle_job_arcs=[],
)


def test_print_schedule_runs(capsys):
    solver_result = SolverResult(
        status="FEASIBLE", solve_time_seconds=0.5,
        assignments=[
            JobAssignment(job_id="J1", driver_id="D1", start_time_t=540,
                          start_datetime=datetime(2025, 12, 8, 9, 0)),
        ],
        stats={"variables": 10, "constraints": 5},
    )
    print_schedule(solver_result, INSTANCE)
    captured = capsys.readouterr()
    assert "FEASIBLE" in captured.out
    assert "Alice" in captured.out
    assert "COLLECT" in captured.out
    assert "AA1 1AA" in captured.out


def test_print_schedule_infeasible(capsys):
    solver_result = SolverResult(
        status="INFEASIBLE", solve_time_seconds=0.1,
        assignments=[], stats={},
    )
    print_schedule(solver_result, INSTANCE)
    captured = capsys.readouterr()
    assert "INFEASIBLE" in captured.out
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_exporter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scheduler.exporter'`

**Step 3: Write minimal implementation**

Create `src/scheduler/exporter.py`:

```python
"""Output formatters: console summary and CSV export."""

from __future__ import annotations

from collections import defaultdict

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

    # Group assignments by driver
    by_driver: dict[str, list] = defaultdict(list)
    for a in result.assignments:
        by_driver[a.driver_id].append(a)

    # Sort each driver's assignments by start time
    for driver_id in sorted(by_driver):
        driver = drivers_by_id[driver_id]
        assignments = sorted(by_driver[driver_id], key=lambda a: a.start_time_t)
        print(f"\n--- {driver.name} ({driver_id}) ---")
        for a in assignments:
            job = jobs_by_id[a.job_id]
            dt = a.start_datetime.strftime("%Y-%m-%d %H:%M")
            print(f"  [{dt}] {job.action.value.upper()} {job.vehicle_group} @ {job.target_location.postcode}")

    # Summary
    drivers_used = len(by_driver)
    print(f"\n--- Summary ---")
    print(f"Jobs assigned: {len(result.assignments)}")
    print(f"Drivers used: {drivers_used} / {len(instance.drivers)}")
    print(f"Solve time: {result.solve_time_seconds:.3f}s")
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_exporter.py -v`
Expected: All pass.

**Step 5: Commit**

```bash
git add src/scheduler/exporter.py tests/test_exporter.py
git commit -m "feat: add console schedule printer"
```

---

## Task 7: CSV export — export_csv()

**Files:**
- Modify: `src/scheduler/exporter.py`
- Modify: `tests/test_exporter.py`

**Step 1: Write the failing test**

Add to `tests/test_exporter.py`:

```python
import csv
from pathlib import Path
from scheduler.exporter import export_csv


def test_export_csv(tmp_path):
    """Export a solved schedule to CSV. The Drivers column should be filled in."""
    # Create a minimal input CSV
    input_csv = tmp_path / "bookings.csv"
    input_csv.write_text(
        "Book No.,Order ref:,Rental No.,Book Name,Book Status,"
        "Date,Time,Action,Reg No.,Supp'd Grp,Drivers,"
        "Delivery postcode,Collection postcode,Notes\n"
        "#B001,,,,Confirmed,"
        "08/12/2025,09:00,Collect,VAN1,V3,,"
        "AA1 1AA,,\n"
        "#B999,,,,Confirmed,"
        "08/12/2025,10:00,Deliver,VAN2,V3,,"
        "BB2 2BB,,\n"
    )
    solver_result = SolverResult(
        status="FEASIBLE", solve_time_seconds=0.5,
        assignments=[
            JobAssignment(job_id="J1", driver_id="D1", start_time_t=540,
                          start_datetime=datetime(2025, 12, 8, 9, 0)),
        ],
        stats={},
    )
    output_csv = tmp_path / "output.csv"
    export_csv(solver_result, INSTANCE, input_csv, output_csv)

    # Read and verify
    with open(output_csv) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    # First row (B001) should have driver name filled in
    assert rows[0]["Drivers"] == "Alice"
    # Second row (B999) not in instance — should be blank
    assert rows[1]["Drivers"] == ""
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_exporter.py::test_export_csv -v`
Expected: FAIL with `ImportError: cannot import name 'export_csv'`

**Step 3: Write minimal implementation**

Add to `src/scheduler/exporter.py`:

```python
import csv
from pathlib import Path


def export_csv(
    result: SolverResult,
    instance: ProblemInstance,
    input_csv_path: Path,
    output_csv_path: Path,
) -> None:
    """Write a copy of the input CSV with the Drivers column filled in."""
    if not result.assignments:
        return

    # Build lookup: book_no -> driver_name
    jobs_by_id = {j.job_id: j for j in instance.jobs}
    drivers_by_id = {d.driver_id: d for d in instance.drivers}
    assignment_by_job_id = {a.job_id: a for a in result.assignments}

    book_no_to_driver: dict[str, str] = {}
    for job_id, assignment in assignment_by_job_id.items():
        job = jobs_by_id[job_id]
        driver = drivers_by_id[assignment.driver_id]
        book_no_to_driver[job.book_no] = driver.name

    # Read input, write output with Drivers column filled
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
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_exporter.py -v`
Expected: All pass.

**Step 5: Commit**

```bash
git add src/scheduler/exporter.py tests/test_exporter.py
git commit -m "feat: add CSV schedule exporter with book_no mapping"
```

---

## Task 8: End-to-end CLI smoke test

Create a simple script that runs the full pipeline: build → solve → print → export. Not a pytest test — a runnable script for manual verification.

**Files:**
- Create: `run_solver.py` (project root)

**Step 1: Write the script**

Create `run_solver.py`:

```python
#!/usr/bin/env python3
"""Run the full pipeline: build problem, solve, print schedule, export CSV."""

from datetime import date
from pathlib import Path

from scheduler.builder import ProblemBuilder
from scheduler.solver import solve
from scheduler.exporter import print_schedule, export_csv

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


if __name__ == "__main__":
    main()
```

**Step 2: Run it**

Run: `source .venv/bin/activate && python3 run_solver.py`
Expected: Prints build stats, solver status, schedule, and exports CSV.

**Step 3: Verify the CSV output**

Run: `head -5 output/schedule.csv`
Expected: CSV with Drivers column filled in for assigned jobs.

**Step 4: Commit**

```bash
git add run_solver.py
git commit -m "feat: add end-to-end solver runner script"
```

---

## Task 9: Final verification

**Step 1: Run full test suite**

Run: `source .venv/bin/activate && pytest -v`
Expected: All tests pass (74 existing + ~10 new = ~84 total).

**Step 2: Run the solver on real data**

Run: `python3 run_solver.py`
Expected: FEASIBLE or OPTIMAL status, all jobs assigned, CSV exported.

**Step 3: Verify no regressions**

Run: `pytest --tb=short`
Expected: Clean pass.
