# Hard Constraints Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add driver shift span limits (Constraint 5) and TBA vehicle assignment (Constraint 6) to the CP-SAT solver.

**Architecture:** Extends `DriverJobArc` with `return_deadhead_minutes`, adds `is_working`/`shift_start`/`shift_end` per driver, adds `y[v,j]` depot vehicle booleans and `vd_active[d,i,j]` chain booleans with `add_exactly_one` van sourcing.

**Tech Stack:** Google OR-Tools CP-SAT, Pydantic frozen models.

**Design doc:** `docs/plans/2026-03-07-hard-constraints-design.md`

---

## Task 1: Add `return_deadhead_minutes` to DriverJobArc and `earliest_arrival_t` to VehicleJobArc

**Files:**
- Modify: `src/scheduler/models.py:78-81` and `src/scheduler/models.py:84-87`

**Step 1: Update the models**

In `src/scheduler/models.py`, change `DriverJobArc` from:

```python
class DriverJobArc(BaseModel, frozen=True):
    driver_id: str
    job_id: str
    deadhead_minutes: int
```

to:

```python
class DriverJobArc(BaseModel, frozen=True):
    driver_id: str
    job_id: str
    deadhead_minutes: int
    return_deadhead_minutes: int
```

Also change `VehicleJobArc` from:

```python
class VehicleJobArc(BaseModel, frozen=True):
    vehicle_reg: str
    job_id: str
    driving_minutes: int
```

to:

```python
class VehicleJobArc(BaseModel, frozen=True):
    vehicle_reg: str
    job_id: str
    driving_minutes: int
    earliest_arrival_t: int
```

**Step 1b: Fix arcs.py — populate earliest_arrival_t**

In `src/scheduler/arcs.py`, update `compute_vehicle_job_arcs` to compute and
store the earliest arrival time. Change lines 59-63 from:

```python
            arcs.append(VehicleJobArc(
                vehicle_reg=vehicle.reg,
                job_id=job.job_id,
                driving_minutes=driving,
            ))
```

to:

```python
            arcs.append(VehicleJobArc(
                vehicle_reg=vehicle.reg,
                job_id=job.job_id,
                driving_minutes=driving,
                earliest_arrival_t=vehicle.available_from_t + driving,
            ))
```

**Step 1c: Fix test_models.py VehicleJobArc test**

In `tests/test_models.py`, update the `test_vehicle_job_arc` test (line ~148-149):

```python
arc = VehicleJobArc(vehicle_reg="MK22EEA", job_id="J002", driving_minutes=30, earliest_arrival_t=30)
```

**Step 1d: Fix test_arcs.py VehicleJobArc assertions**

In `tests/test_arcs.py`, the `test_vehicle_job_arc_basic` test asserts
`arcs[0].driving_minutes == 35`. Add an assertion for `earliest_arrival_t`.
The vehicle has `available_from_t=0`, so `earliest_arrival_t = 0 + 35 = 35`:

```python
    assert arcs[0].earliest_arrival_t == 35
```

**Step 2: Run tests to see what breaks**

Run: `source .venv/bin/activate && pytest tests/ --tb=short 2>&1 | tail -30`
Expected: Multiple failures wherever `DriverJobArc(...)` is constructed without the new field.

**Step 3: Fix test_models.py**

In `tests/test_models.py:144`, change:

```python
arc = DriverJobArc(driver_id="D001", job_id="J001", deadhead_minutes=45)
```

to:

```python
arc = DriverJobArc(driver_id="D001", job_id="J001", deadhead_minutes=45, return_deadhead_minutes=45)
```

**Step 4: Fix test_solver.py — all DriverJobArc constructors**

Every `DriverJobArc(...)` in `tests/test_solver.py` needs `return_deadhead_minutes`.
Use the transit matrix to determine the correct value. All test drivers live at
LOC_A (AA1 1AA) by default. The MATRIX has:

