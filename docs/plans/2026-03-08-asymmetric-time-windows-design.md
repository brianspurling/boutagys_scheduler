# Asymmetric Time Windows with Piecewise Penalties

**Date:** 2026-03-08
**Status:** Approved

## Problem

The current model treats all booking times as the centre of a symmetric ±60-minute soft window. This is wrong for both job types:

- **Collect:** the booking time is the *earliest the driver can depart with the van* (customer not ready before then). There is no upper hard bound — lateness is penalised softly.
- **Deliver:** the booking time is the *latest the customer wants the van*. Early delivery on the same day is free. Late delivery incurs a steep, ramping penalty.

---

## Job Time Semantics

### COLLECT

| Zone | Constraint type | Penalty |
|---|---|---|
| Arrival before `earliest_departure_t` | Allowed (driver waits) | None |
| Departure before `earliest_departure_t` | **Hard constraint — impossible** | — |
| Departure within `[earliest_departure_t, grace_end_t]` | Soft | 0 |
| Departure within `(grace_end_t, same_day_end_t]` | Soft | `LATE_SAME_DAY_RATE` per minute |
| Departure after `same_day_end_t` | Soft | `SEVERE_NEXT_DAY_RATE` per minute (much higher) |

- `earliest_departure_t` = booking time
- `grace_end_t` = booking time + 120 min
- `same_day_end_t` = end of scheduled day (day offset * 1440 + 1439)

### DELIVER

| Zone | Constraint type | Penalty |
|---|---|---|
| Arrival on same day, before `deadline_t` | Soft | 0 |
| Arrival before `same_day_start_t` (prior day or earlier) | Soft | `EARLY_RATE` per minute (ramps per day naturally) |
| Arrival within `(deadline_t, deadline_t + 60]` | Soft | `LATE_TIER1_RATE` per minute |
| Arrival beyond `deadline_t + 60` | Soft | `LATE_TIER2_RATE` per minute (much higher) |

- `deadline_t` = booking time
- `same_day_start_t` = start of scheduled day (day offset * 1440)

---

## CP-SAT Encoding

### Arrival variable domain

All job node arrival variables widen to `[0, horizon.t_max]`. The narrow `[window_start_t, window_end_t]` domain is removed.

The `arrival_time` variable acts as **service-start time** (standard VRP pattern). Temporal propagation `arrival[head] >= arrival[tail] + travel` is unchanged.

### Hard collect constraint

```python
model.add(arrival_time[driver_id][collect_node] >= job.earliest_departure_t)
```

Unconditional. The solver absorbs wait time at the preceding node naturally — the driver can arrive early and wait; the outgoing arc chains from `earliest_departure_t` at the earliest.

### Penalty auxiliary variables

**No integer division anywhere.** All penalties are strictly linear in auxiliary variables produced by `add_max_equality`.

```python
# COLLECT
minutes_past_grace = model.new_int_var(0, t_max, f"past_grace_{job_id}")
model.add_max_equality(minutes_past_grace, [0, arrival - grace_end_t])

minutes_past_day = model.new_int_var(0, t_max, f"past_day_{job_id}")
model.add_max_equality(minutes_past_day, [0, arrival - same_day_end_t])

penalty = LATE_SAME_DAY_RATE * minutes_past_grace + SEVERE_NEXT_DAY_RATE * minutes_past_day

# DELIVER
minutes_early = model.new_int_var(0, t_max, f"early_{job_id}")
model.add_max_equality(minutes_early, [0, same_day_start_t - arrival])

minutes_late_t1 = model.new_int_var(0, 60, f"late_t1_{job_id}")
model.add_max_equality(minutes_late_t1, [0, min(arrival - deadline_t, 60)])

minutes_late_t2 = model.new_int_var(0, t_max, f"late_t2_{job_id}")
model.add_max_equality(minutes_late_t2, [0, arrival - deadline_t - 60])

penalty = (EARLY_RATE * minutes_early
         + LATE_TIER1_RATE * minutes_late_t1
         + LATE_TIER2_RATE * minutes_late_t2)
```

`EARLY_RATE` is set as a per-minute value; delivering 1 day early = `1440 * EARLY_RATE`, giving a natural per-day ramp without division.

All penalty terms are added to the existing `objective_terms` list.

---

## Penalty Constants (`penalty_config.py`)

```python
# COLLECT
LATE_SAME_DAY_RATE    = 2    # per minute after grace period
SEVERE_NEXT_DAY_RATE  = 10   # per minute past end of scheduled day (>> same-day rate)

# DELIVER
EARLY_RATE            = 1    # per minute early (1440/day ≈ "300 per day" feel)
LATE_TIER1_RATE       = 10   # per minute late, first 60 min
LATE_TIER2_RATE       = 30   # per minute late, beyond 60 min
```

All values are placeholder — the module exists so they can be tuned without touching solver logic.

---

## Files Changed

| File | Change |
|---|---|
| `models.py` | Remove `window_start_t`, `window_end_t`. Add `earliest_departure_t`, `grace_end_t`, `same_day_end_t`, `same_day_start_t`, `deadline_t` to `Job` |
| `builder.py` | Replace ±60min window calc with per-action-type field computation. Remove `_WINDOW_BEFORE/AFTER_MINUTES` |
| `penalty_config.py` | New file — all five rate constants |
| `circuit_solver.py` | Widen arrival domains; add hard collect constraint; add per-job penalty vars and objective terms; remove old `transit_minutes > window_end_t` pruning |
| `circuit_builder.py` | Update job→job temporal pruning to use new fields |
| `arcs.py` | Update `window_end_t` references in `compute_driver_job_arcs` and `compute_job_chain_arcs` |
| `tests/` | Update window-based tests; add new tests for hard constraint and each penalty tier boundary |
