# Van Rental Driver Scheduling System - Product Specification

**Version:** 1.0 (Draft)
**Date:** December 6, 2025
**Status:** For Review

---

## 1. Executive Summary

### Problem Statement
The van rental business currently manages driver scheduling manually using spreadsheets. With 20 drivers completing ~100 jobs daily, the manual process is time-consuming and suboptimal, leading to:
- High public transport costs due to poor job sequencing
- Inefficient use of driver time (excessive travel between jobs)
- Missed opportunities for job chaining and early delivery optimization
- Difficulty adapting to daily changes (new orders, cancellations, time changes)
- Inability to plan efficiently across multiple days

### Proposed Solution
An automated scheduling system that optimizes driver assignments and job sequencing to minimize costs while respecting all business constraints. The system will:
- Plan 4 days ahead with rolling updates
- Maximize job chaining to reduce public transport costs
- Optimize for fuel efficiency, public transport costs, and overnight stays
- Handle driver skills/certifications and working hour limits
- Allow human oversight and manual overrides
- Start with CSV/Google Sheets integration, with pathway to full API integration

### Expected Benefits
- **Cost Reduction:** 20-40% reduction in public transport and overnight accommodation costs
- **Time Savings:** [ESTIMATE: X hours/week] saved on manual scheduling
- **Flexibility:** Rapid re-optimization when jobs change
- **Scalability:** System can grow with business
- **Insights:** Data-driven understanding of scheduling patterns and costs

---

## 2. Business Context

### Current Operations
- **Fleet Size:** [TO CONFIRM]
- **Driver Count:** 20 drivers
- **Daily Job Volume:** ~100 jobs/day (5 per driver average)
- **Planning Horizon:** 4 days ahead
- **Current Process:** Manual spreadsheet-based assignment

### Job Types
1. **Collection Jobs:**
   - Driver travels from home/office/overnight location to van location (via public transport)
   - Driver collects van and drives to:
     - Company storage location, OR
     - Delivery location (chained with delivery job)

2. **Delivery Jobs:**
   - Driver has van from previous collection/delivery
   - Driver delivers van to customer location
   - Driver travels to next location (via public transport):
     - Home/office, OR
     - Next collection location (chained job), OR
     - Overnight accommodation (if multiple days)

### Key Constraints
- **Driver Certifications:** Some vehicles (trucks) require specific certifications
- **Working Hours:** Maximum hours per driver per day [TO SPECIFY PER DRIVER]
- **Time Windows:** Each job has a deadline - van must be delivered at or before specified time
- **Driver Availability:** Some drivers unavailable on certain dates
- **Overnight Capability:** Only some drivers can do overnight stays [TO SPECIFY WHICH]

### Optimization Goals (Priority Order)
1. **Maximize job chaining:** Reduce public transport legs between jobs
2. **Minimize public transport costs:** Sequence jobs to minimize transit expenses
3. **Minimize fuel costs:** Reduce total van driving distance
4. **Minimize overnight stays:** Only use when cost-effective for multi-day planning
5. **Utilize early delivery:** Deliver vans early when parking permits and improves chaining

---

## 3. Technical Architecture

### System Components

