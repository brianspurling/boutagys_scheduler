"""
OR-Tools based scheduler optimizer.

Uses constraint programming (CP-SAT) to assign jobs to drivers while:
- Minimizing total cost (public transport + fuel)
- Respecting driver constraints (hours, certifications, time windows)
- Leveraging LLM heuristics as hints for better solutions
"""
from typing import List, Dict, Tuple, Set
from datetime import datetime, timedelta
from collections import defaultdict

from ortools.sat.python import cp_model

from models import Driver, Job, Location, Vehicle, JobType, TransportMode, Assignment
from distance import DistanceCalculator
from llm_heuristics import JobCluster, JobPairSuggestion, DriverRegionAffinity


class ScheduleOptimizer:
    """
    Optimizes job assignments using OR-Tools CP-SAT solver.

    Takes LLM heuristics as hints to guide the search toward good solutions.
    """

    def __init__(
        self,
        jobs: List[Job],
        drivers: List[Driver],
        locations: List[Location],
        vehicles: List[Vehicle],
        distance_calc: DistanceCalculator,
        heuristics: Dict
    ):
        self.jobs = jobs
        self.drivers = drivers
        self.locations = locations
        self.vehicles = vehicles
        self.distance_calc = distance_calc
        self.heuristics = heuristics

        # Create model
        self.model = cp_model.CpModel()
        self.solver = cp_model.CpSolver()

        # Variables and mappings
        self.assignment_vars = {}  # (job_idx, driver_idx) -> BoolVar
        self.job_times = {}  # job_idx -> IntVar (minutes from start of day)

        # Results
        self.solution_assignments: List[Assignment] = []

    def optimize(self, time_limit_seconds: int = 60) -> List[Assignment]:
        """
        Run the optimization and return job assignments.

        Args:
            time_limit_seconds: Maximum solve time

        Returns:
            List of Assignment objects with job-driver pairings
        """
        print(f"\n🔧 OR-Tools Optimizer: Assigning {len(self.jobs)} jobs to {len(self.drivers)} drivers...")

        # Step 1: Create decision variables
        print("  ├─ Creating decision variables...")
        self._create_variables()

        # Step 2: Add hard constraints
        print("  ├─ Adding constraints...")
        self._add_constraints()

        # Step 3: Add objective function
        print("  ├─ Setting objective function...")
        self._set_objective()

        # Step 4: Add LLM hints
        print("  ├─ Adding LLM heuristics as hints...")
        self._add_heuristic_hints()

        # Step 5: Solve
        print(f"  ├─ Solving (time limit: {time_limit_seconds}s)...")
        self.solver.parameters.max_time_in_seconds = time_limit_seconds
        status = self.solver.Solve(self.model)

        # Step 6: Extract solution
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            print(f"  └─ Solution found! (status: {'OPTIMAL' if status == cp_model.OPTIMAL else 'FEASIBLE'})")
            self._extract_solution()
            return self.solution_assignments
        else:
            print(f"  └─ ❌ No solution found (status: {status})")
            return []

    def _create_variables(self):
        """Create decision variables for the optimization problem"""
        # Assignment variables: assignment[j][d] = 1 if job j assigned to driver d
        for job_idx, job in enumerate(self.jobs):
            for driver_idx, driver in enumerate(self.drivers):
                var_name = f'assign_j{job_idx}_d{driver_idx}'
                self.assignment_vars[(job_idx, driver_idx)] = self.model.NewBoolVar(var_name)

    def _add_constraints(self):
        """Add hard constraints to the model"""

        # Constraint 1: Each job must be assigned to exactly one driver
        for job_idx, job in enumerate(self.jobs):
            self.model.Add(
                sum(self.assignment_vars[(job_idx, d)] for d in range(len(self.drivers))) == 1
            )

        # Constraint 2: Driver certification requirements
        impossible_assignments = self.heuristics.get('impossible_assignments', set())
        for job_idx, job in enumerate(self.jobs):
            for driver_idx, driver in enumerate(self.drivers):
                # If this assignment is impossible (certification mismatch), force it to 0
                if (job.booking_ref, driver.driver_id) in impossible_assignments:
                    self.model.Add(self.assignment_vars[(job_idx, driver_idx)] == 0)

        # Constraint 3: Driver working hours (simplified for spike)
        # For each driver, limit total jobs to reasonable number
        # NOTE: Relaxed for spike - in production would model actual times
        for driver_idx, driver in enumerate(self.drivers):
            total_jobs = sum(
                self.assignment_vars[(job_idx, driver_idx)]
                for job_idx in range(len(self.jobs))
            )
            # Very relaxed constraint for spike: allow up to 10 jobs per driver
            # (In production, would calculate actual time windows and travel times)
            max_jobs = 10
            self.model.Add(total_jobs <= max_jobs)

    def _set_objective(self):
        """Define the objective function to minimize"""

        # Build cost matrix: cost[job_idx][driver_idx] = estimated cost
        cost_matrix = []

        for job_idx, job in enumerate(self.jobs):
            job_costs = []
            job_coords = self.distance_calc.geocode_postcode(job.location_postcode)

            for driver_idx, driver in enumerate(self.drivers):
                # Estimate cost: distance from driver home to job location
                # (Simplified - in reality would consider full route)
                distance_km = self.distance_calc.get_distance_km(
                    driver.home_location,
                    job_coords
                )

                # Cost: public transport to job (~£0.20/km) + driving back (~£0.45/km)
                # Simplified cost model for spike
                cost = distance_km * 0.65  # Average cost per km

                # Scale to integer for CP-SAT (multiply by 100 for precision)
                job_costs.append(int(cost * 100))

            cost_matrix.append(job_costs)

        # Objective: minimize total cost
        objective_terms = []
        for job_idx in range(len(self.jobs)):
            for driver_idx in range(len(self.drivers)):
                cost = cost_matrix[job_idx][driver_idx]
                var = self.assignment_vars[(job_idx, driver_idx)]
                objective_terms.append(cost * var)

        self.model.Minimize(sum(objective_terms))

    def _add_heuristic_hints(self):
        """Add LLM heuristics as hints to guide the solver"""

        # Hint 1: Driver-region affinity
        # If driver has high affinity for a job's region, hint that assignment
        driver_affinities = self.heuristics.get('driver_affinities', [])

        # Build mapping: (driver, cluster) -> affinity_score
        affinity_map = {}
        for affinity in driver_affinities:
            key = (affinity.driver.driver_id, affinity.cluster.cluster_id)
            affinity_map[key] = affinity.affinity_score

        # For each job, find its cluster and suggest drivers with high affinity
        clusters = self.heuristics.get('clusters', [])
        job_to_cluster = {}
        for cluster in clusters:
            for job in cluster.jobs:
                job_to_cluster[job.booking_ref] = cluster

        # Add soft constraints (hints) for high-affinity assignments
        for job_idx, job in enumerate(self.jobs):
            if job.booking_ref not in job_to_cluster:
                continue

            cluster = job_to_cluster[job.booking_ref]

            for driver_idx, driver in enumerate(self.drivers):
                key = (driver.driver_id, cluster.cluster_id)
                if key in affinity_map and affinity_map[key] > 0.8:
                    # High affinity - hint this assignment
                    # (Hints don't force the solution, just guide the search)
                    self.model.AddHint(
                        self.assignment_vars[(job_idx, driver_idx)],
                        1  # Hint: assign this job to this driver
                    )

        # Hint 2: Job pair suggestions (DISABLED for spike simplicity)
        # If two jobs are suggested as a chain, try to assign to same driver
        # TODO: Implement job chaining in next phase
        # job_pairs = self.heuristics.get('job_pairs', [])
        pass

    def _extract_solution(self):
        """Extract the solution into Assignment objects"""
        self.solution_assignments = []

        for job_idx, job in enumerate(self.jobs):
            for driver_idx, driver in enumerate(self.drivers):
                # Check if this assignment was selected
                if self.solver.Value(self.assignment_vars[(job_idx, driver_idx)]) == 1:
                    # Calculate transport details
                    job_coords = self.distance_calc.geocode_postcode(job.location_postcode)

                    # Simplified: assume driver travels from home to job
                    transport_time_min = self.distance_calc.get_travel_time_minutes(
                        driver.home_location,
                        job_coords,
                        TransportMode.PUBLIC_TRANSPORT  # Simplified assumption
                    )

                    transport_cost = self.distance_calc.get_transport_cost(
                        driver.home_location,
                        job_coords,
                        TransportMode.PUBLIC_TRANSPORT
                    )

                    # Calculate arrival time (simplified: assume buffer before deadline)
                    arrival_time = job.deadline - timedelta(minutes=30)

                    assignment = Assignment(
                        driver=driver,
                        job=job,
                        arrival_time=arrival_time,
                        transport_mode=TransportMode.PUBLIC_TRANSPORT,
                        transport_cost=transport_cost,
                        transport_time_minutes=transport_time_min,
                        requires_customer_approval=False  # TODO: check early/late
                    )

                    self.solution_assignments.append(assignment)
                    break  # Found assignment for this job

        print(f"\n✅ Generated {len(self.solution_assignments)} job assignments")
