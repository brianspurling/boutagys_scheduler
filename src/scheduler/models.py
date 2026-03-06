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
