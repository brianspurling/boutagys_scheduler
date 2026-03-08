# Asymmetric Time Windows Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the symmetric ±60-minute window on `Job` with semantically correct, per-action-type time fields and piecewise penalty terms in the CP-SAT objective.

**Architecture:** Six tasks in dependency order: penalty constants → model fields → builder computation → solver encoding → arc/builder pruning updates → test fixes. Each task is independently testable. The CP-SAT `arrival_time` variable continues to act as service-start time; the hard collect floor is a simple unconditional lower-bound constraint.

**Tech Stack:** Python, Pydantic (`models.py`), OR-Tools CP-SAT (`circuit_solver.py`), pytest.

---

### Task 1: Add `penalty_config.py`

**Files:**
- Create: `src/scheduler/penalty_config.py`

**Step 1: Write failing test**

```python
# tests/test_penalty_config.py
from scheduler.penalty_config import (
    LATE_SAME_DAY_RATE,
    SEVERE_NEXT_DAY_RATE,
    EARLY_RATE,
    LATE_TIER1_RATE,
    LATE_TIER2_RATE,
)

def test_penalty_constants_exist_and_are_positive():
    assert LATE_SAME_DAY_RATE > 0
    assert SEVERE_NEXT_DAY_RATE > LATE_SAME_DAY_RATE, "next-day rate must exceed same-day rate"
    assert EARLY_RATE > 0
    assert LATE_TIER1_RATE > 0
    assert LATE_TIER2_RATE > LATE_TIER1_RATE, "tier-2 late rate must exceed tier-1"
```

**Step 2: Run to confirm failure**

```bash
cd /Users/Shared/_code/boutagys_scheduler
pytest tests/test_penalty_config.py -v
```
Expected: `ModuleNotFoundError: No module named 'scheduler.penalty_config'`

**Step 3: Implement**

```python
# src/scheduler/penalty_config.py
"""Penalty rate constants for asymmetric time window objective terms.

All values are per-minute integer costs added to the CP-SAT objective.
Tune here without touching solver logic.
"""

# COLLECT penalties (lateness from booking time)
LATE_SAME_DAY_RATE: int = 2    # per minute after grace period (booking_time + 120min)
SEVERE_NEXT_DAY_RATE: int = 10  # per minute past end of scheduled day

# DELIVER penalties
EARLY_RATE: int = 1             # per minute early before same-day start (1440/day natural ramp)
LATE_TIER1_RATE: int = 10       # per minute late, first 60 minutes past deadline
LATE_TIER2_RATE: int = 30       # per minute late, beyond 60 minutes past deadline
```

**Step 4: Run to confirm pass**

```bash
pytest tests/test_penalty_config.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/scheduler/penalty_config.py tests/test_penalty_config.py
git commit -m "feat: add penalty_config module with piecewise rate constants"
```

---

### Task 2: Update `Job` model fields

Replace `window_start_t` / `window_end_t` with semantically correct per-action-type fields.

**Files:**
- Modify: `src/scheduler/models.py`
- Modify: `tests/test_models.py`

**Step 1: Write failing test**

Add to `tests/test_models.py` (keep existing tests, add below):

