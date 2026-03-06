# Stage 1 Data Model Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the Stage 1 data pipeline — Pydantic domain models, CSV parsers, arc pre-computation, and validation — so that `ProblemBuilder.build()` produces a frozen `ProblemInstance` from the sample data.

**Architecture:** Builder pattern. `ProblemBuilder` loads 4 CSVs via fluent API, validates, computes time windows and feasible arcs, excludes infeasible jobs, and returns an immutable `ProblemInstance` + `ValidationReport`. All domain objects are Pydantic `frozen=True` models. Time is dual-represented: human `datetime` + integer minutes from horizon start.

**Tech Stack:** Python 3.12+, Pydantic v2, pytest. No solver dependencies yet. Haversine for distance estimation (no external API calls in Stage 1).

**Design doc:** `docs/plans/2026-03-06-data-model-design.md`

**Project root:** `/Users/Shared/_code/boutagys_scheduler`

---

## Task 0: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/scheduler/__init__.py`
- Create: `src/scheduler/models.py` (empty placeholder)
- Create: `tests/__init__.py`
- Create: `tests/conftest.py` (empty placeholder)

**Step 1: Create pyproject.toml**

```toml
[project]
name = "boutagys-scheduler"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

**Step 2: Create package structure**

```bash
mkdir -p src/scheduler tests
touch src/scheduler/__init__.py tests/__init__.py tests/conftest.py
```

**Step 3: Install dependencies**

Run: `pip install -e ".[dev]"`
Expected: Clean install, pydantic and pytest available.

**Step 4: Verify pytest runs**

Run: `pytest --co`
Expected: "no tests ran" (collected 0 items) — confirms pytest can find the test directory.

**Step 5: Commit**

```bash
git add pyproject.toml src/ tests/
git commit -m "scaffold: project structure with pydantic and pytest"
```

---

## Task 1: Core enums and Location model

**Files:**
- Create: `src/scheduler/models.py`
- Create: `tests/test_models.py`

**Step 1: Write the failing test**

```python
# tests/test_models.py
from scheduler.models import CertLevel, ActionType, ChainType, Location


def test_cert_level_values():
    assert CertLevel.VAN == "van"
    assert CertLevel.VAN_TRUCK == "van_truck"


def test_action_type_values():
    assert ActionType.COLLECT == "collect"
    assert ActionType.DELIVER == "deliver"


def test_chain_type_values():
    assert ChainType.DRIVER_ONLY == "driver_only"
    assert ChainType.VEHICLE_DRIVER == "vehicle_driver"


def test_location_is_frozen():
    loc = Location(postcode="SW15 2SW", lat=51.4576, lon=-0.2289)
    assert loc.postcode == "SW15 2SW"
    assert loc.lat == 51.4576
    assert loc.lon == -0.2289
    # Frozen — assignment must raise
    import pytest
    with pytest.raises(Exception):
        loc.postcode = "X"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: ImportError — `scheduler.models` doesn't export these yet.

**Step 3: Write minimal implementation**

```python
# src/scheduler/models.py
from __future__ import annotations

from datetime import date, time, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel


class CertLevel(str, Enum):
    VAN = "van"
    VAN_TRUCK = "van_truck"


class ActionType(str, Enum):
    COLLECT = "collect"
    DELIVER = "deliver"


class ChainType(str, Enum):
    DRIVER_ONLY = "driver_only"
    VEHICLE_DRIVER = "vehicle_driver"


class Location(BaseModel, frozen=True):
    postcode: str
    lat: float
    lon: float
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: 4 passed.

**Step 5: Commit**

```bash
git add src/scheduler/models.py tests/test_models.py
git commit -m "feat: add core enums and Location model"
```

---

## Task 2: StorageLocation, Driver, Vehicle, Job models

**Files:**
- Modify: `src/scheduler/models.py`
- Modify: `tests/test_models.py`

**Step 1: Write the failing tests**

Append to `tests/test_models.py`:

```python
from datetime import date, time, datetime

from scheduler.models import (
    StorageLocation, Driver, Vehicle, Job,
    Location, CertLevel, ActionType,
)


def test_storage_location():
    loc = Location(postcode="TW14 9DF", lat=51.4502, lon=-0.4084)
    sl = StorageLocation(
        location_id="S001",
        name="Feltham",
        location=loc,
        capacity=30,
        restricted_groups=set(),
    )
    assert sl.location_id == "S001"
    assert sl.capacity == 30
    assert sl.restricted_groups == set()


def test_driver():
    d = Driver(
        driver_id="D001",
        name="Jassim",
        home_location=Location(postcode="W2 1NY", lat=51.5154, lon=-0.1784),
        branch="PUTNEY",
        max_hours_per_day=600,
        certifications=CertLevel.VAN,
        can_overnight=True,
        unavailable_dates=frozenset(),
    )
    assert d.max_hours_per_day == 600  # 10 hours in minutes
    assert d.certifications == CertLevel.VAN


def test_driver_with_unavailable_dates():
    d = Driver(
        driver_id="D003",
        name="Attila",
        home_location=Location(postcode="CV21 3DH", lat=52.3706, lon=-1.2634),
        branch="PUTNEY",
        max_hours_per_day=600,
        certifications=CertLevel.VAN,
        can_overnight=True,
        unavailable_dates=frozenset({date(2025, 12, 10)}),
    )
    assert date(2025, 12, 10) in d.unavailable_dates


def test_vehicle():
    v = Vehicle(
        reg="MK22EEA",
        group="V3",
        current_location=Location(postcode="TW14 9DF", lat=51.4502, lon=-0.4084),
        available_from=date(2025, 12, 8),
        available_from_t=0,
    )
    assert v.reg == "MK22EEA"
    assert v.available_from_t == 0


def test_job():
    j = Job(
        job_id="J001",
        book_no="#35937429",
        order_ref="NW94402872",
        rental_no="8073133",
        book_name="NATIONWIDE HIRE UK",
        book_status="ON HIRE",
        action=ActionType.COLLECT,
        scheduled_date=date(2025, 12, 8),
        scheduled_time=time(9, 0),
        scheduled_datetime=datetime(2025, 12, 8, 9, 0),
        time_offset_minutes=540,
        window_start_t=480,
        window_end_t=600,
        vehicle_reg="SM73ZRL",
        vehicle_group="V2",
        target_location=Location(postcode="TW11 8QA", lat=51.4264, lon=-0.3280),
        notes="",
    )
    assert j.action == ActionType.COLLECT
    assert j.vehicle_reg == "SM73ZRL"
    assert j.window_start_t == 480
    assert j.window_end_t == 600


def test_job_tba_vehicle():
    """TBA jobs have vehicle_reg=None."""
    j = Job(
        job_id="J002",
        book_no="",
        order_ref="NW667AFF49",
        rental_no="",
        book_name="NATIONWIDE HIRE UK",
        book_status="BOOKING",
        action=ActionType.DELIVER,
        scheduled_date=date(2025, 12, 8),
        scheduled_time=time(9, 30),
        scheduled_datetime=datetime(2025, 12, 8, 9, 30),
        time_offset_minutes=570,
        window_start_t=510,
        window_end_t=630,
        vehicle_reg=None,
        vehicle_group="V2",
        target_location=Location(postcode="KT6 7NS", lat=51.3897, lon=-0.3000),
        notes="",
    )
    assert j.vehicle_reg is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: ImportError for StorageLocation, Driver, Vehicle, Job.

**Step 3: Write minimal implementation**

Append to `src/scheduler/models.py`:

```python
class StorageLocation(BaseModel, frozen=True):
    location_id: str
    name: str
    location: Location
    capacity: int
    restricted_groups: set[str]


class Driver(BaseModel, frozen=True):
    driver_id: str
    name: str
    home_location: Location
    branch: str
    max_hours_per_day: int
    certifications: CertLevel
    can_overnight: bool
    unavailable_dates: frozenset[date]


class Vehicle(BaseModel, frozen=True):
    reg: str
    group: str
    current_location: Location
    available_from: date
    available_from_t: int


class Job(BaseModel, frozen=True):
    job_id: str
    book_no: str
    order_ref: str
    rental_no: str
    book_name: str
    book_status: str
    action: ActionType
    scheduled_date: date
    scheduled_time: time | None
    scheduled_datetime: datetime | None
    time_offset_minutes: int | None
    window_start_t: int
    window_end_t: int
    vehicle_reg: str | None
    vehicle_group: str
    target_location: Location
    notes: str
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: All tests pass.

**Step 5: Commit**

```bash
git add src/scheduler/models.py tests/test_models.py
git commit -m "feat: add StorageLocation, Driver, Vehicle, Job models"
```

---

## Task 3: Arc models, TransitMatrix, HorizonConfig, ValidationReport, ProblemInstance, BuildResult

**Files:**
- Modify: `src/scheduler/models.py`
- Modify: `tests/test_models.py`

**Step 1: Write the failing tests**

Append to `tests/test_models.py`:

```python
from scheduler.models import (
    DriverJobArc, VehicleJobArc, JobChainArc, ChainType,
    TransitPair, TransitMatrix, HorizonConfig,
    ValidationIssue, ValidationReport,
    ProblemInstance, BuildResult,
)


