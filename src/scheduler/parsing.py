"""CSV field parsing utilities for bookings data."""

import re

_POSTCODE_RE = re.compile(r"^([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})")


def normalize_postcode(raw: str) -> str | None:
    """Extract the first valid UK postcode from a raw string.

    Strips suffixes like '*PRE-DELIVERY*' or '- EXT BEFORE'.
    Returns None if the string is empty or contains no valid postcode.
    """
    raw = raw.strip()
    if not raw:
        return None
    m = _POSTCODE_RE.match(raw.upper())
    if m:
        pc = m.group(1).replace(" ", "")
        return f"{pc[:-3]} {pc[-3:]}"
    parts = raw.split()
    if len(parts) >= 2:
        candidate = f"{parts[0]} {parts[1]}"
        m2 = _POSTCODE_RE.match(candidate.upper())
        if m2:
            pc = m2.group(1).replace(" ", "")
            return f"{pc[:-3]} {pc[-3:]}"
    return None


def resolve_vehicle_group(raw: str) -> str | None:
    """Resolve vehicle group, taking rightmost value after '>' if upgrade notation present."""
    raw = raw.strip()
    if not raw:
        return None
    if ">" in raw:
        return raw.split(">")[-1].strip()
    return raw