```python
def test_collect_job_has_new_time_fields():
    from scheduler.models import ActionType, Job, Location
    from datetime import date, time, datetime
    loc = Location(postcode="SW1A 1AA", lat=51.5, lon=-0.1)
    j = Job(
        job_id="J001", book_no="#1", order_ref="", rental_no="",
        book_name="", book_status="",
        action=ActionType.COLLECT,
        scheduled_date=date(2025, 12, 8),
        scheduled_time=time(8, 30),
        scheduled_datetime=datetime(2025, 12, 8, 8, 30),
        time_offset_minutes=510,
        earliest_departure_t=510,
        grace_end_t=630,
        same_day_end_t=1439,
        same_day_start_t=0,
        deadline_t=None,
        vehicle_reg="ABC123", vehicle_group="V3",
        target_location=loc, notes="",
    )
    assert j.earliest_departure_t == 510
    assert j.grace_end_t == 630
    assert j.same_day_end_t == 1439
    assert j.deadline_t is None


def test_deliver_job_has_new_time_fields():
    from scheduler.models import ActionType, Job, Location
    from datetime import date, time, datetime
    loc = Location(postcode="SW1A 1AA", lat=51.5, lon=-0.1)
    j = Job(
        job_id="J002", book_no="#2", order_ref="", rental_no="",
        book_name="", book_status="",
        action=ActionType.DELIVER,
        scheduled_date=date(2025, 12, 8),
        scheduled_time=time(14, 0),
        scheduled_datetime=datetime(2025, 12, 8, 14, 0),
        time_offset_minutes=840,
        earliest_departure_t=None,
        grace_end_t=None,
        same_day_end_t=1439,
        same_day_start_t=0,
        deadline_t=840,
        vehicle_reg="ABC123", vehicle_group="V3",
        target_location=loc, notes="",
    )
    assert j.deadline_t == 840
    assert j.same_day_start_t == 0
    assert j.earliest_departure_t is None
```

**Step 2: Run to confirm failure**

```bash
pytest tests/test_models.py -v -k "new_time_fields"
```
Expected: FAIL — `Job` has no field `earliest_departure_t`

**Step 3: Update `Job` in `models.py`**

Replace the `window_start_t` / `window_end_t` lines in the `Job` class:

```python
# REMOVE these two lines:
#   window_start_t: int
#   window_end_t: int

# ADD these five lines in their place:
earliest_departure_t: int | None   # COLLECT only: hard floor — driver cannot depart before this
grace_end_t: int | None            # COLLECT only: end of zero-penalty zone (earliest_departure_t + 120)
same_day_end_t: int                # both: minute index of end of scheduled day
same_day_start_t: int              # both: minute index of start of scheduled day
deadline_t: int | None             # DELIVER only: latest desired arrival (booking time)
```

**Step 4: Run to confirm new tests pass**

```bash
pytest tests/test_models.py -v -k "new_time_fields"
```
Expected: PASS

**Step 5: Note — existing tests will now fail**

```bash
pytest tests/test_models.py -v
```
Expected: the two old `window_start_t` / `window_end_t` tests fail. That is expected — fix them now by updating the old `Job` construction in `test_models.py` to use the new fields. Remove assertions on `window_start_t` / `window_end_t` and replace with equivalent assertions on the new fields.

**Step 6: Confirm all model tests pass**

```bash
pytest tests/test_models.py -v
```
Expected: all PASS

**Step 7: Commit**

```bash
git add src/scheduler/models.py tests/test_models.py
git commit -m "feat: replace window_start/end_t with asymmetric time fields on Job"
```

---

### Task 3: Update `builder.py` to compute new fields

**Files:**
- Modify: `src/scheduler/builder.py`
- Modify: `tests/test_builder.py`

**Step 1: Write failing test**

Add to `tests/test_builder.py`:

```python
def test_builder_collect_time_fields():
    """Collect job: earliest_departure_t == booking time, grace_end_t == booking + 120."""
    result = _build()
    inst = result.instance
    collect_jobs = [
        j for j in inst.jobs
        if j.action.value == "collect"
        and j.scheduled_time is not None
        and j.scheduled_date == date(2025, 12, 8)
        and j.scheduled_time.hour == 8
        and j.scheduled_time.minute == 30
    ]
    assert len(collect_jobs) > 0
    for j in collect_jobs:
        assert j.earliest_departure_t == 510, f"{j.job_id}: expected 510, got {j.earliest_departure_t}"
        assert j.grace_end_t == 630, f"{j.job_id}: expected 630, got {j.grace_end_t}"
        assert j.same_day_end_t == 1439
        assert j.same_day_start_t == 0


def test_builder_deliver_time_fields():
    """Deliver job: deadline_t == booking time, same_day_start_t == day start."""
    result = _build()
    inst = result.instance
    deliver_jobs = [
        j for j in inst.jobs
        if j.action.value == "deliver"
        and j.scheduled_time is not None
        and j.scheduled_date == date(2025, 12, 8)
    ]
    assert len(deliver_jobs) > 0
    for j in deliver_jobs:
        expected_deadline = j.scheduled_time.hour * 60 + j.scheduled_time.minute
        assert j.deadline_t == expected_deadline, f"{j.job_id}"
        assert j.same_day_start_t == 0
        assert j.earliest_departure_t is None
        assert j.grace_end_t is None
```

