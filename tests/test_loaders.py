from pathlib import Path
from datetime import date

from scheduler.loaders import load_drivers, load_vehicles, load_storage_locations, load_bookings
from scheduler.models import CertLevel, ActionType

REF_DATA = Path(__file__).resolve().parent.parent / "ref-data"
INPUT_DATA = Path(__file__).resolve().parent.parent / "input"


# --- Storage locations ---

def test_load_storage_locations():
    locs = load_storage_locations(REF_DATA / "storage_locations.csv")
    assert len(locs) == 3
    feltham = [l for l in locs if l.location_id == "S001"][0]
    assert feltham.name == "Feltham"
    assert feltham.location.postcode == "TW14 9DF"
    assert feltham.capacity == 30


# --- Drivers ---

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


# --- Vehicles ---

def test_load_vehicles_count():
    storage_locs = load_storage_locations(REF_DATA / "storage_locations.csv")
    vehicles = load_vehicles(REF_DATA / "vehicle_inventory.csv", storage_locs)
    assert len(vehicles) >= 17  # At least 17 non-blank rows


def test_load_vehicles_first():
    storage_locs = load_storage_locations(REF_DATA / "storage_locations.csv")
    vehicles = load_vehicles(REF_DATA / "vehicle_inventory.csv", storage_locs)
    v = vehicles[0]
    assert v.reg == "MK22EEA"
    assert v.group == "V3"
    assert v.available_from == date(2025, 12, 8)
    assert v.current_location.postcode == "TW14 9DF"


# --- Bookings ---

def test_load_bookings_strips_blank_rows():
    jobs, _ = load_bookings(INPUT_DATA / "sample_bookings_data.csv")
    for j in jobs:
        assert j.action in (ActionType.COLLECT, ActionType.DELIVER)


def test_load_bookings_count():
    jobs, _ = load_bookings(INPUT_DATA / "sample_bookings_data.csv")
    assert len(jobs) > 50


def test_load_bookings_postcode_normalized():
    jobs, issues = load_bookings(INPUT_DATA / "sample_bookings_data.csv")
    bh_jobs = [j for j in jobs if j.book_no == "#35793063"]
    assert len(bh_jobs) == 1
    assert bh_jobs[0].target_location.postcode == "BH23 5LJ"
    stripped_warnings = [i for i in issues if i.category == "postcode_stripped"]
    assert len(stripped_warnings) > 0


def test_load_bookings_vehicle_group_upgrade():
    jobs, issues = load_bookings(INPUT_DATA / "sample_bookings_data.csv")
    upgraded = [i for i in issues if i.category == "group_upgrade"]
    assert len(upgraded) > 0
    d_b9a_jobs = [j for j in jobs if j.vehicle_group == "D.B9A"]
    assert len(d_b9a_jobs) > 0


def test_load_bookings_tba_vehicle():
    jobs, _ = load_bookings(INPUT_DATA / "sample_bookings_data.csv")
    tba_jobs = [j for j in jobs if j.vehicle_reg is None]
    assert len(tba_jobs) > 0


def test_load_bookings_job_ids_sequential():
    jobs, _ = load_bookings(INPUT_DATA / "sample_bookings_data.csv")
    for i, j in enumerate(jobs):
        assert j.job_id == f"J{i + 1:03d}"
