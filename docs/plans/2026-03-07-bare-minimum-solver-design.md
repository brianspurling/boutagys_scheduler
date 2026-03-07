# Bare-Minimum Feasible Solver — Design

**Goal:** Build a CP-SAT solver that produces any feasible schedule for a day's worth of jobs — proving the model works end-to-end before adding objectives or advanced constraints.

**Architecture:** Boolean arc variables with optional intervals, physical travel enforced via pre-computed JobChainArcs. Standalone `solve(instance) -> SolverResult` function, cleanly separated from the data pipeline.

---

## 1. CP-SAT Model

### Variables

For each `DriverJobArc(driver_id, job_id, deadhead_minutes)` in the instance:

- `x[d, j]` boolean — 1 if driver `d` is assigned to job `j`
- `start[d, j]` integer in `[window_start_t, window_end_t]` — service start time
- `interval[d, j]` optional interval with `size=SERVICE_TIME`, present when `x[d,j]=1`

For each driver `d`, for each unordered pair `{i, j}` where BOTH directions have a `JobChainArc`:

- `seq[d, i, j]` boolean — 1 means i-before-j, 0 means j-before-i

### Constraint 1: Every job assigned to exactly one driver

```
For each job j:
    sum(x[d, j] for all d with arc(d,j)) == 1
```

### Constraint 2: No temporal overlap per driver

```
For each driver d:
    AddNoOverlap(all interval[d, j] for jobs j feasible for d)
```

### Constraint 3: Physical travel between jobs (three cases)

For each driver `d`, for each unordered pair `{i, j}` both feasible for `d`:

**Case 1 — No arc in either direction.** Mutual exclusion:
```
model.Add(x[d, i] + x[d, j] <= 1)
```

**Case 2 — Arc in one direction only (i->j exists, j->i doesn't).** If both assigned, i must precede j:
```
model.Add(start[d, j] >= start[d, i] + SERVICE_TIME + arc_ij.travel_minutes)
    .OnlyEnforceIf([x[d, i], x[d, j]])
```

**Case 3 — Arcs in both directions.** Solver chooses order via disjunctive boolean:
```
seq = model.NewBoolVar(f'seq_{d}_{i}_{j}')

model.Add(start[d, j] >= start[d, i] + SERVICE_TIME + arc_ij.travel_minutes)
    .OnlyEnforceIf([x[d, i], x[d, j], seq])

model.Add(start[d, i] >= start[d, j] + SERVICE_TIME + arc_ji.travel_minutes)
    .OnlyEnforceIf([x[d, i], x[d, j], seq.Not()])
```

### Constraint 4: Deadhead from home

```
For each arc(d, j):
    model.Add(start[d, j] >= arc.deadhead_minutes)
        .OnlyEnforceIf([x[d, j]])
```

### What's NOT included (bare-minimum scope)

- No objective function (pure feasibility, or `Minimize(0)`)
- No daily hours constraint
- No TBA vehicle assignment
- No storage capacity
- No overnight rules
- No soft time window penalties

### OR-Tools API note

`OnlyEnforceIf()` expects a single list of literals when multiple conditions are used:
```python
model.Add(...).OnlyEnforceIf([x[d, i], x[d, j], seq])
```

---

## 2. Solution Model & Output

### Data models (added to models.py)

```python
class JobAssignment(BaseModel, frozen=True):
    job_id: str
    driver_id: str
    start_time_t: int              # integer minutes from horizon start
    start_datetime: datetime       # human-readable, from HorizonConfig

class SolverResult(BaseModel, frozen=True):
    status: str                    # "OPTIMAL", "FEASIBLE", "INFEASIBLE", "MODEL_INVALID"
    solve_time_seconds: float
    assignments: list[JobAssignment]
    stats: dict[str, int]
```

### Time conversion (solver integer -> datetime)

```python
day_offset, minutes_in_day = divmod(start_time_t, 1440)
actual_date = horizon.start_date + timedelta(days=day_offset)
actual_time = time(minutes_in_day // 60, minutes_in_day % 60)
start_datetime = datetime.combine(actual_date, actual_time)
```

### Console output

Print solver status, then for each driver with jobs, list them in time order:
`[start_datetime] ACTION vehicle_group @ postcode`

Summary: jobs assigned, drivers used, solve time.

### CSV exporter

Reads the original bookings CSV row-by-row. Maps `book_no` to `job_id` via the ProblemInstance jobs list, then looks up the assignment. Excluded/unmatched rows pass through with the Drivers column left blank. Output to `output/`.

### Solver API

```python
def solve(instance: ProblemInstance, timeout_seconds: int = 300) -> SolverResult
```

---

## 3. File Structure & Dependencies

### New files

```
src/scheduler/solver.py      # solve() — CP-SAT model construction and extraction
src/scheduler/exporter.py    # print_schedule(), export_csv()
tests/test_solver.py         # Unit tests with synthetic instances + integration test
```

### New dependency

`ortools` added to `pyproject.toml`.

### Test strategy

**Unit tests** use small hand-crafted ProblemInstance objects (2-3 drivers, 3-5 jobs):
- Basic feasibility: 2 non-overlapping jobs, 1 driver -> FEASIBLE
- Infeasible: 2 overlapping jobs, 1 driver, no chain arc -> INFEASIBLE
- Mutual exclusion: 2 jobs, 1 driver, no arc between them -> can't assign both
- Multi-driver: 3 jobs, 2 drivers -> spreads assignments
- Deadhead enforcement: driver can't reach job before window opens

**Integration test:** Run solve() on real sample ProblemInstance, assert FEASIBLE, assert every job assigned.
