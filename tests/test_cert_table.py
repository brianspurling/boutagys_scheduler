from scheduler.cert_table import VEHICLE_GROUP_CERTS, driver_can_do_group
from scheduler.models import CertLevel


def test_all_known_groups_present():
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
    assert VEHICLE_GROUP_CERTS["C.F3"] == CertLevel.VAN_TRUCK
    assert VEHICLE_GROUP_CERTS["C.F4"] == CertLevel.VAN_TRUCK
    assert VEHICLE_GROUP_CERTS["E.A17"] == CertLevel.VAN_TRUCK


def test_van_groups():
    for g in ["V1", "V2", "V3", "V4", "V5"]:
        assert VEHICLE_GROUP_CERTS[g] == CertLevel.VAN


def test_driver_can_do_group_van_cert():
    assert driver_can_do_group(CertLevel.VAN, "V3") is True
    assert driver_can_do_group(CertLevel.VAN, "C.F4") is False


def test_driver_can_do_group_truck_cert():
    assert driver_can_do_group(CertLevel.VAN_TRUCK, "V3") is True
    assert driver_can_do_group(CertLevel.VAN_TRUCK, "C.F4") is True
