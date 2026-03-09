# Boutagy's Scheduler — Project Guide

## What We're Building

A bespoke vehicle relocation solver for a van rental operation. The problem is a **Vehicle Relocation Problem with Independent Crew**: we are routing the *vehicles themselves*, not parcels inside vehicles. Drivers deadhead independently (public transit/cycling) between jobs.

In OR terms: a Deterministic, Multi-Resource, Time-Dependent, Multi-Period Inventory-Routing Problem with External Transfer Modes.

See `docs/specs/high-level-spec.md` for the full problem definition.


---

## Folder Structure

```
docs/
  specs/        # Original high-level spec and Gemini Deep Research output
  plans/        # Intermediary design docs and implementation plans produced by Claude Code and reviewed by Gemini (with superpowers skill)
ref-data/       # Stable reference data (drivers, vehicles, storage locations)
input/          # Daily scheduling export from booking system (bookings CSV). Current example is mostly 8th Dec bookings. Not clear why it doesn't look ahead; not clear why no TBA vehicle assignments. 
output/         # Generated schedules (csv and JSON versions) and HTML report
src/            # Code
tests/          # Test code
```

---

### Solution Overview (simple/conceptual version)

1. Define Nodes: Create a stop for every Job, Depot (Pick-up and Drop-off), and Driver Home.

2. Build Legal Arcs (The Map): 

  - Legality Check: Only draw paths that are physically possible 
    - Custody State: if a driver has a van they cannot pick up another (state-dependent arcs)
    - Certification: Driver must have a valid license for that specific vehicle.
    - Time: They must be able to reach the destination within the window.

  - Costing: Apply "weighted costs" to every path (tolls).
    - Mode: Driving is cheaper; Transit is more expensive.
    - Dwell: Add 15-minute "dwell" time for any path passing through a Depot.

  - Pruning: Discard any arc that is physically impossible or so expensive it’s clearly not optimal (e.g., a 4-hour commute to a 10-minute job).

3. CP-SAT (The Circuit Solver)

  - Constraint Solver: Apply the "Hard Rules."
    - Coverage: Every job node must be visited exactly once.
    - Connectivity: Every driver must follow a continuous loop (Circuit).
    Shift Limits: Total time from Home-to-Home <= Max Hours.
  - Objective Optimizer: Find the set of "Circuits" (closed loops starting/ending at Home) that minimizes:
    - Total Arc Cost (The "Tolls" from Step 2).
    - Driver Activation Penalty (A massive cost added to the first arc leaving Home, forcing the solver to use fewer drivers)

4. Output

  - Data outputs (CSV, JSON formats, as needed)
  - HTML report built on top of data output, to visualise schedule


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
- Respect soft time windows with cost penalties (not hard cutoffs)
- Get as few drivers doing as many jobs as possible (driver density)
- Preserve scarce vehicle groups for future demand (opportunity cost)

---


## MVP Epics & Development Workflow

The project is being built to an **Operational MVP** — the solver replaces the daily spreadsheet for a human dispatcher. Four epics remain (see README for full descriptions):

| Epic | Topic | Priority |
|------|-------|----------|
| Epic 2 | Real Travel Times (Google Maps cache) | must-have |
| Epic 3 | TBA Vehicle Assignment | must-have |
| Epic 4 | Multi-Day Rolling Horizon + `can_overnight` | must-have |
| Epic 5 | Storage Location Capacity Enforcement | should-have |

Epic 1 (solver consolidation — retire `solver.py`, wire `circuit_solver.py`) is **complete** as of 2026-03-09.

### Workflow for each epic

Each epic follows this sequence before any code is written:

1. **Brainstorm** (`superpowers:brainstorming` skill) — explore intent, constraints, approaches
2. **Design doc** — saved to `docs/plans/YYYY-MM-DD-<topic>-design.md`, committed
3. **Implementation plan** (`superpowers:writing-plans` skill) — saved to `docs/plans/YYYY-MM-DD-<topic>-implementation.md`, committed
4. **Implementation** — TDD (`superpowers:test-driven-development` skill), one plan step at a time
5. **Review** (`superpowers:requesting-code-review` skill) before merging

Design and plan docs go through stakeholder review (via Gemini) before implementation begins.

---

**Bookings CSV parsing rules:**
- Strip blank rows first (used as visual separators in the human spreadsheet, carry no meaning)
- Each row is an independent job — do not infer links between adjacent rows
- Strip postcode suffixes: remove everything after the first space-separated postcode token (e.g. `BH23 5LJ*PRE-DELIVERY*` → `BH23 5LJ`, `B92 0AE - EXT BEFORE` → `B92 0AE`)
- `Supp'd Grp` may contain upgrade notation with `>` (e.g. `E.A17>D.B9A`): take the second (rightmost) value as the operative vehicle group
- Job notes are descoped for now — store as a raw string, do not parse for structured constraints