```
┌──────────────────────────────────────────────┐
│         INPUT LAYER                          │
│  - CSV Upload (Jobs, Drivers, Offices)       │
│  - Google Sheets Integration (Phase 1)       │
│  - API Integration (Future Phase)            │
└──────────────┬───────────────────────────────┘
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
- **AI Layer:** LLM API (Claude/OpenAI) for natural language interface
- **Initial Deployment:** [TO DECIDE: Local server vs Cloud (AWS/GCP/Azure)]
- **Future Integration:** REST API for booking system integration

---

## 4. Data Requirements

### Input Data Formats

#### Jobs CSV
```csv
job_id,date,time,job_type,vehicle_reg,vehicle_group,postcode,notes
J001,2025-12-07,09:00,collection,AB12XYZ,van,SW1A1AA,Customer pickup at 10am
J002,2025-12-07,14:30,delivery,AB12XYZ,van,SE17QA,
J003,2025-12-08,08:00,collection,CD34EFG,truck,M11AE,Requires HGV license
```

**Fields:**
- `job_id`: Unique identifier
- `date`: Delivery/collection deadline date
- `time`: Delivery/collection deadline time (van must arrive by this time)
- `job_type`: "collection" or "delivery"
- `vehicle_reg`: Vehicle registration
- `vehicle_group`: van, truck, [OTHER TYPES TO SPECIFY]
- `postcode`: UK postcode for job location
- `notes`: Optional human-readable notes

#### Drivers CSV
```csv
driver_id,name,home_postcode,max_hours_per_day,certifications,can_overnight,unavailable_dates,base_office
D001,John Smith,SE17QA,10,van;truck,yes,,O001
D002,Jane Doe,N11AA,8,van,no,2025-12-10;2025-12-11,O002
```

**Fields:**
- `driver_id`: Unique identifier
- `name`: Driver name
- `home_postcode`: Home address postcode
- `max_hours_per_day`: Maximum working hours
- `certifications`: Semicolon-separated list of vehicle types driver can handle
- `can_overnight`: yes/no - can driver do overnight stays
- `unavailable_dates`: Semicolon-separated list of dates (YYYY-MM-DD)
- `base_office`: Which office driver typically starts from [TO CONFIRM IF NEEDED]

#### Offices/Storage Locations CSV
```csv
office_id,name,postcode,type
O001,London HQ,EC1A1BB,office
O002,Manchester Office,M11AE,office
S001,London Storage,NW10 6RS,storage
```

**Fields:**
- `office_id`: Unique identifier
- `name`: Location name
- `postcode`: UK postcode
- `type`: office or storage

### Output Data Format

#### Driver Schedule CSV
```csv
driver_id,driver_name,date,seq,job_id,job_type,location_postcode,arrival_time,transport_mode,transport_cost,transport_time,notes
D001,John Smith,2025-12-07,1,START,start,SE17QA,08:00,,,Starting from home
D001,John Smith,2025-12-07,2,J001,collection,SW1A1AA,09:00,transit,12.50,45,Train from London Bridge
D001,John Smith,2025-12-07,3,J002,delivery,SE17QA,10:30,drive,8.50,25,Driving van 15 miles
D001,John Smith,2025-12-07,4,J005,collection,SE5 9RS,11:00,transit,3.20,15,Bus from SE17
D001,John Smith,2025-12-07,5,END,end,SE17QA,17:00,transit,8.00,30,Return home
```

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
  - Bonus for efficient job chains   [Reward 3+ consecutive jobs]
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
  → PT to Home/Office/Overnight

Total: 3 jobs, 4 PT legs
```

**Benefits of chaining:**
- Reduces PT legs (one driver does multiple jobs vs. multiple drivers doing one each)
- Keeps drivers in geographic regions with good PT links
- Maximizes productive driving time vs. transit time

### Early Delivery Decisions
Jobs can be delivered before deadline if:
1. **Parking is suitable:** Not city center/difficult parking area
2. **Improves chaining:** Creates better job sequence for current or next day
3. **Reduces costs:** Overall cost decreased by early delivery
4. **Customer allows it:** [TO CONFIRM - do we need customer approval flag?]

**Parking assessment heuristic:**
- City center postcodes (SW1, EC1, WC1, M1, etc.) = difficult parking = avoid early delivery
- Suburban/residential = suitable for early delivery
- [TO PROVIDE: List of problematic postcode areas]

### Overnight Stay Logic
Driver stays overnight away from home if:
1. **Multi-day benefit:** Sets up good job chains next day
2. **Cost effective:** Overnight cost (£65) < savings in PT costs
3. **Driver capable:** Driver flagged as can_overnight=yes
4. **Good PT location:** Overnight location near train station/good transit links

---

## 7. Cost Estimates

### Development Costs
**Option A: Internal Development**
- Senior Python Developer: [ESTIMATE: £X/day × Y days = £Z]
- Total estimated development time: [TO ESTIMATE based on phases]

