# Circuit-Based Solver with Vehicle Custody & Objective Function — Design

**Goal:** Replace the current pairwise feasibility solver with a circuit-based routing model that enforces vehicle custody as a hard physical constraint, and minimises a weighted cost objective that naturally discovers optimal job chaining and driver density.

**Architecture:** One `add_circuit` per driver over a graph of job nodes, depot-action nodes, and the driver's home node. Vehicle custody is enforced structurally — the graph only contains arcs that respect the driver's physical state (Empty-Handed or In-Vehicle). The objective function is the sum of arc costs across all active drivers.

---

## 1. The Driver State Machine

A driver is always in one of two states:

```
EMPTY_HANDED  ──Collect──>  IN_VEHICLE(reg)
      ^                           |
      |                           |
      +───Deliver/DepotDrop───────+
```

**EMPTY_HANDED:** The driver has no van. They travel by public transit. Legal next actions:
- Travel (transit) to a Collect job
- Travel (transit) to a Depot, pick up a van (15 min dwell), become IN_VEHICLE

**IN_VEHICLE(reg):** The driver is holding a specific van. They travel by driving. Legal next actions:
- Drive to a Deliver job for a matching vehicle → EMPTY_HANDED
- Drive to a Depot, park the van (15 min dwell) → EMPTY_HANDED
- Drive home (end of day, overnight)

Every driver starts the day EMPTY_HANDED (overnight-start-in-vehicle deferred to overnight modelling).

---

## 2. Graph Structure (Per Driver)

Each driver gets their own circuit graph. The node set for driver `d`:

### Node Types

| Node | Description | State on arrival |
|------|-------------|-----------------|
| `HOME_d` | Driver's home. Circuit start and end. | EMPTY_HANDED |
| `COLLECT_j` | Collect job `j`. Driver picks up a van. | IN_VEHICLE |
| `DELIVER_j` | Deliver job `j`. Driver drops off a van. | EMPTY_HANDED |
| `DEPOT_DROP_s` | Depot `s` drop-off. Driver parks a van. | EMPTY_HANDED |
| `DEPOT_PICKUP_s` | Depot `s` pickup. Driver takes a van. | IN_VEHICLE |

**Important:** There are separate DEPOT_DROP and DEPOT_PICKUP nodes for each storage location. A driver who drops a van at Feltham and picks up a different van from Feltham passes through two distinct nodes (DEPOT_DROP_S001 → DEPOT_PICKUP_S001), with 15 min dwell on each.

### Arc Types (State-Legal Connections)

Arcs are only created where the state transition is physically legal:

| From (state after) | To (state required) | Travel mode | Cost basis |
|---|---|---|---|
| HOME (empty) | COLLECT_j (empty→vehicle) | Transit | transit_minutes * TRANSIT_WEIGHT |
| HOME (empty) | DEPOT_PICKUP_s (empty→vehicle) | Transit | transit_minutes * TRANSIT_WEIGHT |
| HOME (empty) | DELIVER_j (empty, needs van†) | — | Not direct; must go via DEPOT_PICKUP first |
| COLLECT_j (vehicle) | DELIVER_j' (vehicle→empty) | Driving | driving_minutes * DRIVING_WEIGHT + turnaround |
| COLLECT_j (vehicle) | DEPOT_DROP_s (vehicle→empty) | Driving | driving_minutes * DRIVING_WEIGHT |
| DEPOT_DROP_s (empty) | COLLECT_j (empty→vehicle) | Transit | transit_minutes * TRANSIT_WEIGHT |
| DEPOT_DROP_s (empty) | DEPOT_PICKUP_s' (empty→vehicle) | Transit | transit_minutes * TRANSIT_WEIGHT |
| DEPOT_DROP_s (empty) | HOME (empty) | Transit | transit_minutes * TRANSIT_WEIGHT |
| DELIVER_j (empty) | COLLECT_j' (empty→vehicle) | Transit | transit_minutes * TRANSIT_WEIGHT |
| DELIVER_j (empty) | DEPOT_PICKUP_s (empty→vehicle) | Transit | transit_minutes * TRANSIT_WEIGHT |
| DELIVER_j (empty) | HOME (empty) | Transit | transit_minutes * TRANSIT_WEIGHT |
| DEPOT_PICKUP_s (vehicle) | DELIVER_j (vehicle→empty) | Driving | driving_minutes * DRIVING_WEIGHT |
| DEPOT_PICKUP_s (vehicle) | DEPOT_DROP_s' (vehicle→empty) | Driving | driving_minutes * DRIVING_WEIGHT |
| COLLECT_j (vehicle) | HOME (vehicle, end of day) | Driving | driving_minutes * DRIVING_WEIGHT |
| DEPOT_PICKUP_s (vehicle) | HOME (vehicle, end of day) | Driving | driving_minutes * DRIVING_WEIGHT |