- AA1 1AA → BB2 2BB = 30 min transit, so BB2 2BB → AA1 1AA = 30 (return)
- AA1 1AA → CC3 3CC = 40 min transit, so CC3 3CC → AA1 1AA = 40 (return)

Jobs at LOC_B → return = 30. Jobs at LOC_C → return = 40.

For the `test_solve_multi_driver` test, D2 lives at LOC_B:
- BB2 2BB → BB2 2BB = 0 (same postcode)
- BB2 2BB → CC3 3CC = 50, so CC3 3CC → BB2 2BB = 50 (return)

Update all constructors. Here is every line that needs changing:

```python
# test_solve_basic_feasible (D1@LOC_A, jobs at LOC_B)
DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=30, return_deadhead_minutes=30),
DriverJobArc(driver_id="D1", job_id="J2", deadhead_minutes=30, return_deadhead_minutes=30),

# test_solve_multi_driver (D1@LOC_A, D2@LOC_B, J1@LOC_B, J2@LOC_C)
DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=30, return_deadhead_minutes=30),
DriverJobArc(driver_id="D1", job_id="J2", deadhead_minutes=40, return_deadhead_minutes=40),
DriverJobArc(driver_id="D2", job_id="J1", deadhead_minutes=0, return_deadhead_minutes=0),
DriverJobArc(driver_id="D2", job_id="J2", deadhead_minutes=50, return_deadhead_minutes=50),

# test_solve_mutual_exclusion_no_chain_arc (D1@LOC_A, J1@LOC_B, J2@LOC_C)
DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=30, return_deadhead_minutes=30),
DriverJobArc(driver_id="D1", job_id="J2", deadhead_minutes=40, return_deadhead_minutes=40),

# test_solve_deadhead_too_late (D1@LOC_A, J1@LOC_B)
DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=500, return_deadhead_minutes=30),

# test_solve_strict_order_enforced (D1@LOC_A, J1@LOC_B, J2@LOC_C)
DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=30, return_deadhead_minutes=30),
DriverJobArc(driver_id="D1", job_id="J2", deadhead_minutes=40, return_deadhead_minutes=40),

# test_solve_disjunctive_sequence (D1@LOC_A, J1@LOC_B, J2@LOC_C)
DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=30, return_deadhead_minutes=30),
DriverJobArc(driver_id="D1", job_id="J2", deadhead_minutes=40, return_deadhead_minutes=40),

# test_solve_start_datetime_correct (D1@LOC_A, J1@LOC_B)
DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=0, return_deadhead_minutes=30),
```

**Step 5: Fix arcs.py — populate return_deadhead_minutes**

In `src/scheduler/arcs.py`, update `compute_driver_job_arcs` to compute and
store the return transit time. Change lines 33-37 from:

```python
            arcs.append(DriverJobArc(
                driver_id=driver.driver_id,
                job_id=job.job_id,
                deadhead_minutes=deadhead,
            ))
```

to:

```python
            return_pair = transit_matrix.get(job.target_location, driver.home_location)
            return_deadhead = return_pair.transit_minutes if return_pair else 0
            arcs.append(DriverJobArc(
                driver_id=driver.driver_id,
                job_id=job.job_id,
                deadhead_minutes=deadhead,
                return_deadhead_minutes=return_deadhead,
            ))
```

**Step 6: Run all tests**

Run: `source .venv/bin/activate && pytest tests/ -v --tb=short`
Expected: All 88 tests pass.

**Step 7: Commit**

```bash
git add src/scheduler/models.py src/scheduler/arcs.py tests/test_models.py tests/test_solver.py
git commit -m "feat: add return_deadhead_minutes to DriverJobArc"
```

---

## Task 2: Update test_arcs.py for return_deadhead_minutes

**Files:**
- Modify: `tests/test_arcs.py`

**Step 1: Add assertion for return_deadhead_minutes**

In `test_driver_job_arc_basic`, add an assertion that the return deadhead is
correctly computed. The driver is at LOC_A (SW15 2SW), the job is at LOC_B
(TW14 9DF). The MATRIX has (TW14 9DF → SW15 2SW) = 55 transit minutes.

