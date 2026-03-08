"""Penalty rate constants for asymmetric time window objective terms.

All values are per-minute integer costs added to the CP-SAT objective.
Tune here without touching solver logic.
"""

# COLLECT penalties (lateness from booking time)
LATE_SAME_DAY_RATE: int = 2    # per minute after grace period (booking_time + 120min)
SEVERE_NEXT_DAY_RATE: int = 10  # per minute past end of scheduled day

# DELIVER penalties
EARLY_RATE: int = 1             # per minute early before same-day start (1440/day natural ramp)
LATE_TIER1_RATE: int = 10       # per minute late, first 60 minutes past deadline
LATE_TIER2_RATE: int = 30       # per minute late, beyond 60 minutes past deadline