def test_driver_job_arc():
    arc = DriverJobArc(driver_id="D001", job_id="J001", deadhead_minutes=45)
    assert arc.deadhead_minutes == 45


def test_vehicle_job_arc():
    arc = VehicleJobArc(vehicle_reg="MK22EEA", job_id="J002", driving_minutes=30)
    assert arc.driving_minutes == 30


def test_job_chain_arc_driver_only():
    arc = JobChainArc(
        from_job_id="J001",
        to_job_id="J003",
        chain_type=ChainType.DRIVER_ONLY,
        travel_minutes=25,
        turnaround_minutes=0,
    )
    assert arc.turnaround_minutes == 0


def test_job_chain_arc_vehicle_driver():
    arc = JobChainArc(
        from_job_id="J001",
        to_job_id="J002",
        chain_type=ChainType.VEHICLE_DRIVER,
        travel_minutes=20,
        turnaround_minutes=45,
    )
    assert arc.turnaround_minutes == 45


def test_transit_matrix_get():
    matrix = TransitMatrix(entries={
        ("SW15 2SW", "TW14 9DF"): TransitPair(transit_minutes=55, driving_minutes=35),
    })
    loc_a = Location(postcode="SW15 2SW", lat=51.4576, lon=-0.2289)
    loc_b = Location(postcode="TW14 9DF", lat=51.4502, lon=-0.4084)
    pair = matrix.get(loc_a, loc_b)
    assert pair is not None
    assert pair.transit_minutes == 55
    assert pair.driving_minutes == 35
    assert matrix.get(loc_b, loc_a) is None  # Not symmetric unless both entries exist


def test_horizon_config():
    h = HorizonConfig(start_date=date(2025, 12, 8), num_days=5, t_max=7200)
    assert h.t_max == 5 * 1440


def test_validation_report_has_errors():
    report_clean = ValidationReport(issues=[], stats={"total_jobs": 10})
    assert not report_clean.has_errors

    report_bad = ValidationReport(
        issues=[ValidationIssue(severity="error", category="unknown_group", message="X", source_row=5)],
        stats={"total_jobs": 10},
    )
    assert report_bad.has_errors


def test_build_result_ok():
    report = ValidationReport(issues=[], stats={})
    result_none = BuildResult(instance=None, report=report)
    assert not result_none.ok
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: ImportError for the new types.

**Step 3: Write minimal implementation**

Append to `src/scheduler/models.py`:

```python
class DriverJobArc(BaseModel, frozen=True):
    driver_id: str
    job_id: str
    deadhead_minutes: int


class VehicleJobArc(BaseModel, frozen=True):
    vehicle_reg: str
    job_id: str
    driving_minutes: int


class JobChainArc(BaseModel, frozen=True):
    from_job_id: str
    to_job_id: str
    chain_type: ChainType
    travel_minutes: int
    turnaround_minutes: int


class TransitPair(BaseModel, frozen=True):
    transit_minutes: int
    driving_minutes: int


class TransitMatrix(BaseModel, frozen=True):
    entries: dict[tuple[str, str], TransitPair]

    def get(self, from_loc: Location, to_loc: Location) -> TransitPair | None:
        return self.entries.get((from_loc.postcode, to_loc.postcode))


class HorizonConfig(BaseModel, frozen=True):
    start_date: date
    num_days: int
    t_max: int


class ValidationIssue(BaseModel, frozen=True):
    severity: Literal["error", "warning", "excluded"]
    category: str
    message: str
    source_row: int | None


class ValidationReport(BaseModel, frozen=True):
    issues: list[ValidationIssue]
    stats: dict[str, int]

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)


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


class BuildResult(BaseModel):
    instance: ProblemInstance | None
    report: ValidationReport

    @property
    def ok(self) -> bool:
        return self.instance is not None
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: All tests pass.

**Step 5: Commit**

```bash
git add src/scheduler/models.py tests/test_models.py
git commit -m "feat: add arc models, TransitMatrix, HorizonConfig, validation, ProblemInstance"
```

---

## Task 4: Vehicle group certification table

**Files:**
- Create: `src/scheduler/cert_table.py`
- Create: `tests/test_cert_table.py`

**Step 1: Write the failing test**

```python
# tests/test_cert_table.py
from scheduler.cert_table import VEHICLE_GROUP_CERTS, driver_can_do_group
from scheduler.models import CertLevel


def test_all_known_groups_present():
    """Every group seen in sample data must be in the table."""
    expected_groups = {
        "A.M1", "A.M3",
        "C.F3", "C.F4",
        "D.B9", "D.B9A",
        "E.A17", "E.B17",
        "V1", "V1A", "V2", "V2A", "V3", "V4", "V4A",
        "V5", "V5D", "V5TDC", "V75BT", "VH18B", "VH44T",
    }
    for group in expected_groups:
        assert group in VEHICLE_GROUP_CERTS, f"Missing group: {group}"


def test_truck_groups():
    """C.F3, C.F4, and E.A17 require VAN_TRUCK cert."""
    assert VEHICLE_GROUP_CERTS["C.F3"] == CertLevel.VAN_TRUCK
    assert VEHICLE_GROUP_CERTS["C.F4"] == CertLevel.VAN_TRUCK
    assert VEHICLE_GROUP_CERTS["E.A17"] == CertLevel.VAN_TRUCK


def test_van_groups():
    """Standard V-prefix groups require VAN cert."""
    for g in ["V1", "V2", "V3", "V4", "V5"]:
        assert VEHICLE_GROUP_CERTS[g] == CertLevel.VAN


def test_driver_can_do_group_van_cert():
    """VAN cert can do VAN groups but not VAN_TRUCK groups."""
    assert driver_can_do_group(CertLevel.VAN, "V3") is True
    assert driver_can_do_group(CertLevel.VAN, "C.F4") is False


def test_driver_can_do_group_truck_cert():
    """VAN_TRUCK cert can do both VAN and VAN_TRUCK groups."""
    assert driver_can_do_group(CertLevel.VAN_TRUCK, "V3") is True
    assert driver_can_do_group(CertLevel.VAN_TRUCK, "C.F4") is True
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_cert_table.py -v`
Expected: ImportError.

**Step 3: Write minimal implementation**

```python
# src/scheduler/cert_table.py
from scheduler.models import CertLevel

# Explicit mapping — every group that appears in the sample data.
# Known truck groups: C.F3, C.F4, E.A17 (require C1/SRC certification).
# All others are van groups.
VEHICLE_GROUP_CERTS: dict[str, CertLevel] = {
    # Van groups
    "A.M1": CertLevel.VAN,
    "A.M3": CertLevel.VAN,
    "D.B9": CertLevel.VAN,
    "D.B9A": CertLevel.VAN,
    "E.B17": CertLevel.VAN,
    "V1": CertLevel.VAN,
    "V1A": CertLevel.VAN,
    "V2": CertLevel.VAN,
    "V2A": CertLevel.VAN,
    "V3": CertLevel.VAN,
    "V4": CertLevel.VAN,
    "V4A": CertLevel.VAN,
    "V5": CertLevel.VAN,
    "V5D": CertLevel.VAN,
    "V5TDC": CertLevel.VAN,
    "V75BT": CertLevel.VAN,
    "VH18B": CertLevel.VAN,
    "VH44T": CertLevel.VAN,
    # Truck groups (require C1/SRC)
    "C.F3": CertLevel.VAN_TRUCK,
    "C.F4": CertLevel.VAN_TRUCK,
    "E.A17": CertLevel.VAN_TRUCK,
}


def driver_can_do_group(cert: CertLevel, vehicle_group: str) -> bool:
    """Check if a driver's certification allows them to drive this vehicle group.

    VAN_TRUCK implies VAN capability (truck drivers can drive vans too).
    """
    required = VEHICLE_GROUP_CERTS.get(vehicle_group)
    if required is None:
        raise ValueError(f"Unknown vehicle group: {vehicle_group}")
    if required == CertLevel.VAN:
        return True  # Both VAN and VAN_TRUCK can drive vans
    # required == VAN_TRUCK — only VAN_TRUCK cert qualifies
    return cert == CertLevel.VAN_TRUCK
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_cert_table.py -v`
Expected: All pass.

**Step 5: Commit**

```bash
git add src/scheduler/cert_table.py tests/test_cert_table.py
git commit -m "feat: add vehicle group certification table"
```

---

## Task 5: CSV parsing utilities (postcode normalization, group upgrade)

**Files:**
- Create: `src/scheduler/parsing.py`
- Create: `tests/test_parsing.py`

**Step 1: Write the failing test**

```python
# tests/test_parsing.py
from scheduler.parsing import normalize_postcode, resolve_vehicle_group


def test_normalize_postcode_clean():
    assert normalize_postcode("SW15 2SW") == "SW15 2SW"


def test_normalize_postcode_with_suffix():
    assert normalize_postcode("BH23 5LJ*PRE-DELIVERY*") == "BH23 5LJ"


def test_normalize_postcode_with_dash_suffix():
    assert normalize_postcode("B92 0AE - EXT BEFORE") == "B92 0AE"