†A Deliver job requires the driver to already be IN_VEHICLE. The graph structurally prevents going HOME→DELIVER directly because HOME produces state EMPTY_HANDED and DELIVER requires EMPTY_HANDED entry but needs a van. The driver must pass through either a COLLECT or DEPOT_PICKUP first.

### Collect→Deliver Vehicle Matching

A COLLECT_j → DELIVER_j' arc is only created when the vehicle groups are compatible:
- If DELIVER_j' has a specific `vehicle_reg`, the Collect must be for that same reg
- If DELIVER_j' is TBA (no reg), the Collect must be for a matching `vehicle_group`

This is enforced at graph construction time (in the builder), not as a solver constraint.

### Self-Loop Arcs (Skipping Nodes)

Every job node and depot node gets a self-loop arc `(n, n, ~visited_n)` allowing the circuit to skip it. The HOME node is mandatory (no self-loop) — every active driver must start and end at home.

---

## 3. Depot Dwell Time

`DEPOT_DWELL_MINUTES = 15`

This is a hard time addition baked into arcs during graph construction:

- Any arc arriving at a DEPOT_DROP node has the 15-min dwell added to its travel time
- Any arc arriving at a DEPOT_PICKUP node has the 15-min dwell added to its travel time

If a driver does DROP then PICKUP at the same depot (parking one van, taking another), the total dwell is 30 minutes (15 + 15). This is computed in the ProblemBuilder, not the solver.

---

## 4. Time Windows & Temporal Constraints

Each job node has a time window `[window_start_t, window_end_t]` from the existing model. The circuit constraint gives us sequencing, but we still need temporal feasibility:

For each arc `(u, v)` in driver `d`'s circuit:
```
arrival_time[v] >= departure_time[u] + arc_travel_time(u, v)
```

Where:
- `departure_time[u] = arrival_time[u] + service_time(u)` (service_time is 0 for most nodes, DEPOT_DWELL for depot nodes)
- Job nodes: `arrival_time[j]` must be within `[window_start_t, window_end_t]`
- HOME departure: `arrival_time[HOME] >= 0` (start of horizon)

These are `OnlyEnforceIf(arc_var)` constraints on the arc boolean variables.

### Shift Span

```
shift_end[d] - shift_start[d] <= max_hours_per_day * 60
```

Where `shift_start` = HOME departure time, `shift_end` = HOME arrival time (last arc into HOME).

---

## 5. Job Assignment Constraints

### Every job assigned to exactly one driver

Same as current model, but now expressed through the circuit's visited variables:

```python
for job in instance.jobs:
    model.add_exactly_one(visited[d][job_node] for d in feasible_drivers(job))
```

### TBA Vehicle Assignment

