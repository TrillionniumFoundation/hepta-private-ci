# Frozen policy comparison from original journals

`evaluate_policy_journals` joins real `ShadowJournal` / `TreatmentJournal`
records to a single `CheckOpportunityJournal`. It is a descriptive research
boundary. It does not create independent truth, authorize a checker, or promote
a learned policy.

## Execution order

1. Create distinct original shadow/treatment journals for every policy, with the
   same frozen attempt roster, target event, horizon and continuation contract.
   Each policy has its own frozen model/scheduler manifest and physical database.
2. Freeze each policy's complete intended `CostItem` roster. Include stable IDs
   for possible optional checker starts, with `stage="checker"` and the original
   trajectory ID as `attempt_id`. Preserve unused items as actual not-run
   receipts, and unknown executions as missing costs; these are different cases.
3. Call `freeze_evaluation_spec(cost_rosters, losses=..., rates=...,
   utility_unit=..., bins=...)`. The full loss table, all four resource prices,
   calibration bins and cost-roster hashes are included. Freeze its digest as
   the opportunity plan's `evaluation_spec_sha256` before observations.
4. Record each policy's original predecision prediction. Reserve the source
   opportunity and bind each other policy with `bind_policy`, using the same
   original free-evidence digest and exact snapshot. Retain the original offer;
   neither recovery nor evaluation redraws it. Then use the original policy,
   checker, mandatory host gate and terminal-label paths.
5. Supply original `CostReceipt` values and call:

```python
report = evaluate_policy_journals(
    opportunities,
    policy_journals,
    specification=frozen_specification,
    cost_rosters=frozen_cost_rosters,
    cost_receipts=original_cost_receipts,
)
```

The comparison rejects changed policy/target/roster identities, reused physical
databases, post-freeze repricing, omitted planned cost items, unconsumed or
unoffered checker execution, mismatched free snapshots and changed checker
versions. An actual optional start must appear in its frozen cost roster and
cannot carry a not-run receipt. Known completion costs must agree with charged
wall/CPU/energy measurements; wall intervals permit only nanosecond rounding.
Overlapping exclusive resource intervals and duplicate physical operations
also refuse, including across policies.

## Interpretation

Every planned attempt remains in the denominator. Missing finishes, host
dispositions, labels, predictions, tickets, consumption and costs stay explicit.
Pending opportunity draws stay UNKNOWN. The report includes acceptance and
false-accept missing-label bounds; Unknown dispositions; fixed-bin reliability,
Brier and log loss; optional starts/completions/pending exposures; original-label
attestation counts; declared terminal loss and resource costs.

`postdecision_clean_reject_count` is **not** a causal false-rejection count.
A correct named property does not prove authorization, current ownership,
revocation or every other obligation required for acceptance. The report does
not manufacture this missing adjudication.

Declared net utility is unavailable if any terminal outcome, disposition,
resource metric or declared operation is missing, or an optional execution is
still pending. A zero price does not turn unmeasured energy into a complete
measurement. Even complete supplied receipts do not prove the entire physical
lifetime was accounted for. Cross-journal trusted chronology, complete free
information, random-source custody and independent terminal truth remain
unproved. Scientific admission stays **HOLD**, production authority **NONE**.

The integration controls use real SQLite files and original journal APIs with
explicit software fixtures, legacy fixture labels and controlled RNG outcomes.
They add no independently adjudicated business task or demonstrated policy gain.
