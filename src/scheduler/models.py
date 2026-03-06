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
