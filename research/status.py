"""Run status uses the completeness model (plans/INITIAL.md Section 8)."""


def compute_run_status(category_statuses, total_item_count):
    """Roll terminal category statuses + item total into a run status."""
    if total_item_count <= 0 or all(s == "red" for s in category_statuses):
        return "red"
    if any(s == "red" for s in category_statuses):
        return "yellow"
    return "green"  # every category finished cleanly and items exist