**Option B: Contract Development**
- Fixed price for MVP (Phase 1-2): [TO OBTAIN QUOTES]

**Option C: Hybrid (Claude Code assisted)**
- Accelerated development using AI assistance
- Estimated time reduction: 30-50%
- [TO ESTIMATE based on developer availability]

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
   - Many route pairs repeat (home locations, offices, common job areas)
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
- One-time hardware cost: £500-1,000
- Electricity: ~£10/month
- **Ongoing: ~£10/month**

#### Database/Storage
- CSV-based (Phase 1): Minimal cost (~$5/month cloud storage)
- Future database (Phase 4): $20-50/month

### Total Monthly Operating Costs
| Component | Cost (£/month) |
|-----------|----------------|
| Google Maps API | £90-100 |
| LLM API | £8-15 |
| Hosting | £20-50 |
| Storage | £5-10 |
| **TOTAL** | **£125-175/month** |

### Break-Even Analysis
**Current estimated costs (manual process):**
- Suboptimal scheduling cost: [TO ESTIMATE - excess PT costs, wasted time]
- Manager time spent scheduling: [X hours/week × £Y/hour]

**Estimated savings:**
- PT cost reduction (20-30%): [TO CALCULATE based on current spend]
- Time savings: [X hours/week × £Y/hour]

**Payback period:** [TO CALCULATE once current costs known]

---

## 8. Outstanding Questions & Decisions Needed

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

4. **Early delivery:**
   - [ ] Does customer need to approve early delivery, or can we deliver anytime before deadline?
   - [ ] List of postcodes/areas with difficult parking

5. **Storage locations:**
   - [ ] How many storage locations?
   - [ ] Should optimizer prefer delivering to storage vs customer? (Or customer-determined?)

6. **Time windows:**
   - [ ] What % of jobs are "exact time" vs "flexible window"?
   - [ ] How is this indicated in current spreadsheet?

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

4. **Integration timeline:**
   - [ ] What booking system is used currently?
   - [ ] Timeline for Phase 4 API integration?

### Optimization Parameters
1. **Cost rates:**
   - [ ] Fuel cost per mile (currently estimated £0.50)
   - [ ] Value of driver time per hour (currently estimated £20)
   - [ ] Overnight accommodation (confirmed £65 - any variation by location?)

2. **Optimization preferences:**
   - [ ] Max acceptable overnight stays per week per driver?
   - [ ] Prefer regional specialization (drivers stick to areas) or full flexibility?
   - [ ] Any preferred job chains (e.g., always pair certain vehicle types)?

---

## 9. Success Metrics

### Primary KPIs
1. **Cost Reduction:**
   - PT cost per job (target: 20-30% reduction)
   - Total weekly PT spend
   - Overnight accommodation costs
   - Fuel costs

2. **Efficiency Metrics:**
   - Average jobs per driver per day (target: maintain or increase current 5)
   - Average job chain length (target: 3+ consecutive jobs)
   - PT legs per driver per day (target: minimize)
   - Time spent scheduling (target: 80% reduction in manual effort)

3. **Service Quality:**
   - % jobs completed on-time (target: 100%)
   - % jobs delivered early (measure benefit)
   - Driver satisfaction (reduced travel time/cost)

### Secondary Metrics
- Re-optimization frequency (how often schedules change)
- System uptime/reliability
- Time to re-optimize when jobs change
- Accuracy of cost predictions vs actual

---

## 10. Risks & Mitigations

### Technical Risks
| Risk | Impact | Mitigation |
|------|--------|------------|
| Google Maps API costs higher than estimated | Medium | Implement aggressive caching; monitor usage; consider alternative APIs |
| Optimization too slow for real-time updates | Medium | Use heuristics for large problems; pre-compute common scenarios |
| Transit cost estimates inaccurate | High | Validate against historical data; manual override capability |
| API rate limits/downtime | Medium | Cache results; fallback to estimated costs; queue requests |

