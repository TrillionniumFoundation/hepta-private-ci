# Additional P3–P5 review

Current scientific status: **NOT_EVALUATED**. These files contain an additional
read-only aggregate audit and engineering fixtures. They do not execute or
replace the frozen experiment, supplement, bootstrap, or original review.

Before first use, include this module and its tests in the new operational
source freeze. After the actual original postseal review completes, run:

```bash
PYTHONDONTWRITEBYTECODE=1 "$VERIFIED_PYTHON" -B postseal_analysis_coverage.py \
  --review-complete "$ACTUAL_REVIEW_COMPLETE" \
  --expected-review-complete-sha256 "$EXTERNALLY_HELD_COMPLETE_SHA256"
```

The completion hash must come from the actual execution closure. The helper
verifies the completion and original implementation bytes, calls that original
`review.open_gate(arguments, supplement_wait4)`, and requires its full primary
pipeline, source, 14-job, 30-seal, and literal-restore admission before decoding
the bound `REVIEW.json` or aggregate. It rechecks original input stability.
Providing no arguments safely returns `NOT_EVALUATED` without outcome access.

Exit 0 means **DECLARED_COVERAGE_CHECKED** only. Exit 2 means unavailable or
rejected input (`NOT_EVALUATED`) or inconsistency after admission
(`INTEGRITY_FAILURE`). Exit 3 reports missing declared costs or original review
integrity issues. None of these statuses assigns net benefit, full campaign
cost completeness, efficacy adoption, all-positive effects, or global optimality.

P3 retains all B field/history/full-current-state effects and fixed seeds.
P5 checks every C simple effect, interaction, and retention contrast; a positive
interaction can coexist with two negative simple effects. The original frozen
boolean is checked exactly and is never strengthened after looking at outcomes.

P4 checks physical work, expected paths, required metrics, and metric coverage
against `run.evaluate_paths`, `Costs.since`, `architecture_kernel.Work`,
`architecture_endpoints.work_delta`, and `report_results.cost_rows`. Known
optional zero-suppressed counters are distinguished from missing paths. Their
original conditional means are retained. B selected-operation timers are not
whole-path CPU/wall measurements; original preflight total CPU was not recorded.
These limitations and unknown historical work remain explicit. C frozen
references carry their own warm-up cost. Per-path ledgers never replace global
stage/scoring rows, and overlapping scopes are never added together.

Engineering verification (synthetic data only):

```bash
PYTHONDONTWRITEBYTECODE=1 "$VERIFIED_PYTHON" -B -m unittest test_postseal_analysis_coverage -v
```
