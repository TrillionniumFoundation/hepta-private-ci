"""Recompute the frozen producer's plateau and strict-best selection rules.

This checks recorded metric arithmetic. It neither authenticates a producer
nor independently recomputes the development metrics from a model.
"""

import math


def stopping_history(epochs, plan):
    """Return each prefix state and the first eligible plateau epoch."""
    minimum, patience, delta = (
        plan[name] for name in ("min_epochs", "patience", "plateau_delta")
    )
    if (
        type(minimum) is not int
        or minimum <= 0
        or type(patience) is not int
        or patience <= 0
        or type(delta) not in (int, float)
        or not math.isfinite(delta)
        or not 0 <= delta <= 1
        or type(epochs) is not list
        or not epochs
    ):
        raise ValueError("invalid frozen stopping rule or epoch history")
    best, best_epoch, anchor, stale, first_stop = -1.0, None, -1.0, 0, None
    states = []
    for number, row in enumerate(epochs, 1):
        if (
            type(row.get("epoch")) is not int
            or row["epoch"] != number
            or row.get("complete") is not True
        ):
            raise ValueError(
                "stopping history must be an exact complete contiguous prefix"
            )
        score = row["development"]["macro_f1_11_classes"]
        if (
            type(score) not in (int, float)
            or not math.isfinite(score)
            or not 0 <= score <= 1
        ):
            raise ValueError("invalid recorded development score")
        if score > best:
            best, best_epoch = score, number
        if score > anchor + delta:
            anchor, stale = score, 0
        else:
            stale += 1
        states.append(
            dict(
                best=best,
                best_epoch=best_epoch,
                plateau_anchor=anchor,
                stale_epochs=stale,
            )
        )
        if first_stop is None and number >= minimum and stale >= patience:
            first_stop = number
    return states, first_stop


def terminal_stopping(prior, result, plan, maximum_epochs):
    """Reject unearned plateau, ignored earlier stop, or misselected best epoch."""
    # Legacy parent reports omit the event journal's explicit complete flag.
    # Their epochs field is already the retained prefix used by this gate's
    # resume/count checks. Never erase an explicit incomplete/ambiguous flag.
    parent_rows = [
        {**row, "complete": row.get("complete", True)} for row in prior["epochs"]
    ]
    history = parent_rows + result["epochs"]
    states, first_stop = stopping_history(history, plan)
    if type(maximum_epochs) is not int or maximum_epochs < len(history):
        raise ValueError("invalid cumulative epoch cap")
    if first_stop is not None and first_stop <= len(prior["epochs"]):
        raise ValueError("parent already passed its stopping boundary")
    if first_stop is not None:
        if first_stop != len(history) or result["stop_reason"] != "development_plateau":
            raise ValueError("producer did not stop at its first eligible plateau")
    elif (
        len(history) != maximum_epochs
        or result["stop_reason"] != "epoch_cap_not_convergence"
    ):
        raise ValueError(
            "no recorded plateau or reached epoch cap supports terminal stop"
        )
    if (
        type(result.get("best_epoch")) is not int
        or result["best_epoch"] != states[-1]["best_epoch"]
    ):
        raise ValueError("reported best epoch is not the earliest strict maximum")
    return states[len(prior["epochs"]) :]
