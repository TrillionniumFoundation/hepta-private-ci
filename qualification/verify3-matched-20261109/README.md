# VERIFY matched prospective scheduling comparison — engineering protocol

Status: **implementation tested, prospective independent data NOT collected; HOLD**. Production authority: **NONE**.

`matched_qualification.py` scores two fixed schedulers on a frozen, paired task roster. The scorer is intentionally independent of the earlier model-pilot data and does not invent new trials. The host must freeze the following **before** the first candidate outcome:

1. A source/model/policy/evaluator identity, fixed error event and horizon, a full pair roster and cluster identities, physical environments for each arm, and order allocation.
2. A common disposition-specific loss table for correct/error truth, all paid costs converted into a **predeclared common unit**, and primary coverage/error/utility/statistical thresholds.
3. Independently held label receipt verification and full-physical-cost verification callbacks. A SHA-256, issuer name, signature-looking string or `True` returned by an untrusted caller is not independent evaluation or cost verification.

Inputs to `analyze_matched(manifest, observations, verify_label=..., verify_cost=...)` are plain canonical JSON-compatible objects. Every observed arm row identifies its exact pair, environment, source, decision, terminal disposition, label evidence and time, and complete declared cost receipt. Missing execution is represented by an **absent row** in the frozen roster; a missing horizon label is `terminal_error=None` with no fabricated label receipt. A missing cost is also `None`, not zero. All fields must match their exact schemas; unexpected fields, duplicates, source drift, environment drift, typed-boolean confusion and an early label are rejected.

The result always reports planned denominators and lossless identity digests. It additionally reports acceptance coverage, conditional accepted-error bounds (or `null` at zero acceptance), errors per planned task, whole-horizon error bounds, missing/cost counts, and a **paired loss improvement** only when both arms have complete truth and costs. No propensity or censoring correction is silently assumed. If entire arm observations are missing, coverage is an interval, not a point estimate; missing error states are worst-case bounded, not imputed clean. Clustered pairs contribute one mean per cluster to a one-sided exact sign-flip **descriptive statistic**, limited to 20 clusters. It requires randomized independent experimental clusters and a locked estimand for valid inference; source-group names alone do not prove this.

Even if every numerical criterion and externally supplied callback returns success, the flag is `gates.externally_reviewable`, **not** scientific/production adoption. Independent evaluator custody, timestamp chronology, randomization, task validity, reproducible physical metering, trial preregistration, actual repair/accept effects and multiple-comparison treatment must be established outside this scorer. `scientific_admission=HOLD` and `production_authority=NONE` remain fixed.

## Quick local test

```sh
python3 -B -m unittest experiments.verification_cell_verify1.test_matched_qualification -v
```

The nine tests are deliberately synthetic **counterexamples**, including reject-everything, interrupted missing horizons, dropped receipts, stale/forged identities, duplicated task rows, correlated templates counted as one cluster, lack of terminal improvement, and unauthorized attestation callbacks. A positive numerical fixture demonstrates only that the scorer has an attainable review path; it is **not** an actual scheduler win or a claim of independent field evidence.

## Unclosed gates

- Collect truly independent tasks from a qualified owner, and freeze the experiment before outputs.
- Obtain independent authenticated terminal truth for accept, reject, interrupted and UNKNOWN, including external future outcomes where applicable.
- Measure *all* risk training/fit, candidate selection, checks, repairs, failed/unpublished efforts, native child/parent CPU, memory, time, energy, price and full historical amortization in non-overlapping scopes.
- Compare frozen candidate against appropriately resourced, strong fixed/VOI and existing controls. Preserve complete coverage and all missing observations, and audit cluster dependence/selection multiplicity.
- Obtain full exact-integration-head CI plus reviewed `cargo-deny` diagnostics. Do not reinterpret engineering test success as full deployment qualification.
