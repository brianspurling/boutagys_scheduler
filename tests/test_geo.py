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
    assert pair.driving_minutes < pair.transit_minutes
    assert pair.driving_minutes > 0
    assert pair.transit_minutes > 0


def test_estimate_transit_pair_same_location():
    loc = Location(postcode="SW15 2SW", lat=51.4576, lon=-0.2289)
    pair = estimate_transit_pair(loc, loc)
    assert pair.driving_minutes == 0
    assert pair.transit_minutes == 0
