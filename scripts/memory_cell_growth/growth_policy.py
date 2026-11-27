"""Predeclared source-selection policy for bounded memory arrival experiments."""

ARMS = ("nochange", "single", "split")
RULE = (
    "Preserve every parent-correct old item; single needs at least one extra "
    "correct source selection answer over nochange; split needs at least two "
    "over the best eligible cheaper arm; ties retain the cheaper/nochange arm."
)
COST_FIELDS = {
    "private_parameter_bytes",
    "retained_checkpoint_bytes",
    "optimizer_steps",
}


def choose_growth(source_assessments, costs):
    """Accept only source-held-out correctness vectors and measured cost vectors.

    The policy prices no byte in accuracy units. Split has a predeclared minimum
    improvement and its additional storage is reported, not called compression.
    Final test scores are not an input to this interface.
    """
    if type(source_assessments) is not dict or set(source_assessments) != set(ARMS):
        raise ValueError("exact source-selection arms required")
    if type(costs) is not dict or set(costs) != set(ARMS):
        raise ValueError("exact measured cost arms required")
    sizes = None
    totals = {}
    for arm in ARMS:
        row = source_assessments[arm]
        if type(row) is not dict or set(row) != {"old", "new"}:
            raise ValueError("old/new source correctness vectors required")
        for values in row.values():
            if (
                type(values) is not list
                or not 1 <= len(values) <= 64
                or any(type(v) is not bool for v in values)
            ):
                raise ValueError("bounded boolean correctness vectors required")
        lengths = len(row["old"]), len(row["new"])
        if sizes is None:
            sizes = lengths
        if lengths != sizes:
            raise ValueError("matched source cohorts required")
        cost = costs[arm]
        if (
            type(cost) is not dict
            or set(cost) != COST_FIELDS
            or any(type(v) is not int or not 0 <= v < 2**63 for v in cost.values())
        ):
            raise ValueError("closed nonnegative measured cost vector required")
        if not cost["private_parameter_bytes"] or not cost["retained_checkpoint_bytes"]:
            raise ValueError("retained model costs cannot be omitted")
        totals[arm] = sum(row["old"]) + sum(row["new"])
    if (
        costs["nochange"]["optimizer_steps"] != 0
        or costs["single"]["private_parameter_bytes"]
        != costs["nochange"]["private_parameter_bytes"]
        or costs["split"]["private_parameter_bytes"]
        != 2 * costs["single"]["private_parameter_bytes"]
    ):
        raise ValueError(
            "registered one-parent/one-single/two-split private budgets required"
        )
    if (
        costs["single"]["optimizer_steps"] != costs["split"]["optimizer_steps"]
        or not costs["single"]["optimizer_steps"]
    ):
        raise ValueError("matched positive optimizer work required")
    preserved = {
        arm: all(
            not old or new
            for old, new in zip(
                source_assessments["nochange"]["old"],
                source_assessments[arm]["old"],
                strict=True,
            )
        )
        for arm in ARMS
    }
    eligible_single = preserved["single"] and totals["single"] >= totals["nochange"] + 1
    cheaper = "single" if eligible_single else "nochange"
    eligible_split = preserved["split"] and totals["split"] >= totals[cheaper] + 2
    chosen = "split" if eligible_split else cheaper
    return {
        "schema": "hepta.parametric-memory.growth-selection.v1",
        "chosen_arm": chosen,
        "rule": RULE,
        "source_correct_counts": totals,
        "parent_correct_old_preserved": preserved,
        "single_eligible": eligible_single,
        "split_eligible": eligible_split,
        "best_eligible_cheaper_arm": cheaper,
        "selected_cost": costs[chosen],
        "additional_private_bytes_over_parent": costs[chosen]["private_parameter_bytes"]
        - costs["nochange"]["private_parameter_bytes"],
        "final_scores_used": False,
        "price_utility_claimed": False,
        "production_accepted": False,
    }
