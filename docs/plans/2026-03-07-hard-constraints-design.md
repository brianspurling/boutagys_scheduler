# Hard Constraints: Driver Shift Limits & TBA Vehicle Assignment — Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add two hard constraints to the CP-SAT solver: (A) driver daily shift span limits including return home, and (B) TBA vehicle assignment with depot-or-chain sourcing.

**Architecture:** Extends the existing solver with new variables and constraints. Requires a model change to `DriverJobArc` (new field `return_deadhead_minutes`) and corresponding builder/arc updates.

**Tech Stack:** Google OR-Tools CP-SAT, Pydantic models.

---

## Constraint A: Driver Daily Hours (Shift Span)

### What it enforces

For each driver, the wall-clock span from "leave home" (first job start minus
deadhead) to "arrive home" (last job end plus return deadhead) must be ≤
`max_hours_per_day` (stored as integer minutes, e.g. 600 = 10 hours).

### Model change

`DriverJobArc` gains a new field:

```python
class DriverJobArc(BaseModel, frozen=True):
    driver_id: str
    job_id: str
    deadhead_minutes: int
    return_deadhead_minutes: int   # NEW: transit from job back to driver's home
```

Populated in `compute_driver_job_arcs()`:
```python
return_pair = transit_matrix.get(job.target_location, driver.home_location)
return_deadhead = return_pair.transit_minutes if return_pair else 0
```

### Solver variables (per driver d)

- `is_working[d]` — boolean, 1 if driver has any job assignments
- `shift_start[d]` — integer `[0, t_max]`, earliest departure from home
- `shift_end[d]` — integer `[0, t_max]`, latest arrival back home

### Linking `is_working[d]` to assignments

```
model.add(sum(x[d, j] for all j feasible for d) >= 1).only_enforce_if(is_working[d])
model.add(sum(x[d, j] for all j feasible for d) == 0).only_enforce_if(is_working[d].negated())
```

### When working (is_working[d] = 1)

For each arc(d, j):
```
shift_start[d] <= start[d, j] - arc.deadhead_minutes
    .only_enforce_if(x[d, j])

shift_end[d] >= start[d, j] + SERVICE_TIME + arc.return_deadhead_minutes
    .only_enforce_if(x[d, j])
```

Span constraint:
```
shift_end[d] - shift_start[d] <= driver.max_hours_per_day
    .only_enforce_if(is_working[d])
```

### When not working (is_working[d] = 0)

Pin variables to zero — no floating search space:
```
shift_start[d] == 0   .only_enforce_if(is_working[d].negated())
shift_end[d] == 0     .only_enforce_if(is_working[d].negated())
```

### Overnight note

This strictly enforces the return drive for all drivers. The `can_overnight`
exception (allowing drivers to skip the return drive and resume the next day)
is deferred to a future ticket.

---

## Constraint B: TBA Vehicle Assignment

### What it enforces

Every TBA job (Deliver with `vehicle_reg = None`) must be served by exactly
one physical van, sourced from either:
- A depot vehicle (via `VehicleJobArc`), OR
- A driver bringing a van from a preceding Collect job (via a VEHICLE_DRIVER chain)

### Pre-computation: VEHICLE_DRIVER chain index

Before the min-time arc consolidation (which loses chain type info), build:

```python
vd_pairs: set[tuple[str, str]] = set()
for arc in instance.job_chain_arcs:
    if arc.chain_type == "vehicle_driver":
        vd_pairs.add((arc.from_job_id, arc.to_job_id))
```

This set records which directed job pairs have a VEHICLE_DRIVER chain.

### Solver variables

For each `VehicleJobArc(v, j, driving_minutes)`:
- `y[v, j]` — boolean, 1 if depot vehicle `v` is assigned to TBA job `j`

For each VEHICLE_DRIVER pair `(i, j)` where `j` is a TBA job, for each
driver `d` feasible for both `i` and `j`:
- `vd_active[d, i, j]` — boolean, 1 if driver `d` executes the
  VEHICLE_DRIVER chain from `i` into `j`

