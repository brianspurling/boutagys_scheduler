# High-Level Architecture Specification: Vehicle Repositioning Solver

## 1. The Core Problem Statement
We are operating a **Vehicle Relocation Problem with Independent Crew**. Unlike standard delivery models (GPDP) which route parcels inside vehicles, our challenge is routing the vehicles themselves. We are transitioning from manual spreadsheet scheduling to an automated algorithmic solver.

In Operations Research terminology, this is a **Deterministic, Multi-Resource, Time-Dependent, Multi-Period Inventory-Routing Problem with External Transfer Modes**.

## 2. Operational Scale & Viability
This operation sits in the computational "sweet spot" — too complex for human calculation, but light enough to be solved in minutes by a modern algorithm without requiring enterprise supercomputers.
* **Volume:** ~100 relocation jobs (drop-offs and pick-ups) per day.
* **Resources:** ~700 assets (vans) and ~20 independent actors (drivers).
* **Asset Diversity:** The vehicle inventory is consolidated into ~10 distinct vehicle groups (e.g., V3, V5, D.B9).

## 3. Core Mathematical Constraints (The Rules)
The solver must strictly obey these parameters to ensure mathematical outputs are physically and legally possible:
* **Independent Crew Deadheading:** Drivers do not travel with the assets between jobs. The algorithm must calculate the time and cost of public transit or cycling to move drivers between nodes.
* **Heterogeneous Workforce (Skill Mapping):** Driver certifications are a simple binary (`van` and `van+truck`). The solver must apply binary constraints mapping qualified drivers to specific vehicle groups.
* **Driver Duty Limits:** The solver must track cumulative shift duration (driving + deadheading) and strictly enforce a `max_hours_per_day` (default 10) for each driver, utilizing a `can_overnight` boolean flag when necessary.
* **Spatially Distributed Inventory & State Transitions:** The system cannot assume a static hub-and-spoke model. The daily input will provide the exact starting coordinates of all 700 assets (often sitting at customer locations). The solver must mathematically track the state transitions of these vehicles across the 5-day rolling horizon, dynamically updating their starting nodes for Days 2-5 based on the simulated routing of the previous days.
* **Node Capacity Limits:** Physical storage locations have strict capacity constraints (e.g., Feltham = 30, Putney = 6, Wetlands = 70). The solver must track real-time spatial inventory and close locations when capacity is reached.
* **Time-Dependent Vehicle Availability:** Vehicles with future `availability_date` timestamps or scheduled maintenance must NOT be excluded from the matrix. Instead, the solver must register their current geographic coordinates but apply a **Time-Release Constraint**, locking the asset and preventing any routing assignments until its specific availability threshold is reached within the rolling horizon.
* **Dynamic Asset Assignment:** For delivery jobs where the specific vehicle is unassigned (TBA), the solver must dynamically select the most mathematically efficient vehicle from the distributed inventory that matches the required vehicle group.
* **The 2-Stage Job Model:** The solver must calculate and track *both* the deadhead transit time (PT/cycling) AND the physical driving time of the van itself, as both consume the driver's strict daily hour limit.
* **Geographic Parking Constraints:** The "Soft Time Window" flexibility is location-dependent. A pre-processing rule must block or heavily penalize early drop-offs in restricted, high-density city postcodes (e.g., SW1, EC1) where parking is not viable.
* **Turnaround Buffers for Direct Chaining:** The solver is highly encouraged to chain a vehicle collection directly into a new delivery to eliminate deadheading. However, when doing so, a mandatory temporal buffer (e.g., 45 minutes) must be injected between the two jobs to account for real-world cleaning and refueling.

