"""
Generate output CSVs for LLM heuristics and final schedule.
"""
import csv
from pathlib import Path
from typing import List, Dict
from datetime import datetime

from models import Driver, Job, Assignment
from llm_heuristics import JobCluster, JobPairSuggestion, DriverRegionAffinity


def write_llm_heuristics_output(
    heuristics_result: Dict,
    output_dir: str = 'output'
) -> None:
    """
    Write LLM heuristics analysis to CSV files.

    Creates multiple CSV files showing the LLM's "thinking":
    1. job_clusters.csv - Geographical clustering
    2. job_pair_suggestions.csv - Suggested chains
    3. driver_region_affinity.csv - Driver-region matching
    4. impossible_assignments.csv - Pre-filtered assignments
    """
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 1. Job Clusters
    clusters_file = output_path / f'llm_01_job_clusters_{timestamp}.csv'
    with open(clusters_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'cluster_id', 'region_name', 'num_jobs', 'center_lat', 'center_lon',
            'job_refs', 'job_types', 'job_times'
        ])

        for cluster in heuristics_result['clusters']:
            job_refs = '; '.join([j.booking_ref for j in cluster.jobs])
            job_types = '; '.join([j.job_type.value for j in cluster.jobs])
            job_times = '; '.join([f"{j.date.strftime('%m/%d')} {j.time}" for j in cluster.jobs])

            writer.writerow([
                cluster.cluster_id,
                cluster.region_name,
                len(cluster.jobs),
                f"{cluster.center_lat:.4f}",
                f"{cluster.center_lon:.4f}",
                job_refs,
                job_types,
                job_times
            ])

    print(f"  ├─ LLM Output: {clusters_file}")

    # 2. Job Pair Suggestions
    pairs_file = output_path / f'llm_02_job_pair_suggestions_{timestamp}.csv'
    with open(pairs_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'job1_ref', 'job1_type', 'job1_time', 'job1_location',
            'job2_ref', 'job2_type', 'job2_time', 'job2_location',
            'chain_type', 'cost_saving_gbp', 'time_saving_min', 'confidence'
        ])

        for pair in heuristics_result['job_pairs']:
            writer.writerow([
                pair.job1.booking_ref,
                pair.job1.job_type.value,
                f"{pair.job1.date.strftime('%m/%d')} {pair.job1.time}",
                pair.job1.location_postcode,
                pair.job2.booking_ref,
                pair.job2.job_type.value,
                f"{pair.job2.date.strftime('%m/%d')} {pair.job2.time}",
                pair.job2.location_postcode,
                pair.chain_type,
                f"{pair.cost_saving:.2f}",
                pair.time_saving_minutes,
                pair.confidence
            ])

    print(f"  ├─ LLM Output: {pairs_file}")

    # 3. Driver-Region Affinity
    affinity_file = output_path / f'llm_03_driver_region_affinity_{timestamp}.csv'
    with open(affinity_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'driver_id', 'driver_name', 'region', 'num_jobs_in_region',
            'affinity_score', 'reason'
        ])

        for affinity in heuristics_result['driver_affinities']:
            writer.writerow([
                affinity.driver.driver_id,
                affinity.driver.name,
                affinity.cluster.region_name,
                len(affinity.cluster.jobs),
                f"{affinity.affinity_score:.3f}",
                affinity.reason
            ])

    print(f"  ├─ LLM Output: {affinity_file}")

    # 4. Impossible Assignments (filtered out)
    impossible_file = output_path / f'llm_04_impossible_assignments_{timestamp}.csv'
    with open(impossible_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['job_ref', 'driver_id', 'reason'])

        for job_ref, driver_id in heuristics_result['impossible_assignments']:
            writer.writerow([job_ref, driver_id, 'Certification mismatch or unavailable'])

    print(f"  └─ LLM Output: {impossible_file}")

    print(f"\n📊 LLM Heuristics outputs written to: {output_dir}/")


def write_final_schedule(
    assignments: List[Assignment],
    output_dir: str = 'output',
    filename: str = 'final_schedule.csv'
) -> None:
    """
    Write the final optimized schedule to CSV.

    This is the output from the OR-Tools optimizer.
    """
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)

    filepath = output_path / filename

    with open(filepath, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'job_driver', 'date', 'time', 'action', 'booking_ref',
            'vehicle_reg', 'vehicle_group', 'location_postcode',
            'customer_name', 'arrival_time', 'transport_mode',
            'transport_cost_gbp', 'transport_time_min',
            'customer_approval_required', 'notes'
        ])

        # Sort by driver, then by arrival time
        sorted_assignments = sorted(
            assignments,
            key=lambda a: (a.driver.driver_id, a.arrival_time)
        )

        for assignment in sorted_assignments:
            writer.writerow([
                assignment.driver.driver_id,
                assignment.job.date.strftime('%Y-%m-%d'),
                assignment.job.time,
                assignment.job.job_type.value,
                assignment.job.booking_ref,
                assignment.job.vehicle_reg or '',
                assignment.job.vehicle_group,
                assignment.job.location_postcode,
                assignment.job.customer_name,
                assignment.arrival_time.strftime('%H:%M'),
                assignment.transport_mode.value,
                f"{assignment.transport_cost:.2f}",
                assignment.transport_time_minutes,
                'yes' if assignment.requires_customer_approval else 'no',
                assignment.job.notes
            ])

    print(f"\n✅ Final schedule written to: {filepath}")