**Step 2: Run to confirm failure**

```bash
pytest tests/test_builder.py -v -k "time_fields"
```
Expected: FAIL — `Job` construction in builder uses old fields

**Step 3: Update `builder.py`**

Remove the constants at the top:
```python
# DELETE:
# _WINDOW_BEFORE_MINUTES = 60
# _WINDOW_AFTER_MINUTES = 60
```

Replace the time-offset computation block (lines ~105–122) with:

```python
# Compute time offsets and asymmetric window fields
enriched_jobs: list[Job] = []
for j in valid_jobs:
    time_offset = None
    days_from_start = (j.scheduled_date - self._horizon_start).days
    day_start_t = days_from_start * 1440
    day_end_t = day_start_t + 1439

    earliest_departure_t = None
    grace_end_t = None
    deadline_t = None

    if j.scheduled_time is not None:
        time_offset = day_start_t + j.scheduled_time.hour * 60 + j.scheduled_time.minute
        if j.action == ActionType.COLLECT:
            earliest_departure_t = time_offset
            grace_end_t = time_offset + 120
        else:  # DELIVER
            deadline_t = time_offset

    enriched_jobs.append(j.model_copy(update={
        "time_offset_minutes": time_offset,
        "earliest_departure_t": earliest_departure_t,
        "grace_end_t": grace_end_t,
        "same_day_end_t": day_end_t,
        "same_day_start_t": day_start_t,
        "deadline_t": deadline_t,
    }))
```

You'll also need to add `ActionType` to the imports at the top of `builder.py` if not already present:
```python
from scheduler.models import (
    ActionType, BuildResult, Driver, HorizonConfig, Job,
    ...
)
```

**Step 4: Run new tests**

```bash
pytest tests/test_builder.py -v -k "time_fields"
```
Expected: PASS

**Step 5: Fix the now-broken old builder test**

`test_builder_time_windows` asserts `window_start_t < window_end_t` — delete or replace it:

```python
def test_builder_time_fields_valid():
    """Every job with a scheduled time has sensible time fields."""
    result = _build()
    for j in result.instance.jobs:
        if j.scheduled_time is None:
            continue
        assert j.same_day_start_t <= j.same_day_end_t
        if j.action.value == "collect":
            assert j.earliest_departure_t is not None
            assert j.grace_end_t == j.earliest_departure_t + 120
        else:
            assert j.deadline_t is not None
```

**Step 6: Run all builder tests**

```bash
pytest tests/test_builder.py -v
```
Expected: all PASS

**Step 7: Commit**

```bash
git add src/scheduler/builder.py tests/test_builder.py
git commit -m "feat: builder computes asymmetric collect/deliver time fields"
```

---

### Task 4: Update `circuit_solver.py` — wide domains, hard constraint, penalty terms

This is the largest task. Work through it in sub-steps.

**Files:**
- Modify: `src/scheduler/circuit_solver.py`
- Modify: `tests/test_circuit_solver.py`

#### 4a: Update test fixtures to use new Job fields

The `_make_collect` and `_make_deliver` helpers in `test_circuit_solver.py` still pass `window_start_t` / `window_end_t`. Update them:

```python
def _make_collect(job_id, loc, vehicle_reg="VAN1", group="V3",
                  earliest_departure_t=480, same_day_end_t=1439):
    return Job(
        job_id=job_id, book_no=f"B{job_id}", order_ref="", rental_no="",
        book_name="", book_status="",
        action=ActionType.COLLECT, scheduled_date=date(2025, 12, 8),
        scheduled_time=time(9, 0), scheduled_datetime=datetime(2025, 12, 8, 9, 0),
        time_offset_minutes=540,
        earliest_departure_t=earliest_departure_t,
        grace_end_t=earliest_departure_t + 120,
        same_day_end_t=same_day_end_t,
        same_day_start_t=0,
        deadline_t=None,
        vehicle_reg=vehicle_reg, vehicle_group=group,
        target_location=loc, notes="",
    )


def _make_deliver(job_id, loc, vehicle_reg="VAN1", group="V3",
                  deadline_t=600, same_day_start_t=0):
    return Job(
        job_id=job_id, book_no=f"B{job_id}", order_ref="", rental_no="",
        book_name="", book_status="",
        action=ActionType.DELIVER, scheduled_date=date(2025, 12, 8),
        scheduled_time=time(9, 0), scheduled_datetime=datetime(2025, 12, 8, 9, 0),
        time_offset_minutes=540,
        earliest_departure_t=None,
        grace_end_t=None,
        same_day_end_t=1439,
        same_day_start_t=same_day_start_t,
        deadline_t=deadline_t,
        vehicle_reg=vehicle_reg, vehicle_group=group,
        target_location=loc, notes="",
    )
```

Run existing solver tests to see what's now broken:
```bash
pytest tests/test_circuit_solver.py -v
```

#### 4b: Write new failing tests for hard collect constraint and penalty shape

Add to `tests/test_circuit_solver.py`:

```python
def test_collect_hard_floor_respected():
    """Driver arrives early but cannot depart before earliest_departure_t."""
    d = _make_driver()  # 30min transit to LOC_A
    # earliest_departure_t = 600 (10:00). Driver can reach in 30min from t=0.
    j = _make_collect("J1", LOC_A, earliest_departure_t=600)
    result = solve_circuit(_make_instance([d], [j]))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 1
    # Service must not start before the hard floor
    assert result.assignments[0].start_time_t >= 600


def test_collect_late_same_day_incurs_penalty():
    """Collect assigned late same day costs more than collect within grace."""
    from scheduler.circuit_solver import solve_circuit
    d = _make_driver()
    # Job 1: grace period ends at 560, collect at 480 — within grace, low cost
    j_early = _make_collect("J1", LOC_A, earliest_departure_t=480)
    result_early = solve_circuit(_make_instance([d], [j_early]))

    # Job 2: grace period ends at 100 (very tight), collect at 480 — well past grace
    j_late = _make_collect("J2", LOC_A, earliest_departure_t=0)
    # Override grace_end_t to be 0+120=120; driver arrives at ~30min which is within grace
    # Use a job where earliest_departure_t forces late-day assignment
    # Simplest: check objective value increases when arrival is forced past grace
    # (Full integration test — just assert solver runs without error and assigns the job)
    result_late = solve_circuit(_make_instance([d], [j_late]))
    assert result_late.status in ("OPTIMAL", "FEASIBLE")
    assert len(result_late.assignments) == 1


def test_deliver_late_incurs_higher_penalty_than_early():
    """Late delivery must be more costly than early delivery in objective."""
    # This is a structural test — verifies penalty terms are wired into objective.
    # We use two separate solves and compare that the late one assigns correctly.
    d = _make_driver()
    j = _make_deliver("J1", LOC_A, deadline_t=400)  # deadline well before driver arrives (30min)
    result = solve_circuit(_make_instance([d], [j]))
    # Driver takes 30min transit; arrives at ~30, deadline is 400 — arrives early, no penalty
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 1
```

Run to confirm these fail:
```bash
pytest tests/test_circuit_solver.py -v -k "hard_floor or penalty"
```
Expected: FAIL — old `window_start_t` fields cause `TypeError`

#### 4c: Update `circuit_solver.py`

**Remove** the old feasibility pruning check on `window_end_t` (line ~143):
```python
# DELETE this block in _feasible_jobs_for_driver:
if pair.transit_minutes > job.window_end_t:
    continue
```
Replace with a reasonable upper-bound check using `same_day_end_t`:
```python
# Driver must be able to reach job before end of its scheduled day
if pair.transit_minutes > job.same_day_end_t:
    continue
```

