# MemoryCell disjoint 40+72: original-shard archive closure

This read-only repair is NOT a new model experiment, independent source
population, human sufficiency judgment, learned-memory result, or production
qualification. The existing source-committed disjoint 40+72 plan remains
unchanged. The generating workflow [#38423223376](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38423223376)
ran at source `bc76ac57ba972bf105c71ddd997cd215cec5df2e`,
attempt 16. All 16 calibration-shard and 16 evaluation-shard jobs ended
successfully, but its evaluation collector FAILED before release/replay.
The original run's terminal conclusion therefore remains **failure**.

The failure was traced to the collector CLI parsing `prep, plan, inputs`
while the preregistered workflow passed `plan, inputs, prep`. It opened
`observations/plan.json` instead of the independently pinned original
`plan/plan.json`. Commit `f4c0876023a2b5ecc69ae30b81bfb53ee5c0b7b0`
repairs **evaluation collector routing only** and adds a positional
regression. No historical raw model answer is edited.

The new `hepta-memory-disjoint-archived-closure.yml` checks exact
original failed-run identity, 32 successful generation job statuses, all
18 source-pinned Actions outer artifact IDs, byte counts and SHA-256
digests, and each archive's safe member population. It then reopens
the **already frozen** calibration policy, reconstructs 72 original
evaluation rows, and independently verifies source bytes, original
evidence selection, citations, task success and costs in a separate
process. It has no optimizer and issues **zero new model calls**.

Verification SHA and generating SHA are recorded separately. Success
here can certify an immutable historical 40+72 within-fixture result,
not prospective transfer or a successful original workflow. Failure
must remain explicit; no earlier completed run is spliced into gaps.

**Four-stage disposition:** Reader reference still lacks independent human
sufficient-evidence reviews. Nonparametric event organization has historical
within-fixture gains but no independently held-out human entailment proof.
Parametric-policy and knowledge-module candidates must beat the strongest
same-reader, same-tools organized baseline on genuinely future sources and
actual program execution outcomes, with frozen source-before-task snapshots.
Source retention, extraction, indexing, training, each read, revocation,
maintenance and deployed recovery must be measured; unknown terms remain
unknown. `blocking-ci` and all production owners remain mandatory.

Run model-free archive tests:
`python3 -m unittest discover -s scripts/memory_cell -p test_disjoint_archive_recovery.py -v`.
Inspect the **exact new Actions SHA and both replay jobs** before treating
the archive closure as complete.
