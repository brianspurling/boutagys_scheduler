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


class DriverJobArc(BaseModel, frozen=True):
    driver_id: str
    job_id: str
    deadhead_minutes: int
    return_deadhead_minutes: int


class VehicleJobArc(BaseModel, frozen=True):
    vehicle_reg: str
    job_id: str
    driving_minutes: int
    earliest_arrival_t: int


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
        if from_loc.postcode == to_loc.postcode:
            return TransitPair(transit_minutes=0, driving_minutes=0)
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


class CircuitNode(BaseModel, frozen=True):
    """A node in a driver's circuit graph."""
    index: int  # unique per driver's graph, 0 = home
    node_type: Literal["home", "collect", "deliver", "depot_drop", "depot_pickup"]
    driver_id: str
    postcode: str
    job_id: str | None = None  # set for collect/deliver nodes
    storage_location_id: str | None = None  # set for depot nodes


class CircuitArc(BaseModel, frozen=True):
    """A directed arc in a driver's circuit graph."""
    tail: int  # index of source node
    head: int  # index of destination node
    travel_minutes: int
    cost: int  # weighted cost (integer, for CP-SAT)
    mode: Literal["transit", "driving"]
    vehicle_reg: str | None = None  # set for driving arcs with specific vehicle


class DriverCircuitGraph(BaseModel, frozen=True):
    """Complete circuit graph for one driver."""
    driver_id: str
    nodes: list[CircuitNode]
    arcs: list[CircuitArc]


class BuildResult(BaseModel):
    instance: ProblemInstance | None
    report: ValidationReport

    @property
    def ok(self) -> bool:
        return self.instance is not None


class JobAssignment(BaseModel, frozen=True):
    job_id: str
    driver_id: str
    start_time_t: int
    start_datetime: datetime


class RouteLeg(BaseModel, frozen=True):
    """One travel leg in a driver's day: from one location to the next."""
    from_postcode: str
    to_postcode: str
    mode: Literal["transit", "driving"]
    duration_minutes: int | None  # None = unknown (not yet computed)
    # Present when mode="driving" and leg comes from a depot vehicle pickup
    via_depot_postcode: str | None = None
    via_depot_transit_minutes: int | None = None
    via_depot_driving_minutes: int | None = None
    # Booking reference for the job at the destination (if any)
    job_id: str | None = None
    vehicle_reg: str | None = None


class DriverRoute(BaseModel, frozen=True):
    """Full route for one driver on one day."""
    driver_id: str
    driver_name: str
    home_postcode: str
    legs: list[RouteLeg]
    deadhead_minutes_total: int


class SolverResult(BaseModel, frozen=True):
    status: str
    solve_time_seconds: float
    assignments: list[JobAssignment]
    driver_routes: list[DriverRoute]
    stats: dict[str, int]