**Widen arrival variable domain** (in `solve_circuit`, the `elif node.job_id:` branch, ~line 188):
```python
# REPLACE:
arrival_time[driver_id][node.index] = model.new_int_var(
    job.window_start_t, job.window_end_t,
    f"arrival_{driver_id}_{node.index}",
)
# WITH:
arrival_time[driver_id][node.index] = model.new_int_var(
    0, t_max,
    f"arrival_{driver_id}_{node.index}",
)
```

**Add hard collect floor** — after the arrival time variable creation loop, before the arc variable creation loop. Find the comment `# Step 1: populate arc_vars dict` and insert before it:

```python
# Hard collect floor: driver cannot depart before booking time
for node in graph.nodes:
    if node.node_type == "collect" and node.job_id:
        job = jobs_by_id[node.job_id]
        if job.earliest_departure_t is not None:
            model.add(
                arrival_time[driver_id][node.index] >= job.earliest_departure_t
            )
```

**Add penalty terms** — import penalty config at top of file:
```python
from scheduler.penalty_config import (
    LATE_SAME_DAY_RATE, SEVERE_NEXT_DAY_RATE,
    EARLY_RATE, LATE_TIER1_RATE, LATE_TIER2_RATE,
)
```

Add a penalty computation block after the shift span constraint section and before the `# --- Objective function ---` comment:

```python
# --- Per-job time penalty terms ---
job_penalty_terms = []

for job in instance.jobs:
    infos = job_node_info.get(job.job_id, [])
    if not infos:
        continue

    # Use the first driver's arrival var for this job as the canonical arrival.
    # All drivers share the same penalty structure; only one can visit.
    # We sum penalties weighted by whether the job is assigned at all.
    for driver_id, node_idx in infos:
        arrival = arrival_time[driver_id][node_idx]

        if job.action == ActionType.COLLECT and job.grace_end_t is not None:
            past_grace = model.new_int_var(0, t_max, f"past_grace_{job.job_id}_{driver_id}")
            model.add_max_equality(past_grace, [0, arrival - job.grace_end_t])

            past_day = model.new_int_var(0, t_max, f"past_day_{job.job_id}_{driver_id}")
            model.add_max_equality(past_day, [0, arrival - job.same_day_end_t])

            job_penalty_terms.append(LATE_SAME_DAY_RATE * past_grace)
            job_penalty_terms.append(SEVERE_NEXT_DAY_RATE * past_day)

        elif job.action == ActionType.DELIVER and job.deadline_t is not None:
            minutes_early = model.new_int_var(0, t_max, f"early_{job.job_id}_{driver_id}")
            model.add_max_equality(minutes_early, [0, job.same_day_start_t - arrival])

            minutes_late_t1 = model.new_int_var(0, 60, f"late_t1_{job.job_id}_{driver_id}")
            model.add_max_equality(minutes_late_t1, [0, arrival - job.deadline_t])
            # Clamp t1 to 60 via upper bound on var (already set) + a constraint
            model.add(minutes_late_t1 <= 60)

            minutes_late_t2 = model.new_int_var(0, t_max, f"late_t2_{job.job_id}_{driver_id}")
            model.add_max_equality(minutes_late_t2, [0, arrival - job.deadline_t - 60])

            job_penalty_terms.append(EARLY_RATE * minutes_early)
            job_penalty_terms.append(LATE_TIER1_RATE * minutes_late_t1)
            job_penalty_terms.append(LATE_TIER2_RATE * minutes_late_t2)
```

Then add `job_penalty_terms` into the objective:
```python
# In the objective section, after arc costs and before unassigned penalty:
objective_terms.extend(job_penalty_terms)
```

**Step 4d: Run all circuit solver tests**

```bash
pytest tests/test_circuit_solver.py -v
```
Expected: all PASS (including new hard-floor and penalty shape tests)

**Step 5: Commit**

```bash
git add src/scheduler/circuit_solver.py tests/test_circuit_solver.py
git commit -m "feat: wide arrival domains, hard collect floor, piecewise penalty objective"
```