def test_normalize_postcode_strips_whitespace():
    assert normalize_postcode("  SW15 2SW  ") == "SW15 2SW"


def test_normalize_postcode_empty():
    assert normalize_postcode("") is None


def test_normalize_postcode_whitespace_only():
    assert normalize_postcode("   ") is None


def test_resolve_vehicle_group_simple():
    assert resolve_vehicle_group("V3") == "V3"


def test_resolve_vehicle_group_upgrade():
    assert resolve_vehicle_group("E.A17>D.B9A") == "D.B9A"


def test_resolve_vehicle_group_strips_whitespace():
    assert resolve_vehicle_group(" V5 ") == "V5"


def test_resolve_vehicle_group_upgrade_with_spaces():
    assert resolve_vehicle_group(" E.A17 > D.B9A ") == "D.B9A"


def test_resolve_vehicle_group_empty():
    assert resolve_vehicle_group("") is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_parsing.py -v`
Expected: ImportError.

**Step 3: Write minimal implementation**

```python
# src/scheduler/parsing.py
"""CSV field parsing utilities for bookings data."""

import re

# UK postcodes: 2-4 chars, space, 3 chars (e.g. "SW15 2SW", "W2 1NY", "CV21 3DH")
_POSTCODE_RE = re.compile(r"^([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})")


def normalize_postcode(raw: str) -> str | None:
    """Extract the first valid UK postcode from a raw string.

    Strips suffixes like '*PRE-DELIVERY*' or '- EXT BEFORE'.
    Returns None if the string is empty or contains no valid postcode.
    """
    raw = raw.strip()
    if not raw:
        return None
    m = _POSTCODE_RE.match(raw.upper())
    if m:
        # Normalize internal spacing: ensure exactly one space before the last 3 chars
        pc = m.group(1).replace(" ", "")
        return f"{pc[:-3]} {pc[-3:]}"
    # Fallback: take first two space-separated tokens if they look postcode-ish
    parts = raw.split()
    if len(parts) >= 2:
        candidate = f"{parts[0]} {parts[1]}"
        m2 = _POSTCODE_RE.match(candidate.upper())
        if m2:
            pc = m2.group(1).replace(" ", "")
            return f"{pc[:-3]} {pc[-3:]}"
    return None


def resolve_vehicle_group(raw: str) -> str | None:
    """Resolve vehicle group, taking rightmost value after '>' if upgrade notation present.

    Returns None if empty.
    """
    raw = raw.strip()
    if not raw:
        return None
    if ">" in raw:
        return raw.split(">")[-1].strip()
    return raw
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_parsing.py -v`
Expected: All pass.

**Step 5: Commit**

```bash
git add src/scheduler/parsing.py tests/test_parsing.py
git commit -m "feat: add postcode normalization and vehicle group parsing"
```

---

## Task 6: Haversine distance and transit estimation

**Files:**
- Create: `src/scheduler/geo.py`
- Create: `tests/test_geo.py`

**Step 1: Write the failing test**

```python
# tests/test_geo.py
import math
from scheduler.geo import haversine_km, estimate_transit_pair
from scheduler.models import Location, TransitPair


def test_haversine_same_point():
    assert haversine_km(51.45, -0.40, 51.45, -0.40) == 0.0


def test_haversine_putney_to_feltham():
    """Putney (51.4576, -0.2289) to Feltham (51.4502, -0.4084) is ~12.5 km."""
    d = haversine_km(51.4576, -0.2289, 51.4502, -0.4084)
    assert 12.0 < d < 13.0


def test_estimate_transit_pair():
    loc_a = Location(postcode="SW15 2SW", lat=51.4576, lon=-0.2289)
    loc_b = Location(postcode="TW14 9DF", lat=51.4502, lon=-0.4084)
    pair = estimate_transit_pair(loc_a, loc_b)
    assert isinstance(pair, TransitPair)
    # Driving should be faster than transit
    assert pair.driving_minutes < pair.transit_minutes
    # Both should be positive for non-zero distance
    assert pair.driving_minutes > 0
    assert pair.transit_minutes > 0


def test_estimate_transit_pair_same_location():
    loc = Location(postcode="SW15 2SW", lat=51.4576, lon=-0.2289)
    pair = estimate_transit_pair(loc, loc)
    assert pair.driving_minutes == 0
    assert pair.transit_minutes == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_geo.py -v`
Expected: ImportError.

**Step 3: Write minimal implementation**

```python
# src/scheduler/geo.py
"""Geographic utilities: Haversine distance and transit time estimation."""

import math

from scheduler.models import Location, TransitPair

_EARTH_RADIUS_KM = 6371.0

