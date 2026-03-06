# Data Model Design — Boutagy's Scheduler

**Date:** 2026-03-06
**Status:** Approved
**Scope:** Stage 1 Data Pipeline — the domain model that is the input to the optimiser framework

---

## Design Decisions

- **Implementation:** Pydantic `BaseModel(frozen=True)` — immutable, validated, serializable
- **Architecture:** Builder pattern — `ProblemBuilder` ingests CSVs, validates, computes arcs, produces an immutable `ProblemInstance`
- **Time representation:** Dual — human-readable `datetime` fields alongside integer-minute offsets from horizon start (for solver consumption)
- **Certification mapping:** Explicit lookup table — no prefix-guessing. Builder fails on unknown vehicle groups.
- **Arc pre-computation:** Builder pre-prunes infeasible arcs (driver→job, job→job, vehicle→job) before the solver sees them

---

## Section 1: Core Domain Objects

### Location

Represents any point on the map — customer postcodes and storage depots alike.

```python
class Location(BaseModel, frozen=True):
    postcode: str              # Normalized (e.g., "SW15 2SW")
    lat: float
    lon: float
```

### StorageLocation

```python
class StorageLocation(BaseModel, frozen=True):
    location_id: str           # "S001", "S002", "S003"
    name: str                  # "Feltham", "Putney Head Office", etc.
    location: Location
    capacity: int              # Hard limit on vehicles stored
    restricted_groups: set[str] # Vehicle groups NOT allowed (empty = all allowed)
```

### Driver

```python
class CertLevel(str, Enum):
    VAN = "van"
    VAN_TRUCK = "van_truck"

class Driver(BaseModel, frozen=True):
    driver_id: str             # "D001"
    name: str
    home_location: Location
    branch: str                # "PUTNEY" or "FELTHAM"
    max_hours_per_day: int     # In minutes (600 = 10 hours)
    certifications: CertLevel
    can_overnight: bool
    unavailable_dates: frozenset[date]
```

- `max_hours_per_day` in **minutes** (consistent with integer-minute timeline)
- `certifications` is a single enum — `VAN_TRUCK` implies van capability
- `unavailable_dates` as `frozenset` for immutability

### Vehicle

```python
class Vehicle(BaseModel, frozen=True):
    reg: str                   # "KP67 XYZ" or "" for TBA pool
    group: str                 # Normalized group code (e.g., "D.B9A")
    current_location: Location # Anywhere on the map — depot, customer site, etc.
    available_from: date
    available_from_t: int      # Minutes from horizon start (for solver)
```

- `current_location` is a full `Location`, not a storage location ID — vehicles are spatially distributed
- Dual time representation: `available_from` (human) + `available_from_t` (solver)

### Job

```python
class ActionType(str, Enum):
    COLLECT = "collect"        # Pick up van from customer
    DELIVER = "deliver"        # Drop van to customer

class Job(BaseModel, frozen=True):
    job_id: str                # Generated: "J001", "J002", etc.
    book_no: str
    order_ref: str
    rental_no: str
    book_name: str             # Customer name
    book_status: str

    action: ActionType
    scheduled_date: date
    scheduled_time: time | None
    scheduled_datetime: datetime | None
    time_offset_minutes: int | None   # Nominal time from horizon start

    window_start_t: int               # Earliest arrival (minutes from horizon start)
    window_end_t: int                 # Latest arrival (soft penalty beyond this)

    vehicle_reg: str | None           # None = TBA (solver must assign)
    vehicle_group: str                # Normalized (rightmost after ">")

    target_location: Location         # Single location where job physically happens

    notes: str                        # Raw, unparsed
```

- Single `target_location` — a COLLECT or DELIVER is one atomic task at one place
- `window_start_t` / `window_end_t` computed by the builder from scheduled time + parking rules
- `vehicle_reg` is `None` for TBA deliveries

---

## Section 2: Arc Graph and Transit Matrix

### Transit Matrix (dual-mode)

Stores both travel modes between location pairs. Sparse — only pairs that appear in feasible arcs.

```python
class TransitPair(BaseModel, frozen=True):
    transit_minutes: int       # Public transit / deadhead (includes +15% stochastic buffer)
    driving_minutes: int       # Driving the vehicle directly

class TransitMatrix(BaseModel, frozen=True):
    entries: dict[tuple[str, str], TransitPair]

    def get(self, from_loc: Location, to_loc: Location) -> TransitPair | None:
        return self.entries.get((from_loc.postcode, to_loc.postcode))
```

### Vehicle Group Certification Table

Explicit mapping — no prefix-guessing. Builder fails if a booking references an unknown group.

```python
VEHICLE_GROUP_CERTS: dict[str, CertLevel]
# e.g., {"V1": CertLevel.VAN, "C.F4": CertLevel.VAN_TRUCK, "E.A17": CertLevel.VAN_TRUCK, ...}
```

### DriverJobArc

"Can this driver reach this job on time?"

```python
class DriverJobArc(BaseModel, frozen=True):
    driver_id: str
    job_id: str
    deadhead_minutes: int      # Transit time from driver's current location to job
```

Pruned when:
- Driver lacks certification for the job's vehicle group
- Driver is unavailable on the job's scheduled date
- Deadhead time makes it impossible to arrive within the job's time window

### VehicleJobArc (asset sparsification)

"Can this vehicle serve this TBA job?" Reduces ~70,000 potential assignments to a sparse feasible set.

```python
class VehicleJobArc(BaseModel, frozen=True):
    vehicle_reg: str
    job_id: str
    driving_minutes: int       # Drive time from vehicle location to job target
```

