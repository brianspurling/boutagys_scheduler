"""Geographic utilities: Haversine distance and transit time estimation."""

import math

from scheduler.models import Location, TransitPair

_EARTH_RADIUS_KM = 6371.0
_DRIVING_KPH = 30.0
_TRANSIT_KPH = 20.0
_TRANSIT_BUFFER = 1.15


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in km."""
    lat1, lon1, lat2, lon2 = (math.radians(x) for x in (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def estimate_transit_pair(from_loc: Location, to_loc: Location) -> TransitPair:
    """Estimate driving and transit times using Haversine with detour factor."""
    km = haversine_km(from_loc.lat, from_loc.lon, to_loc.lat, to_loc.lon)
    if km == 0.0:
        return TransitPair(transit_minutes=0, driving_minutes=0)

    road_km = km * 1.3
    driving_minutes = round(road_km / _DRIVING_KPH * 60)
    transit_minutes = round(road_km / _TRANSIT_KPH * 60 * _TRANSIT_BUFFER)

    return TransitPair(
        transit_minutes=max(1, transit_minutes),
        driving_minutes=max(1, driving_minutes),
    )