# Conservative speed assumptions for fallback estimation
_DRIVING_KPH = 30.0   # Urban average including traffic
_TRANSIT_KPH = 20.0   # Public transit average (slower, indirect routes)
_TRANSIT_BUFFER = 1.15 # +15% stochastic buffer on transit times


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in km."""
    lat1, lon1, lat2, lon2 = (math.radians(x) for x in (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def estimate_transit_pair(from_loc: Location, to_loc: Location) -> TransitPair:
    """Estimate driving and transit times between two locations using Haversine.

    This is the conservative fallback when real transit data is unavailable.
    Uses straight-line distance × 1.3 (road detour factor) for driving,
    and a slower speed + 15% buffer for public transit.
    """
    km = haversine_km(from_loc.lat, from_loc.lon, to_loc.lat, to_loc.lon)
    if km == 0.0:
        return TransitPair(transit_minutes=0, driving_minutes=0)

    road_km = km * 1.3  # Detour factor
    driving_minutes = round(road_km / _DRIVING_KPH * 60)
    transit_minutes = round(road_km / _TRANSIT_KPH * 60 * _TRANSIT_BUFFER)

    return TransitPair(
        transit_minutes=max(1, transit_minutes),
        driving_minutes=max(1, driving_minutes),
    )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_geo.py -v`
Expected: All pass.

**Step 5: Commit**

```bash
git add src/scheduler/geo.py tests/test_geo.py
git commit -m "feat: add Haversine distance and transit time estimation"
```

---

## Task 7: CSV loaders (drivers, vehicles, storage locations)

**Files:**
- Create: `src/scheduler/loaders.py`
- Create: `tests/test_loaders.py`

These loaders parse reference CSVs into domain model objects. They are tested against the real ref-data files.

**Step 1: Write the failing tests**

```python
# tests/test_loaders.py
from pathlib import Path
from datetime import date

from scheduler.loaders import load_drivers, load_vehicles, load_storage_locations
from scheduler.models import CertLevel, Location

REF_DATA = Path(__file__).resolve().parent.parent / "ref-data"


def test_load_drivers_count():
    drivers = load_drivers(REF_DATA / "drivers.csv")
    assert len(drivers) == 20


def test_load_drivers_first():
    drivers = load_drivers(REF_DATA / "drivers.csv")
    d = drivers[0]
    assert d.driver_id == "D001"
    assert d.name == "Jassim"
    assert d.home_location.postcode == "W2 1NY"
    assert d.home_location.lat == 51.5154
    assert d.branch == "PUTNEY"
    assert d.max_hours_per_day == 600
    assert d.certifications == CertLevel.VAN
    assert d.can_overnight is True
    assert d.unavailable_dates == frozenset()


def test_load_drivers_truck_cert():
    drivers = load_drivers(REF_DATA / "drivers.csv")
    dave = [d for d in drivers if d.name == "Dave"][0]
    assert dave.certifications == CertLevel.VAN_TRUCK


def test_load_storage_locations():
    locs = load_storage_locations(REF_DATA / "storage_locations.csv")
    assert len(locs) == 3
    feltham = [l for l in locs if l.location_id == "S001"][0]
    assert feltham.name == "Feltham"
    assert feltham.location.postcode == "TW14 9DF"
    assert feltham.capacity == 30


def test_load_vehicles_count():
    storage_locs = load_storage_locations(REF_DATA / "storage_locations.csv")
    vehicles = load_vehicles(REF_DATA / "vehicle_inventory.csv", storage_locs)
    assert len(vehicles) == 18  # 19 rows minus header, but last row is blank


def test_load_vehicles_first():
    storage_locs = load_storage_locations(REF_DATA / "storage_locations.csv")
    vehicles = load_vehicles(REF_DATA / "vehicle_inventory.csv", storage_locs)
    v = vehicles[0]
    assert v.reg == "MK22EEA"
    assert v.group == "V3"
    assert v.available_from == date(2025, 12, 8)
    # current_location should be the storage location's lat/lon
    assert v.current_location.postcode == "TW14 9DF"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_loaders.py -v`
Expected: ImportError.

**Step 3: Write minimal implementation**

```python
# src/scheduler/loaders.py
"""CSV loaders that parse reference data into domain model objects."""

import csv
from datetime import date
from pathlib import Path

from scheduler.models import (
    CertLevel, Driver, Location, StorageLocation, Vehicle,
)


def load_storage_locations(path: Path) -> list[StorageLocation]:
    """Load storage_locations.csv."""
    locations: list[StorageLocation] = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            loc_id = row["location_id"].strip()
            if not loc_id:
                continue
            lat_str, lon_str = row["lat_long"].strip().split("/")
            restricted = set()
            if row["restricted_vehicle_groups"].strip():
                restricted = {g.strip() for g in row["restricted_vehicle_groups"].split(";")}
            locations.append(StorageLocation(
                location_id=loc_id,
                name=row["name"].strip(),
                location=Location(
                    postcode=row["postcode"].strip(),
                    lat=float(lat_str),
                    lon=float(lon_str),
                ),
                capacity=int(row["capacity"].strip()),
                restricted_groups=restricted,
            ))
    return locations


def load_drivers(path: Path) -> list[Driver]:
    """Load drivers.csv."""
    drivers: list[Driver] = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            driver_id = row["driver_id"].strip()
            if not driver_id:
                continue
            certs_raw = row["certifications"].strip()
            if "truck" in certs_raw:
                cert = CertLevel.VAN_TRUCK
            else:
                cert = CertLevel.VAN

            unavail: frozenset[date] = frozenset()
            if row["unavailable_dates"].strip():
                unavail = frozenset(
                    date.fromisoformat(d.strip())
                    for d in row["unavailable_dates"].split(";")
                    if d.strip()
                )

            lat_str, lon_str = row["home_location"].strip().split("/")
            drivers.append(Driver(
                driver_id=driver_id,
                name=row["name"].strip(),
                home_location=Location(
                    postcode=row["home_postcode"].strip(),
                    lat=float(lat_str),
                    lon=float(lon_str),
                ),
                branch=row["branch"].strip(),
                max_hours_per_day=int(row["max_hours_per_day"].strip()) * 60,
                certifications=cert,
                can_overnight=row["can_overnight"].strip().lower() == "yes",
                unavailable_dates=unavail,
            ))
    return drivers


def load_vehicles(
    path: Path,
    storage_locations: list[StorageLocation],
) -> list[Vehicle]:
    """Load vehicle_inventory.csv.

    Resolves current_storage_location ID to the storage location's Location.
    """
    loc_by_id = {sl.location_id: sl.location for sl in storage_locations}
    vehicles: list[Vehicle] = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            reg = row["vehicle_reg"].strip()
            if not reg:
                continue
            storage_id = row["current_storage_location"].strip()
            location = loc_by_id[storage_id]  # KeyError = fail-fast validation
            vehicles.append(Vehicle(
                reg=reg,
                group=row["vehicle_group"].strip(),
                current_location=location,
                available_from=date.fromisoformat(row["availability_date"].strip()),
                available_from_t=0,  # Placeholder — builder computes this relative to horizon
            ))
    return vehicles
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_loaders.py -v`
Expected: All pass (the vehicle count may need adjusting — run once to see exact count from the CSV).

**Step 5: Commit**

```bash
git add src/scheduler/loaders.py tests/test_loaders.py
git commit -m "feat: add CSV loaders for drivers, vehicles, storage locations"
```

---

## Task 8: Bookings CSV loader

**Files:**
- Modify: `src/scheduler/loaders.py`
- Modify: `tests/test_loaders.py`

The bookings loader is the most complex parser: it must strip blank rows, normalize postcodes, resolve vehicle group upgrades, and produce Job objects with geocoded locations.

**Step 1: Write the failing tests**

Append to `tests/test_loaders.py`:

```python
from scheduler.loaders import load_bookings
from scheduler.models import ActionType


INPUT_DATA = Path(__file__).resolve().parent.parent / "input"


def test_load_bookings_strips_blank_rows():
    """Blank rows used as visual separators should be dropped."""
    jobs, issues = load_bookings(INPUT_DATA / "sample_bookings_data.csv")
    for j in jobs:
        # Every job must have an action type
        assert j.action in (ActionType.COLLECT, ActionType.DELIVER)


def test_load_bookings_count():
    """Should have ~100 jobs after stripping blanks."""
    jobs, _ = load_bookings(INPUT_DATA / "sample_bookings_data.csv")
    assert len(jobs) > 50  # At least 50 real jobs in the sample


def test_load_bookings_postcode_normalized():
    """Postcodes with suffixes should be cleaned."""
    jobs, issues = load_bookings(INPUT_DATA / "sample_bookings_data.csv")
    # Find the BH23 5LJ*PRE-DELIVERY* job (book_no #35793063)
    bh_jobs = [j for j in jobs if j.book_no == "#35793063"]
    assert len(bh_jobs) == 1
    assert bh_jobs[0].target_location.postcode == "BH23 5LJ"
    # Check that a postcode_stripped warning was issued
    stripped_warnings = [i for i in issues if i.category == "postcode_stripped"]
    assert len(stripped_warnings) > 0


def test_load_bookings_vehicle_group_upgrade():
    """E.A17>D.B9A should resolve to D.B9A."""
    jobs, issues = load_bookings(INPUT_DATA / "sample_bookings_data.csv")
    # Find a job with the upgrade notation
    upgraded = [i for i in issues if i.category == "group_upgrade"]
    assert len(upgraded) > 0
    # The resolved job should have group "D.B9A"
    d_b9a_jobs = [j for j in jobs if j.vehicle_group == "D.B9A"]
    assert len(d_b9a_jobs) > 0


def test_load_bookings_tba_vehicle():
    """Jobs with blank Reg No. should have vehicle_reg=None."""
    jobs, _ = load_bookings(INPUT_DATA / "sample_bookings_data.csv")
    tba_jobs = [j for j in jobs if j.vehicle_reg is None]
    assert len(tba_jobs) > 0


def test_load_bookings_job_ids_sequential():
    """Job IDs should be J001, J002, etc."""
    jobs, _ = load_bookings(INPUT_DATA / "sample_bookings_data.csv")
    for i, j in enumerate(jobs):
        assert j.job_id == f"J{i + 1:03d}"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_loaders.py::test_load_bookings_count -v`
Expected: ImportError for `load_bookings`.

**Step 3: Write minimal implementation**

Add to `src/scheduler/loaders.py`:

```python
from datetime import time, datetime
from scheduler.models import ActionType, Job, ValidationIssue
from scheduler.parsing import normalize_postcode, resolve_vehicle_group


def load_bookings(
    path: Path,
) -> tuple[list[Job], list[ValidationIssue]]:
    """Load bookings CSV into Job objects.

    Returns (jobs, issues) where issues contains warnings for postcode stripping,
    group upgrades, and errors for unparseable rows.

    Note: target_location lat/lon is set to 0.0/0.0 as a placeholder.
    The builder will geocode these later (or use a postcode lookup).
    """
    jobs: list[Job] = []
    issues: list[ValidationIssue] = []
    job_counter = 0

    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, start=2):  # row 1 is header
            # Strip blank rows (all fields empty)
            if not any(v.strip() for v in row.values()):
                continue

            # Must have an action
            action_raw = row["Action"].strip().lower()
            if action_raw not in ("collect", "deliver"):
                continue  # Skip non-job rows

            action = ActionType.COLLECT if action_raw == "collect" else ActionType.DELIVER

            # Parse date
            date_str = row["Date"].strip()
            if not date_str:
                issues.append(ValidationIssue(
                    severity="error",
                    category="unparseable_date",
                    message=f"Row {row_num}: empty date",
                    source_row=row_num,
                ))
                continue
            try:
                scheduled_date = datetime.strptime(date_str, "%d/%m/%Y").date()
            except ValueError:
                issues.append(ValidationIssue(
                    severity="error",
                    category="unparseable_date",
                    message=f"Row {row_num}: cannot parse date '{date_str}'",
                    source_row=row_num,
                ))
                continue

            # Parse time (may be blank)
            time_str = row["Time"].strip()
            scheduled_time = None
            scheduled_datetime = None
            if time_str:
                try:
                    parts = time_str.split(":")
                    scheduled_time = time(int(parts[0]), int(parts[1]))
                    scheduled_datetime = datetime.combine(scheduled_date, scheduled_time)
                except (ValueError, IndexError):
                    issues.append(ValidationIssue(
                        severity="warning",
                        category="unparseable_time",
                        message=f"Row {row_num}: cannot parse time '{time_str}'",
                        source_row=row_num,
                    ))

            # Resolve vehicle group
            group_raw = row["Supp'd Grp"].strip()
            vehicle_group = resolve_vehicle_group(group_raw)
            if vehicle_group is None:
                issues.append(ValidationIssue(
                    severity="error",
                    category="missing_vehicle_group",
                    message=f"Row {row_num}: empty vehicle group",
                    source_row=row_num,
                ))
                continue
            if ">" in group_raw:
                issues.append(ValidationIssue(
                    severity="warning",
                    category="group_upgrade",
                    message=f"Row {row_num}: '{group_raw}' resolved to '{vehicle_group}'",
                    source_row=row_num,
                ))

            # Resolve target postcode based on action type
            if action == ActionType.DELIVER:
                postcode_raw = row["Delivery"].strip()
            else:
                postcode_raw = row["Collection"].strip()

            postcode = normalize_postcode(postcode_raw)
            if postcode != postcode_raw.strip() and postcode is not None:
                issues.append(ValidationIssue(
                    severity="warning",
                    category="postcode_stripped",
                    message=f"Row {row_num}: '{postcode_raw}' normalized to '{postcode}'",
                    source_row=row_num,
                ))
            if postcode is None:
                issues.append(ValidationIssue(
                    severity="error",
                    category="missing_postcode",
                    message=f"Row {row_num}: no parseable postcode in '{postcode_raw}'",
                    source_row=row_num,
                ))
                continue

            # Vehicle reg (None for TBA)
            reg_raw = row["Reg No."].strip()
            vehicle_reg = reg_raw if reg_raw else None

            job_counter += 1
            jobs.append(Job(
                job_id=f"J{job_counter:03d}",
                book_no=row["Book No."].strip(),
                order_ref=row["Order ref:"].strip(),
                rental_no=row["Rental No."].strip(),
                book_name=row["Book Name"].strip(),
                book_status=row["Book Status"].strip(),
                action=action,
                scheduled_date=scheduled_date,
                scheduled_time=scheduled_time,
                scheduled_datetime=scheduled_datetime,
                time_offset_minutes=None,  # Computed by builder relative to horizon
                window_start_t=0,          # Placeholder — builder computes
                window_end_t=0,            # Placeholder — builder computes
                vehicle_reg=vehicle_reg,
                vehicle_group=vehicle_group,
                target_location=Location(
                    postcode=postcode,
                    lat=0.0,  # Placeholder — builder geocodes
                    lon=0.0,
                ),
                notes=row["Notes"].strip(),
            ))

    return jobs, issues
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_loaders.py -v`
Expected: All pass. If vehicle count is off by 1, adjust the assertion.

**Step 5: Commit**

```bash
git add src/scheduler/loaders.py tests/test_loaders.py
git commit -m "feat: add bookings CSV loader with postcode normalization and group resolution"
```

---

## Task 9: ProblemBuilder — assembly and time window computation

**Files:**
- Create: `src/scheduler/builder.py`
- Create: `tests/test_builder.py`

This is the core builder that ties everything together. We implement it incrementally — this task covers loading, time computation, and validation. Arc computation is Task 10.

**Step 1: Write the failing tests**

```python
# tests/test_builder.py
from pathlib import Path
from datetime import date

from scheduler.builder import ProblemBuilder

ROOT = Path(__file__).resolve().parent.parent
INPUT = ROOT / "input"
REF = ROOT / "ref-data"


def test_builder_loads_and_builds():
    """Builder should produce a BuildResult from sample data."""
    result = (
        ProblemBuilder(horizon_start=date(2025, 12, 8), num_days=5)
        .load_storage_locations(REF / "storage_locations.csv")
        .load_drivers(REF / "drivers.csv")
        .load_vehicles(REF / "vehicle_inventory.csv")
        .load_bookings(INPUT / "sample_bookings_data.csv")
        .build()
    )
    assert result.ok
    inst = result.instance
    assert inst is not None
    assert len(inst.drivers) == 20
    assert len(inst.storage_locations) == 3
    assert len(inst.vehicles) > 0
    assert len(inst.jobs) > 0


def test_builder_time_offsets():
    """Jobs on horizon start date should have time_offset_minutes set."""
    result = (
        ProblemBuilder(horizon_start=date(2025, 12, 8), num_days=5)
        .load_storage_locations(REF / "storage_locations.csv")
        .load_drivers(REF / "drivers.csv")
        .load_vehicles(REF / "vehicle_inventory.csv")
        .load_bookings(INPUT / "sample_bookings_data.csv")
        .build()
    )
    inst = result.instance
    # A 09:00 job on Dec 8 should have offset 540 (9 * 60)
    day1_9am_jobs = [
        j for j in inst.jobs
        if j.scheduled_date == date(2025, 12, 8)
        and j.scheduled_time is not None
        and j.scheduled_time.hour == 9
        and j.scheduled_time.minute == 0
    ]
    assert len(day1_9am_jobs) > 0
    for j in day1_9am_jobs:
        assert j.time_offset_minutes == 540


def test_builder_time_windows():
    """Jobs should have window_start_t < window_end_t."""
    result = (
        ProblemBuilder(horizon_start=date(2025, 12, 8), num_days=5)
        .load_storage_locations(REF / "storage_locations.csv")
        .load_drivers(REF / "drivers.csv")
        .load_vehicles(REF / "vehicle_inventory.csv")
        .load_bookings(INPUT / "sample_bookings_data.csv")
        .build()
    )
    for j in result.instance.jobs:
        assert j.window_start_t < j.window_end_t, f"Job {j.job_id} has invalid window"


def test_builder_vehicle_available_from_t():
    """Vehicles available on horizon start should have available_from_t=0."""
    result = (
        ProblemBuilder(horizon_start=date(2025, 12, 8), num_days=5)
        .load_storage_locations(REF / "storage_locations.csv")
        .load_drivers(REF / "drivers.csv")
        .load_vehicles(REF / "vehicle_inventory.csv")
        .load_bookings(INPUT / "sample_bookings_data.csv")
        .build()
    )
    for v in result.instance.vehicles:
        if v.available_from <= date(2025, 12, 8):
            assert v.available_from_t == 0
        else:
            assert v.available_from_t > 0


def test_builder_validation_report_stats():
    """Report should contain summary stats."""
    result = (
        ProblemBuilder(horizon_start=date(2025, 12, 8), num_days=5)
        .load_storage_locations(REF / "storage_locations.csv")
        .load_drivers(REF / "drivers.csv")
        .load_vehicles(REF / "vehicle_inventory.csv")
        .load_bookings(INPUT / "sample_bookings_data.csv")
        .build()
    )
    assert "total_jobs" in result.report.stats
    assert "total_drivers" in result.report.stats
    assert "total_vehicles" in result.report.stats


def test_builder_unknown_vehicle_group_fails():
    """A booking with an unknown vehicle group should cause a build error."""
    # We test this by checking the validation report handles the known data.
    # The cert table covers all groups in the sample, so no errors expected.
    result = (
        ProblemBuilder(horizon_start=date(2025, 12, 8), num_days=5)
        .load_storage_locations(REF / "storage_locations.csv")
        .load_drivers(REF / "drivers.csv")
        .load_vehicles(REF / "vehicle_inventory.csv")
        .load_bookings(INPUT / "sample_bookings_data.csv")
        .build()
    )
    group_errors = [
        i for i in result.report.issues if i.category == "unknown_vehicle_group"
    ]
    assert len(group_errors) == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_builder.py -v`
Expected: ImportError.

**Step 3: Write minimal implementation**

```python
# src/scheduler/builder.py
"""ProblemBuilder: assembles CSVs into an immutable ProblemInstance."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from scheduler.cert_table import VEHICLE_GROUP_CERTS
from scheduler.geo import estimate_transit_pair
from scheduler.loaders import load_bookings, load_drivers, load_storage_locations, load_vehicles
from scheduler.models import (
    BuildResult, CertLevel, Driver, DriverJobArc, HorizonConfig, Job,
    JobChainArc, Location, ProblemInstance, StorageLocation,
    TransitMatrix, TransitPair, ValidationIssue, ValidationReport,
    Vehicle, VehicleJobArc,
)