After line 56 (`assert arcs[0].deadhead_minutes == 55`), add:

```python
    assert arcs[0].return_deadhead_minutes == 55
```

**Step 2: Run test**

Run: `source .venv/bin/activate && pytest tests/test_arcs.py::test_driver_job_arc_basic -v`
Expected: PASS.

**Step 3: Commit**

```bash
git add tests/test_arcs.py
git commit -m "test: assert return_deadhead_minutes in arc computation test"
```

---

## Task 3: Update solver arc indexing for return_deadhead_minutes

The solver currently indexes `driver_arcs` as `dict[str, list[tuple[str, int]]]`
storing `(job_id, deadhead_minutes)`. It needs the return deadhead too.

**Files:**
- Modify: `src/scheduler/solver.py:34-37`

**Step 1: Update the arc indexing**

Change the `driver_arcs` type and population from:

```python
    # driver_id -> list of (job_id, deadhead_minutes)
    driver_arcs: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for arc in instance.driver_job_arcs:
        driver_arcs[arc.driver_id].append((arc.job_id, arc.deadhead_minutes))
```

to:

```python
    # driver_id -> list of (job_id, deadhead_minutes, return_deadhead_minutes)
    driver_arcs: dict[str, list[tuple[str, int, int]]] = defaultdict(list)
    for arc in instance.driver_job_arcs:
        driver_arcs[arc.driver_id].append((arc.job_id, arc.deadhead_minutes, arc.return_deadhead_minutes))
```

**Step 2: Update all tuple unpacking**

Every place that unpacks `(job_id, deadhead)` from `driver_arcs` must now
unpack `(job_id, deadhead, return_dh)`. There are 4 locations:

Line 62-63 (variable creation loop):
```python
    for driver_id, arc_list in driver_arcs.items():
        for job_id, deadhead, return_dh in arc_list:
```

Line 91-92 (Constraint 3 loop):
```python
    for driver_id, arc_list in driver_arcs.items():
        job_ids = [job_id for job_id, _, _ in arc_list]
```

Line 132-133 (Constraint 4 loop):
```python
    for driver_id, arc_list in driver_arcs.items():
        for job_id, deadhead, return_dh in arc_list:
```

**Step 3: Run all tests**

Run: `source .venv/bin/activate && pytest tests/ -v --tb=short`
Expected: All 88+ tests pass (no behavior change yet, just data threading).

**Step 4: Commit**

```bash
git add src/scheduler/solver.py
git commit -m "refactor: thread return_deadhead_minutes through solver arc indexing"
```

---

## Task 4: Constraint 5 — Driver shift span (tests first)

**Files:**
- Modify: `tests/test_solver.py`

**Step 1: Write the tests**

Add these tests to `tests/test_solver.py`:

