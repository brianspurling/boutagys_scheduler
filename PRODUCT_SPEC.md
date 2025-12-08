# Van Rental Driver Scheduling System - Product Specification

**Version:** 1.0 (Draft)
**Date:** December 6, 2025
**Status:** For Review

---

## 1. Executive Summary

### Problem Statement
The van rental business currently manages driver scheduling manually using spreadsheets. With 20 drivers completing ~100 jobs daily, the manual process is extremely time-consuming and possibly sub-optimal schedules.

### Proposed Solution
An automated scheduling system that optimizes driver assignments and job sequencing to minimize costs while respecting all business constraints. The system will:
- Plan 4 days ahead with rolling updates
- Maximize job chaining to keep complete as many jobs as possible
- Optimize for job completion rate, fuel efficiency, public transport costs, and overnight stays
- Handle driver skills/certifications and working hour limits
- Allow human oversight and manual overrides
- Start with CSV/Google Sheets integration, with pathway to full API integration

### Expected Benefits
- **Cost Reduction:** [ESTIMATE: X%] reduction in fuel, public transport and overnight accommodation costs
- **Manager Time Savings:** [ESTIMATE: X hours/week] saved on manual scheduling
- **Driver Efficiency Imprvoement:** [ESTIMATE: X%] increase in jobs completed 
- **Flexibility:** Rapid re-optimization when jobs change
- **Scalability:** System can grow with business
- **Insights:** Data-driven understanding of scheduling patterns and costs

---

## 2. Business Context

### Current Operations
- **Fleet Size:** [TO CONFIRM: X vans, Y trucks, etc]
- **Driver Count:** 20 drivers
- **Daily Job Volume:** ~100 jobs/day (roughly 5 per driver)
- **Planning Horizon:** 4 days ahead
- **Current Process:** Manual spreadsheet-based assignment

### An Example 36 hours in the Life of a Driver