## 4. The Optimization Strategy & Heuristics (How it Solves)
* **Soft Time Windows (VRPTW):** Customer bookings have highly flexible dates. Instead of using rigid deadlines, the system will apply cost penalties to evaluate the cheapest routing combinations.
* **Multi-Period Inventory Routing:** The solver must evaluate vehicle scarcity. It calculates the *opportunity cost* of dropping a van off early (using the flex window) versus preserving that asset for future unknown demand.
* **Rolling Horizon Execution:** To balance optimization with reality, the system evaluates a 4-to-5-day rolling look-ahead window.
* **NO Pre-Emptive Moves:** The solver operates purely deterministically. It only routes vans to fulfill actual, booked customer jobs. It must never predict future demand or pre-emptively shuffle empty vans to balance depot stock.
* **Demand-Driven Variable Generation (Job-Centric):** The CP-SAT model must be strictly Demand-Driven, not Asset-Driven. The script must NOT instantiate 5-day interval timelines or sequence variables for all 700 vehicles. Instead, the model's core variables must be built around the ~100 daily Bookings/Jobs. The 700 vehicles act purely as a stateful resource pool. For "TBA" jobs, the solver utilizes a simple integer assignment variable (`assigned_vehicle_id`) to pull the optimal asset from the pool, applying `NoOverlap` constraints only to the specific subset of vehicles actually activated by jobs.
* **Integer Time Resolution:** Because CP-SAT relies on integer arithmetic, time must be evaluated as discrete integer minutes (e.g., 15-minute buckets or exact minutes) rather than broad shifts (Morning/Afternoon) or fractional seconds.
* **Geographic Clustering:** A pre-processing script must group jobs into geographic zones (e.g., North West, South East) using spatial algorithms to reduce the search space before the heavy routing math begins.
* **Stochastic Transit Buffers:** Because deadhead transit times are unpredictable, the system must apply a static percentage time buffer (e.g., +15%) to all public transit calculations to absorb real-world delays.
* **Sparse Graph Generation (Pre-Processing Pruning):** To prevent memory overload and combinatorial explosion (e.g., generating millions of useless variables), the Python script must aggressively prune impossible arcs *before* instantiating CP-SAT variables. Because this is a national network, pruning must be based on **Temporal Feasibility**, NOT arbitrary geographic radius caps:
  * **Asset Sparsification (Physics Check):** For TBA deliveries, evaluate vehicles nationwide. Only prune a vehicle assignment if the physical driving time from the asset's current location to the job exceeds the time remaining before the strict booking deadline.
  * **Transit & Shift Feasibility:** Do not cap public transit duration. Long-haul trains (e.g., London to Newcastle) are explicitly permitted. Instead, prune `Driver` -> `Job` connections only if the combined duration of the transit leg + driving leg strictly exceeds the driver's `max_hours_per_day`, factoring in their `can_overnight` permission.
  * **Chaining Feasibility:** Pre-calculate `Job A` -> `Job B` chaining. If the completion time of Job A + transit/turnaround time + minimum driving time for Job B mathematically exceeds Job B's latest possible time window (or violates the driver's hours), the chain arc must be pruned.

## 5. Execution & Infrastructure
* **Continuous Time Horizon:** The solver must NOT model the 5-day horizon as discrete 24-hour loops that reset daily. Time must be modeled as a **Single Continuous Integer Timeline** (e.g., T=0 to T=7200 minutes). All jobs, transit legs, and driving legs must be instantiated as CP-SAT `IntervalVar` objects on this continuous line to natively handle overnight stays and multi-day asset states. Daily constraints (e.g., the 10-hour driver limit) must be enforced via **Hierarchical Shift Bounding**, where job intervals are forced inside a `Shift_Interval`, and the `Shift_Interval` duration is capped and bounded within specific 24-hour modulus windows.
* **Transit Time Caching (Asynchronous):** The system cannot calculate public transit API links synchronously during the solver run. Background scripts must query transit APIs (Google Maps/TfL) between postcodes and cache the resulting time matrix in a database.
* **Daily Replanning with Hard Freezing:** The solver runs at the end of the day to plan the next day. Once run, **Day 1 is Hard Frozen** for dispatch. The solver will maintain fluid, optimized drafts for Days 2-5, which are recalculated during the next daily run.
* **Solver Timeout Fallback:** If the scheduler cannot prove the absolute mathematically perfect solution within a 5-minute time limit, it must not crash. It will return the *Best Incumbent Solution* (the best valid schedule found before the clock expired).

## 6. Technical Path Forward
Standard routing SaaS (e.g., Onfleet, Route4Me) cannot decouple drivers from vehicles. The path forward is building a bespoke solver using an open-source library (e.g., **Google OR-Tools** leveraging **CP-SAT** or **MIP** under the hood). Alternatively, an Optimization-as-a-Service API (Nextmv, RouteQ) could be evaluated, but may lack the necessary customizability for independent crew deadheading.