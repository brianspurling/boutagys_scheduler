# Boutagy's Scheduler

A bespoke vehicle relocation solver for a van rental operation. It replaces manual spreadsheet scheduling with an automated algorithmic solver powered by Google OR-Tools CP-SAT.

---

## The Problem

Every day, ~100 vans need to be collected from customers or delivered to customers across the UK. Drivers travel *between* jobs independently (public transit, cycling) — they don't ride inside the vans. The solver must figure out which driver does which job, in what order, while respecting shift limits, driver certifications, vehicle availability, and depot capacity.

In OR terms: a **Vehicle Relocation Problem with Independent Crew** — a Multi-Resource, Time-Dependent, Multi-Period Inventory-Routing Problem with External Transfer Modes.

---

## How It Works

The pipeline has four stages:

### 1. Load & Validate (Builder)

`ProblemBuilder` reads all input and reference files, validates them, and produces a `ProblemInstance`. It checks for:
- Unknown vehicle groups or postcodes
- Drivers unavailable on the horizon dates
- Vehicles not yet available (`availability_date` in the future)
- Bookings outside the horizon window

Any fatal errors abort the build; warnings are reported but allowed through.

### 2. Build Arcs (Graph Construction)

For each driver, a directed graph of nodes and arcs is built:

- **Nodes**: driver home, each collect/deliver job, depot stops
- **Arcs**: every feasible transition between nodes, costed by travel time and mode

**Arc costing:**
- Transit (deadhead) arcs cost more than driving arcs — the solver prefers keeping drivers in vans
- A driver activation penalty is added to the first arc leaving home, discouraging use of extra drivers

