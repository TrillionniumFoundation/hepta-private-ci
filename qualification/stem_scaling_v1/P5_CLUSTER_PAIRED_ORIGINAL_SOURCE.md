# P5 original-source paired scaling qualification

**Research only / DENY_ALL.** This child of [P5 source-bound five-axis evaluator #2270](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2270) keeps the exact original P5 output and inherited 15-process CPU/RSS source ancestry. It adds a separate consumer of future *original withheld-label owner* group-scoring receipts; it does **not** invent or claim those real-world receipts exist.

## Physical problem: do four scale levels score the SAME sources?

The base P5 reviewer already requires the same model, task-family SHA, evaluator revision, predeclared training budget and cost axes when varying Cell count, active experts, recursive depth, training rows or compute budget. However, a single 33/64 aggregate score does not establish that candidate answers belong to the same original independent passages or episodes. Repeating 3 random seeds does not create 3 independent source families.

`p5_cluster_replay.py` requires a sidecar produced **only after label-blind predictions have been sealed**, with one record per `trial_id × source_group_id`. Each record binds the source-group SHA, original label-owning score, actual `correct`, actual `total`, and a Boolean descriptive producer statement that human labels were scored. The verifier:

1. Reruns the existing complete five-axis source and cost-entry checks; it never falls back to a fabricated sample.
2. Rejects missing/duplicate/unregistered group IDs or SHA, fake boolean/negative costs, different group counts, or group scores that do not sum **exactly** to original experiment's `correct/total`.
3. On all four points of an otherwise admissible one-axis series, demands identical group IDs, source hashes and candidate denominators; it refuses a putative scaling gain created by a different evaluation cohort.
4. Recomputes the paired group-by-group correct delta between the two largest scales and, for 2–12 declared groups only, enumerates all sign flips as a **descriptive** diagnostic. Missing group coverage is never imputed.
5. Returns `outcome_receipts_independently_authenticated=false`, `independent_cluster_sampling_established=false`, `statistical_gain_claim_admitted=false`, `teacher_or_10t_100t_equivalence_established=false` and `DENY_ALL` regardless of a positive observed difference.

**Critical limitation:** original source SHA strings and `label_owner_scored=True` cannot authenticate the publisher, human annotator, host, truly future data or permitted data access. A dishonest producer could shift correct counts between groups while preserving aggregate totals. The **independent original-label score owner** must cryptographically/source-authenticate per-group outcomes before stronger claims. Only then can paired cluster inference be considered, still with source independence and multiple-testing controls.

## Actual execution and acceptance

Authoring-side Linux local 10 synthetic-contract tests passed in ordinary Python, and 10/10 passed with Python `-O`. The local source imported an explicit minimal `scaling_frontier` test stub and therefore these runs **do not qualify actual parent P5 module integration**, let alone pretrained quality. The uploaded remote source and test Git blobs are to be verified against the exact local tested hashes, and the inherited P5 GitHub workflow now runs both suites against **the real parent P5 source** in current source-head CI. No new original pretrained model or teacher is run here.

To run with genuine approved original evidence:

```sh
PYTHONPATH=qualification/stem_scaling_v1 python3 qualification/stem_scaling_v1/p5_cluster_replay.py \
  --original /sealed/experiment-source-and-scored-totals.json \
  --held-group-outputs /independent/postseal-original-group-label-score.json \
  --output /new/create-only/original-group-pairing-review.json
```

The first input is the strict P5 `hepta.stem-cell-one-axis-scale.v1` observation bundle; the second is `hepta.stem-scaling-original-group-outcomes.v1` with the exact full-byte SHA of the original input. A missing source-score artifact must fail rather than being replaced by synthetic examples. Do not merge to main, promote a selected Stem, re-enable NDU or make a 10T/100T comparison from source-only tests.


## P5 completeness failure (2026-10-15)

Previously a structurally valid three-level sidecar with zero complete four-level comparisons could produce a zero-sweep descriptive review. This did **not** certify a model win, but would leave a missing experiment indistinguishable from a completed negative result to an inattentive caller. The current child source now **raises `ClusterDenied` whenever no complete source-matched four-level sweep exists**. It still rejects missing/altered groups within any present complete series.

A new test removes the entire 4,096-Cell highest-scale trial and its group ledger, rebinds the exact source digest, and proves the missing fourth level is denied instead of counted as a valid empty review. **11/11** normal and **11/11** `python -O` local tests passed on the original test fixtures, with the clearly declared minimal `scaling_frontier` stub used only for local contract execution; exact Git blobs of the updated source/test match the local tested bytes. The full native original parent `scaling_frontier` integration and the exact-head hosted CI still have to finish.
