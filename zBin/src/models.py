"""
Data models for the van rental scheduler.
Represents drivers, jobs, vehicles, locations, and assignments.
"""
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, List, Set
from enum import Enum


class JobType(Enum):
    """Type of job: delivery or collection"""
    DELIVER = "Deliver"
    COLLECT = "Collect"


class TransportMode(Enum):
    """How the driver travels"""
    DRIVE = "drive"
    PUBLIC_TRANSPORT = "transit"
    WALK = "walk"


@dataclass
class Location:
    """A storage location"""
    location_id: str
    name: str
    postcode: str
    capacity: int
    restricted_vehicle_groups: Set[str]
    lat: float
    lon: float

    @property
    def lat_lon(self) -> tuple[float, float]:
        return (self.lat, self.lon)


@dataclass
class Driver:
    """A driver who can complete jobs"""
    driver_id: str
    name: str
    home_postcode: str
    branch: str
    max_hours_per_day: int
    certifications: Set[str]  # e.g., {'van', 'truck'}
    can_overnight: bool
    unavailable_dates: List[date]
    home_lat: float
    home_lon: float
    notes: str

    @property
    def home_location(self) -> tuple[float, float]:
        return (self.home_lat, self.home_lon)

    def can_drive_vehicle_group(self, vehicle_group: str) -> bool:
        """Check if driver is certified for this vehicle type"""
        # Simplify vehicle group to base certification
        if vehicle_group.startswith(('V', 'E', 'D')):
            return 'van' in self.certifications
        elif vehicle_group.startswith('C'):
            return 'truck' in self.certifications
        else:
            # Unknown type - require truck cert to be safe
            return 'truck' in self.certifications


@dataclass
class Vehicle:
    """A vehicle in the inventory"""
    vehicle_reg: str
    vehicle_group: str
    current_storage_location: str
    availability_date: date
    notes: str


@dataclass
class Job:
    """A single job (delivery or collection) from the bookings CSV"""
    booking_ref: str  # Book No. from CSV
    job_type: JobType
    date: date
    time: str  # Time as string (e.g., "08:30")
    vehicle_reg: Optional[str]  # May be blank for BOOKING deliveries
    vehicle_group: str  # Supp'd Grp
    location_postcode: str  # Delivery or Collection postcode
    customer_name: str  # From "Drivers" column (the customer)
    notes: str

    # For collections, we need to know where to take the vehicle
    storage_destination: Optional[str] = None  # Set by optimizer

    @property
    def datetime(self) -> datetime:
        """Parse date and time into datetime object"""
        return datetime.combine(self.date, datetime.strptime(self.time, "%H:%M").time())

    @property
    def deadline(self) -> datetime:
        """Alias for datetime - the deadline for this job"""
        return self.datetime


@dataclass
class JobChain:
    """A sequence of jobs assigned to a driver"""
    driver: Driver
    jobs: List[Job]
    total_cost: float = 0.0
    total_time_hours: float = 0.0
    requires_overnight: bool = False
    customer_approval_required: Set[int] = field(default_factory=set)  # Indices of jobs needing approval

    def add_job(self, job: Job):
        """Add a job to this chain"""
        self.jobs.append(job)


@dataclass
class Assignment:
    """A job assigned to a driver with timing and cost details"""
    driver: Driver
    job: Job
    arrival_time: datetime
    transport_mode: TransportMode
    transport_cost: float
    transport_time_minutes: int
    requires_customer_approval: bool = False