**Arc pruning** — arcs are discarded before the solver ever sees them if:
- The driver lacks certification for the vehicle group
- The driver cannot physically reach the job in time given their remaining shift hours
- Chaining two jobs is impossible (completion of job A + travel + minimum job B time exceeds job B's latest window)

### 3. Solve (CP-SAT Circuit)

The pruned graphs go into a CP-SAT model. Each driver must form a closed **circuit** (loop) starting and ending at home.

**Hard constraints:**
- Every job node is visited exactly once across all driver circuits
- Driver shift duration (driving + deadhead) ≤ `max_hours_per_day` (default 10h)
- Driver certifications must match vehicle group (`van` or `van+truck`)
- Vehicles with a future `availability_date` cannot be assigned before that date
- `can_overnight` must be true for multi-day assignments

**Objective (minimise):**
- Arc travel costs (weighted transit > driving)
- Driver activation penalties (use fewer drivers)
- Time window penalties for collect and deliver jobs (see below)
- A small span penalty to tighten schedules

**Soft time windows with asymmetric penalties:**

| Job type | Penalty |
|---|---|
| Collect — after booking time + 2h grace | 2 pts/min late |
| Collect — past end of scheduled day | 10 pts/min late |
| Deliver — before scheduled day starts | 1 pt/min early |
| Deliver — up to 60 min late | 10 pts/min late |
| Deliver — more than 60 min late | 30 pts/min late |

The solver runs for up to `timeout_seconds` (default 60s) and returns the best solution found, even if not proven optimal.

### 4. Export

Results are written to `output/`:
- `schedule.csv` — one row per job, with assigned driver, times, and vehicle
- `schedule.json` — full structured output including driver routes and solver stats
- `report.html` — visual HTML schedule loaded from `schedule.json` in the browser

### The HTML Report

Open `output/report.html` directly in a browser (no server needed). It reads `schedule.json` from the same folder and renders four sections:

- **Driver Summary** — a Gantt-style bar chart showing each driver's collect and deliver jobs across the day, with idle drivers greyed out
- **Drivers** — expandable accordion per driver, showing their full route as a sequence of legs (transit or driving), with postcodes, durations, and vehicle regs
- **Vehicles** — expandable accordion per vehicle, listing all jobs it is assigned to
- **Bookings** — full job table with assigned driver, scheduled time, action, vehicle, and location; unassigned jobs are highlighted in red

If any jobs are unassigned, a warning banner appears at the top and a "Download unassigned KML" button lets you export the unassigned job locations for viewing in Google Maps or similar.

---

## Files & Folders

```
run_solver.py              # Entry point — configure horizon here
input/
  sample_bookings_data.csv # Daily bookings export
ref-data/
  drivers.csv              # Driver roster and constraints
  vehicle_inventory.csv    # Fleet with current locations
  storage_locations.csv    # Depots (Feltham, Putney, Wetlands)
  postcode_coords.csv      # Lat/lon lookup for postcodes
src/scheduler/
  builder.py               # Loads data, validates, builds ProblemInstance
  arcs.py                  # Feasibility checks and arc costing
  circuit_builder.py       # Constructs per-driver circuit graphs
  circuit_solver.py        # CP-SAT model and solve loop
  penalty_config.py        # Time window penalty rates (tune here)
  exporter.py              # CSV / JSON output
  models.py                # All data types (Pydantic)
  loaders.py               # CSV parsing for each file type
  parsing.py               # Bookings CSV cleaning rules
  geo.py                   # Distance and travel time calculations
  cert_table.py            # Vehicle group → certification mapping
output/
  schedule.csv / .json     # Latest solver output
  report.html              # Visual schedule report
docs/
  specs/                   # Original problem spec and research
  plans/                   # Design docs and implementation plans
tests/                     # Unit tests (pytest)
```

---

## Configuration

### Horizon

Edit `run_solver.py` to set the planning window:

```python
ProblemBuilder(horizon_start=date(2025, 12, 8), num_days=5)
```

`horizon_start` defaults to tomorrow if omitted. Day 1 of the output is intended to be frozen for dispatch; Days 2–5 are rolling drafts.

### Solver timeout

```python
solve_circuit(inst, timeout_seconds=60)
```

Increase for better solutions on harder instances; decrease for faster iteration.

### Penalty rates

`src/scheduler/penalty_config.py` — all per-minute integer costs used by the objective function. Tune these to change how aggressively the solver prioritises on-time performance vs. travel cost.

```python
LATE_SAME_DAY_RATE    = 2    # collect: minutes late past grace period
SEVERE_NEXT_DAY_RATE  = 10   # collect: minutes past end of day
EARLY_RATE            = 1    # deliver: minutes early
LATE_TIER1_RATE       = 10   # deliver: first 60 min late
LATE_TIER2_RATE       = 30   # deliver: beyond 60 min late
```

### Reference data

| File | What to update |
|---|---|
| `ref-data/drivers.csv` | Add/remove drivers, change certifications, hours, availability |
| `ref-data/vehicle_inventory.csv` | Update current locations and availability dates after moves |
| `ref-data/storage_locations.csv` | Depot capacities and restricted vehicle groups |
| `ref-data/postcode_coords.csv` | Lat/lon for any new postcodes that appear in bookings |

### Vehicle group certifications

`src/scheduler/cert_table.py` maps each vehicle group to the certification it requires (`van` or `van+truck`). Known truck groups: **C.F4, E.A17**. Update this file if new groups are introduced.

---

## Running

```bash
python run_solver.py
```

Output is written to `output/`. The console prints a per-driver schedule summary and flags any unassigned jobs.

### Tests

```bash
pytest
```

---

## Key Concepts

**Deadhead** — a driver travelling between jobs using public transit or cycling. This time counts against their daily hour limit.

**TBA vehicle** — a Deliver job where no specific van is assigned. The solver picks the best available vehicle from the pool matching the required group.

**Circuit** — each driver's route is modelled as a closed loop (home → job → job → ... → home). The CP-SAT circuit constraint enforces continuity.

**Collect vs Deliver** — a Collect means picking up a van from a customer; a Deliver means dropping a van to a customer. They have asymmetric time window rules (collects have a grace period; delivers have hard late penalties).

**Job chaining** — when a driver collects a van and then immediately delivers it, a mandatory 45-minute turnaround buffer is inserted between the two jobs.

---

## Known Limitations & To Do

### Travel time accuracy (high priority)

Transit and driving times are currently estimated using straight-line (Haversine) distance with fixed speed assumptions (30 km/h driving, 20 km/h transit with a 15% buffer). This is a placeholder. Real travel times — especially for public transit across the UK — can differ significantly.

**Needed:** Replace `geo.py`'s `estimate_transit_pair` with a Google Maps API lookup (Distance Matrix API, transit mode). Times should be pre-computed and cached in a lookup table (keyed by postcode pair) so the solver doesn't make live API calls. The caching layer and cache-population script need to be built.

### Multi-day / rolling horizon

The solver currently runs against a single day's bookings. The 4–5 day rolling horizon described in the spec — where Day 1 is frozen and vehicle positions carry forward into Days 2–5 — is not yet implemented. Vehicle states are treated as static (current position only, no forward propagation).

### TBA vehicle assignment

Deliver jobs with no `Reg No.` (TBA) are not yet handled. The solver needs to dynamically select the best available vehicle from the pool matching the required group, and apply `NoOverlap` constraints to prevent double-assignment.

### Storage location capacity tracking

Depot capacity limits exist in `storage_locations.csv` but are not yet enforced in the solver. Cumulative/Reservoir constraints tracking vehicle arrivals minus departures at each depot need to be added.