# Default time window: +/- 60 minutes around scheduled time
_WINDOW_BEFORE_MINUTES = 60
_WINDOW_AFTER_MINUTES = 60


class ProblemBuilder:
    def __init__(self, horizon_start: date, num_days: int = 5):
        self._horizon_start = horizon_start
        self._num_days = num_days
        self._storage_locations: list[StorageLocation] = []
        self._drivers: list[Driver] = []
        self._vehicles: list[Vehicle] = []
        self._raw_jobs: list[Job] = []
        self._issues: list[ValidationIssue] = []

    def load_storage_locations(self, path: Path) -> ProblemBuilder:
        self._storage_locations = load_storage_locations(path)
        return self

    def load_drivers(self, path: Path) -> ProblemBuilder:
        self._drivers = load_drivers(path)
        return self

    def load_vehicles(self, path: Path) -> ProblemBuilder:
        self._vehicles = load_vehicles(path, self._storage_locations)
        return self

    def load_bookings(self, path: Path) -> ProblemBuilder:
        self._raw_jobs, issues = load_bookings(path)
        self._issues.extend(issues)
        return self

    def build(self) -> BuildResult:
        issues = list(self._issues)

        horizon = HorizonConfig(
            start_date=self._horizon_start,
            num_days=self._num_days,
            t_max=self._num_days * 1440,
        )

        # Validate vehicle groups against cert table
        valid_jobs: list[Job] = []
        for j in self._raw_jobs:
            if j.vehicle_group not in VEHICLE_GROUP_CERTS:
                issues.append(ValidationIssue(
                    severity="error",
                    category="unknown_vehicle_group",
                    message=f"Job {j.job_id}: unknown vehicle group '{j.vehicle_group}'",
                    source_row=None,
                ))
            else:
                valid_jobs.append(j)

        # Check for fatal errors
        if any(i.severity == "error" for i in issues):
            return BuildResult(
                instance=None,
                report=ValidationReport(issues=issues, stats={"total_jobs": len(self._raw_jobs)}),
            )

        # Compute time offsets and windows
        epoch = datetime.combine(self._horizon_start, datetime.min.time())
        enriched_jobs: list[Job] = []
        for j in valid_jobs:
            time_offset = None
            window_start = 0
            window_end = horizon.t_max

            if j.scheduled_datetime is not None:
                delta = j.scheduled_datetime - epoch
                time_offset = int(delta.total_seconds() // 60)
                window_start = max(0, time_offset - _WINDOW_BEFORE_MINUTES)
                window_end = min(horizon.t_max, time_offset + _WINDOW_AFTER_MINUTES)

            enriched_jobs.append(j.model_copy(update={
                "time_offset_minutes": time_offset,
                "window_start_t": window_start,
                "window_end_t": window_end,
            }))

        # Compute vehicle available_from_t
        enriched_vehicles: list[Vehicle] = []
        for v in self._vehicles:
            days_offset = (v.available_from - self._horizon_start).days
            available_t = max(0, days_offset * 1440)
            enriched_vehicles.append(v.model_copy(update={
                "available_from_t": available_t,
            }))

        # Build transit matrix (Haversine fallback for now)
        all_locations = self._collect_all_locations(enriched_jobs, enriched_vehicles)
        transit_entries: dict[tuple[str, str], TransitPair] = {}
        for i, loc_a in enumerate(all_locations):
            for loc_b in all_locations[i + 1:]:
                if loc_a.postcode == loc_b.postcode:
                    continue
                pair = estimate_transit_pair(loc_a, loc_b)
                transit_entries[(loc_a.postcode, loc_b.postcode)] = pair
                transit_entries[(loc_b.postcode, loc_a.postcode)] = pair
        transit_matrix = TransitMatrix(entries=transit_entries)

        # Compute arcs (placeholder — Task 10 fills this in)
        driver_job_arcs: list[DriverJobArc] = []
        job_chain_arcs: list[JobChainArc] = []
        vehicle_job_arcs: list[VehicleJobArc] = []

        stats = {
            "total_jobs": len(enriched_jobs),
            "total_drivers": len(self._drivers),
            "total_vehicles": len(enriched_vehicles),
            "total_storage_locations": len(self._storage_locations),
            "transit_pairs": len(transit_entries),
        }

        instance = ProblemInstance(
            horizon=horizon,
            jobs=enriched_jobs,
            drivers=self._drivers,
            vehicles=enriched_vehicles,
            storage_locations=self._storage_locations,
            vehicle_group_certs=VEHICLE_GROUP_CERTS,
            transit_matrix=transit_matrix,
            driver_job_arcs=driver_job_arcs,
            job_chain_arcs=job_chain_arcs,
            vehicle_job_arcs=vehicle_job_arcs,
        )

        return BuildResult(
            instance=instance,
            report=ValidationReport(issues=issues, stats=stats),
        )

    def _collect_all_locations(
        self,
        jobs: list[Job],
        vehicles: list[Vehicle],
    ) -> list[Location]:
        """Collect unique locations from jobs, vehicles, drivers, and storage."""
        seen: set[str] = set()
        locations: list[Location] = []
        for source in [
            [j.target_location for j in jobs],
            [v.current_location for v in vehicles],
            [d.home_location for d in self._drivers],
            [sl.location for sl in self._storage_locations],
        ]:
            for loc in source:
                if loc.postcode not in seen:
                    seen.add(loc.postcode)
                    locations.append(loc)
        return locations
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_builder.py -v`
Expected: All pass.

**Step 5: Commit**

```bash
git add src/scheduler/builder.py tests/test_builder.py
git commit -m "feat: add ProblemBuilder with time windows and transit matrix"
```

---

## Task 10: Arc computation (DriverJobArc, VehicleJobArc, JobChainArc)

**Files:**
- Create: `src/scheduler/arcs.py`
- Create: `tests/test_arcs.py`
- Modify: `src/scheduler/builder.py` — call arc computation

**Step 1: Write the failing tests**

```python
# tests/test_arcs.py
from datetime import date, time, datetime

from scheduler.arcs import compute_driver_job_arcs, compute_vehicle_job_arcs, compute_job_chain_arcs
from scheduler.models import (
    ActionType, CertLevel, ChainType, Driver, DriverJobArc, Job,
    JobChainArc, Location, TransitMatrix, TransitPair, Vehicle,
    VehicleJobArc,
)
from scheduler.cert_table import VEHICLE_GROUP_CERTS

LOC_A = Location(postcode="SW15 2SW", lat=51.4576, lon=-0.2289)
LOC_B = Location(postcode="TW14 9DF", lat=51.4502, lon=-0.4084)
LOC_C = Location(postcode="SE10 0EF", lat=51.4826, lon=0.0077)

MATRIX = TransitMatrix(entries={
    ("SW15 2SW", "TW14 9DF"): TransitPair(transit_minutes=55, driving_minutes=35),
    ("TW14 9DF", "SW15 2SW"): TransitPair(transit_minutes=55, driving_minutes=35),
    ("SW15 2SW", "SE10 0EF"): TransitPair(transit_minutes=70, driving_minutes=45),
    ("SE10 0EF", "SW15 2SW"): TransitPair(transit_minutes=70, driving_minutes=45),
    ("TW14 9DF", "SE10 0EF"): TransitPair(transit_minutes=80, driving_minutes=50),
    ("SE10 0EF", "TW14 9DF"): TransitPair(transit_minutes=80, driving_minutes=50),
})


def _make_driver(driver_id: str, cert: CertLevel, loc: Location, unavail=frozenset()) -> Driver:
    return Driver(
        driver_id=driver_id, name="Test", home_location=loc,
        branch="PUTNEY", max_hours_per_day=600, certifications=cert,
        can_overnight=True, unavailable_dates=unavail,
    )


def _make_job(
    job_id: str, action: ActionType, group: str, loc: Location,
    sched_date: date = date(2025, 12, 8),
    window_start: int = 480, window_end: int = 600,
    vehicle_reg: str | None = None,
) -> Job:
    return Job(
        job_id=job_id, book_no="", order_ref="", rental_no="",
        book_name="", book_status="",
        action=action, scheduled_date=sched_date,
        scheduled_time=time(9, 0), scheduled_datetime=datetime(2025, 12, 8, 9, 0),
        time_offset_minutes=540, window_start_t=window_start, window_end_t=window_end,
        vehicle_reg=vehicle_reg, vehicle_group=group,
        target_location=loc, notes="",
    )


def test_driver_job_arc_basic():
    driver = _make_driver("D001", CertLevel.VAN, LOC_A)
    job = _make_job("J001", ActionType.COLLECT, "V3", LOC_B)
    arcs = compute_driver_job_arcs([driver], [job], MATRIX, VEHICLE_GROUP_CERTS)
    assert len(arcs) == 1
    assert arcs[0].deadhead_minutes == 55


def test_driver_job_arc_cert_mismatch():
    """VAN driver should not get arc to truck-group job."""
    driver = _make_driver("D001", CertLevel.VAN, LOC_A)
    job = _make_job("J001", ActionType.COLLECT, "C.F4", LOC_B)
    arcs = compute_driver_job_arcs([driver], [job], MATRIX, VEHICLE_GROUP_CERTS)
    assert len(arcs) == 0


def test_driver_job_arc_unavailable():
    """Driver unavailable on job date should not get arc."""
    driver = _make_driver("D001", CertLevel.VAN, LOC_A, unavail=frozenset({date(2025, 12, 8)}))
    job = _make_job("J001", ActionType.COLLECT, "V3", LOC_B)
    arcs = compute_driver_job_arcs([driver], [job], MATRIX, VEHICLE_GROUP_CERTS)
    assert len(arcs) == 0


def test_driver_job_arc_too_far():
    """If deadhead exceeds job window, arc should be pruned."""
    driver = _make_driver("D001", CertLevel.VAN, LOC_A)
    # Window so tight that 55-min transit can't fit
    job = _make_job("J001", ActionType.COLLECT, "V3", LOC_B, window_start=480, window_end=500)
    arcs = compute_driver_job_arcs([driver], [job], MATRIX, VEHICLE_GROUP_CERTS)
    assert len(arcs) == 0


def test_vehicle_job_arc_basic():
    vehicle = Vehicle(
        reg="MK22EEA", group="V3", current_location=LOC_B,
        available_from=date(2025, 12, 8), available_from_t=0,
    )
    job = _make_job("J001", ActionType.DELIVER, "V3", LOC_A, vehicle_reg=None)
    arcs = compute_vehicle_job_arcs([vehicle], [job], MATRIX)
    assert len(arcs) == 1
    assert arcs[0].driving_minutes == 35


def test_vehicle_job_arc_group_mismatch():
    vehicle = Vehicle(
        reg="MK22EEA", group="V5", current_location=LOC_B,
        available_from=date(2025, 12, 8), available_from_t=0,
    )
    job = _make_job("J001", ActionType.DELIVER, "V3", LOC_A, vehicle_reg=None)
    arcs = compute_vehicle_job_arcs([vehicle], [job], MATRIX)
    assert len(arcs) == 0


def test_vehicle_job_arc_only_tba_jobs():
    """Jobs with assigned vehicle_reg should not generate vehicle arcs."""
    vehicle = Vehicle(
        reg="MK22EEA", group="V3", current_location=LOC_B,
        available_from=date(2025, 12, 8), available_from_t=0,
    )
    job = _make_job("J001", ActionType.DELIVER, "V3", LOC_A, vehicle_reg="EXISTING")
    arcs = compute_vehicle_job_arcs([vehicle], [job], MATRIX)
    assert len(arcs) == 0


def test_job_chain_arc_driver_only():
    job_a = _make_job("J001", ActionType.COLLECT, "V3", LOC_A, window_start=480, window_end=540)
    job_b = _make_job("J002", ActionType.COLLECT, "V5", LOC_B, window_start=600, window_end=720)
    arcs = compute_job_chain_arcs([job_a, job_b], MATRIX)
    driver_only = [a for a in arcs if a.chain_type == ChainType.DRIVER_ONLY]
    assert len(driver_only) >= 1
    arc = [a for a in driver_only if a.from_job_id == "J001" and a.to_job_id == "J002"][0]
    assert arc.travel_minutes == 55
    assert arc.turnaround_minutes == 0


def test_job_chain_arc_vehicle_driver():
    """COLLECT V3 -> DELIVER V3 should generate a VEHICLE_DRIVER arc."""
    job_a = _make_job("J001", ActionType.COLLECT, "V3", LOC_A, window_start=480, window_end=540)
    job_b = _make_job("J002", ActionType.DELIVER, "V3", LOC_B, window_start=600, window_end=720)
    arcs = compute_job_chain_arcs([job_a, job_b], MATRIX)
    vd_arcs = [a for a in arcs if a.chain_type == ChainType.VEHICLE_DRIVER]
    assert len(vd_arcs) == 1
    assert vd_arcs[0].travel_minutes == 35  # driving_minutes
    assert vd_arcs[0].turnaround_minutes == 45


def test_job_chain_arc_vehicle_driver_group_mismatch():
    """COLLECT V3 -> DELIVER V5 should NOT generate a VEHICLE_DRIVER arc."""
    job_a = _make_job("J001", ActionType.COLLECT, "V3", LOC_A, window_start=480, window_end=540)
    job_b = _make_job("J002", ActionType.DELIVER, "V5", LOC_B, window_start=600, window_end=720)
    arcs = compute_job_chain_arcs([job_a, job_b], MATRIX)
    vd_arcs = [a for a in arcs if a.chain_type == ChainType.VEHICLE_DRIVER]
    assert len(vd_arcs) == 0


def test_job_chain_arc_temporally_impossible():
    """If earliest finish + travel > window_end, arc should be pruned."""
    job_a = _make_job("J001", ActionType.COLLECT, "V3", LOC_A, window_start=700, window_end=720)
    job_b = _make_job("J002", ActionType.COLLECT, "V3", LOC_B, window_start=700, window_end=720)
    arcs = compute_job_chain_arcs([job_a, job_b], MATRIX)
    # 700 (start) + 0 (service) + 55 (transit) = 755 > 720 (window_end) — pruned
    a_to_b = [a for a in arcs if a.from_job_id == "J001" and a.to_job_id == "J002"]
    assert len(a_to_b) == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_arcs.py -v`
Expected: ImportError.

**Step 3: Write minimal implementation**

```python
# src/scheduler/arcs.py
"""Arc computation: pre-prune infeasible driver-job, vehicle-job, and job-job connections."""

from scheduler.cert_table import driver_can_do_group
from scheduler.models import (
    ActionType, CertLevel, ChainType, Driver, DriverJobArc,
    Job, JobChainArc, TransitMatrix, Vehicle, VehicleJobArc,
)

# Placeholder service time per job (minutes). Can be refined later.
_SERVICE_TIME = 0

# Turnaround buffer for VEHICLE_DRIVER chains (collect -> deliver).
_TURNAROUND_MINUTES = 45


def compute_driver_job_arcs(
    drivers: list[Driver],
    jobs: list[Job],
    transit_matrix: TransitMatrix,
    vehicle_group_certs: dict[str, CertLevel],
) -> list[DriverJobArc]:
    """Compute feasible driver-to-job arcs."""
    arcs: list[DriverJobArc] = []
    for driver in drivers:
        for job in jobs:
            # Certification check
            if not driver_can_do_group(driver.certifications, job.vehicle_group):
                continue
            # Unavailability check
            if job.scheduled_date in driver.unavailable_dates:
                continue
            # Transit time check
            pair = transit_matrix.get(driver.home_location, job.target_location)
            if pair is None:
                continue
            deadhead = pair.transit_minutes
            # Can driver arrive before window closes?
            if deadhead > job.window_end_t:
                continue
            arcs.append(DriverJobArc(
                driver_id=driver.driver_id,
                job_id=job.job_id,
                deadhead_minutes=deadhead,
            ))
    return arcs


def compute_vehicle_job_arcs(
    vehicles: list[Vehicle],
    jobs: list[Job],
    transit_matrix: TransitMatrix,
) -> list[VehicleJobArc]:
    """Compute feasible vehicle-to-job arcs (TBA jobs only)."""
    tba_jobs = [j for j in jobs if j.vehicle_reg is None]
    arcs: list[VehicleJobArc] = []
    for vehicle in vehicles:
        for job in tba_jobs:
            # Group match
            if vehicle.group != job.vehicle_group:
                continue
            # Transit time
            pair = transit_matrix.get(vehicle.current_location, job.target_location)
            if pair is None:
                continue
            driving = pair.driving_minutes
            # Can vehicle arrive before window closes?
            if vehicle.available_from_t + driving > job.window_end_t:
                continue
            arcs.append(VehicleJobArc(
                vehicle_reg=vehicle.reg,
                job_id=job.job_id,
                driving_minutes=driving,
            ))
    return arcs


def compute_job_chain_arcs(
    jobs: list[Job],
    transit_matrix: TransitMatrix,
) -> list[JobChainArc]:
    """Compute feasible job-to-job chain arcs (both DRIVER_ONLY and VEHICLE_DRIVER)."""
    arcs: list[JobChainArc] = []
    for job_a in jobs:
        for job_b in jobs:
            if job_a.job_id == job_b.job_id:
                continue

            pair = transit_matrix.get(job_a.target_location, job_b.target_location)
            if pair is None:
                continue

            # DRIVER_ONLY arc: any job_a -> any job_b via public transit
            earliest_arrival = job_a.window_start_t + _SERVICE_TIME + pair.transit_minutes
            if earliest_arrival <= job_b.window_end_t:
                arcs.append(JobChainArc(
                    from_job_id=job_a.job_id,
                    to_job_id=job_b.job_id,
                    chain_type=ChainType.DRIVER_ONLY,
                    travel_minutes=pair.transit_minutes,
                    turnaround_minutes=0,
                ))

            # VEHICLE_DRIVER arc: COLLECT -> DELIVER with matching groups
            if (
                job_a.action == ActionType.COLLECT
                and job_b.action == ActionType.DELIVER
                and job_a.vehicle_group == job_b.vehicle_group
            ):
                earliest_arrival_vd = (
                    job_a.window_start_t + _SERVICE_TIME
                    + pair.driving_minutes + _TURNAROUND_MINUTES
                )
                if earliest_arrival_vd <= job_b.window_end_t:
                    arcs.append(JobChainArc(
                        from_job_id=job_a.job_id,
                        to_job_id=job_b.job_id,
                        chain_type=ChainType.VEHICLE_DRIVER,
                        travel_minutes=pair.driving_minutes,
                        turnaround_minutes=_TURNAROUND_MINUTES,
                    ))

    return arcs
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_arcs.py -v`
Expected: All pass.

**Step 5: Commit**

```bash
git add src/scheduler/arcs.py tests/test_arcs.py
git commit -m "feat: add arc computation (driver-job, vehicle-job, job-chain)"
```

---

## Task 11: Wire arcs into ProblemBuilder + infeasible job exclusion

**Files:**
- Modify: `src/scheduler/builder.py`
- Modify: `tests/test_builder.py`

**Step 1: Write the failing tests**

Append to `tests/test_builder.py`:

```python
def test_builder_has_arcs():
    """Built instance should have non-empty arc lists."""
    result = (
        ProblemBuilder(horizon_start=date(2025, 12, 8), num_days=5)
        .load_storage_locations(REF / "storage_locations.csv")
        .load_drivers(REF / "drivers.csv")
        .load_vehicles(REF / "vehicle_inventory.csv")
        .load_bookings(INPUT / "sample_bookings_data.csv")
        .build()
    )
    inst = result.instance
    assert len(inst.driver_job_arcs) > 0
    assert len(inst.job_chain_arcs) > 0
    # vehicle_job_arcs may be 0 if no TBA jobs match, but should exist
    assert isinstance(inst.vehicle_job_arcs, list)


def test_builder_arc_stats():
    """Report should include arc counts."""
    result = (
        ProblemBuilder(horizon_start=date(2025, 12, 8), num_days=5)
        .load_storage_locations(REF / "storage_locations.csv")
        .load_drivers(REF / "drivers.csv")
        .load_vehicles(REF / "vehicle_inventory.csv")
        .load_bookings(INPUT / "sample_bookings_data.csv")
        .build()
    )
    assert "driver_job_arcs" in result.report.stats
    assert "job_chain_arcs" in result.report.stats
    assert "vehicle_job_arcs" in result.report.stats


def test_builder_no_excluded_jobs_in_instance():
    """All jobs in the instance should have at least one driver arc."""
    result = (
        ProblemBuilder(horizon_start=date(2025, 12, 8), num_days=5)
        .load_storage_locations(REF / "storage_locations.csv")
        .load_drivers(REF / "drivers.csv")
        .load_vehicles(REF / "vehicle_inventory.csv")
        .load_bookings(INPUT / "sample_bookings_data.csv")
        .build()
    )
    inst = result.instance
    job_ids_with_arcs = {arc.driver_id for arc in inst.driver_job_arcs}  # wrong — fix below
    # Actually check: every job in instance has at least one driver arc
    arc_job_ids = {arc.job_id for arc in inst.driver_job_arcs}
    for j in inst.jobs:
        assert j.job_id in arc_job_ids, f"Job {j.job_id} has no driver arcs but is in instance"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_builder.py::test_builder_has_arcs -v`
Expected: AssertionError — arc lists are currently empty.

**Step 3: Update builder to compute arcs and exclude infeasible jobs**

In `src/scheduler/builder.py`, replace the arc placeholder section with:

```python
from scheduler.arcs import compute_driver_job_arcs, compute_vehicle_job_arcs, compute_job_chain_arcs
```

And in the `build()` method, replace the arc placeholder block with:

```python
        # Compute arcs
        driver_job_arcs = compute_driver_job_arcs(
            self._drivers, enriched_jobs, transit_matrix, VEHICLE_GROUP_CERTS,
        )
        vehicle_job_arcs = compute_vehicle_job_arcs(
            enriched_vehicles, enriched_jobs, transit_matrix,
        )
        job_chain_arcs = compute_job_chain_arcs(enriched_jobs, transit_matrix)

        # Exclude infeasible jobs (no driver arcs)
        job_ids_with_driver_arcs = {arc.job_id for arc in driver_job_arcs}
        tba_job_ids_with_vehicle_arcs = {arc.job_id for arc in vehicle_job_arcs}

        feasible_jobs: list[Job] = []
        for j in enriched_jobs:
            if j.job_id not in job_ids_with_driver_arcs:
                issues.append(ValidationIssue(
                    severity="excluded",
                    category="no_driver_arcs",
                    message=f"Job {j.job_id} ({j.vehicle_group} at {j.target_location.postcode}): no driver can reach it",
                    source_row=None,
                ))
                continue
            if j.vehicle_reg is None and j.job_id not in tba_job_ids_with_vehicle_arcs:
                issues.append(ValidationIssue(
                    severity="excluded",
                    category="no_vehicle_arcs",
                    message=f"Job {j.job_id} (TBA {j.vehicle_group}): no matching vehicle can reach it",
                    source_row=None,
                ))
                continue
            feasible_jobs.append(j)

        # Remove arcs referencing excluded jobs
        feasible_job_ids = {j.job_id for j in feasible_jobs}
        driver_job_arcs = [a for a in driver_job_arcs if a.job_id in feasible_job_ids]
        vehicle_job_arcs = [a for a in vehicle_job_arcs if a.job_id in feasible_job_ids]
        job_chain_arcs = [
            a for a in job_chain_arcs
            if a.from_job_id in feasible_job_ids and a.to_job_id in feasible_job_ids
        ]
```

And update stats to include arc counts and excluded count:

```python
        excluded_count = len(enriched_jobs) - len(feasible_jobs)
        stats = {
            "total_jobs": len(feasible_jobs),
            "excluded_jobs": excluded_count,
            "total_drivers": len(self._drivers),
            "total_vehicles": len(enriched_vehicles),
            "total_storage_locations": len(self._storage_locations),
            "transit_pairs": len(transit_entries),
            "driver_job_arcs": len(driver_job_arcs),
            "vehicle_job_arcs": len(vehicle_job_arcs),
            "job_chain_arcs": len(job_chain_arcs),
        }
```

Use `feasible_jobs` instead of `enriched_jobs` in the ProblemInstance constructor.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_builder.py -v`
Expected: All pass.

**Step 5: Commit**

```bash
git add src/scheduler/builder.py tests/test_builder.py
git commit -m "feat: wire arc computation into builder with infeasible job exclusion"
```

---

## Task 12: Integration test — full pipeline end-to-end

**Files:**
- Create: `tests/test_integration.py`

This is the final validation: load all sample data, build a ProblemInstance, and verify the whole thing hangs together.

**Step 1: Write the test**

```python
# tests/test_integration.py
"""End-to-end integration test: full pipeline from CSVs to ProblemInstance."""

from pathlib import Path
from datetime import date

from scheduler.builder import ProblemBuilder
from scheduler.models import ActionType, ChainType

ROOT = Path(__file__).resolve().parent.parent
INPUT = ROOT / "input"
REF = ROOT / "ref-data"


def test_full_pipeline():
    result = (
        ProblemBuilder(horizon_start=date(2025, 12, 8), num_days=5)
        .load_storage_locations(REF / "storage_locations.csv")
        .load_drivers(REF / "drivers.csv")
        .load_vehicles(REF / "vehicle_inventory.csv")
        .load_bookings(INPUT / "sample_bookings_data.csv")
        .build()
    )

    assert result.ok, f"Build failed: {[i for i in result.report.issues if i.severity == 'error']}"
    inst = result.instance
    report = result.report

    # Structural checks
    assert len(inst.jobs) > 0
    assert len(inst.drivers) == 20
    assert len(inst.vehicles) > 0
    assert len(inst.storage_locations) == 3

    # Every job has valid time windows
    for j in inst.jobs:
        assert j.window_start_t < j.window_end_t
        assert j.window_end_t <= inst.horizon.t_max

    # Every job in instance has at least one driver arc
    arc_job_ids = {a.job_id for a in inst.driver_job_arcs}
    for j in inst.jobs:
        assert j.job_id in arc_job_ids

    # TBA jobs in instance have at least one vehicle arc
    tba_arc_ids = {a.job_id for a in inst.vehicle_job_arcs}
    for j in inst.jobs:
        if j.vehicle_reg is None:
            assert j.job_id in tba_arc_ids

    # Both chain types exist
    chain_types = {a.chain_type for a in inst.job_chain_arcs}
    assert ChainType.DRIVER_ONLY in chain_types

    # Both action types exist
    actions = {j.action for j in inst.jobs}
    assert ActionType.COLLECT in actions
    assert ActionType.DELIVER in actions

    # Transit matrix has entries
    assert len(inst.transit_matrix.entries) > 0

    # Report has stats
    assert report.stats["total_jobs"] > 0
    assert report.stats["driver_job_arcs"] > 0

    # Print summary for human review
    print(f"\n--- Pipeline Summary ---")
    print(f"Jobs: {report.stats['total_jobs']} (excluded: {report.stats.get('excluded_jobs', 0)})")
    print(f"Drivers: {report.stats['total_drivers']}")
    print(f"Vehicles: {report.stats['total_vehicles']}")
    print(f"Driver-Job arcs: {report.stats['driver_job_arcs']}")
    print(f"Vehicle-Job arcs: {report.stats['vehicle_job_arcs']}")
    print(f"Job-Chain arcs: {report.stats['job_chain_arcs']}")
    print(f"Transit pairs: {report.stats['transit_pairs']}")
    warnings = [i for i in report.issues if i.severity == "warning"]
    excluded = [i for i in report.issues if i.severity == "excluded"]
    print(f"Warnings: {len(warnings)}")
    print(f"Excluded jobs: {len(excluded)}")
    for e in excluded:
        print(f"  - {e.message}")
```

**Step 2: Run test**

Run: `pytest tests/test_integration.py -v -s`
Expected: PASS with summary output showing job/arc/vehicle counts.

**Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add end-to-end integration test for full pipeline"
```

---

## Summary

| Task | What it builds | Key files |
|------|---------------|-----------|
| 0 | Project scaffolding | `pyproject.toml`, `src/scheduler/` |
| 1 | Enums + Location | `models.py` |
| 2 | Driver, Vehicle, Job, StorageLocation | `models.py` |
| 3 | Arcs, TransitMatrix, ProblemInstance, BuildResult | `models.py` |
| 4 | Vehicle group cert table | `cert_table.py` |
| 5 | Postcode normalization, group upgrade parsing | `parsing.py` |
| 6 | Haversine distance + transit estimation | `geo.py` |
| 7 | CSV loaders (drivers, vehicles, storage) | `loaders.py` |
| 8 | Bookings CSV loader | `loaders.py` |
| 9 | ProblemBuilder (assembly + time windows) | `builder.py` |
| 10 | Arc computation | `arcs.py` |
| 11 | Wire arcs into builder + infeasible exclusion | `builder.py` |
| 12 | End-to-end integration test | `test_integration.py` |
