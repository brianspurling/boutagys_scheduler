"""ProblemBuilder: assembles CSVs into an immutable ProblemInstance."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from scheduler.arcs import compute_driver_job_arcs, compute_job_chain_arcs, compute_vehicle_job_arcs
from scheduler.cert_table import VEHICLE_GROUP_CERTS
from scheduler.geo import estimate_transit_pair
from scheduler.loaders import load_bookings, load_drivers, load_postcode_coords, load_storage_locations, load_vehicles
from scheduler.models import (
    BuildResult, Driver, HorizonConfig, Job,
    Location, ProblemInstance, StorageLocation,
    TransitMatrix, TransitPair, ValidationIssue, ValidationReport,
    Vehicle,
)

# Default time window: +/- 60 minutes around scheduled time
_WINDOW_BEFORE_MINUTES = 60
_WINDOW_AFTER_MINUTES = 60


class ProblemBuilder:
    def __init__(self, horizon_start: date, num_days: int = 5):
        self._horizon_start = horizon_start
        self._num_days = num_days
        self._storage_locations: list[StorageLocation] = []
        self._drivers: list[Driver] = []
        self._vehicles: list[Vehicle] = []
        self._raw_jobs: list[Job] = []
        self._issues: list[ValidationIssue] = []
        self._postcode_coords: dict[str, tuple[float, float]] = {}

    def load_postcode_coords(self, path: Path) -> ProblemBuilder:
        self._postcode_coords = load_postcode_coords(path)
        return self

    def load_storage_locations(self, path: Path) -> ProblemBuilder:
        self._storage_locations = load_storage_locations(path)
        return self

    def load_drivers(self, path: Path) -> ProblemBuilder:
        self._drivers = load_drivers(path)
        return self

    def load_vehicles(self, path: Path) -> ProblemBuilder:
        self._vehicles = load_vehicles(path, self._storage_locations)
        return self

    def load_bookings(self, path: Path) -> ProblemBuilder:
        self._raw_jobs, issues = load_bookings(path)
        self._issues.extend(issues)
        return self

    def build(self) -> BuildResult:
        issues = list(self._issues)

        horizon = HorizonConfig(
            start_date=self._horizon_start,
            num_days=self._num_days,
            t_max=self._num_days * 1440,
        )

        # Geocode job locations from postcode lookup
        geocoded_jobs: list[Job] = []
        for j in self._raw_jobs:
            pc = j.target_location.postcode
            if j.target_location.lat == 0.0 and j.target_location.lon == 0.0:
                if pc in self._postcode_coords:
                    lat, lon = self._postcode_coords[pc]
                    geocoded_jobs.append(j.model_copy(update={
                        "target_location": Location(postcode=pc, lat=lat, lon=lon),
                    }))
                else:
                    issues.append(ValidationIssue(
                        severity="excluded",
                        category="no_coordinates",
                        message=f"Job {j.job_id}: no coordinates for postcode '{pc}'",
                        source_row=None,
                    ))
            else:
                geocoded_jobs.append(j)

        # Validate vehicle groups against cert table
        valid_jobs: list[Job] = []
        for j in geocoded_jobs:
            if j.vehicle_group not in VEHICLE_GROUP_CERTS:
                issues.append(ValidationIssue(
                    severity="error",
                    category="unknown_vehicle_group",
                    message=f"Job {j.job_id}: unknown vehicle group '{j.vehicle_group}'",
                    source_row=None,
                ))
            else:
                valid_jobs.append(j)

        # Check for fatal errors
        if any(i.severity == "error" for i in issues):
            return BuildResult(
                instance=None,
                report=ValidationReport(issues=issues, stats={"total_jobs": len(self._raw_jobs)}),
            )

        # Compute time offsets and windows (DST-safe: nominal days * 1440 + h*60 + m)
        enriched_jobs: list[Job] = []
        for j in valid_jobs:
            time_offset = None
            window_start = 0
            window_end = horizon.t_max

            if j.scheduled_date is not None and j.scheduled_time is not None:
                days_from_start = (j.scheduled_date - self._horizon_start).days
                time_offset = days_from_start * 1440 + j.scheduled_time.hour * 60 + j.scheduled_time.minute
                window_start = max(0, time_offset - _WINDOW_BEFORE_MINUTES)
                window_end = min(horizon.t_max, time_offset + _WINDOW_AFTER_MINUTES)

            enriched_jobs.append(j.model_copy(update={
                "time_offset_minutes": time_offset,
                "window_start_t": window_start,
                "window_end_t": window_end,
            }))

        # Compute vehicle available_from_t
        enriched_vehicles: list[Vehicle] = []
        for v in self._vehicles:
            days_offset = (v.available_from - self._horizon_start).days
            available_t = max(0, days_offset * 1440)
            enriched_vehicles.append(v.model_copy(update={
                "available_from_t": available_t,
            }))

        # Build transit matrix (Haversine fallback for now)
        all_locations = self._collect_all_locations(enriched_jobs, enriched_vehicles)
        transit_entries: dict[tuple[str, str], TransitPair] = {}
        for i, loc_a in enumerate(all_locations):
            for loc_b in all_locations[i + 1:]:
                if loc_a.postcode == loc_b.postcode:
                    continue
                pair = estimate_transit_pair(loc_a, loc_b)
                transit_entries[(loc_a.postcode, loc_b.postcode)] = pair
                transit_entries[(loc_b.postcode, loc_a.postcode)] = pair
        transit_matrix = TransitMatrix(entries=transit_entries)

        # Compute arcs
        driver_job_arcs = compute_driver_job_arcs(
            self._drivers, enriched_jobs, transit_matrix, VEHICLE_GROUP_CERTS,
        )
        vehicle_job_arcs = compute_vehicle_job_arcs(
            enriched_vehicles, enriched_jobs, transit_matrix,
        )
        job_chain_arcs = compute_job_chain_arcs(enriched_jobs, transit_matrix)

        # Exclude infeasible jobs (no driver arcs, or TBA with no vehicle arcs)
        job_ids_with_driver_arcs = {arc.job_id for arc in driver_job_arcs}
        tba_job_ids_with_vehicle_arcs = {arc.job_id for arc in vehicle_job_arcs}

        feasible_jobs: list[Job] = []
        for j in enriched_jobs:
            if j.job_id not in job_ids_with_driver_arcs:
                issues.append(ValidationIssue(
                    severity="excluded",
                    category="no_driver_arcs",
                    message=f"Job {j.job_id} ({j.vehicle_group} at {j.target_location.postcode}): no driver can reach it",
                    source_row=None,
                ))
                continue
            if j.vehicle_reg is None and j.job_id not in tba_job_ids_with_vehicle_arcs:
                issues.append(ValidationIssue(
                    severity="excluded",
                    category="no_vehicle_arcs",
                    message=f"Job {j.job_id} (TBA {j.vehicle_group}): no matching vehicle can reach it",
                    source_row=None,
                ))
                continue
            feasible_jobs.append(j)

        # Remove arcs referencing excluded jobs
        feasible_job_ids = {j.job_id for j in feasible_jobs}
        driver_job_arcs = [a for a in driver_job_arcs if a.job_id in feasible_job_ids]
        vehicle_job_arcs = [a for a in vehicle_job_arcs if a.job_id in feasible_job_ids]
        job_chain_arcs = [
            a for a in job_chain_arcs
            if a.from_job_id in feasible_job_ids and a.to_job_id in feasible_job_ids
        ]

        excluded_count = len(enriched_jobs) - len(feasible_jobs)
        stats = {
            "total_jobs": len(feasible_jobs),
            "excluded_jobs": excluded_count,
            "total_drivers": len(self._drivers),
            "total_vehicles": len(enriched_vehicles),
            "total_storage_locations": len(self._storage_locations),
            "transit_pairs": len(transit_entries),
            "driver_job_arcs": len(driver_job_arcs),
            "vehicle_job_arcs": len(vehicle_job_arcs),
            "job_chain_arcs": len(job_chain_arcs),
        }

        instance = ProblemInstance(
            horizon=horizon,
            jobs=feasible_jobs,
            drivers=self._drivers,
            vehicles=enriched_vehicles,
            storage_locations=self._storage_locations,
            vehicle_group_certs=VEHICLE_GROUP_CERTS,
            transit_matrix=transit_matrix,
            driver_job_arcs=driver_job_arcs,
            job_chain_arcs=job_chain_arcs,
            vehicle_job_arcs=vehicle_job_arcs,
        )

        return BuildResult(
            instance=instance,
            report=ValidationReport(issues=issues, stats=stats),
        )

    def _collect_all_locations(
        self,
        jobs: list[Job],
        vehicles: list[Vehicle],
    ) -> list[Location]:
        """Collect unique locations from jobs, vehicles, drivers, and storage."""
        seen: set[str] = set()
        locations: list[Location] = []
        for source in [
            [j.target_location for j in jobs],
            [v.current_location for v in vehicles],
            [d.home_location for d in self._drivers],
            [sl.location for sl in self._storage_locations],
        ]:
            for loc in source:
                if loc.postcode not in seen:
                    seen.add(loc.postcode)
                    locations.append(loc)
        return locations
