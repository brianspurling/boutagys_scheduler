"""
LLM-powered heuristics for job analysis and preprocessing.

This module uses geographical analysis and business logic to:
1. Cluster jobs by region
2. Suggest job pairings/chains
3. Calculate driver-region affinity
4. Pre-filter impossible assignments
5. Provide initial cost estimates

The output is an intermediary CSV that shows the LLM's "thinking"
before the OR-Tools optimizer refines the schedule.
"""
from typing import List, Dict, Set, Tuple, Optional
from collections import defaultdict
from datetime import datetime, timedelta

from models import Driver, Job, Location, Vehicle, JobType, TransportMode
from distance import DistanceCalculator


class JobCluster:
    """A geographical cluster of jobs"""
    def __init__(self, cluster_id: str, region_name: str):
        self.cluster_id = cluster_id
        self.region_name = region_name
        self.jobs: List[Job] = []
        self.center_lat: float = 0.0
        self.center_lon: float = 0.0

    def add_job(self, job: Job, lat: float, lon: float):
        """Add a job to this cluster"""
        self.jobs.append(job)
        # Update centroid
        n = len(self.jobs)
        self.center_lat = (self.center_lat * (n - 1) + lat) / n
        self.center_lon = (self.center_lon * (n - 1) + lon) / n


class JobPairSuggestion:
    """A suggested pairing of two jobs"""
    def __init__(
        self,
        job1: Job,
        job2: Job,
        chain_type: str,
        cost_saving: float,
        time_saving_minutes: int,
        confidence: str  # "high", "medium", "low"
    ):
        self.job1 = job1
        self.job2 = job2
        self.chain_type = chain_type
        self.cost_saving = cost_saving
        self.time_saving_minutes = time_saving_minutes
        self.confidence = confidence


class DriverRegionAffinity:
    """Driver's affinity to a geographical region"""
    def __init__(self, driver: Driver, cluster: JobCluster, affinity_score: float, reason: str):
        self.driver = driver
        self.cluster = cluster
        self.affinity_score = affinity_score  # 0.0 to 1.0
        self.reason = reason


