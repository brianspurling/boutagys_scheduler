"""CSV loaders that parse reference data and bookings into domain model objects."""

import csv
from datetime import date, time, datetime
from pathlib import Path

from scheduler.models import (
    ActionType, CertLevel, Driver, Job, Location, StorageLocation,
    ValidationIssue, Vehicle,
)
from scheduler.parsing import normalize_postcode, resolve_vehicle_group


def load_storage_locations(path: Path) -> list[StorageLocation]:
    """Load storage_locations.csv."""
    locations: list[StorageLocation] = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            loc_id = row["location_id"].strip()
            if not loc_id:
                continue
            lat_str, lon_str = row["lat_long"].strip().split("/")
            restricted = set()
            if row["restricted_vehicle_groups"].strip():
                restricted = {g.strip() for g in row["restricted_vehicle_groups"].split(";")}
            locations.append(StorageLocation(
                location_id=loc_id,
                name=row["name"].strip(),
                location=Location(
                    postcode=row["postcode"].strip(),
                    lat=float(lat_str),
                    lon=float(lon_str),
                ),
                capacity=int(row["capacity"].strip()),
                restricted_groups=restricted,
            ))
    return locations


def load_drivers(path: Path) -> list[Driver]:
    """Load drivers.csv."""
    drivers: list[Driver] = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            driver_id = row["driver_id"].strip()
            if not driver_id:
                continue
            certs_raw = row["certifications"].strip()
            if "truck" in certs_raw:
                cert = CertLevel.VAN_TRUCK
            else:
                cert = CertLevel.VAN

            unavail: frozenset[date] = frozenset()
            if row["unavailable_dates"].strip():
                unavail = frozenset(
                    date.fromisoformat(d.strip())
                    for d in row["unavailable_dates"].split(";")
                    if d.strip()
                )

            lat_str, lon_str = row["home_location"].strip().split("/")
            drivers.append(Driver(
                driver_id=driver_id,
                name=row["name"].strip(),
                home_location=Location(
                    postcode=row["home_postcode"].strip(),
                    lat=float(lat_str),
                    lon=float(lon_str),
                ),
                branch=row["branch"].strip(),
                max_hours_per_day=int(row["max_hours_per_day"].strip()) * 60,
                certifications=cert,
                can_overnight=row["can_overnight"].strip().lower() == "yes",
                unavailable_dates=unavail,
            ))
    return drivers


def load_vehicles(
    path: Path,
    storage_locations: list[StorageLocation],
) -> list[Vehicle]:
    """Load vehicle_inventory.csv.

    Resolves current_storage_location ID to the storage location's Location.
    """
    loc_by_id = {sl.location_id: sl.location for sl in storage_locations}
    vehicles: list[Vehicle] = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            reg = row["vehicle_reg"].strip()
            if not reg:
                continue
            storage_id = row["current_storage_location"].strip()
            location = loc_by_id[storage_id]
            vehicles.append(Vehicle(
                reg=reg,
                group=row["vehicle_group"].strip(),
                current_location=location,
                available_from=date.fromisoformat(row["availability_date"].strip()),
                available_from_t=0,  # Placeholder — builder computes relative to horizon
            ))
    return vehicles


