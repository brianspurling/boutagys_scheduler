"""Arc computation: pre-prune infeasible driver-job, vehicle-job, and job-job connections."""

from scheduler.cert_table import driver_can_do_group
from scheduler.models import (
    ActionType, CertLevel, ChainType, Driver, DriverJobArc,
    Job, JobChainArc, TransitMatrix, Vehicle, VehicleJobArc,
)

_SERVICE_TIME = 0
_TURNAROUND_MINUTES = 45


def compute_driver_job_arcs(
    drivers: list[Driver],
    jobs: list[Job],
    transit_matrix: TransitMatrix,
    vehicle_group_certs: dict[str, CertLevel],
) -> list[DriverJobArc]:
    """Compute feasible driver-to-job arcs."""
    arcs: list[DriverJobArc] = []
    for driver in drivers:
        for job in jobs:
            if not driver_can_do_group(driver.certifications, job.vehicle_group):
                continue
            if job.scheduled_date in driver.unavailable_dates:
                continue
            pair = transit_matrix.get(driver.home_location, job.target_location)
            if pair is None:
                continue
            deadhead = pair.transit_minutes
            if deadhead > job.window_end_t:
                continue
            arcs.append(DriverJobArc(
                driver_id=driver.driver_id,
                job_id=job.job_id,
                deadhead_minutes=deadhead,
            ))
    return arcs


def compute_vehicle_job_arcs(
    vehicles: list[Vehicle],
    jobs: list[Job],
    transit_matrix: TransitMatrix,
) -> list[VehicleJobArc]:
    """Compute feasible vehicle-to-job arcs (TBA jobs only)."""
    tba_jobs = [j for j in jobs if j.vehicle_reg is None]
    arcs: list[VehicleJobArc] = []
    for vehicle in vehicles:
        for job in tba_jobs:
            if vehicle.group != job.vehicle_group:
                continue
            pair = transit_matrix.get(vehicle.current_location, job.target_location)
            if pair is None:
                continue
            driving = pair.driving_minutes
            if vehicle.available_from_t + driving > job.window_end_t:
                continue
            arcs.append(VehicleJobArc(
                vehicle_reg=vehicle.reg,
                job_id=job.job_id,
                driving_minutes=driving,
            ))
    return arcs


def compute_job_chain_arcs(
    jobs: list[Job],
    transit_matrix: TransitMatrix,
) -> list[JobChainArc]:
    """Compute feasible job-to-job chain arcs (both DRIVER_ONLY and VEHICLE_DRIVER)."""
    arcs: list[JobChainArc] = []
    for job_a in jobs:
        for job_b in jobs:
            if job_a.job_id == job_b.job_id:
                continue

            pair = transit_matrix.get(job_a.target_location, job_b.target_location)
            if pair is None:
                continue

            # DRIVER_ONLY arc: any job_a -> any job_b via public transit
            earliest_arrival = job_a.window_start_t + _SERVICE_TIME + pair.transit_minutes
            if earliest_arrival <= job_b.window_end_t:
                arcs.append(JobChainArc(
                    from_job_id=job_a.job_id,
                    to_job_id=job_b.job_id,
                    chain_type=ChainType.DRIVER_ONLY,
                    travel_minutes=pair.transit_minutes,
                    turnaround_minutes=0,
                ))

            # VEHICLE_DRIVER arc: COLLECT -> DELIVER with matching groups and compatible regs
            regs_compatible = (
                job_b.vehicle_reg is None
                or job_a.vehicle_reg == job_b.vehicle_reg
            )
            if (
                job_a.action == ActionType.COLLECT
                and job_b.action == ActionType.DELIVER
                and job_a.vehicle_group == job_b.vehicle_group
                and regs_compatible
            ):
                earliest_arrival_vd = (
                    job_a.window_start_t + _SERVICE_TIME
                    + pair.driving_minutes + _TURNAROUND_MINUTES
                )
                if earliest_arrival_vd <= job_b.window_end_t:
                    arcs.append(JobChainArc(
                        from_job_id=job_a.job_id,
                        to_job_id=job_b.job_id,
                        chain_type=ChainType.VEHICLE_DRIVER,
                        travel_minutes=pair.driving_minutes,
                        turnaround_minutes=_TURNAROUND_MINUTES,
                    ))

    return arcs