TBA Deliver jobs (no vehicle_reg) must get a van from somewhere. In the circuit model, this is structural:
- A TBA DELIVER node can only be reached from a COLLECT (with matching group) or a DEPOT_PICKUP (where the specific vehicle is selected)
- For DEPOT_PICKUP → TBA_DELIVER arcs, we add a vehicle selection variable `y[vehicle_reg, job_id]` as in the current Constraint 6
- `add_exactly_one` over all vehicle sources per TBA job (same logic as current, but the VEHICLE_DRIVER chain is now naturally handled by COLLECT→DELIVER arcs in the circuit)

---

## 6. Objective Function

The solver minimises total weighted cost:

```
Minimize:
    sum(arc_cost[d][u][v] * arc_var[d][u][v]  for all drivers d, all arcs (u,v))
  + sum(ACTIVATION_PENALTY * is_active[d]      for all drivers d)
  + sum(SPAN_PENALTY * (shift_end[d] - shift_start[d])  for all active drivers d)
```

### Cost Components

**Arc costs (computed in builder, integers):**

| Component | Formula | Rationale |
|-----------|---------|-----------|
| Transit leg | `transit_minutes * TRANSIT_WEIGHT` | PT is more costly than driving (friction, unreliability) |
| Driving leg | `driving_minutes * DRIVING_WEIGHT` | Base cost of moving a van |
| Turnaround buffer | `45` (only on COLLECT→DELIVER arcs) | Mandatory cleaning/refueling buffer |
| Depot dwell | `15` per depot visit | Baked into arc travel time |

**Driver-level costs:**

| Component | Formula | Rationale |
|-----------|---------|-----------|
| Activation penalty | `ACTIVATION_PENALTY * is_active[d]` | Encourage fewer drivers (density) |
| Shift span penalty | `SPAN_PENALTY * (shift_end[d] - shift_start[d])` | Discourage idle waiting, compress schedules |

### Weight Constants (Tuneable)

```python
TRANSIT_WEIGHT = 3      # Transit minutes are 3x more expensive than driving
DRIVING_WEIGHT = 1      # Base unit
ACTIVATION_PENALTY = 120  # Equivalent to 120 driving-minutes; roughly "2 hours of driving cost"
SPAN_PENALTY = 1        # Each minute of shift span costs 1 unit
```

These are initial values. The key property is that `TRANSIT_WEIGHT > DRIVING_WEIGHT`, which means the solver will prefer routes where the driver is driving a van rather than deadheading on transit — naturally discovering that Collect→Deliver chains are cheaper than Collect→Depot→Transit→Collect.

**Why no chaining bonus:** If the weights are calibrated correctly, chaining emerges as the cheapest path. A Collect→Deliver chain costs `driving_minutes * 1 + 45 turnaround`. The alternative (Collect→Depot→transit→next job) costs `driving_to_depot * 1 + 15 dwell + transit_to_next * 3`. The solver will chain whenever the direct drive + turnaround is cheaper than the depot detour.

---

## 7. Graph Size Estimation

For the current sample data (59 jobs, 20 drivers, 3 depots):

- Job nodes per driver: up to 59 (pruned by certification + temporal feasibility)
- Depot nodes per driver: 6 (3 locations x 2 actions: drop/pickup)
- Home node: 1
- **Total nodes per driver:** ~66 max, typically ~40 after pruning
- **Total arcs per driver:** much sparser than N^2 because state constraints eliminate most connections (e.g., no COLLECT→COLLECT arcs exist at all)

Estimated arcs per driver: ~300-500 (vs. ~3400 in a full 59x59 graph). Across 20 drivers: ~6000-10000 arc variables total. This is well within CP-SAT's capacity.

### Pruning (in builder)

Arcs are pre-pruned using the same criteria as current DriverJobArc pruning:
- Certification compatibility
- Temporal feasibility (can the driver physically reach the next node within its time window?)
- Unavailable dates
- Vehicle group matching for COLLECT→DELIVER arcs

---

## 8. What Changes

### New / Rewritten Files

