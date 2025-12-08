"""
Load CSV data into Python data models.
"""
import csv
from datetime import datetime
from pathlib import Path
from typing import List, Dict

from models import Driver, Location, Vehicle, Job, JobType


def load_drivers(filepath: str) -> List[Driver]:
    """Load drivers from CSV"""
    drivers = []
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Parse certifications
            certs = set(row['certifications'].split(';')) if row['certifications'] else set()

            # Parse home location
            lat_lon = row['home_location'].split('/')
            lat = float(lat_lon[0])
            lon = float(lat_lon[1])

            # Parse unavailable dates (empty for now in our data)
            unavailable = []

            driver = Driver(
                driver_id=row['driver_id'],
                name=row['name'],
                home_postcode=row['home_postcode'],
                branch=row['branch'],
                max_hours_per_day=int(row['max_hours_per_day']),
                certifications=certs,
                can_overnight=row['can_overnight'].lower() == 'yes',
                unavailable_dates=unavailable,
                home_lat=lat,
                home_lon=lon,
                notes=row['notes']
            )
            drivers.append(driver)

    return drivers


def load_storage_locations(filepath: str) -> List[Location]:
    """Load storage locations from CSV"""
    locations = []
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Parse lat/lon
            lat_lon = row['lat_long'].split('/')
            lat = float(lat_lon[0])
            lon = float(lat_lon[1])

            # Parse restricted vehicle groups
            restricted = set(row['restricted_vehicle_groups'].split(';')) if row['restricted_vehicle_groups'] else set()

            location = Location(
                location_id=row['location_id'],
                name=row['name'],
                postcode=row['postcode'],
                capacity=int(row['capacity']),
                restricted_vehicle_groups=restricted,
                lat=lat,
                lon=lon
            )
            locations.append(location)

    return locations


def load_vehicle_inventory(filepath: str) -> List[Vehicle]:
    """Load vehicle inventory from CSV"""
    vehicles = []
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Parse availability date
            avail_date = datetime.strptime(row['availability_date'], '%Y-%m-%d').date()

            vehicle = Vehicle(
                vehicle_reg=row['vehicle_reg'],
                vehicle_group=row['vehicle_group'],
                current_storage_location=row['current_storage_location'],
                availability_date=avail_date,
                notes=row['notes']
            )
            vehicles.append(vehicle)

    return vehicles


def load_bookings(filepath: str) -> List[Job]:
    """
    Load bookings from CSV and convert to Job objects.

    Each row in the bookings CSV represents a job (either delivery or collection).
    We extract the relevant fields and create Job objects.
    """
    jobs = []
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Skip empty rows
            if not row.get('Date') or not row.get('Action'):
                continue

            # Parse date (format: DD/MM/YYYY)
            try:
                job_date = datetime.strptime(row['Date'], '%d/%m/%Y').date()
            except ValueError:
                # Skip invalid dates
                continue

            # Determine job type and location
            action = row['Action'].strip()
            if action == 'Deliver':
                job_type = JobType.DELIVER
                location_postcode = row['Delivery'].split('*')[0].strip()  # Remove *PRE-DELIVERY* etc
            elif action == 'Collect':
                job_type = JobType.COLLECT
                location_postcode = row['Collection'].split('*')[0].strip()
            else:
                # Unknown action type
                continue

            # Create job
            job = Job(
                booking_ref=row['Book No.'],
                job_type=job_type,
                date=job_date,
                time=row['Time'],
                vehicle_reg=row['Reg No.'] if row['Reg No.'] else None,
                vehicle_group=row["Supp'd Grp"],
                location_postcode=location_postcode,
                customer_name=row['Drivers'],
                notes=row['Notes']
            )
            jobs.append(job)

    return jobs


def load_all_data(data_dir: str = 'data') -> Dict:
    """Load all data files and return as dictionary"""
    data_path = Path(data_dir)

    return {
        'drivers': load_drivers(data_path / 'drivers.csv'),
        'locations': load_storage_locations(data_path / 'storage_locations.csv'),
        'vehicles': load_vehicle_inventory(data_path / 'vehicle_inventory.csv'),
        'jobs': load_bookings('sample_bookings_data.csv')  # In root directory
    }