### Binding `vd_active` (equivalence, not implication)

**Strict order case** — only `(i, j)` exists in `chain_lookup`, not `(j, i)`:
```
vd_active[d, i, j] == 1  IFF  x[d, i] == 1 AND x[d, j] == 1
```
Implemented via:
```python
model.add_bool_and([x[d, i], x[d, j]]).only_enforce_if(vd_active[d, i, j])
model.add_bool_or([x[d, i].negated(), x[d, j].negated()]).only_enforce_if(vd_active[d, i, j].negated())
```

**Disjunctive case** — both `(i, j)` and `(j, i)` exist in `chain_lookup`:
```
vd_active[d, i, j] == 1  IFF  x[d, i] == 1 AND x[d, j] == 1 AND seq[d, i, j] == 1
```
Implemented via:
```python
model.add_bool_and([x[d, i], x[d, j], seq[d, i, j]]).only_enforce_if(vd_active[d, i, j])
model.add_bool_or([x[d, i].negated(), x[d, j].negated(), seq[d, i, j].negated()]).only_enforce_if(vd_active[d, i, j].negated())
```

### Rule 1: Exactly one van source per TBA job

```python
model.add_exactly_one(
    [y[v, j] for all v with VehicleJobArc to j]
    + [vd_active[d, i, j] for all valid (d, i) VEHICLE_DRIVER chains into j]
)
```

### Rule 2: Each depot vehicle assigned to at most one TBA job

```
For each vehicle v:
    sum(y[v, j] for all TBA jobs j) <= 1
```

### Rule 3: Temporal link — depot vehicle must arrive before job starts

```
For each VehicleJobArc(v, j), for each driver d feasible for j:
    start[d, j] >= vehicle.available_from_t + arc.driving_minutes
        .only_enforce_if([y[v, j], x[d, j]])
```

### Spatial routing TODO

The current `DriverJobArc.deadhead_minutes` for TBA Deliver jobs routes the
driver directly to the customer location. In reality, the driver needs to
travel to the van's depot location first, then drive to the customer. This
two-leg routing is deferred to a future ticket.

```python
# TODO: Dynamic Driver->Van->Customer routing for TBA jobs
```

---

## What's NOT included

- No objective function (still pure feasibility)
- No storage location capacity constraints
- No overnight/multi-day rules
- No soft time window penalties
- No spatial routing fix for TBA driver deadhead

---

## Files changed

- `src/scheduler/models.py` — add `return_deadhead_minutes` to `DriverJobArc`
- `src/scheduler/arcs.py` — populate `return_deadhead_minutes`
- `src/scheduler/solver.py` — add Constraint 5 (shift span) and Constraint 6 (TBA vehicles)
- `tests/test_solver.py` — new tests for both constraints
- `tests/test_arcs.py` — update existing tests for new field
- `tests/test_models.py` — update `test_driver_job_arc` for new field
- All test helpers that create `DriverJobArc` — add `return_deadhead_minutes`

## Test strategy

**Constraint A tests:**
- Driver with 1 job, shift span within limit → FEASIBLE
- Driver with 1 job, deadhead + return exceeds limit → INFEASIBLE
- Driver with 2 jobs, combined span within limit → FEASIBLE
- Driver with 2 jobs, combined span exceeds limit → INFEASIBLE
- `is_working` correctness: driver with no jobs doesn't affect feasibility

**Constraint B tests:**
- TBA job with matching depot vehicle → FEASIBLE, vehicle assigned
- TBA job with no depot vehicle and no chain → INFEASIBLE (excluded by builder, but test at solver level too)
- TBA job served by VEHICLE_DRIVER chain (collect→deliver) → FEASIBLE, no depot vehicle used
- Two TBA jobs, one depot vehicle → only one gets the vehicle (test with chain providing the other)
