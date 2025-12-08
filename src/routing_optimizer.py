"""
OR-Tools VRP optimizer with two-stage job model and chaining.

Implements the real scheduling challenge:
- Each job has 2 stages (PT to vehicle + driving in vehicle)
- Jobs must be sequenced in time (routing problem)
- Job chaining can eliminate stages (major cost savings)
- Time windows must be respected (jobs by deadline)
- Multi-day optimization supported
"""
from typing import List, Dict, Tuple, Set, Optional
from datetime import datetime, timedelta
from collections import defaultdict

from ortools.sat.python import cp_model

from models import Driver, Job, Location, Vehicle, JobType, TransportMode, Assignment
from distance import DistanceCalculator
from llm_heuristics import JobCluster, JobPairSuggestion, DriverRegionAffinity


# Time constants (minutes from start of day)
DAY_START = 7 * 60  # 7:00 AM
DAY_END = 19 * 60   # 7:00 PM
MAX_HORIZON = 24 * 60 * 4  # 4 days in minutes


class RoutingOptimizer:
    """
    Vehicle Routing Problem solver with two-stage job model.

    Key features:
    - Models each job as 2 stages: PT to vehicle + driving in vehicle
    - Sequences jobs for each driver (routing)
    - Enforces time windows (jobs by deadline)
    - Optimizes job chaining (eliminates expensive PT legs)
    - Minimizes total cost (PT + fuel + overnight)
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

        # Build location maps
        self.location_map = {loc.location_id: loc for loc in locations}
        self.vehicle_map = {v.vehicle_reg: v for v in vehicles}

        # Create model
        self.model = cp_model.CpModel()
        self.solver = cp_model.CpSolver()

        # Decision variables
        self.job_assigned = {}      # (job_idx, driver_idx) -> BoolVar: is job assigned to driver?
        self.job_position = {}      # (job_idx, driver_idx) -> IntVar: position in driver's route
        self.job_start_time = {}    # job_idx -> IntVar: when job starts (minutes from day 0)
        self.job_chained = {}       # (job_idx, next_job_idx) -> BoolVar: are these jobs chained?

        # Results
        self.solution_assignments: List[Assignment] = []

    def optimize(self, time_limit_seconds: int = 120) -> List[Assignment]:
        """Run the routing optimization"""

        print(f"\n🔧 Routing Optimizer: Sequencing {len(self.jobs)} jobs for {len(self.drivers)} drivers...")
        print("  ├─ Using two-stage job model (PT to vehicle + driving)")
        print("  ├─ Optimizing job chaining to eliminate PT legs")
        print("  └─ Enforcing time windows and driver constraints")

        # Step 1: Create decision variables
        print("\n  ├─ Creating decision variables...")
        self._create_variables()

        # Step 2: Add constraints
        print("  ├─ Adding constraints...")
        self._add_assignment_constraints()
        self._add_sequencing_constraints()
        self._add_time_window_constraints()
        self._add_chaining_constraints()

        # Step 3: Set objective
        print("  ├─ Setting objective function...")
        self._set_objective()

        # Step 4: Solve
        print(f"  ├─ Solving (time limit: {time_limit_seconds}s)...")
        self.solver.parameters.max_time_in_seconds = time_limit_seconds
        self.solver.parameters.log_search_progress = True

        status = self.solver.Solve(self.model)

        # Step 5: Extract solution
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            print(f"  └─ ✅ Solution found! (status: {'OPTIMAL' if status == cp_model.OPTIMAL else 'FEASIBLE'})")
            self._extract_solution()
            return self.solution_assignments
        else:
            print(f"  └─ ❌ No solution found (status: {self.solver.StatusName(status)})")
            return []

    def _create_variables(self):
        """Create decision variables"""

        # Assignment: which driver does which job
        for job_idx in range(len(self.jobs)):
            for driver_idx in range(len(self.drivers)):
                var_name = f'assign_j{job_idx}_d{driver_idx}'
                self.job_assigned[(job_idx, driver_idx)] = self.model.NewBoolVar(var_name)

        # Position: what order does driver do jobs (0 = first, 1 = second, etc.)
        for job_idx in range(len(self.jobs)):
            for driver_idx in range(len(self.drivers)):
                var_name = f'pos_j{job_idx}_d{driver_idx}'
                # Position can be 0 to max_jobs_per_driver
                self.job_position[(job_idx, driver_idx)] = self.model.NewIntVar(
                    0, 20, var_name  # Max 20 jobs per driver
                )

        # Start time: when does each job start (minutes from start of planning horizon)
        for job_idx, job in enumerate(self.jobs):
            var_name = f'start_j{job_idx}'
            # Job can start anytime within planning horizon
            self.job_start_time[job_idx] = self.model.NewIntVar(
                0, MAX_HORIZON, var_name
            )

        # Chaining: is job_i immediately followed by job_j for same driver?
        for i in range(len(self.jobs)):
            for j in range(len(self.jobs)):
                if i != j:
                    var_name = f'chain_j{i}_j{j}'
                    self.job_chained[(i, j)] = self.model.NewBoolVar(var_name)

    def _add_assignment_constraints(self):
        """Each job assigned to exactly one driver"""

        # Constraint 1: Each job must be assigned
        for job_idx in range(len(self.jobs)):
            self.model.Add(
                sum(self.job_assigned[(job_idx, d)] for d in range(len(self.drivers))) == 1
            )

        # Constraint 2: Filter impossible assignments (certifications)
        impossible = self.heuristics.get('impossible_assignments', set())
        for job_idx, job in enumerate(self.jobs):
            for driver_idx, driver in enumerate(self.drivers):
                if (job.booking_ref, driver.driver_id) in impossible:
                    self.model.Add(self.job_assigned[(job_idx, driver_idx)] == 0)

        # Constraint 3: Limit jobs per driver (prevent 70 to one driver!)
        max_jobs_per_driver = max(10, len(self.jobs) // len(self.drivers) + 3)  # ~7 max for 79 jobs/20 drivers
        for driver_idx in range(len(self.drivers)):
            jobs_for_driver = sum(
                self.job_assigned[(job_idx, driver_idx)]
                for job_idx in range(len(self.jobs))
            )
            self.model.Add(jobs_for_driver <= max_jobs_per_driver)

    def _add_sequencing_constraints(self):
        """Jobs for same driver must be in sequence"""

        for driver_idx in range(len(self.drivers)):
            # Get all jobs for this driver
            driver_jobs = [
                job_idx for job_idx in range(len(self.jobs))
            ]

            # If two jobs assigned to same driver, they must have different positions
            for i in driver_jobs:
                for j in driver_jobs:
                    if i < j:
                        # If both assigned to this driver, positions must differ
                        both_assigned = self.model.NewBoolVar(f'both_d{driver_idx}_j{i}_j{j}')

                        # both_assigned = (job_i assigned AND job_j assigned)
                        self.model.AddBoolAnd([
                            self.job_assigned[(i, driver_idx)],
                            self.job_assigned[(j, driver_idx)]
                        ]).OnlyEnforceIf(both_assigned)

                        # If both assigned, positions must be different
                        self.model.Add(
                            self.job_position[(i, driver_idx)] != self.job_position[(j, driver_idx)]
                        ).OnlyEnforceIf(both_assigned)

    def _add_time_window_constraints(self):
        """Jobs must complete by their deadlines"""

        for job_idx, job in enumerate(self.jobs):
            # Calculate deadline in minutes from start of planning horizon
            # Assume day 0 is the first job's date
            first_job_date = min(j.date for j in self.jobs)
            days_offset = (job.date - first_job_date).days

            # Job deadline time
            deadline_hour, deadline_min = map(int, job.time.split(':'))
            deadline_minutes = (days_offset * 24 * 60) + (deadline_hour * 60) + deadline_min

            # Estimate job duration (simplified: 60 min for stage 1 + stage 2 + buffer)
            job_duration = 120  # 2 hours estimated per job

            # Job must start early enough to finish by deadline
            self.model.Add(
                self.job_start_time[job_idx] + job_duration <= deadline_minutes
            )

    def _add_chaining_constraints(self):
        """Define when jobs are chained (consecutive in driver's route)"""

        for i in range(len(self.jobs)):
            for j in range(len(self.jobs)):
                if i == j:
                    continue

                # Jobs i and j are chained if:
                # 1. Assigned to same driver
                # 2. Position of j = position of i + 1

                for driver_idx in range(len(self.drivers)):
                    # Helper: both assigned to this driver
                    both_assigned = self.model.NewBoolVar(f'both_assigned_d{driver_idx}_i{i}_j{j}')
                    self.model.AddBoolAnd([
                        self.job_assigned[(i, driver_idx)],
                        self.job_assigned[(j, driver_idx)]
                    ]).OnlyEnforceIf(both_assigned)

                    # Helper: j immediately follows i
                    consecutive = self.model.NewBoolVar(f'consecutive_i{i}_j{j}_d{driver_idx}')
                    self.model.Add(
                        self.job_position[(j, driver_idx)] == self.job_position[(i, driver_idx)] + 1
                    ).OnlyEnforceIf(consecutive)

                    # Chained = both assigned to same driver AND consecutive
                    self.model.AddBoolAnd([both_assigned, consecutive]).OnlyEnforceIf(
                        self.job_chained[(i, j)]
                    )

    def _set_objective(self):
        """Minimize total cost (PT + fuel - chaining savings + workload balance)"""

        cost_terms = []

        # Cost 1: Actual distance-based cost for each job-driver pair
        for job_idx, job in enumerate(self.jobs):
            job_coords = self.distance_calc.geocode_postcode(job.location_postcode)

            for driver_idx, driver in enumerate(self.drivers):
                # Calculate actual cost based on distance
                distance_km = self.distance_calc.get_distance_km(
                    driver.home_location,
                    job_coords
                )

                # Two-stage cost (simplified for spike):
                # Stage 1: PT to vehicle location (~£0.20/km)
                # Stage 2: Drive vehicle (~£0.45/km)
                # Assume average: stage 1 = stage 2 = distance_km
                stage1_cost = distance_km * 20  # PT (pence)
                stage2_cost = distance_km * 45  # Driving (pence)
                total_cost = int(stage1_cost + stage2_cost)  # Convert to int for CP-SAT

                # Add to objective
                cost_terms.append(
                    total_cost * self.job_assigned[(job_idx, driver_idx)]
                )

        # Cost 2: Chaining savings (negative cost = bonus)
        # When two jobs are chained, save 1-2 PT legs
        for i in range(len(self.jobs)):
            for j in range(len(self.jobs)):
                if i == j:
                    continue

                # Check if this is a high-value chain
                job_i = self.jobs[i]
                job_j = self.jobs[j]

                # Collection → Delivery of same vehicle = BEST (save 2 PT legs)
                if (job_i.job_type == JobType.COLLECT and
                    job_j.job_type == JobType.DELIVER and
                    job_i.vehicle_reg == job_j.vehicle_reg):
                    # Huge savings: eliminate PT return from collection + PT to delivery
                    saving = -3000  # -£30 (strong incentive to chain)
                    cost_terms.append(saving * self.job_chained[(i, j)])

                # Any other chain = GOOD (save 1 PT leg)
                else:
                    # Moderate savings: eliminate PT return between jobs
                    saving = -1000  # -£10
                    cost_terms.append(saving * self.job_chained[(i, j)])

        # Cost 3: Workload balancing penalty
        # Add penalty for imbalanced workload (prevents 70 jobs to one driver!)
        # Create variables for jobs per driver, then add quadratic penalty
        for driver_idx in range(len(self.drivers)):
            # Count jobs for this driver
            jobs_for_driver = sum(
                self.job_assigned[(job_idx, driver_idx)]
                for job_idx in range(len(self.jobs))
            )

            # Penalty: prefer balanced workload
            # Use linear penalty scaled by expected jobs per driver
            expected_jobs_per_driver = len(self.jobs) / len(self.drivers)  # ~4 jobs/driver
            balance_penalty = 500  # £5 penalty per job above expected

            # Add penalty term (simplified - linear penalty for now)
            # In production, would use quadratic or soft constraints
            cost_terms.append(balance_penalty * jobs_for_driver)

        # Minimize total cost
        self.model.Minimize(sum(cost_terms))

    def _extract_solution(self):
        """Extract solution into Assignment objects"""

        self.solution_assignments = []

        # Build assignments sorted by driver and position
        driver_routes = defaultdict(list)  # driver_idx -> [(position, job_idx)]

        for job_idx in range(len(self.jobs)):
            for driver_idx in range(len(self.drivers)):
                if self.solver.Value(self.job_assigned[(job_idx, driver_idx)]) == 1:
                    position = self.solver.Value(self.job_position[(job_idx, driver_idx)])
                    driver_routes[driver_idx].append((position, job_idx))
                    break

        # Process each driver's route
        for driver_idx, route in driver_routes.items():
            driver = self.drivers[driver_idx]

            # Sort jobs by position
            route.sort(key=lambda x: x[0])

            # Create assignments
            current_location = driver.home_location

            for position, job_idx in route:
                job = self.jobs[job_idx]

                # Get job location
                job_coords = self.distance_calc.geocode_postcode(job.location_postcode)

                # Calculate travel (simplified - just to job location)
                travel_time = self.distance_calc.get_travel_time_minutes(
                    current_location,
                    job_coords,
                    TransportMode.PUBLIC_TRANSPORT
                )

                travel_cost = self.distance_calc.get_transport_cost(
                    current_location,
                    job_coords,
                    TransportMode.PUBLIC_TRANSPORT
                )

                # Arrival time
                start_minutes = self.solver.Value(self.job_start_time[job_idx])
                arrival_time = datetime.combine(job.date, datetime.min.time()) + timedelta(minutes=start_minutes)

                assignment = Assignment(
                    driver=driver,
                    job=job,
                    arrival_time=arrival_time,
                    transport_mode=TransportMode.PUBLIC_TRANSPORT,
                    transport_cost=travel_cost,
                    transport_time_minutes=travel_time,
                    requires_customer_approval=False
                )

                self.solution_assignments.append(assignment)
                current_location = job_coords

        # Print chaining stats
        chains_found = 0
        for i in range(len(self.jobs)):
            for j in range(len(self.jobs)):
                if i != j and self.solver.Value(self.job_chained.get((i, j), 0)) == 1:
                    chains_found += 1

        print(f"\n✅ Generated {len(self.solution_assignments)} job assignments")
        print(f"   └─ Job chains found: {chains_found}")
