from scheduler.parsing import normalize_postcode, resolve_vehicle_group


def test_normalize_postcode_clean():
    assert normalize_postcode("SW15 2SW") == "SW15 2SW"


def test_normalize_postcode_with_suffix():
    assert normalize_postcode("BH23 5LJ*PRE-DELIVERY*") == "BH23 5LJ"


def test_normalize_postcode_with_dash_suffix():
    assert normalize_postcode("B92 0AE - EXT BEFORE") == "B92 0AE"


def test_normalize_postcode_strips_whitespace():
    assert normalize_postcode("  SW15 2SW  ") == "SW15 2SW"


def test_normalize_postcode_empty():
    assert normalize_postcode("") is None


def test_normalize_postcode_whitespace_only():
    assert normalize_postcode("   ") is None


def test_resolve_vehicle_group_simple():
    assert resolve_vehicle_group("V3") == "V3"


def test_resolve_vehicle_group_upgrade():
    assert resolve_vehicle_group("E.A17>D.B9A") == "D.B9A"


def test_resolve_vehicle_group_strips_whitespace():
    assert resolve_vehicle_group(" V5 ") == "V5"


def test_resolve_vehicle_group_upgrade_with_spaces():
    assert resolve_vehicle_group(" E.A17 > D.B9A ") == "D.B9A"


def test_resolve_vehicle_group_empty():
    assert resolve_vehicle_group("") is None
