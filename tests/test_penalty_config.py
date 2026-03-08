from scheduler.penalty_config import (
    LATE_SAME_DAY_RATE,
    SEVERE_NEXT_DAY_RATE,
    EARLY_RATE,
    LATE_TIER1_RATE,
    LATE_TIER2_RATE,
)

def test_penalty_constants_exist_and_are_positive():
    assert LATE_SAME_DAY_RATE > 0
    assert SEVERE_NEXT_DAY_RATE > LATE_SAME_DAY_RATE, "next-day rate must exceed same-day rate"
    assert EARLY_RATE > 0
    assert LATE_TIER1_RATE > 0
    assert LATE_TIER2_RATE > LATE_TIER1_RATE, "tier-2 late rate must exceed tier-1"

def test_penalty_constants_are_integers():
    for name, val in [
        ("LATE_SAME_DAY_RATE", LATE_SAME_DAY_RATE),
        ("SEVERE_NEXT_DAY_RATE", SEVERE_NEXT_DAY_RATE),
        ("EARLY_RATE", EARLY_RATE),
        ("LATE_TIER1_RATE", LATE_TIER1_RATE),
        ("LATE_TIER2_RATE", LATE_TIER2_RATE),
    ]:
        assert isinstance(val, int) and not isinstance(val, bool), f"{name} must be int"