class LLMHeuristics:
    """
    Intelligent preprocessing of jobs using geographical and business logic.

    This represents the "LLM thinking" phase that happens before optimization.
    """

    def __init__(self, distance_calc: DistanceCalculator):
        self.distance_calc = distance_calc
        self.clusters: List[JobCluster] = []
        self.job_pairs: List[JobPairSuggestion] = []
        self.driver_affinities: List[DriverRegionAffinity] = []

    def analyze_jobs(
        self,
        jobs: List[Job],
        drivers: List[Driver],
        locations: List[Location],
        vehicles: List[Vehicle]
    ) -> Dict:
        """
        Main analysis function: cluster jobs, suggest pairs, calculate affinities.

        Returns a dictionary with all heuristics for output.
        """
        print(f"\n🧠 LLM Heuristics: Analyzing {len(jobs)} jobs for {len(drivers)} drivers...")

        # Step 1: Geographical clustering
        print("  ├─ Clustering jobs by region...")
        self.clusters = self._cluster_jobs_geographically(jobs)
        print(f"  │  └─ Found {len(self.clusters)} geographical clusters")

        # Step 2: Job pairing suggestions
        print("  ├─ Identifying job chain opportunities...")
        self.job_pairs = self._suggest_job_pairs(jobs, vehicles, locations)
        print(f"  │  └─ Found {len(self.job_pairs)} potential job chains")

        # Step 3: Driver-region affinity
        print("  ├─ Calculating driver-region affinity...")
        self.driver_affinities = self._calculate_driver_affinities(drivers, self.clusters)
        print(f"  │  └─ Calculated {len(self.driver_affinities)} affinity scores")

        # Step 4: Pre-filter impossible assignments
        print("  └─ Pre-filtering impossible assignments...")
        impossible = self._identify_impossible_assignments(jobs, drivers, vehicles)
        print(f"     └─ Filtered out {len(impossible)} impossible job-driver pairs")

        return {
            'clusters': self.clusters,
            'job_pairs': self.job_pairs,
            'driver_affinities': self.driver_affinities,
            'impossible_assignments': impossible
        }

    def _cluster_jobs_geographically(self, jobs: List[Job]) -> List[JobCluster]:
        """
        Cluster jobs by geographical region.

        Uses simple distance-based clustering for spike.
        Later could use k-means or DBSCAN.
        """
        # Define regions based on postcode areas
        region_map = {
            'Central London': ['EC', 'WC', 'E1', 'N1'],
            'East London': ['E', 'IG', 'RM'],
            'North London': ['N', 'NW', 'HA'],
            'South East London': ['SE', 'BR', 'CR'],
            'South West London': ['SW', 'TW', 'KT'],
            'West London': ['W', 'UB'],
            'Greater London': ['EN', 'HA', 'WD'],
            'South': ['GU', 'RH', 'BN', 'PO', 'SO', 'BH', 'SP'],
            'South East': ['ME', 'TN', 'CT', 'RG', 'SL'],
            'South West': ['BA', 'BS', 'TA', 'GL'],
            'Midlands': ['B', 'CV', 'DY', 'WS', 'WV'],
            'East': ['CB', 'PE', 'IP', 'NR'],
            'North': ['NG', 'DE', 'LE', 'NN'],
            'Wales': ['CF', 'SA', 'NP', 'HR']
        }

        # Reverse map: postcode area -> region
        area_to_region = {}
        for region, areas in region_map.items():
            for area in areas:
                area_to_region[area] = region

        # Cluster jobs by region
        clusters_dict = defaultdict(lambda: JobCluster(f"C{len(clusters_dict)+1:02d}", "Unknown"))

        for job in jobs:
            # Get postcode area
            postcode_area = job.location_postcode.split()[0][:2]
            region = area_to_region.get(postcode_area, 'Other')

            # Get or create cluster
            if region not in clusters_dict:
                cluster = JobCluster(f"C{len(clusters_dict)+1:02d}", region)
                clusters_dict[region] = cluster
            else:
                cluster = clusters_dict[region]

            # Geocode and add to cluster
            coords = self.distance_calc.geocode_postcode(job.location_postcode)
            cluster.add_job(job, coords[0], coords[1])

        return list(clusters_dict.values())

    def _suggest_job_pairs(
        self,
        jobs: List[Job],
        vehicles: List[Vehicle],
        locations: List[Location]
    ) -> List[JobPairSuggestion]:
        """
        Suggest high-value job pairings/chains.

        Analyzes the 6 chain types and estimates cost savings.
        """
        suggestions = []

        # Separate jobs by type and date
        deliveries_by_date = defaultdict(list)
        collections_by_date = defaultdict(list)

        for job in jobs:
            if job.job_type == JobType.DELIVER:
                deliveries_by_date[job.date].append(job)
            else:
                collections_by_date[job.date].append(job)

        # For each date, look for good pairings
        for job_date in deliveries_by_date.keys():
            deliveries = deliveries_by_date[job_date]
            collections = collections_by_date.get(job_date, [])

            # Chain Type 1: Collection -> Delivery (OPTIMAL - same vehicle)
            # Look for collection/delivery pairs of the same vehicle
            for collection in collections:
                if not collection.vehicle_reg:
                    continue
                for delivery in deliveries:
                    if delivery.vehicle_reg == collection.vehicle_reg:
                        # Same vehicle! Optimal chain
                        suggestions.append(JobPairSuggestion(
                            collection, delivery,
                            "Collection->Delivery (same vehicle)",
                            cost_saving=15.0,  # Saves PT leg
                            time_saving_minutes=60,
                            confidence="high"
                        ))

            # Chain Type 2: Delivery -> Collection (different vehicles, same region)
            for delivery in deliveries:
                for collection in collections:
                    # Check if they're in similar locations
                    coords1 = self.distance_calc.geocode_postcode(delivery.location_postcode)
                    coords2 = self.distance_calc.geocode_postcode(collection.location_postcode)
                    distance_km = self.distance_calc.get_distance_km(coords1, coords2)

                    if distance_km < 10:  # Within 10km
                        # Check timing compatibility (collection after delivery)
                        time_gap = (collection.datetime - delivery.datetime).total_seconds() / 60
                        if 30 <= time_gap <= 180:  # 30min to 3 hours gap
                            suggestions.append(JobPairSuggestion(
                                delivery, collection,
                                "Delivery->Collection (nearby)",
                                cost_saving=8.0,
                                time_saving_minutes=int(time_gap),
                                confidence="medium"
                            ))

            # Chain Type 3: Delivery -> Delivery (via storage)
            # Look for two deliveries where first could route via storage to pick up second vehicle
            # (More complex - skip for initial spike)

            # Chain Type 4: Collection -> Collection
            # Similar to above
            # (Skip for initial spike)

        return suggestions

    def _calculate_driver_affinities(
        self,
        drivers: List[Driver],
        clusters: List[JobCluster]
    ) -> List[DriverRegionAffinity]:
        """
        Calculate each driver's affinity to each geographical cluster.

        Based on:
        - Proximity of driver's home to cluster
        - Driver's notes (e.g., "Kensington area")
        """
        affinities = []

        for driver in drivers:
            driver_coords = driver.home_location

            for cluster in clusters:
                # Calculate distance from driver home to cluster center
                distance_km = self.distance_calc.get_distance_km(
                    driver_coords,
                    (cluster.center_lat, cluster.center_lon)
                )

                # Affinity score: inverse of distance (closer = higher affinity)
                # Score from 0.0 (far) to 1.0 (very close)
                max_distance = 100  # km
                affinity_score = max(0.0, 1.0 - (distance_km / max_distance))

                # Boost affinity if driver's notes mention this region
                reason = f"{distance_km:.1f}km from home"
                if cluster.region_name.lower() in driver.notes.lower():
                    affinity_score = min(1.0, affinity_score * 1.5)
                    reason = f"Home area ({reason})"

                # Only record significant affinities
                if affinity_score > 0.2:
                    affinities.append(DriverRegionAffinity(
                        driver, cluster, affinity_score, reason
                    ))

        # Sort by affinity score (highest first)
        affinities.sort(key=lambda a: a.affinity_score, reverse=True)

        return affinities

    def _identify_impossible_assignments(
        self,
        jobs: List[Job],
        drivers: List[Driver],
        vehicles: List[Vehicle]
    ) -> Set[Tuple[str, str]]:
        """
        Pre-filter job-driver pairs that are impossible.

        Returns set of (job_booking_ref, driver_id) tuples to exclude.
        """
        impossible = set()

        for job in jobs:
            for driver in drivers:
                # Check certification
                if not driver.can_drive_vehicle_group(job.vehicle_group):
                    impossible.add((job.booking_ref, driver.driver_id))
                    continue

                # Check unavailability
                if job.date in driver.unavailable_dates:
                    impossible.add((job.booking_ref, driver.driver_id))
                    continue

        return impossible