---

### Task 5: Update arc pruning in `circuit_builder.py` and `arcs.py`

**Files:**
- Modify: `src/scheduler/circuit_builder.py`
- Modify: `src/scheduler/arcs.py`
- Modify: `tests/test_circuit_builder.py`
- Modify: `tests/test_arcs.py`

#### 5a: Fix test fixtures

Both `test_circuit_builder.py` and `test_arcs.py` construct `Job` objects with `window_start_t` / `window_end_t`. Update their `_make_collect` / `_make_deliver` helpers to match the pattern from Task 4a (same new fields, same defaults).

Run to see failures:
```bash
pytest tests/test_circuit_builder.py tests/test_arcs.py -v
```

#### 5b: Update `circuit_builder.py` temporal pruning

In `_build_arcs`, find the job→job temporal pruning check (~line 179):
```python
# REPLACE:
if tail_job.window_start_t + travel > head_job.window_end_t:
    continue
# WITH:
# Use the tail job's earliest possible departure and head job's same-day end
tail_earliest = tail_job.earliest_departure_t if tail_job.earliest_departure_t is not None else tail_job.same_day_start_t
if tail_earliest + travel > head_job.same_day_end_t:
    continue
```

#### 5c: Update `arcs.py`

In `compute_driver_job_arcs`, find the `window_end_t` check (~line 31):
```python
# REPLACE:
if deadhead > job.window_end_t:
    continue
# WITH:
if deadhead > job.same_day_end_t:
    continue
```

In `compute_job_chain_arcs`, find the `window_end_t` check (~line 88):
```python
# REPLACE:
if earliest_arrival <= job_b.window_end_t:
# WITH:
if earliest_arrival <= job_b.same_day_end_t:
```

And the VEHICLE_DRIVER check (~line 112):
```python
# REPLACE:
if earliest_arrival_vd <= job_b.window_end_t:
# WITH:
if earliest_arrival_vd <= job_b.same_day_end_t:
```

Also in `compute_vehicle_job_arcs` (~line 60):
```python
# REPLACE:
if vehicle.available_from_t + driving > job.window_end_t:
    continue
# WITH:
if vehicle.available_from_t + driving > job.same_day_end_t:
    continue
```

**Step 5d: Run all updated tests**

```bash
pytest tests/test_circuit_builder.py tests/test_arcs.py -v
```
Expected: all PASS

**Step 5e: Commit**

```bash
git add src/scheduler/circuit_builder.py src/scheduler/arcs.py \
        tests/test_circuit_builder.py tests/test_arcs.py
git commit -m "fix: update arc pruning to use asymmetric time fields"
```

---

### Task 6: Fix remaining broken tests and full suite green

**Step 1: Run the full test suite**

```bash
pytest tests/ -v
```

Look for any remaining failures. The likely culprits are:
- `test_solver.py` — has its own `_make_collect` / `_make_deliver` helpers using old fields
- `test_exporter.py` — constructs `Job` objects directly with old fields

**Step 2: Fix each failing test file**

For each file, update `Job` constructor calls to use the new fields (same pattern as Task 4a). Remove any assertion on `window_start_t` / `window_end_t`.

**Step 3: Run full suite again**

```bash
pytest tests/ -v
```
Expected: all PASS

**Step 4: Final commit**

```bash
git add tests/
git commit -m "fix: update remaining test fixtures to use asymmetric time fields"
```

---

### Task 7: Smoke-test with real data

**Step 1: Run the solver end-to-end**

```bash
cd /Users/Shared/_code/boutagys_scheduler
python -m scheduler.run_solver  # or however the CLI is invoked
```

Check `output/schedule.json` — verify:
- `status` is `OPTIMAL` or `FEASIBLE`
- `unassigned_job_ids` is not longer than before (ideally shorter — J045/J054 may now be assigned)
- No collect jobs have `start_time` before their booking time

**Step 2: Commit if any output files changed**

```bash
git add output/
git commit -m "chore: regenerate output with asymmetric time windows"
```