| File | Change |
|------|--------|
| `src/scheduler/models.py` | Add `CircuitNode`, `CircuitArc`, `DriverCircuitGraph` models. Remove old chain/arc models or keep for backward compat. |
| `src/scheduler/circuit_builder.py` | **New.** Builds the per-driver circuit graphs from `ProblemInstance`. Handles arc pruning, cost computation, depot dwell injection, state-legal arc generation. |
| `src/scheduler/solver.py` | **Rewrite.** Circuit-based model construction, objective function, solution extraction. |
| `src/scheduler/exporter.py` | Update to extract routes from circuit solution (mostly already done via `DriverRoute`). |
| `tests/test_solver.py` | **Rewrite.** New tests for circuit model. |
| `tests/test_circuit_builder.py` | **New.** Tests for graph construction and arc pruning. |

### Unchanged Files

| File | Status |
|------|--------|
| `src/scheduler/models.py` (core domain) | `Job`, `Driver`, `Vehicle`, `ProblemInstance` etc. unchanged |
| `src/scheduler/builder.py` | Unchanged — still builds the `ProblemInstance` |
| `src/scheduler/arcs.py` | Retained for now; `circuit_builder.py` may use some of its logic |
| `src/scheduler/loaders.py` | Unchanged |
| `src/scheduler/parsing.py` | Unchanged |
| `src/scheduler/geo.py` | Unchanged |

### Kept Constraints (reimplemented in circuit form)

- Constraint 1: Every job assigned to exactly one driver (via `visited` vars)
- Constraint 4: Deadhead from home (now structural — HOME→first node arc cost includes transit time)
- Constraint 5: Shift span limit (same formulation, wired to circuit's temporal vars)
- Constraint 6: TBA vehicle assignment (same `y` variables, but depot-pickup is now a circuit node)

### Removed / Superseded

- Constraint 2: No temporal overlap (superseded by circuit sequencing)
- Constraint 3: Pairwise travel (superseded by circuit arc constraints)
- The `seq_vars` disjunctive sequencing logic (no longer needed)

---

## 9. What's NOT Included

- Storage location capacity constraints (deferred until objective function is validated)
- `can_overnight` / multi-day assignment rules (deferred)
- Soft time window penalties as separate terms (the time windows remain as hard bounds for now; softening is a future tuning step)
- Geographic parking constraints for restricted postcodes (future)

---

## 10. Sequencing

This design covers two logical phases that will be implemented together:

1. **Vehicle custody state machine** — the circuit graph structure with state-legal arcs
2. **Objective function** — weighted cost minimisation (transit penalty, activation penalty, span penalty)

These must be implemented together because the circuit model without an objective would produce random feasible routes, and the objective without custody would produce the same broken schedules we have now.

---

## 11. Test Strategy

**Circuit builder tests (unit):**
- State-legal arc generation: verify no COLLECT→COLLECT or DELIVER→DELIVER arcs
- Depot dwell: verify 15 min added to depot arc travel times
- Vehicle group matching: verify COLLECT→DELIVER arcs only for compatible groups
- Certification pruning: verify arcs excluded for unqualified drivers
- Temporal pruning: verify arcs excluded when travel time exceeds window

**Solver tests (unit, synthetic instances):**
- Single driver, 1 Collect + 1 matching Deliver → chains them, cost = driving + turnaround
- Single driver, 1 Collect (no matching Deliver) → routes to depot, cost includes depot dwell
- Two Collects, no Delivers → driver must visit depot between them (no double-hold)
- Activation penalty: with enough drivers, solver prefers fewer active ones
- Shift span: driver can't take jobs that would exceed max_hours_per_day
- TBA Deliver: solver routes driver through depot pickup

**Integration test:**
- Run on full sample data (59 jobs, 20 drivers)
- Assert FEASIBLE
- Assert no driver holds two vans simultaneously (verify state machine)
- Assert solution cost < some reasonable upper bound
- Compare driver count and total cost against current solver output
