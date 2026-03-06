# Boutagy's Scheduler — Project Guide

## What We're Building

A bespoke vehicle relocation solver for a van rental operation. The problem is a **Vehicle Relocation Problem with Independent Crew**: we are routing the *vehicles themselves*, not parcels inside vehicles. Drivers deadhead independently (public transit/cycling) between jobs.

In OR terms: a Deterministic, Multi-Resource, Time-Dependent, Multi-Period Inventory-Routing Problem with External Transfer Modes.

See `docs/specs/high-level-spec.md` for the full problem definition.

---

## Working Philosophy — READ THIS FIRST

**We move slowly and deliberately. No rushing to code.**

**Before starting any new task: check in with the user first. Confirm what we're about to build, agree on the approach, then proceed.**

The sequence is fixed:

**Discuss & agree** before building anything

1. **Data pipeline** — load and validate input/ref data into domain model
2. **Test suite** — real-world examples with human-generated schedules as baseline
3. **Objective Function** — the objective/cost function we seek to optimise for (we'll start by using these to score the human-created schedules)
4. **Algorithm** — only after we can measure what "better" means

Do not skip ahead. Do not scaffold the optimizer while working on the data pipeline. Each stage is complete when it is tested and agreed.

---

## Folder Structure

```
input/          # Daily scheduling input (bookings CSV)
ref-data/       # Stable reference data (drivers, vehicles, storage locations)
docs/
  specs/        # Problem specification documents
  plans/        # Design docs and implementation plans
output/         # Generated schedules and scoring output
zBin/           # Old spike code — kept for reference only, do not modify
```

---

## Data Sources

### Input (changes daily)
- `input/sample_bookings_data.csv` — bookings with columns: Book No., Order ref, Rental No., Book Name, Book Status, Date, Time, Action (Collect/Deliver), Reg No., Supp'd Grp, Drivers, Delivery postcode, Collection postcode, Notes
- The `Drivers` column in the input is blank on raw input files — it is populated in the human-solved output (used for test case baselines in Stage 2)

### Reference (stable)
- `ref-data/drivers.csv` — driver_id, name, home_postcode, branch, max_hours_per_day, certifications (van / van+truck), can_overnight, unavailable_dates, home_location (lat/lon), notes
- `ref-data/vehicle_inventory.csv` — vehicle_reg, vehicle_group, current_storage_location, availability_date, notes
- `ref-data/storage_locations.csv` — location_id, name, postcode, capacity, restricted_vehicle_groups, lat_long

---

## Key Domain Concepts

- **Job**: a single relocation task — either a Collect (pick up van from customer) or Deliver (drop van to customer). Two jobs can be chained: collect a van, then deliver it, with a mandatory 45-minute turnaround buffer. Jobs are independent rows in the input CSV — do not infer any link between adjacent rows.
- **Deadhead**: driver travel *between* jobs using public transit or cycling. This counts against their daily hour limit.
- **Vehicle group**: ~10 types (V2, V3, V5, D.B9, E.A17, etc.). Driver certifications must match — `van` cert covers standard groups, `van+truck` covers trucks only. **Known truck groups: C.F4 and E.A17. Verify this list is complete before finalising the constraint model.**
- **TBA vehicle**: a Deliver job where `Reg No.` is blank — solver must select the best available vehicle from the pool matching the required group.
- **Rolling horizon**: 4–5 day look-ahead window. Day 1 is frozen for dispatch after each run. The horizon start date is passed in as a parameter; if omitted it defaults to tomorrow.
- **Nodes**: there are two types of location node — **customer postcodes** (hundreds, from job Delivery/Collection fields) and **storage locations** (3 depots: Feltham, Putney, Wetlands). They are modelled the same way but are distinct in scale and purpose.
- **Storage locations**: Physical depots with hard capacity limits. Overall node capacity must be tracked across the horizon using Cumulative/Reservoir constraints (tracking the integer sum of vehicle arrivals minus departures), rather than tracking the individual identities of idle assets.

---

## Hard Constraints (must never be violated)

- Driver daily hours ≤ `max_hours_per_day` (default 10), counting both driving and deadhead time
- Driver certifications must match vehicle group requirements
- Vehicles with future `availability_date` cannot be assigned until that date
- Storage location capacity must not be exceeded
- `can_overnight` must be true for any multi-day assignment
- Drivers with entries in `unavailable_dates` cannot be assigned on those dates

---

## Optimization Objectives (what "better" means)

To be formally defined in the scoring stage, but the high-level targets are:
- Minimise total deadhead time/cost across all drivers
- Maximise job chaining (collect → deliver with turnaround buffer)
- Balance workload across drivers
- Respect soft time windows with cost penalties (not hard cutoffs)
- Preserve scarce vehicle groups for future demand (opportunity cost)

---

## Build Stages

### Stage 1 — Data Pipeline
Parse and validate all input/ref data into a typed domain model. Goal: a clean, validated in-memory representation of a day's scheduling problem, ready to be consumed by downstream stages.

- No solver logic here
- But data model must be designed with the high-level solution in mind
- Must surface data quality issues (missing postcodes, unknown vehicle groups, etc.)
- Must produce a deterministic, reproducible output from the same input

**Data model design**: see `docs/plans/2026-03-06-data-model-design.md` for the approved design. Key decisions:
- **Pydantic frozen models** — immutable, validated, serializable domain objects
- **Builder pattern** — `ProblemBuilder` ingests CSVs, validates, computes arcs, produces an immutable `ProblemInstance`
- **Dual time representation** — human-readable `datetime` + integer-minute offsets from horizon start on all time fields
- **Pre-computed arc graph** — builder pre-prunes infeasible DriverJobArcs, VehicleJobArcs, and JobChainArcs before the solver sees them
- **Dual-mode transit matrix** — stores both `transit_minutes` (PT deadhead with +15% buffer) and `driving_minutes` per location pair
- **Two chain types** — DRIVER_ONLY (PT between jobs) and VEHICLE_DRIVER (collect→deliver with 45-min turnaround, matching vehicle groups)
- **Infeasible job exclusion** — jobs with zero feasible arcs are excluded from ProblemInstance (not just warned about) to prevent solver INFEASIBLE on the whole board
- **Transit fallback** — missing transit data falls back to Haversine × conservative speed multiplier rather than failing the build
- **Explicit cert lookup** — vehicle group → certification level mapping with no prefix-guessing; fail on unknown groups
- **Arc pruning uses best-case timing** — `window_start_t` (not nominal time) to avoid over-pruning valid soft-window shifts

**Bookings CSV parsing rules:**
- Strip blank rows first (used as visual separators in the human spreadsheet, carry no meaning)
- Each row is an independent job — do not infer links between adjacent rows
- Strip postcode suffixes: remove everything after the first space-separated postcode token (e.g. `BH23 5LJ*PRE-DELIVERY*` → `BH23 5LJ`, `B92 0AE - EXT BEFORE` → `B92 0AE`)
- `Supp'd Grp` may contain upgrade notation with `>` (e.g. `E.A17>D.B9A`): take the second (rightmost) value as the operative vehicle group
- Job notes are descoped for now — store as a raw string, do not parse for structured constraints

### Stage 2 — Test Suite
A set of real-world scheduling days with:
- The raw input data for that day
- The schedule the human team produced (the **baseline**)
- The baseline stored in a format the scorer can evaluate

The human schedule is always the baseline to beat. We never claim victory unless we demonstrably outperform it on the agreed metrics.

### Stage 3 — Objective Function
Define the objective function: the cost/penalty structure that expresses what "better" means (deadhead time, chaining bonuses, soft time window penalties, etc.). Agree on the terms and weights before any code is written.

### Stage 4 — Algorithm
Build the CP-SAT model with the agreed objective function and constraints. The model operates in two modes — same code, same objective function, same constraints, always:

- **Scoring mode**: human schedule is loaded and all assignment variables are fixed ("locked") to what the human chose. The solver evaluates the objective on the locked board instantly. No search required.
- **Optimisation mode**: variables are free, solver searches for the minimum cost solution.

This is the **variable fixing** pattern — there is one single source of truth for all business logic. There is no separate scorer and no risk of logic drift between two codebases computing costs differently.

---

## Technical Notes

- **Time resolution**: integer minutes throughout. No floats, no broad shift buckets.
- **Transit caching**: public transit times between postcodes must be pre-cached, not queried live during solver runs.
- **Geographic clustering**: pre-processing step to group jobs by zone before the heavy routing math.
- **Sparse graph pruning**: prune impossible job-to-job and driver-to-job arcs before instantiating solver variables — based on temporal feasibility, not arbitrary radius caps.
- **Solver**: Google OR-Tools CP-SAT is the target. 5-minute timeout with best-incumbent fallback.
- **Parking constraints**: high-density restricted postcodes (SW1, EC1, etc.) must block or heavily penalize early drop-offs.
