"""
Distance and time calculation.
For spike: uses mock data (haversine distance as proxy).
Later: integrate Google Maps API for real driving/transit times and costs.
"""
import math
from typing import Tuple
from models import TransportMode


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate straight-line distance between two points in kilometers.
    Uses Haversine formula.
    """
    R = 6371  # Earth's radius in kilometers

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))

    return R * c


class DistanceCalculator:
    """
    Calculates distances, travel times, and costs between locations.

    For the spike, uses mock calculations based on straight-line distance.
    Can be replaced with Google Maps API integration later.
    """

    def __init__(self, use_mock: bool = True):
        self.use_mock = use_mock
        # Cache for postcode geocoding (postcode -> (lat, lon))
        self.postcode_cache = {}

    def get_distance_km(self, from_coords: Tuple[float, float], to_coords: Tuple[float, float]) -> float:
        """Get distance in kilometers between two coordinates"""
        return haversine_distance(from_coords[0], from_coords[1], to_coords[0], to_coords[1])

    def get_travel_time_minutes(
        self,
        from_coords: Tuple[float, float],
        to_coords: Tuple[float, float],
        mode: TransportMode
    ) -> int:
        """
        Estimate travel time in minutes.

        Mock calculation:
        - DRIVE: 50 km/h average (includes traffic, city driving)
        - PUBLIC_TRANSPORT: 30 km/h average (includes waiting, connections)
        - WALK: 5 km/h
        """
        distance_km = self.get_distance_km(from_coords, to_coords)

        if mode == TransportMode.DRIVE:
            avg_speed = 50  # km/h
        elif mode == TransportMode.PUBLIC_TRANSPORT:
            avg_speed = 30  # km/h
        else:  # WALK
            avg_speed = 5  # km/h

        time_hours = distance_km / avg_speed
        return int(time_hours * 60)

    def get_transport_cost(
        self,
        from_coords: Tuple[float, float],
        to_coords: Tuple[float, float],
        mode: TransportMode
    ) -> float:
        """
        Estimate transport cost in GBP.

        Mock calculation:
        - DRIVE: £0.45/km (fuel + vehicle wear)
        - PUBLIC_TRANSPORT: £0.20/km (average train/bus fare)
        - WALK: £0
        """
        distance_km = self.get_distance_km(from_coords, to_coords)

        if mode == TransportMode.DRIVE:
            return distance_km * 0.45
        elif mode == TransportMode.PUBLIC_TRANSPORT:
            return distance_km * 0.20
        else:  # WALK
            return 0.0

    def geocode_postcode(self, postcode: str) -> Tuple[float, float]:
        """
        Convert postcode to coordinates.

        For spike: uses a simple mock based on postcode prefix.
        Later: integrate with Google Maps Geocoding API or UK postcode database.
        """
        # Check cache first
        if postcode in self.postcode_cache:
            return self.postcode_cache[postcode]

        # Mock geocoding - just for spike
        # In reality, we'd call Google Maps API or use a UK postcode database
        # For now, assign rough London coordinates based on postcode area
        mock_coords = self._mock_geocode(postcode)
        self.postcode_cache[postcode] = mock_coords
        return mock_coords

    def _mock_geocode(self, postcode: str) -> Tuple[float, float]:
        """
        Mock geocoding for spike.
        Maps postcode areas to approximate London coordinates.
        """
        # Extract postcode area (first 1-2 letters)
        area = postcode.split()[0] if ' ' in postcode else postcode[:2]

        # Mock mapping - very rough London areas
        mock_map = {
            'E': (51.5252, -0.0393),   # East London
            'EC': (51.5155, -0.0922),  # East Central
            'N': (51.5897, -0.1338),   # North London
            'NW': (51.5588, -0.3269),  # North West
            'SE': (51.4549, -0.0123),  # South East
            'SW': (51.4614, -0.1935),  # South West
            'W': (51.5142, -0.1494),   # West London
            'WC': (51.5155, -0.1267),  # West Central
            'TW': (51.4479, -0.3540),  # Twickenham area
            'KT': (51.3976, -0.3004),  # Kingston area
            'CR': (51.3762, -0.0982),  # Croydon
            'BR': (51.4064, 0.0164),   # Bromley
            'IG': (51.5889, 0.0890),   # Ilford
            'RM': (51.5779, 0.1821),   # Romford
            'UB': (51.5134, -0.4746),  # Uxbridge
            'HA': (51.5898, -0.3346),  # Harrow
            'HP': (51.7500, -0.4750),  # Hemel Hempstead
            'CV': (52.4081, -1.5106),  # Coventry
            'NG': (52.9548, -1.1581),  # Nottingham
            'B': (52.4862, -1.8904),   # Birmingham
            'RG': (51.4544, -0.9731),  # Reading
            'SP': (51.0709, -1.7944),  # Salisbury
            'SA': (51.6214, -3.9436),  # Swansea
            'ME': (51.3927, 0.5255),   # Medway
            'TN': (51.1323, 0.2633),   # Tonbridge
            'GL': (51.8652, -2.2382),  # Gloucester
            'GU': (51.2429, -0.5707),  # Guildford
            'BH': (50.7197, -1.8808),  # Bournemouth
            'PO': (50.8198, -1.0880),  # Portsmouth
            'SO': (50.9097, -1.4044),  # Southampton
            'MK': (52.0406, -0.7594),  # Milton Keynes
            'PE': (52.5695, -0.2405),  # Peterborough
            'DY': (52.4582, -2.1248),  # Dudley
            'TA': (51.0194, -3.1000),  # Taunton
            'CB': (52.2053, 0.1218),   # Cambridge
            'CF': (51.4816, -3.1791),  # Cardiff
            'NP': (51.5842, -2.9977),  # Newport
            'OX': (51.7520, -1.2577),  # Oxford
            'WD': (51.6573, -0.3949),  # Watford
            'CM': (51.7357, 0.4695),   # Chelmsford
            'SN': (51.5558, -1.7797),  # Swindon
            'BS': (51.4545, -2.5879),  # Bristol
            'CT': (51.2787, 1.0798),   # Canterbury
            'HR': (52.0565, -2.7160),  # Hereford
        }

        # Find matching area
        for prefix, coords in mock_map.items():
            if area.startswith(prefix):
                return coords

        # Default to central London if unknown
        return (51.5074, -0.1278)
