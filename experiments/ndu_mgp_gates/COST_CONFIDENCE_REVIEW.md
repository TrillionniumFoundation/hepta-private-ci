# P1 paired actual-resource comparability: conservative uncertainty gate

Status: **RESEARCH_ONLY / HOLD_NO_GO / DENY_ALL**. This patch is an additive child of draft PR #3251 and does not alter #3055's frozen model, protocol, or any real heldout sample.

## Reproduced bug

The original evaluator's `physical_total_cost` gate compares only the observed across-seed total-cost ratio. It already computes seed/world paired bootstrap differences but does not use their uncertainty in the cost *ratio*. A controller can pass the point margin despite a large repeat-seed risk of violating the declared resource constraint.

In the deterministic synthetic regression (registered three training seeds, all 32 paired worlds per seed), the expected NDU/free-controller ratio is **1.0198019802**, below the preregistered limit **1.05**, but seed 101 has an observed ratio **1.1485148515**. A paired seed-then-world bootstrap gives an upper familywise-adjusted ratio bound above 1.05. The previous implementation incorrectly returned `physical_total_cost=True`.

## Fix

- Preserve the original point cost ratio and observed full-stage cost ledger; do **not** substitute proxy MAC for actual resource cost.
- Reuse precisely the existing paired hierarchical bootstrap sample indices for all arms and calculate an actual cost ratio on each replicate, not a ratio of confidence bounds.
- Set `physical_total_cost` only if **both** the point ratio and Bonferroni-adjusted upper bootstrap ratio are no greater than the registered cap.
- Surface `bootstrap_upper_cost_ratio` in each of the six control comparison receipts so the limit decision is auditable.
- Add a targeted adversarial seed-cost fluctuation regression that old code fails and the new code passes. Prior 15 P1 tests remain unaffected.

## Verification

`python -m pytest -q test_paired_superiority.py` requires NumPy and pytest; local current-session run completed 16 P1 tests and 37 combined risk/output/P1 tests successfully on Python 3.13 / NumPy 2.3.5. Reverify GitHub **exact-head** scoped tests and blocking CI before any integration. This does not authenticate caller-supplied raw-output witnesses, prove independence, validate a real NDU advantage, or approve production use.

An empirical bootstrap interval, even simultaneous and paired, is not a strict deterministic per-world resource guarantee. When a hard request-level cap is required, it must be separately enforced at runtime with actual metering and irrevocable abort/denial. This patch addresses the statistical **fairness claim** only.
