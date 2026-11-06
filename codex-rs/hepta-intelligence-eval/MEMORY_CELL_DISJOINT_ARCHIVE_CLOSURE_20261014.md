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

## Verified original-answer closure (2026-10-14)

**New verifier source:** [`73f282338cbe`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/73f282338cbed20edee6cf945fadeef9983de265); [Actions run #38590620658](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38590620658) **success**. Both [archive-replay](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38590620658/job/115944202419) and [independent-replay](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38590620658/job/115944520800) succeeded; their 40+72 original-answer/source/citation/task replay JSON reports are byte-for-byte equal. The **original generating run #38423223376 remains failure**. The verifier called **no models**, did no training, and did not invent historical answers.

**Exact source-bound outcome:** 40/40 calibration inferences and 72/72 nine-arm evaluation inferences are present, successful and independently replayed. The frozen source-only calibration selected k=1 (4/8 strict success on the 8 calibration tasks). On the 8 exposed development evaluation cases (two each: new fact, correction, composition, procedure), no-evidence was **0/8**, hybrid k4 **3/8**, selected k1 **5/8**, single-hop **4/8**, entity/time **8/8**, organized evidence **8/8**, and authored program-support **8/8**. Organized − hybrid k4: **5 paired wins, 0 losses, 3 ties**; these are descriptive within-fixture numbers, *not* a confidence interval for new families. See the [independent archived receipt](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38590620658/artifacts/11906918262).

**Citation and reader go/no-go:** Despite organized and authored support conditions answering 8/8, only **4/8 correct responses in each condition cited the complete program-declared public support chain**. “Correct answer” is therefore not sufficient to qualify faithful memory or source necessity. The support condition is authored, not an independently human-certified sufficient oracle. Removed-premise causal ablation and complete stronger-reader reference remain unavailable or unqualified. Stage 1 **reader/sufficiency certification: BLOCKED**. Stage 2 **nonparametric development improvement: OBSERVED**, with citation and holdout limitations.

**Cost and learning go/no-go:** The identical base Reader consumed **10,806 hybrid-k4 prompt tokens versus 5,179 organized prompt tokens**, with original recorded inference totals **228.52 s vs 116.69 s**, respectively. The latter are sums of actual research calls, *not calibrated like-for-like deployed latency*; model staging, original retention, extraction/indexing, future maintenance/revocation and recovery remain separate, unclosed terms. No prospective learned-policy or knowledge-module task benefit has been established. Stage 3 **parameter learning: NOT QUALIFIED**. Stage 4 **production and lifetime economics: BLOCKED**. `blocking-ci` was not altered or waived.

The [machine-readable audited result](MEMORY_CELL_DISJOINT_VERIFIED_40X72_20261014.json) captures every arm’s original task success, prompt/output tokens, inference seconds, declared support-chain fidelity, the paired contrasts, source digests, artifact IDs and explicit no-promotion gates.
