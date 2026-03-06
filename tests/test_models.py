from scheduler.models import CertLevel, ActionType, ChainType, Location
import pytest


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
    with pytest.raises(Exception):
        loc.postcode = "X"