def load_bookings(
    path: Path,
) -> tuple[list[Job], list[ValidationIssue]]:
    """Load bookings CSV into Job objects.

    Returns (jobs, issues) where issues contains warnings for postcode stripping,
    group upgrades, and errors for unparseable rows.

    Note: target_location lat/lon is set to 0.0/0.0 as a placeholder.
    The builder will geocode these later (or use a postcode lookup).
    """
    jobs: list[Job] = []
    issues: list[ValidationIssue] = []
    job_counter = 0

    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, start=2):  # row 1 is header
            # Strip blank rows (all fields empty)
            if not any(v.strip() for v in row.values()):
                continue

            # Must have an action
            action_raw = row["Action"].strip().lower()
            if action_raw not in ("collect", "deliver"):
                continue

            action = ActionType.COLLECT if action_raw == "collect" else ActionType.DELIVER

            # Parse date
            date_str = row["Date"].strip()
            if not date_str:
                issues.append(ValidationIssue(
                    severity="error",
                    category="unparseable_date",
                    message=f"Row {row_num}: empty date",
                    source_row=row_num,
                ))
                continue
            try:
                scheduled_date = datetime.strptime(date_str, "%d/%m/%Y").date()
            except ValueError:
                issues.append(ValidationIssue(
                    severity="error",
                    category="unparseable_date",
                    message=f"Row {row_num}: cannot parse date '{date_str}'",
                    source_row=row_num,
                ))
                continue

            # Parse time (may be blank)
            time_str = row["Time"].strip()
            scheduled_time = None
            scheduled_datetime = None
            if time_str:
                try:
                    parts = time_str.split(":")
                    scheduled_time = time(int(parts[0]), int(parts[1]))
                    scheduled_datetime = datetime.combine(scheduled_date, scheduled_time)
                except (ValueError, IndexError):
                    issues.append(ValidationIssue(
                        severity="warning",
                        category="unparseable_time",
                        message=f"Row {row_num}: cannot parse time '{time_str}'",
                        source_row=row_num,
                    ))

            # Resolve vehicle group
            group_raw = row["Supp'd Grp"].strip()
            vehicle_group = resolve_vehicle_group(group_raw)
            if vehicle_group is None:
                issues.append(ValidationIssue(
                    severity="error",
                    category="missing_vehicle_group",
                    message=f"Row {row_num}: empty vehicle group",
                    source_row=row_num,
                ))
                continue
            if ">" in group_raw:
                issues.append(ValidationIssue(
                    severity="warning",
                    category="group_upgrade",
                    message=f"Row {row_num}: '{group_raw}' resolved to '{vehicle_group}'",
                    source_row=row_num,
                ))

            # Resolve target postcode based on action type
            if action == ActionType.DELIVER:
                postcode_raw = row["Delivery"].strip()
            else:
                postcode_raw = row["Collection"].strip()

            postcode = normalize_postcode(postcode_raw)
            if postcode != postcode_raw.strip() and postcode is not None:
                issues.append(ValidationIssue(
                    severity="warning",
                    category="postcode_stripped",
                    message=f"Row {row_num}: '{postcode_raw}' normalized to '{postcode}'",
                    source_row=row_num,
                ))
            if postcode is None:
                issues.append(ValidationIssue(
                    severity="excluded",
                    category="missing_postcode",
                    message=f"Row {row_num}: no parseable postcode in '{postcode_raw}'",
                    source_row=row_num,
                ))
                continue

            # Vehicle reg (None for TBA)
            reg_raw = row["Reg No."].strip()
            vehicle_reg = reg_raw if reg_raw else None

            job_counter += 1
            jobs.append(Job(
                job_id=f"J{job_counter:03d}",
                book_no=row["Book No."].strip(),
                order_ref=row["Order ref:"].strip(),
                rental_no=row["Rental No."].strip(),
                book_name=row["Book Name"].strip(),
                book_status=row["Book Status"].strip(),
                action=action,
                scheduled_date=scheduled_date,
                scheduled_time=scheduled_time,
                scheduled_datetime=scheduled_datetime,
                time_offset_minutes=None,  # Computed by builder
                earliest_departure_t=None, # Computed by builder
                grace_end_t=None,          # Computed by builder
                same_day_start_t=0,        # Computed by builder
                same_day_end_t=0,          # Computed by builder
                deadline_t=None,           # Computed by builder
                vehicle_reg=vehicle_reg,
                vehicle_group=vehicle_group,
                target_location=Location(
                    postcode=postcode,
                    lat=0.0,  # Placeholder — builder geocodes
                    lon=0.0,
                ),
                notes=row["Notes"].strip(),
            ))

    return jobs, issues


def load_postcode_coords(path: Path) -> dict[str, tuple[float, float]]:
    """Load postcode_coords.csv into a postcode -> (lat, lon) lookup dict."""
    coords: dict[str, tuple[float, float]] = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            postcode = row["postcode"].strip()
            if postcode:
                coords[postcode] = (float(row["lat"]), float(row["lon"]))
    return coords
