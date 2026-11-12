"""Snapshot declared cost inputs and bind optional operations to their charges.

This enforces consistency with original checker receipts; it does not prove
that the caller's frozen roster covers every physical resource or operation.
"""

import math

from .contracts import _require, _text
from .cost_ledger import snapshot_cost_inputs


def snapshot_costs(rosters, receipts=None):
    """Revalidate and detach typed inputs; frozen dataclasses are not a trust boundary."""
    _require(
        type(rosters) is dict and 1 <= len(rosters) <= 8,
        "bounded cost rosters required",
    )
    _require(
        all(type(rows) in (list, tuple) for rows in rosters.values())
        and sum(len(rows) for rows in rosters.values()) <= 10000,
        "bounded cost arrays required",
    )
    _require(
        receipts is None or type(receipts) is dict and set(receipts) == set(rosters),
        "cost receipt policies changed",
    )
    copied, result = {}, {}
    for policy, rows in rosters.items():
        _text(policy, "policy")
        _require(len(policy) <= 256, "policy identity too long")
        copied[policy], result[policy] = snapshot_cost_inputs(
            rows, () if receipts is None else receipts[policy]
        )
    return copied, None if receipts is None else result


def bind_optional_costs(state, roster, receipts):
    """Bind actual starts and original measured completions to declared charges."""
    items = {item.operation_id: item for item in roster}
    receipts = {row.item.operation_id: row for row in receipts}
    for operation, start in state["starts"].items():
        item, receipt = items.get(operation), receipts.get(operation)
        _require(
            item is not None
            and item.stage == "checker"
            and item.attempt_id == start["trajectory_id"],
            "actual optional operation missing from its frozen cost roster",
        )
        _require(
            receipt is None or receipt.status != "not_run",
            "started optional operation cannot have a not-run cost receipt",
        )
        completion = state["completions"].get(operation)
        if receipt is not None and completion is not None:
            for recorded, measured in (
                ("wall_seconds", "wall_seconds"),
                ("cpu_seconds", "process_cpu_seconds"),
                ("energy_joules", "energy_joules"),
            ):
                original, charged = (
                    completion["costs"][recorded],
                    getattr(receipt, measured),
                )
                _require(
                    original is None
                    or charged is None
                    or math.isclose(
                        original,
                        charged,
                        rel_tol=1e-12,
                        abs_tol=1e-9 if recorded == "wall_seconds" else 0,
                    ),
                    "optional operation cost contradicts its original completion",
                )