```python
# --- Driver shift span ---

def test_solve_shift_span_within_limit():
    """One job, deadhead 30 + service 0 + return 30 = 60 min span.
    Driver max_hours_per_day=600. FEASIBLE."""
    d1 = _make_driver("D1")  # max_hours_per_day=600
    j1 = _make_job("J1", LOC_B, window_start=480, window_end=540)
    arcs = [DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=30, return_deadhead_minutes=30)]
    result = solve(_make_instance([d1], [j1], arcs, []))
    assert result.status in ("OPTIMAL", "FEASIBLE")


def test_solve_shift_span_exceeds_limit():
    """One job at LOC_B. Deadhead=30, return=30, job starts at 480.
    Shift span = (480 + 0 + 30) - (480 - 30) = 60 min.
    But if we set max_hours_per_day=50, the 60 min span exceeds it. INFEASIBLE."""
    d1 = Driver(
        driver_id="D1", name="D1", home_location=LOC_A,
        branch="TEST", max_hours_per_day=50, certifications=CertLevel.VAN,
        can_overnight=True, unavailable_dates=frozenset(),
    )
    j1 = _make_job("J1", LOC_B, window_start=480, window_end=540)
    arcs = [DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=30, return_deadhead_minutes=30)]
    result = solve(_make_instance([d1], [j1], arcs, []))
    assert result.status == "INFEASIBLE"


def test_solve_shift_span_two_jobs_feasible():
    """Two jobs, same location. D1 leaves at (480-30)=450, returns at (660+0+30)=690.
    Span=240 min. max_hours_per_day=600. FEASIBLE."""
    d1 = _make_driver("D1")
    j1 = _make_job("J1", LOC_B, window_start=480, window_end=540)
    j2 = _make_job("J2", LOC_B, window_start=600, window_end=660)
    arcs = [
        DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=30, return_deadhead_minutes=30),
        DriverJobArc(driver_id="D1", job_id="J2", deadhead_minutes=30, return_deadhead_minutes=30),
    ]
    chains = [
        JobChainArc(from_job_id="J1", to_job_id="J2", chain_type="driver_only",
                    travel_minutes=0, turnaround_minutes=0),
        JobChainArc(from_job_id="J2", to_job_id="J1", chain_type="driver_only",
                    travel_minutes=0, turnaround_minutes=0),
    ]
    result = solve(_make_instance([d1], [j1, j2], arcs, chains))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 2


def test_solve_shift_span_two_jobs_exceeds():
    """Two jobs spread far apart in time. J1@480, J2@1200 (8pm).
    Shift span: (1200 + 0 + 30) - (480 - 30) = 780 min.
    max_hours_per_day=600. INFEASIBLE for one driver — but 2 drivers available."""
    d1 = _make_driver("D1")
    d2 = _make_driver("D2")
    j1 = _make_job("J1", LOC_B, window_start=480, window_end=540)
    j2 = _make_job("J2", LOC_B, window_start=1200, window_end=1260)
    arcs = [
        DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=30, return_deadhead_minutes=30),
        DriverJobArc(driver_id="D1", job_id="J2", deadhead_minutes=30, return_deadhead_minutes=30),
        DriverJobArc(driver_id="D2", job_id="J1", deadhead_minutes=30, return_deadhead_minutes=30),
        DriverJobArc(driver_id="D2", job_id="J2", deadhead_minutes=30, return_deadhead_minutes=30),
    ]
    chains = [
        JobChainArc(from_job_id="J1", to_job_id="J2", chain_type="driver_only",
                    travel_minutes=0, turnaround_minutes=0),
        JobChainArc(from_job_id="J2", to_job_id="J1", chain_type="driver_only",
                    travel_minutes=0, turnaround_minutes=0),
    ]
    result = solve(_make_instance([d1, d2], [j1, j2], arcs, chains))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 2
    # Each driver should do exactly 1 job (can't combine due to shift limit)
    drivers_used = {a.driver_id for a in result.assignments}
    assert len(drivers_used) == 2
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_solver.py::test_solve_shift_span_exceeds_limit -v`
Expected: FAIL — currently returns FEASIBLE because constraint doesn't exist yet.

**Step 3: Commit the tests**

```bash
git add tests/test_solver.py
git commit -m "test: add driver shift span tests (red — constraint not implemented yet)"
```

---

## Task 5: Constraint 5 — Driver shift span (implementation)

**Files:**
- Modify: `src/scheduler/solver.py`

**Step 1: Add the constraint**

In `src/scheduler/solver.py`, after Constraint 4 (deadhead from home, ~line 136),
add Constraint 5. You need access to `drivers_by_id`, so add that index near
the top (after `jobs_by_id`):

After line 31 (`jobs_by_id = {j.job_id: j for j in instance.jobs}`), add:

```python
    drivers_by_id = {d.driver_id: d for d in instance.drivers}
```

Then after the Constraint 4 block, add:

```python
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

        # Shift span constraint
        model.add(s_end - s_start <= driver.max_hours_per_day).only_enforce_if(is_w)
```