- The driver wakes at home in the London suburbs
- They don't already have a vehicle with them, so they check their schedule and hop on public transport to their first collection - from a nearby customer
- They get the keys from the customer and drive the van to another customer, also nearby, who's rental starts today. It's not too dirty, so the driver gives it a quick hoover at a gas station and arrives at the customer's location 10 minutes before the booked delivery time
- Then they're back on public transport and heading to one of the company storage locations to pick up another vehicle
- They get the keys from the staff member at the storage location and drive the van all the way up to a customer in Edinburgh
- (This delivery is a few days early, but there's a vehicle in Newcastle due to be picked up that's needed back in London tomorrow, so rather than sending a driver up to get it on public transport, it's great to get this delivery job done at the same time)
- With that delivery done, they jump on public transport, head down to Newcastle, and collect the next van
- It's the end of their day now, so they check into overnight accommodation
- The next day, they're back in their collected van and bringing it back down to London. It's filthy, so they go via a car wash then drop the van straight to the next customer
- They have time for one more job, which is a nearby collection (public transport to get there). This van isn't needed for a few days, so they take it to a storage location (where it can be cleaned by staff), then head home by public transport

### The Structure of Job

- A **job** is one of two **job types**: a **delivery** job or a **collection** job
- Each job moves a single **vehicle** between either of two location types: **customer locations** and **storage locations**
- Jobs can include an **overnight break**, either at the driver's house or at overnight accommodation
- Each job is comprised of up to two journey **stages**:
  - Stage 1: the driver's travel *to* the vehicle 
  - Stage 2: the driver's travel *in* the vehicle

### Job Chaining

Jobs can be **chained** together in six different **chain types**:

- Collection -> Delivery: A vehicle is *collected* from one customer location (job A), then the driver *delivers* the same vehicle to another customer location (job B)
- Delivery -> Collection: A vehicle is *delivered* to one customer location (job A), then the driver takes public transport to another customer locationto *collect* a second vehicle (job B)
- Delivery -> Delivery: A vehicle is *delivered* to one customer location (job A), then the driver takes public transport to a storage location to pick up a second vhiecle to *deliver* to another customer location (job B)
- Collection -> Collection: A vehicle is *collected* from one customer location and taken to a storage location (job A), then the driver takes public transport to another customer location to *collect* a second vehicle
- Collection (to storage) -> Delivery (from same storage): A vehicle is *collected* from one customer location and taken to a storage location (job A), then the driver picks up a second vehicle to *deliver* to another customer locaion (job B)
- Collection (to storage) -> Delivery (from different storage): A vehicle is *collected* from one customer location and taken to a storage location (job A), then the driver takes public transport to another storage location to pick up a second vehicle to *deliver* to another customer locaion (job B)

The Effect of Chaining on Job Stages: 

- Which of the two stages a job contains depends on the job type and how it has been chained together
- Collection jobs always require stage 1 (travel *to* the vehicle) and delivery jobs always require stage 2 (travel *in* the vehicle)
- A *Collection -> Delivery* chain is optimal as it requires neither of the other two stages (because at the end of collection stage 1 the driver is already at the vehicle ready to start delivery stage 2)
- A *Collection (to storage) -> Delivery (from same storage)* chain does not require delivery stage 1 (because at the end of collection stage 2 the driver is already at the same storage location as the second vehicle)
- For reference, here is a complete description of the job stages for each of the chain types:
   - Collection -> Delivery: Collection job, stage 1 -> delivery job, stage 2
   - Delivery -> Collection: Delivery job, stage 1 -> delivery job, stage 2 -> collection job, stage 1 -> collection job, stage 2
   - Delivery -> Delivery: Delivery job, stage 1 -> delivery job, stage 2 -> delivery job, stage 1 -> delivery job, stage 2
   - Collection -> Collection: Collection job, stage 1 -> collection job, stage 2 -> collection job, stage 1 -> collection job, stage 2
   - Collection (to storage) -> Delivery (from same storage): Collection job, stage 1 -> collection job, stage 2 -> delivery job, stage 2
   - Collection (to storage) -> Delivery (from different storage): Collection job, stage 1 -> collection job, stage 2 -> delivery job, stage 1 -> delivery job, stage 2

### Key Constraints
- **Driver Certifications:** Some vehicles (trucks) require specific certifications [TO SPECIFY PER DRIVER, IN DRIVER CSV]
- **Working Hours:** Maximum hours per driver per day [TO SPECIFY PER DRIVER, IN DRIVER CSV]
- **Time Windows:** Each job has a deadline - vehicle must be delivered at or before specified time
- **Driver Availability:** Some drivers unavailable on certain dates
- **Overnight Capability:** Only some drivers can do overnight stays [TO SPECIFY PER DRIVER, IN DRIVER CSV]
- **Customer Approval:** System must flag any jobs scheduled outside their specified time window (early deliveries or late collections) for manual customer approval before execution

### Optimization Goals (Priority Order)
1. **Maximize job chaining:** Reduce public transport legs between jobs
2. **Minimize public transport costs:** Sequence jobs to minimize transit expenses
3. **Minimize fuel costs:** Reduce total vehicle driving distance
4. **Minimize overnight stays:** Only use when cost-effective for multi-day planning
5. **Utilize early delivery:** Deliver vehicles early when parking permits and improves chaining

---

## 3. Technical Architecture

### System Components

```
┌────────────────────────────────────────────────────────────────┐
│         INPUT LAYER                                            │
│  - Core Data CSV Upload (Drivers, Storage Locations)           │
│  - Jobs Upload (Phase 1: CSV Integration, Future Phase: API)   │
└──────────────┬─────────────────────────────────────────────────┘
               │
               ↓
┌──────────────────────────────────────────────┐
│    DATA VALIDATION & PROCESSING              │
│  - Parse job details                         │
│  - Validate driver certifications            │
│  - Check time window conflicts               │
│  - Flag data errors                          │
└──────────────┬───────────────────────────────┘
               │
               ↓
┌──────────────────────────────────────────────┐
│    EXTERNAL API LAYER                        │
│  - Google Maps Directions API (Transit)      │
│  - Google Maps Distance Matrix API           │
│  - Calculate all PT costs & times            │
│  - Calculate all driving distances           │
│  - Cache results for efficiency              │
└──────────────┬───────────────────────────────┘
               │
               ↓
┌──────────────────────────────────────────────┐
│    OPTIMIZATION ENGINE (Python + OR-Tools)   │
│  - Vehicle Routing Problem (VRP) solver      │
│  - Multi-day planning (4-day window)         │
│  - Job chaining algorithm                    │
│  - Constraint satisfaction                   │
│  - Cost minimization                         │
└──────────────┬───────────────────────────────┘
               │
               ↓
┌──────────────────────────────────────────────┐
│    AI ASSISTANT LAYER (LLM)                  │
│  - Natural language interface                │
│  - Schedule explanation                      │
│  - Manual override handling                  │
│  - Conflict resolution suggestions           │
│  - Cost insights and analysis                │
└──────────────┬───────────────────────────────┘
               │
               ↓
┌──────────────────────────────────────────────┐
│    OUTPUT LAYER                              │
│  - Daily driver schedules                    │
│  - Cost breakdown reports                    │
│  - CSV/Google Sheets export                  │
│  - Conflict/warning alerts                   │
└──────────────────────────────────────────────┘
```

### Technology Stack
- **Core Engine:** Python 3.11+
- **Optimization:** Google OR-Tools (open-source constraint programming)
- **APIs:** Google Maps Platform (Directions + Distance Matrix)
- **Data Processing:** pandas, numpy
- **AI Layer:** LLM API (Claude) for natural language interface
- **Initial Deployment:** [TO DECIDE: Local server vs Cloud (AWS/GCP/Azure)]
- **Future Integration:** TBD

---

## 4. Data Requirements

### Core Data Formats

#### Drivers CSV [TO BE CONFIRMED BY ED]
```csv
driver_id,name,home_postcode,max_hours_per_day,certifications,can_overnight,unavailable_dates,home_location
D001,John Smith,SE17QA,10,van;truck,yes,,51.443232/-0.221951
D002,Jane Doe,N11AA,8,van,no,2025-12-10;2025-12-11,51.36992/-0.18408

```

**Fields:**
- `driver_id`: Unique identifier
- `name`: Driver name
- `home_postcode`: Home address postcode
- `max_hours_per_day`: Maximum working hours
- `certifications`: Semicolon-separated list of vehicle types driver can handle
- `can_overnight`: yes/no - can driver do overnight stays
- `unavailable_dates`: Semicolon-separated list of dates (YYYY-MM-DD)
- `home_location`: lat/long

#### Storage Locations CSV [TO BE CONFIRMED BY ED]
```csv
location_id,name,postcode,restricted_vehicle_groups
O001,London HQ,EC1A1BB,trucks
O002,Manchester Office,M11AE,
S001,London Storage,NW10 6RS,
```

**Fields:**
- `office_id`: Unique identifier
- `name`: Location name
- `postcode`: UK postcode
- `restricted_vehicle_groups`: a semicolon-separated list of vechicle types that the storage location cannot take

### Input Data Formats

#### Bookings CSV (Jobs Sheet from Manager)

**Data Model:** Each row represents a booking (vehicle rental to customer). The booking has a lifecycle:
1. Status = `BOOKING`, Action = `Deliver` → Need to deliver vehicle to customer
2. Status = `ON HIRE`, Action = `Collect` → Customer has vehicle, need to collect it back
3. After collection complete → Row disappears

**Raw CSV columns:**
```csv
Book No.,Order ref:,Rental No.,Book Name,Book Status,Date,Time,Action,Reg No.,Supp'd Grp,Drivers,Delivery,Collection,Notes
#35937429,NW94402872,8073133,NATIONWIDE HIRE UK,ON HIRE,08/12/2025,09:00,Collect,SM73ZRL,V2,,TW11 8QA,TW11 8QA,
,NW667AFF49,,NATIONWIDE HIRE UK,BOOKING,08/12/2025,09:30,Deliver,,V2,,KT6 7NS,KT6 7NS,
#35995475,NW17C28C44,,NATIONWIDE HIRE UK,BOOKING,08/12/2025,09:00,Deliver,BC23OFJ,V3,,GU22 7NJ,GU22 7NJ,FIND A VAN!!
```

**Key fields:**
- `Book No.`: Booking identifier (links delivery and collection for same rental)
- `Book Status`: "BOOKING" or "ON HIRE" (lifecycle state)
- `Date/Time`: Deadline for the current action (delivery or collection)
- `Action`: "Deliver" or "Collect" (what needs to happen)
- `Reg No.`: Vehicle registration (may be blank for BOOKING status if vehicle not yet assigned)
- `Supp'd Grp`: Vehicle group/type (V1, V2, V3, V4, V5, C.F3, C.F4, D.B9, D.B9A, E.A17, E.B17, VH18B, etc.)
- `Drivers`: **EMPTY - this is what the scheduler fills in**
- `Delivery`: Delivery postcode (where to take vehicle to customer)
- `Collection`: Collection postcode (where to collect vehicle from customer)
  - Usually same as Delivery (customer location)
  - If different = one-way hire (uncommon)
- `Notes`: Important operational information (vehicle requirements, extensions, special instructions)

**For the optimizer:** The scheduler treats each row as an independent task:
- Rows with `Action=Deliver` → Delivery jobs at `Delivery` postcode
- Rows with `Action=Collect` → Collection jobs at `Collection` postcode
- The booking linkage (via `Book No.` and `Reg No.`) is metadata that helps track vehicle lifecycle but doesn't constrain scheduling

**Data processing approach:**
- **No physical pivot needed**: The optimizer reads the bookings CSV directly and parses each row into a task
- **Internal representation**: Within the optimizer code, each booking row becomes a job object with properties: location (Delivery or Collection postcode), deadline (Date/Time), vehicle_type (Supp'd Grp), etc.
- **Output mapping**: Results map 1:1 back to booking rows (fill Drivers column)
- **Benefit**: Simpler workflow, no intermediate files, easier to maintain sync with manager's source data



### Output Data Format

#### Primary Output: Updated Bookings CSV
The scheduler fills in the `Drivers` column of the original bookings CSV:

```csv
Book No.,Order ref:,Rental No.,Book Name,Book Status,Date,Time,Action,Reg No.,Supp'd Grp,Drivers,Delivery,Collection,Notes
#35937429,NW94402872,8073133,NATIONWIDE HIRE UK,ON HIRE,08/12/2025,09:00,Collect,SM73ZRL,V2,D001,TW11 8QA,TW11 8QA,
,NW667AFF49,,NATIONWIDE HIRE UK,BOOKING,08/12/2025,09:30,Deliver,,V2,D001,KT6 7NS,KT6 7NS,
#35995475,NW17C28C44,,NATIONWIDE HIRE UK,BOOKING,08/12/2025,09:00,Deliver,BC23OFJ,V3,D003,GU22 7NJ,GU22 7NJ,FIND A VAN!!
```

#### Secondary Output: Driver Schedule Detail CSV
For each driver, a detailed schedule showing the sequence of activities:

```csv
driver_id,driver_name,date,seq,booking_ref,job_type,vehicle_reg,location_postcode,arrival_time,transport_mode,transport_cost,transport_time,customer_approval_required,notes
D001,John Smith,2025-12-07,1,START,start,,SE17QA,08:00,,,,no,Starting from home
D001,John Smith,2025-12-07,2,#35937429,collection,SM73ZRL,TW11 8QA,09:00,transit,12.50,45,no,Train from London Bridge
D001,John Smith,2025-12-07,3,#35937429,storage_drop,SM73ZRL,NW10 6RS,10:00,drive,6.20,30,no,Driving to London Storage
D001,John Smith,2025-12-07,4,NW667AFF49,delivery,TBA,KT6 7NS,10:30,transit,3.20,15,yes,EARLY DELIVERY - customer approval needed
D001,John Smith,2025-12-07,5,END,end,,SE17QA,17:00,transit,8.00,30,no,Return home
```

**Key fields:**
- `booking_ref`: Links to `Book No.` or `Order ref:` from bookings CSV
- `vehicle_reg`: Vehicle registration (may be "TBA" for BOOKING status without vehicle assigned)
- `customer_approval_required`: "yes" if job is scheduled outside specified time window (early delivery or late collection), "no" otherwise
- `job_type`: Can be "collection", "delivery", "storage_drop", "storage_pickup", "start", "end"

**Additional Outputs:**
- Cost summary per driver per day
- Warnings/conflicts report
- Unassigned jobs report (if any)
- Multi-day overview showing overnight locations

---

## 5. System Features

### Phase 1: Core Scheduling (MVP)
- [ ] CSV data import and validation
- [ ] Google Maps API integration for PT costs and times
- [ ] Basic optimization algorithm (single-day scheduling)
- [ ] Driver skill matching (certifications)
- [ ] Time window constraint enforcement
- [ ] Working hours limit enforcement
- [ ] Schedule output as CSV
- [ ] Cost calculation and reporting

### Phase 2: Advanced Optimization
- [ ] Multi-day planning (4-day rolling window)
- [ ] Job chaining optimization
- [ ] Early delivery logic with parking assessment
- [ ] Overnight stay optimization
- [ ] Re-optimization when jobs change/cancel
- [ ] Google Sheets integration (read/write)

### Phase 3: AI Assistant & User Interface
- [ ] Natural language query interface ("Why is driver X doing job Y?")
- [ ] Manual override capabilities ("Move this job to Wednesday")
- [ ] Schedule explanation and reasoning
- [ ] Cost insights and anomaly detection
- [ ] Web dashboard for visualization [OPTIONAL - TO DISCUSS]

### Phase 4: Integration & Automation
- [ ] REST API for booking system integration
- [ ] Automatic re-scheduling on job changes
- [ ] Historical data analysis and pattern learning
- [ ] Demand forecasting for proactive planning

---

## 6. Optimization Logic Details

### Cost Function
The optimizer minimizes total cost across all drivers for the 4-day window:

```
Total Cost =
  Σ (Public Transport Cost)          [Primary optimization target]
  + Σ (Public Transport Time × £20/hour)  [Time has value - TO CONFIRM RATE]
  + Σ (Van Distance × £0.50/mile)    [Fuel cost - TO CONFIRM RATE]
  + Σ (Overnight Stays × £65)        [Fixed accommodation cost]
  + Penalties for constraint violations
  - Bonus for efficient job chains   [Rewards chained jobs, especially: the further away they are from London and for collection -> delivery chains]
```

### Job Chaining Logic
The system identifies opportunities to chain jobs:

**Ideal chain:**
```
Driver starts: Home/Office
  → PT to Collection 1
  → Drive to Delivery 1
  → PT to Collection 2 (SHORT distance - good!)
  → Drive to Delivery 2
  → PT to Collection 3
  → Drive to Delivery 3
  → PT to Home/Overnight

Total: 3 jobs, 4 PT legs
```

**Benefits of chaining:**
- Reduces PT legs (one driver does multiple jobs vs. multiple drivers doing one each)
- Keeps drivers in a geographic region well connected by PT
- Maximizes productive driving time vs. transit time

### Early Delivery Decisions
Jobs can be delivered before deadline if:
1. **Parking is suitable:** I.e. be careful of city centers / difficult parking area
2. **Improves chaining:** Creates better job sequence for current or next day
3. **Reduces costs:** Overall cost decreased by early delivery

**Parking assessment heuristic:**
- City center postcodes (SW1, EC1, WC1, M1, etc.) = difficult parking = avoid early delivery
- Suburban/residential = suitable for early delivery
- [TO PROVIDE: List of problematic postcode areas]

### Overnight Stay Logic
Driver stays overnight away from home if:
1. **Multi-day benefit:** Sets up good job chains next day
2. **Cost effective:** Overnight cost (£65) < savings in PT costs and time costs
3. **Driver capable:** Driver flagged as can_overnight=yes
4. **Good PT location:** Overnight location near train station/good transit links

---

### Monthly Operating Costs

#### Google Maps API Costs
**Assumptions:**
- 100 jobs/day × 4 days = 400 jobs
- Average 10 PT legs per driver per day = 200 PT legs/day
- Pre-compute matrix for all possible job pairs

**API Usage:**
1. **Distance Matrix API** (van driving distances)
   - ~400 origin-destination pairs/day
   - $5 per 1000 elements
   - Estimated: 400 × 30 days = 12,000 elements/month = **$60/month**

2. **Directions API - Transit mode** (PT costs & times)
   - ~500 transit queries/day (with caching)
   - $10 per 1000 requests
   - Estimated: 500 × 30 days = 15,000 requests/month = **$150/month**

3. **Caching benefit:**
   - Many route pairs repeat (home locations, storage locations, common job areas)
   - Cache hit rate estimated: 40-60%
   - **Actual cost with caching: $85-125/month**

**Total Google Maps API: ~$100-125/month**

#### LLM API Costs (AI Assistant Layer)
**Assumptions:**
- 20 queries/day for schedule explanation, overrides, insights
- Average 2,000 tokens per interaction
- Claude API pricing: ~$3 per million tokens (input) + $15 per million tokens (output)

**Estimated:**
- 20 queries × 30 days = 600 queries/month
- 600 × 4,000 tokens avg = 2.4M tokens/month
- **Cost: $10-20/month**

#### Hosting Costs
**Option A: Cloud Hosting (AWS/GCP/Azure)**
- Small compute instance: $20-50/month
- Storage: $5-10/month
- **Total: $25-60/month**

**Option B: Local Server**
- **Ongoing: ~£0/month**

#### Database/Storage
- CSV-based (Phase 1): £0
- Future database (Phase 4): $20-50/month

---

## 8. Outstanding Questions & Decisions Needed

### Strategic Decision (CRITICAL - Informs All Other Decisions)

**Primary Goal: Are we trying to:**
- [ ] **Option A: Automate the current process** - Save manager time, maintain current schedule quality
  - Focus: Time savings, reduce manual effort
  - Acceptable approach: Pure LLM replicating human decision-making
  - Expected outcome: Similar schedules to current, massive time savings

- [ ] **Option B: Improve the current process** - Save time AND reduce operational costs through better optimization
  - Focus: Time savings + cost reduction (estimated 15-30% operational savings)
  - Recommended approach: Hybrid LLM + optimizer OR traditional optimizer
  - Expected outcome: Better schedules than current, time savings + £5-10k/year cost reduction

**This decision determines the technical approach, development timeline, and ROI calculation.**

### Business Requirements
1. **Current costs:** What is current monthly spend on:
   - [ ] Driver public transport costs
   - [ ] Overnight accommodation costs
   - [ ] Fuel costs
   - [ ] Manager time on scheduling (hours/week)

2. **Driver details:**
   - [ ] List of drivers who can do overnight stays
   - [ ] Specific max hours per driver (or standard for all?)
   - [ ] Any other driver preferences/constraints?

3. **Vehicle types:**
   - [ ] Complete list of vehicle groups beyond "van" and "truck"
   - [ ] Certification requirements for each type

4. **Early delivery and late collection:**
   - [ ] Customer approval process: How do staff confirm with customers when jobs are scheduled outside normal windows?
   - [ ] List of postcodes/areas with difficult parking (to avoid early delivery)
   - [ ] Any customers who explicitly allow/disallow schedule flexibility?

5. **Storage locations:**
   - [ ] How many storage locations and their postcodes?
   - [ ] Is there a default/preferred storage per region?
   - [ ] Any capacity limits per storage location?
   - [ ] Any handling time or cost when routing through storage?

6. **Time windows:**
   - [ ] What % of jobs are "exact time" vs "flexible window"?
   - [ ] How is this indicated in current spreadsheet?
   - [ ] For collection jobs: does 'time' mean "collect by this deadline" or "customer returns vehicle at this time"?
   - [ ] Can collections be done early (before scheduled time) or only deliveries?

7. **Job dependencies and incomplete chains:**
   - [ ] If driver runs out of hours mid-chain (collected vehicle but can't deliver), can vehicle stay with them overnight?
   - [ ] If driver can't do overnights, must all their jobs complete same-day?
   - [ ] Can job sequences span multiple days with storage in between?
   - [ ] Any explicit job dependencies beyond vehicle flow?

8. **Multi-vehicle handling:**
   - [ ] Can one driver handle multiple vehicles in one trip (e.g., drive one with another on trailer)?
   - [ ] Or always one vehicle at a time per driver?

9. **Customer handover:**
   - [ ] Do drivers always meet customers for key handover?
   - [ ] Or can keys be left in lockboxes/with concierge/staff?
   - [ ] Does this affect timing (e.g., need buffer time for handover)?

10. **Vehicle cleaning:**
    - [ ] Is vehicle cleaning factored into job timing?
    - [ ] Done by drivers (as in the example) or by storage staff?
    - [ ] Does this affect which jobs can be chained?

### Technical Decisions
1. **Hosting preference:**
   - [ ] Cloud-hosted (AWS/GCP/Azure) vs local server?
   - [ ] Who manages infrastructure?

2. **Google Sheets vs CSV:**
   - [ ] Preference for Phase 1 input method?
   - [ ] Is Google Sheets API integration essential or can wait?

3. **User interface:**
   - [ ] Command-line tool acceptable initially, or need web dashboard?
   - [ ] Who will be primary users of the system?

### Optimization Parameters
1. **Cost rates:**
   - [ ] Fuel cost per mile (currently estimated £0.50)
   - [ ] Value of driver time per hour (currently estimated £20)

2. **Optimization preferences:**
   - [ ] Max acceptable overnight stays per week per driver?
   - [ ] Prefer regional specialization (drivers stick to areas) or full flexibility?
   - [ ] Any preferred job chains (e.g., always pair certain vehicle types)?

---

## 9. Success Metrics

### Primary KPIs

1. **Management Effort Reduction**
   - Time spent scheduling (target: 80% reduction in manual effort)
   - Time spent re-scheduling when jobs change
  
2. **Cost Reduction:**
   - PT cost per job (target: 20-30% reduction)
   - Total weekly PT spend
   - Overnight accommodation costs
   - Fuel costs

3. **Efficiency Metrics:**
   - Average jobs per driver per day (target: maintain or increase current 5)
   - Average job chain length (target: 3+ consecutive jobs)
   - PT legs per driver per day (target: minimize)
   
3. **Service Quality:**
   - % jobs completed on-time (target: 100%)
   - % jobs delivered early (measure benefit)
   - Driver satisfaction (reduced travel time/cost)

---

**Document Control:**
- **Author:** [Your name]
- **Reviewer:** [Manager name]
- **Next Review Date:** [Date]
- **Version History:**
  - v1.0 (2025-12-06): Initial draft for review