### Business Risks
| Risk | Impact | Mitigation |
|------|--------|------------|
| Staff resistance to automated system | Medium | Gradual rollout; maintain manual override capability; training |
| Edge cases not handled by optimizer | Medium | Human review of all schedules initially; feedback loop for improvements |
| Integration with existing systems difficult | Low | Start with CSV; phased integration approach |

---

## 11. Implementation Timeline (Estimated)

### Phase 1: MVP (Core Scheduling)
**Duration:** [X weeks - TO ESTIMATE]
- Week 1-2: Data models, CSV parsing, API integration
- Week 3-4: Basic optimization algorithm
- Week 5-6: Testing with real data, refinement

**Deliverable:** Working single-day scheduler with CSV input/output

### Phase 2: Advanced Features
**Duration:** [X weeks - TO ESTIMATE]
- Multi-day optimization
- Job chaining logic
- Early delivery and overnight stay logic
- Google Sheets integration

**Deliverable:** Production-ready 4-day rolling scheduler

### Phase 3: AI Assistant
**Duration:** [X weeks - TO ESTIMATE]
- LLM integration
- Natural language interface
- Manual override handling
- Web dashboard (optional)

**Deliverable:** User-friendly system with AI assistance

### Phase 4: Full Integration
**Duration:** [X weeks - TO ESTIMATE]
- REST API development
- Booking system integration
- Automated re-scheduling
- Historical analysis

**Deliverable:** Fully automated scheduling system

---

## 12. Next Steps

1. **Review this specification** with manager and stakeholders
2. **Gather answers** to outstanding questions (Section 8)
3. **Validate cost assumptions** with current operational data
4. **Decide on implementation approach:**
   - Internal development vs contract vs hybrid
   - Phased rollout vs full build
5. **Approve budget** for development and monthly operating costs
6. **Set timeline** for Phase 1 delivery
7. **Identify pilot users** for initial testing

---

## Appendix A: Sample Scenarios

### Scenario 1: Optimal Chain
**Input:**
- Job A: Collection in Croydon at 9am, delivery in Sutton
- Job B: Collection in Sutton at 11am, delivery in Kingston
- Job C: Collection in Kingston at 2pm, delivery in Richmond

**Optimal Schedule:**
- Driver starts from home (South London)
- PT to Croydon (£5, 30min)
- Drive to Sutton (6 miles)
- Walk to Job B collection (in Sutton already - £0, 5min!) ← EXCELLENT CHAIN
- Drive to Kingston (5 miles)
- Walk to Job C collection (in Kingston - £0, 5min!) ← EXCELLENT CHAIN
- Drive to Richmond (4 miles)
- PT home (£6, 40min)

**Total PT cost: £11, 3 jobs perfectly chained**

### Scenario 2: Overnight Stay Decision
**Day 1:**
- Driver completes 4 jobs, last delivery in Manchester at 6pm
- Driver home is in London

**Options:**
- Return to London: £45 train, 2.5 hours → Start in London next day
- Stay overnight in Manchester: £65 hotel

**Day 2 Jobs:**
- 3 jobs in Manchester/Liverpool area available

**Optimizer decision:** Stay overnight
- **Cost:** £65 hotel vs £45 return + £45 next morning = £90
- **Savings:** £25
- **Time saved:** 5 hours
- **Better job allocation:** Driver can do Manchester jobs next day

---

## Appendix B: Glossary

- **Job Chaining:** Sequencing jobs so delivery location of one job is near collection location of next job
- **PT:** Public Transport
- **Time Window:** Deadline by which job must be completed
- **Early Delivery:** Delivering van before scheduled deadline
- **Overnight Stay:** Driver accommodation away from home between job days
- **VRP:** Vehicle Routing Problem (class of optimization problems)
- **OR-Tools:** Google's open-source optimization library

---

**Document Control:**
- **Author:** [Your name]
- **Reviewer:** [Manager name]
- **Next Review Date:** [Date]
- **Version History:**
  - v1.0 (2025-12-06): Initial draft for review