**Step 2: Run tests**

Run: `source .venv/bin/activate && pytest tests/test_solver.py -v --tb=short`
Expected: All tests pass including the 4 new shift span tests.

**Step 3: Commit**

```bash
git add src/scheduler/solver.py
git commit -m "feat: add Constraint 5 — driver shift span with is_working guard"
```

---

## Task 6: Constraint 6 — TBA vehicle assignment (tests first)

**Files:**
- Modify: `tests/test_solver.py`

**Step 1: Write the tests**

Add these imports at the top of `tests/test_solver.py` (alongside existing imports):

```python
from scheduler.models import (
    ActionType, CertLevel, ChainType, Driver, DriverJobArc, HorizonConfig, Job,
    JobChainArc, Location, ProblemInstance, TransitMatrix, TransitPair,
    Vehicle, VehicleJobArc,
)
```

Update `_make_instance` to accept vehicles and vehicle_job_arcs:

```python
def _make_instance(
    drivers: list[Driver],
    jobs: list[Job],
    driver_job_arcs: list[DriverJobArc],
    job_chain_arcs: list[JobChainArc] | None = None,
    vehicles: list[Vehicle] | None = None,
    vehicle_job_arcs: list[VehicleJobArc] | None = None,
) -> ProblemInstance:
    return ProblemInstance(
        horizon=HORIZON, jobs=jobs, drivers=drivers,
        vehicles=vehicles or [],
        storage_locations=[], vehicle_group_certs={},
        transit_matrix=MATRIX,
        driver_job_arcs=driver_job_arcs,
        job_chain_arcs=job_chain_arcs or [],
        vehicle_job_arcs=vehicle_job_arcs or [],
    )
```

Add a helper for TBA deliver jobs:

```python
def _make_tba_deliver(
    job_id: str, loc: Location, group: str = "V3",
    window_start: int = 480, window_end: int = 600,
) -> Job:
    return Job(
        job_id=job_id, book_no=f"B{job_id}", order_ref="", rental_no="",
        book_name="", book_status="",
        action=ActionType.DELIVER, scheduled_date=date(2025, 12, 8),
        scheduled_time=time(9, 0), scheduled_datetime=datetime(2025, 12, 8, 9, 0),
        time_offset_minutes=540, window_start_t=window_start, window_end_t=window_end,
        vehicle_reg=None, vehicle_group=group,
        target_location=loc, notes="",
    )
```

Add these tests:

```python
# --- TBA vehicle assignment ---

def test_solve_tba_depot_vehicle():
    """TBA deliver job with a matching depot vehicle — FEASIBLE."""
    d1 = _make_driver("D1")
    j1 = _make_tba_deliver("J1", LOC_B)
    v1 = Vehicle(reg="VAN1", group="V3", current_location=LOC_A,
                 available_from=date(2025, 12, 8), available_from_t=0)
    arcs = [DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=30, return_deadhead_minutes=30)]
    v_arcs = [VehicleJobArc(vehicle_reg="VAN1", job_id="J1", driving_minutes=30, earliest_arrival_t=30)]
    result = solve(_make_instance([d1], [j1], arcs, [], [v1], v_arcs))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 1


def test_solve_tba_no_vehicle_infeasible():
    """TBA deliver job with no depot vehicle and no chain — INFEASIBLE."""
    d1 = _make_driver("D1")
    j1 = _make_tba_deliver("J1", LOC_B)
    arcs = [DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=30, return_deadhead_minutes=30)]
    # No vehicles, no vehicle arcs, no VEHICLE_DRIVER chains
    result = solve(_make_instance([d1], [j1], arcs, [], [], []))
    assert result.status == "INFEASIBLE"


def test_solve_tba_vehicle_driver_chain():
    """TBA deliver served by VEHICLE_DRIVER chain from a collect — no depot vehicle needed."""
    d1 = _make_driver("D1")
    # Collect job (has a reg) at LOC_B
    j_collect = Job(
        job_id="JC", book_no="BC", order_ref="", rental_no="",
        book_name="", book_status="",
        action=ActionType.COLLECT, scheduled_date=date(2025, 12, 8),
        scheduled_time=time(9, 0), scheduled_datetime=datetime(2025, 12, 8, 9, 0),
        time_offset_minutes=540, window_start_t=480, window_end_t=540,
        vehicle_reg="VAN1", vehicle_group="V3",
        target_location=LOC_B, notes="",
    )
    # TBA deliver at LOC_C — same group, no reg
    j_deliver = _make_tba_deliver("JD", LOC_C, group="V3", window_start=600, window_end=700)

    arcs = [
        DriverJobArc(driver_id="D1", job_id="JC", deadhead_minutes=30, return_deadhead_minutes=30),
        DriverJobArc(driver_id="D1", job_id="JD", deadhead_minutes=40, return_deadhead_minutes=40),
    ]
    chains = [
        # DRIVER_ONLY arcs (needed for Constraint 3 sequencing)
        JobChainArc(from_job_id="JC", to_job_id="JD", chain_type="driver_only",
                    travel_minutes=50, turnaround_minutes=0),
        # VEHICLE_DRIVER arc: collect VAN1 at LOC_B, deliver at LOC_C
        JobChainArc(from_job_id="JC", to_job_id="JD", chain_type="vehicle_driver",
                    travel_minutes=30, turnaround_minutes=45),
    ]
    # No depot vehicles — the van comes from the collect chain
    result = solve(_make_instance([d1], [j_collect, j_deliver], arcs, chains, [], []))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 2


def test_solve_tba_depot_vehicle_one_each():
    """Two TBA jobs, one depot vehicle — one must get vehicle, other needs a chain.
    Without a chain for the second, INFEASIBLE."""
    d1 = _make_driver("D1")
    d2 = _make_driver("D2")
    j1 = _make_tba_deliver("J1", LOC_B, window_start=480, window_end=540)
    j2 = _make_tba_deliver("J2", LOC_C, window_start=480, window_end=540)
    v1 = Vehicle(reg="VAN1", group="V3", current_location=LOC_A,
                 available_from=date(2025, 12, 8), available_from_t=0)
    arcs = [
        DriverJobArc(driver_id="D1", job_id="J1", deadhead_minutes=30, return_deadhead_minutes=30),
        DriverJobArc(driver_id="D1", job_id="J2", deadhead_minutes=40, return_deadhead_minutes=40),
        DriverJobArc(driver_id="D2", job_id="J1", deadhead_minutes=30, return_deadhead_minutes=30),
        DriverJobArc(driver_id="D2", job_id="J2", deadhead_minutes=40, return_deadhead_minutes=40),
    ]
    # Only one depot vehicle, for J1 only
    v_arcs = [VehicleJobArc(vehicle_reg="VAN1", job_id="J1", driving_minutes=30, earliest_arrival_t=30)]
    # No chains — J2 has no van source. INFEASIBLE.
    result = solve(_make_instance([d1, d2], [j1, j2], arcs, [], [v1], v_arcs))
    assert result.status == "INFEASIBLE"
```

**Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest tests/test_solver.py::test_solve_tba_no_vehicle_infeasible -v`
Expected: FAIL — currently returns FEASIBLE because TBA constraint doesn't exist.

**Step 3: Commit the tests**

```bash
git add tests/test_solver.py
git commit -m "test: add TBA vehicle assignment tests (red — constraint not implemented yet)"
```

---

## Task 7: Constraint 6 — TBA vehicle assignment (implementation)

**Files:**
- Modify: `src/scheduler/solver.py`

**Step 1: Add the VEHICLE_DRIVER chain index**

After the chain_lookup consolidation block (around line 52), add:

```python
    # VEHICLE_DRIVER chain index: set of (from_job_id, to_job_id) pairs
    # Built BEFORE min-time consolidation which loses chain_type info
    vd_pairs: set[tuple[str, str]] = set()
    for arc in instance.job_chain_arcs:
        if arc.chain_type == "vehicle_driver":
            vd_pairs.add((arc.from_job_id, arc.to_job_id))