Pruned when:
- Vehicle group doesn't match job's required vehicle group
- `available_from_t + driving_minutes > job.window_end_t` (can't arrive in time)

### JobChainArc (two chain types)

Two distinct types of job-to-job chains. No same-day pruning — continuous timeline respects `can_overnight`.

```python
class ChainType(str, Enum):
    DRIVER_ONLY = "driver_only"       # Driver abandons vehicle, takes PT to next job
    VEHICLE_DRIVER = "vehicle_driver"  # Driver drives collected vehicle to deliver job

class JobChainArc(BaseModel, frozen=True):
    from_job_id: str
    to_job_id: str
    chain_type: ChainType
    travel_minutes: int        # transit_minutes for DRIVER_ONLY, driving_minutes for VEHICLE_DRIVER
    turnaround_minutes: int    # 45 min for VEHICLE_DRIVER, 0 for DRIVER_ONLY
```

**DRIVER_ONLY** arcs:
- Any job A -> any job B where temporal math works
- Uses `transit_minutes` (deadhead)
- `turnaround_minutes = 0`

**VEHICLE_DRIVER** arcs (strict conditions):
- Job A must be COLLECT, Job B must be DELIVER
- Vehicle groups must match
- Uses `driving_minutes`
- `turnaround_minutes = 45`

**Pruning rule (both types):**
```
from_job.window_start_t + service_time + travel_minutes + turnaround_minutes > to_job.window_end_t
```

Uses `window_start_t` (best-case earliest finish) to avoid over-pruning valid soft-window shifts. Only prune when mathematically impossible.

### HorizonConfig

```python
class HorizonConfig(BaseModel, frozen=True):
    start_date: date           # Day 1 of the rolling window
    num_days: int              # Typically 4-5
    t_max: int                 # Total minutes in horizon (num_days * 1440)
```

---

## Section 3: ProblemInstance and Builder

### ProblemInstance (top-level immutable container)

```python
class ProblemInstance(BaseModel, frozen=True):
    horizon: HorizonConfig

    jobs: list[Job]
    drivers: list[Driver]
    vehicles: list[Vehicle]
    storage_locations: list[StorageLocation]

    vehicle_group_certs: dict[str, CertLevel]
    transit_matrix: TransitMatrix

    driver_job_arcs: list[DriverJobArc]
    job_chain_arcs: list[JobChainArc]
    vehicle_job_arcs: list[VehicleJobArc]
```

### ProblemBuilder (fluent API)

```python
class ProblemBuilder:
    def load_bookings(self, path: Path) -> ProblemBuilder: ...
    def load_drivers(self, path: Path) -> ProblemBuilder: ...
    def load_vehicles(self, path: Path) -> ProblemBuilder: ...
    def load_storage_locations(self, path: Path) -> ProblemBuilder: ...
    def load_transit_matrix(self, path: Path) -> ProblemBuilder: ...

    def build(self) -> BuildResult:
        # 1. Parse & validate all CSVs into domain objects
        # 2. Compute time offsets and windows
        # 3. Compute feasible arcs (driver->job, job->job, vehicle->job)
        # 4. Exclude infeasible jobs (zero arcs)
        # 5. Return frozen ProblemInstance + ValidationReport
```

### BuildResult

```python
class BuildResult(BaseModel):
    instance: ProblemInstance | None    # None if fatal errors
    report: ValidationReport

    @property
    def ok(self) -> bool:
        return self.instance is not None
```

---

## Section 4: Validation Rules

### Fail-Fast Errors (builder cannot produce a ProblemInstance)

1. **Unknown vehicle group** — booking references a group not in `VEHICLE_GROUP_CERTS`
2. **Missing target location** — job has no parseable postcode for its action type
3. **Unparseable date/time** — booking date or time cannot be parsed
4. **Duplicate job IDs** — guard against generation bugs
5. **Storage location not defined** — vehicle references unknown storage location ID

### Excluded Jobs (severity: "excluded")

Jobs with zero feasible arcs are **removed from `ProblemInstance.jobs`** to prevent the solver returning INFEASIBLE for the entire board. These are:

- Jobs with no feasible driver arcs (no driver can reach them)
- TBA jobs with no feasible vehicle arcs (no matching vehicle can arrive in time)

Logged prominently so dispatchers know which jobs need manual handling.

### Warnings (builder logs, continues)

1. **Transit data missing** — fallback to Haversine straight-line distance x conservative speed multiplier. Logged as `category="transit_fallback"`.
2. **Driver with zero feasible job arcs** — driver exists but can't reach any job.
3. **Postcode suffix stripped** — audit trail (e.g., `BH23 5LJ*PRE-DELIVERY*` -> `BH23 5LJ`).
4. **Vehicle group upgrade applied** — `>` notation resolved (e.g., `E.A17>D.B9A` -> `D.B9A`).

### ValidationReport

```python
class ValidationIssue(BaseModel, frozen=True):
    severity: Literal["error", "warning", "excluded"]
    category: str
    message: str
    source_row: int | None     # CSV row number, if applicable

class ValidationReport(BaseModel, frozen=True):
    issues: list[ValidationIssue]
    stats: dict[str, int]      # Summary: total_jobs, excluded_jobs, total_arcs, etc.

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)
```

---

## CSV Parsing Rules (from CLAUDE.md)

- Strip blank rows (visual separators, no meaning)
- Each row is an independent job — no inferred links between adjacent rows
- Strip postcode suffixes: remove everything after first space-separated postcode token
- `Supp'd Grp` with `>` notation: take rightmost value as operative vehicle group
- Job notes: store as raw string, do not parse for structured constraints
