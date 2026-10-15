"""Research-only equal-budget differentiation gate.

This module compares a shared Stem plus typed Head arm with an unsplit control.
It never selects a winner or grants NDU/production authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


class BudgetGateRejected(ValueError):
    pass


@dataclass(frozen=True)
class ArmReceipt:
    name: str
    trainable_parameters: int
    optimizer_bytes: int
    update_steps: int
    encoder_forwards: int
    exposed_train_rows: int
    future_window_successes: tuple[int, ...]
    complete_task_denominator: int
    authority: str = "DENY_ALL"


def _same(values: Iterable[int], field: str) -> None:
    values = tuple(values)
    if not values or len(set(values)) != 1:
        raise BudgetGateRejected(f"{field} is not equal across arms")


def compare_equal_budget(
    differentiated: ArmReceipt, unsplit: ArmReceipt
) -> dict[str, object]:
    arms = (differentiated, unsplit)
    if any(arm.authority != "DENY_ALL" for arm in arms):
        raise BudgetGateRejected("research arms must remain DENY_ALL")
    if any(arm.complete_task_denominator <= 0 for arm in arms):
        raise BudgetGateRejected("complete-task denominator must be positive")
    _same((arm.trainable_parameters for arm in arms), "trainable_parameters")
    _same((arm.optimizer_bytes for arm in arms), "optimizer_bytes")
    _same((arm.update_steps for arm in arms), "update_steps")
    _same((arm.encoder_forwards for arm in arms), "encoder_forwards")
    _same((arm.exposed_train_rows for arm in arms), "exposed_train_rows")
    if len(differentiated.future_window_successes) != len(
        unsplit.future_window_successes
    ):
        raise BudgetGateRejected("future-window inventory differs")
    windows = len(differentiated.future_window_successes)
    if windows == 0:
        raise BudgetGateRejected("future-window evidence is required")
    paired = tuple(
        a - b
        for a, b in zip(
            differentiated.future_window_successes,
            unsplit.future_window_successes,
        )
    )
    differentiated_total = sum(differentiated.future_window_successes)
    unsplit_total = sum(unsplit.future_window_successes)
    return {
        "schema": "hepta.shared-stem.equal-budget-review.v1",
        "arms": [differentiated.name, unsplit.name],
        "equal_budget_verified": True,
        "future_window_count": windows,
        "future_window_deltas": list(paired),
        "differentiated_total_success": differentiated_total,
        "unsplit_total_success": unsplit_total,
        "complete_task_denominators": [
            differentiated.complete_task_denominator,
            unsplit.complete_task_denominator,
        ],
        "three_future_windows_available": windows >= 3,
        "differentiated_arm_wins": differentiated_total > unsplit_total,
        "statistical_or_causal_winner_selected": False,
        "ndu_authority_granted": False,
        "production_promotion_permitted": False,
        "authority": "DENY_ALL",
    }