```

Note: this must be added BEFORE the `chain_lookup` block, or moved so that
the `vd_pairs` index is built from the raw `instance.job_chain_arcs` before
the min-time consolidation. The ordering in the file should be:

1. `vd_pairs` index (raw chain arcs)
2. `chain_lookup` (min-time consolidation)

**Step 2: Add vehicle and TBA job indexes**

After the `vd_pairs` block, add:

```python
    # --- Index vehicles and TBA jobs ---
    vehicles_by_reg = {v.reg: v for v in instance.vehicles}
    tba_job_ids = {j.job_id for j in instance.jobs if j.vehicle_reg is None}

    # vehicle_reg -> list of (job_id, driving_minutes) from VehicleJobArcs
    vehicle_arcs: dict[str, list[tuple[str, int]]] = defaultdict(list)
    # job_id -> list of vehicle_regs
    job_vehicles: dict[str, list[str]] = defaultdict(list)
    for arc in instance.vehicle_job_arcs:
        vehicle_arcs[arc.vehicle_reg].append((arc.job_id, arc.driving_minutes))
        job_vehicles[arc.job_id].append(arc.vehicle_reg)
```

**Step 3: Add the Constraint 6 block**

After the Constraint 5 block, add:

```python
    # --- Constraint 6: TBA vehicle assignment ---
    # y[vehicle_reg, job_id] = BoolVar: depot vehicle assignment
    y: dict[tuple[str, str], cp_model.IntVar] = {}
    # vd_active[driver_id, from_job_id, to_job_id] = BoolVar: VEHICLE_DRIVER chain active
    vd_active: dict[tuple[str, str, str], cp_model.IntVar] = {}

    # Create y variables for depot vehicles
    for arc in instance.vehicle_job_arcs:
        y_var = model.new_bool_var(f"y_{arc.vehicle_reg}_{arc.job_id}")
        y[arc.vehicle_reg, arc.job_id] = y_var

    # Create vd_active variables for VEHICLE_DRIVER chains into TBA jobs
    # Also need access to seq variables — store them during Constraint 3
    # We need to refactor: store seq vars in a dict for reuse here.
    # For now, rebuild the seq lookup from Constraint 3's naming convention.

    # Actually, we need to store seq vars during Constraint 3. Add a dict before
    # the Constraint 3 loop:
    #   seq_vars: dict[tuple[str, str, str], cp_model.IntVar] = {}
    # and store: seq_vars[driver_id, ji, jj] = seq
    # Then reference it here.

    # (See Step 4 below for the Constraint 3 refactor)

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
                # Strict order: vd_active iff both assigned
                model.add_bool_and([x[driver_id, ji], x[driver_id, jj]]).only_enforce_if(vda)
                model.add_bool_or([x[driver_id, ji].negated(), x[driver_id, jj].negated()]).only_enforce_if(vda.negated())
            elif has_i_to_j and has_j_to_i:
                # Disjunctive: vd_active iff both assigned AND i-before-j
                # Need the seq var — look it up. The key convention is
                # (driver_id, min(ji,jj), max(ji,jj)) to match how Constraint 3
                # creates them with idx_a < idx_b.
                # If ji < jj in the arc_list ordering, seq=1 means ji-before-jj.
                # If jj < ji in the arc_list ordering, seq=1 means jj-before-ji,
                # so we need seq.negated().
                # Using the stored seq_vars dict avoids this complexity.
                seq_key = (driver_id, ji, jj) if (driver_id, ji, jj) in seq_vars else None
                if seq_key:
                    seq_v = seq_vars[seq_key]
                    model.add_bool_and([x[driver_id, ji], x[driver_id, jj], seq_v]).only_enforce_if(vda)
                    model.add_bool_or([x[driver_id, ji].negated(), x[driver_id, jj].negated(), seq_v.negated()]).only_enforce_if(vda.negated())
                else:
                    # Try reversed key
                    seq_key_rev = (driver_id, jj, ji)
                    if seq_key_rev in seq_vars:
                        seq_v = seq_vars[seq_key_rev]
                        # seq_v=1 means jj-before-ji, so we need negated for ji-before-jj
                        model.add_bool_and([x[driver_id, ji], x[driver_id, jj], seq_v.negated()]).only_enforce_if(vda)
                        model.add_bool_or([x[driver_id, ji].negated(), x[driver_id, jj].negated(), seq_v]).only_enforce_if(vda.negated())

    # Rule 1: exactly one van source per TBA job
    for job_id in tba_job_ids:
        van_sources = []
        # Depot vehicles
        for v_reg in job_vehicles.get(job_id, []):
            van_sources.append(y[v_reg, job_id])
        # VEHICLE_DRIVER chains
        for (di, ji, jj), vda in vd_active.items():
            if jj == job_id:
                van_sources.append(vda)
        if van_sources:
            model.add_exactly_one(van_sources)
        else:
            # No van source at all — force infeasible for this job
            # (This shouldn't happen if builder excluded properly, but safety net)
            model.add(0 == 1)

    # Rule 2: each depot vehicle at most one TBA job
    for v_reg in vehicles_by_reg:
        assigned = [y[v_reg, job_id] for (vr, job_id) in y if vr == v_reg]
        if len(assigned) > 1:
            model.add(sum(assigned) <= 1)

    # Rule 3: temporal link — depot vehicle arrival time (pre-computed on arc)
    for arc in instance.vehicle_job_arcs:
        for d_id in job_drivers.get(arc.job_id, []):
            model.add(
                start[d_id, arc.job_id] >= arc.earliest_arrival_t
            ).only_enforce_if([y[arc.vehicle_reg, arc.job_id], x[d_id, arc.job_id]])

    # TODO: Dynamic Driver->Van->Customer routing for TBA jobs
