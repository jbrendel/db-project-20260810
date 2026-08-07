from research.status import compute_run_status


def test_all_clean_with_items_is_green():
    assert compute_run_status(["green", "yellow"], 5) == "green"


def test_empty_but_clean_category_does_not_demote():
    # A category that legitimately found nothing (yellow) does NOT demote (§8).
    assert compute_run_status(["green", "yellow", "yellow"], 3) == "green"


def test_error_makes_yellow():
    assert compute_run_status(["green", "red"], 5) == "yellow"


def test_zero_items_is_red():
    assert compute_run_status(["yellow", "yellow"], 0) == "red"


def test_all_errored_is_red():
    assert compute_run_status(["red", "red"], 0) == "red"