```

**Step 4: Refactor Constraint 3 to store seq variables**

Before the Constraint 3 loop, add a dict:

```python
    seq_vars: dict[tuple[str, str, str], cp_model.IntVar] = {}
```

Inside the Case 3 block (both directions), after creating the `seq` variable,
store it:

```python
                    seq_vars[driver_id, ji, jj] = seq
```

**Step 5: Run tests**

Run: `source .venv/bin/activate && pytest tests/test_solver.py -v --tb=short`
Expected: All tests pass including the 4 new TBA tests.

**Step 6: Commit**

```bash
git add src/scheduler/solver.py
git commit -m "feat: add Constraint 6 — TBA vehicle assignment with depot-or-chain sourcing"
```

---

## Task 8: Integration test — verify real data still solves

**Files:**
- None new — just run existing tests

**Step 1: Run full test suite**

Run: `source .venv/bin/activate && pytest tests/ -v --tb=short`
Expected: All tests pass. The real sample data has zero TBA jobs in the
instance, so Constraint 6 is a no-op. Constraint 5 (shift span) should
still allow feasible scheduling since `max_hours_per_day=600` (10 hours)
is generous for the sample data.

**Step 2: Run the solver on real data**

Run: `source .venv/bin/activate && python3 run_solver.py`
Expected: OPTIMAL or FEASIBLE, all 59 jobs assigned. Verify no driver's
schedule spans more than 10 hours.

**Step 3: Commit if any fixes were needed**

If tests required adjustments, commit them. Otherwise, no commit needed.

---

## Task 9: Final verification and cleanup

**Step 1: Run full test suite**

Run: `source .venv/bin/activate && pytest tests/ -v`
Expected: All tests pass (88 existing + ~6 new = ~94 total).

**Step 2: Verify no regressions on existing tests**

Run: `source .venv/bin/activate && pytest tests/ --tb=short`
Expected: Clean pass.

**Step 3: Commit any final fixes**

If any cleanup was needed, commit.
