# P0 / P6 Native Agent A/B/C comparison — frozen source identities

This folder pins the original **three source commits and tree SHAs**. The pinned
commits are **research baselines**, not assertions about today's branch tips.
They do not assert current production qualification or grant any new effect
authority. Do not rewrite this record when an upstream branch advances; make
a new preregistered experiment revision.

- **A:** current Hepta + bound Codex App Server
- **B:** Hepta + independently versioned Codex Bridge
- **C:** Hepta native Agentd + model-neutral inference + Hepta Runtime
- Evaluate identical task fixture/oracle, random seed, model profile, physical
  target host profile and exact resource budget in all three arms.
- Cell scales are 64 / 256 / 1024 / 4096. These are logical Cells, not four
  separate budgets, models or claims of simultaneously resident agents.
- Source identity means the **actual built SHA/tree** of each required project.
  Merely repeating its digest in a JSON file is not source attestation.
- Include full process and provider traces, tool effects, CPU/RSS/GPU, p95/p99,
  model costs, restarts, cancellation and unknown-effect reconciliations.
- Independently test Cell splits against **no-change, reuse, fixed Cell count,
  shared Head and equal-compute sparse MoE** with grouped future holdouts and
  negative-transfer/old-task retention measures.

## Commands

`python3 -m unittest discover -s qualification/native-agent-comparison -p 'test_*.py' -q`

`python3 qualification/native-agent-comparison/compare.py BASELINE.json real-observations.json`

The committed `BASELINE.json` intentionally has no task fixtures or real
model/target identities. The CLI **must fail closed** on this baseline.
The local test suite exercises synthetic fixtures solely to verify the
comparison checker and **does not produce runtime evidence**. An internally
consistent collection of receipts only shows structural comparability;
`independent_acceptance=false` and `physical_execution_proven=false` remain
hardcoded until an external, independently authenticated evidence owner
validates actual provider, tool, runner and device outcomes.

The execution-port source changes belong to
`codex-rs/execution-core/src/ports.rs`. They do not override the existing
Hepta V8 Codex App Server execution spine or authorize physical cutover.
The referenced upstream Runtime PR stack, real model calls, mandatory Rust CI
and signed Final-use verification remain independent P2–P6 blockers.

## P5 split/merge efficacy holdout (source-only)

`python3 -m unittest discover -s qualification/native-agent-comparison -p 'test_*.py' -q`

`python3 qualification/native-agent-comparison/cell_split.py frozen-cell-plan.json independently-observed-cell-rows.json`

`cell_split.py` requires six equal-limit arms: `no_change`, `reuse`,
`fixed_count`, `shared_head`, `sparse_moe` and `split`, paired over
64/256/1024/4096 logical Cells. The preregistered cohort contains exact
source/model/target/evaluator digests, task fixture/oracle digests, grouped old
test tasks and at least five entirely unseen future groups with disjoint
families. Only `test` and `future` observations enter measured scores; any
train/calibration overlap with the evaluation families fails closed.

The structural scorer compares future-group gains against the strongest
other arm *within each future group*, uses a seed-bound grouped bootstrap,
measures old-task retention against `no_change`, enforces per-row measured
resource limits and refuses missing/duplicate pairs, changed source or
model profiles, unknown effects and idempotency replay. Its output can
report `candidate_meets_structural_metrics` but it **always** returns
`HOLD_NO_GO_INDEPENDENT_EVIDENCE_REQUIRED`, with
`independent_acceptance=false` and `physical_execution_proven=false`.

These are synthetic unit tests for evaluator invariants, **not** learning
runs, valid held-out results, source/host attestations or evidence that Cell
division produces AGI. A distinct authenticated evaluator must authenticate
the actual source, model, corpus, measurements and producer identities before
any selection or production promotion.

## P5 source-family independence hardening (source-only)

The future bootstrap operates on **independent original-source family groups**,
not merely on distinct text labels for groups. Five groups named differently
but sharing the same family are one correlated family, not five independent
future sources. The evaluator now rejects a future family appearing in more than
one future group, rejects a future group mixing unrelated families, and rejects
an identical original fixture digest reused between otherwise independent
cohort groups or train/calibration/test/future boundaries. Repeated seeds of an
original source **within the same group and split** remain allowed and do not
increase the number of bootstrap groups.

These checks prevent one form of pseudoreplication and exact-byte leakage;
they do not authenticate the manifest, prove independent data collection or
rule out near-duplicate sources with different bytes. The frozen evaluator still
returns `HOLD_NO_GO_INDEPENDENT_EVIDENCE_REQUIRED` even if structural metrics
pass. Require external original-source identity review, signer-verified physical
receipts, statistical review and all real model/host gates before selection.

## P6 scale-isolated A/B/C descriptive statistics (source-only)

The A/B/C comparator now publishes `scale_summaries["64"|"256"|"1024"|"4096"]["A"|"B"|"C"]
with per-scale task success, tool/recovery correctness, wall p95/p99 and peak
RSS. Historic pooled `mode_summaries` remain for compatibility; they may
conceal severe scale-specific regressions and must not be used to authorize
4096-Cell deployment. The test fixture verifies a 4096-Cell C failure remains
visible even while the pooled C success fraction is 75%.

`concurrent_throughput_proven=false` is unconditional. These records are not
concurrent 4096-Cell throughput measurements, and the v1 comparison does not
report independently measured CPU/GPU usage, queueing, power or wall-clock
throughput. Those physical measurements and signed original-source evidence
remain **OPEN** P6 acceptance blockers. All result values are synthetic/
untrusted unless authenticated by a separate owner; the comparator always
returns `independent_acceptance=false` and `physical_execution_proven=false`.

## P6 paired native-vs-Codex deltas (source-only)

The descriptive `paired_effects[scale][C_vs_A|C_vs_B]` values compare the
**same frozen task ID and seed** at each Cell scale. Unlike pooled per-mode
averages, a Native C failure against an A/B pass is counted as a distinct
`reference_only_passes` regression. Quality deltas are percentage points;
resource deltas are mean **C-minus-reference**, so negative cost means less
resource use by C. The result includes conservative
`any_paired_quality_regression` across task success, tool correctness and
recovery, as well as discordant win/loss counts.

These are *descriptive* counts, not valid significance tests: separate task
IDs are not evidence of independent original-source families. The source-only
pairing layer intentionally returns
`statistical_significance_proven=false` and
`independent_measurement_proven=false`. A future independent evaluator
must authenticate task-family independence, real tool/provider/target-host
receipts, CPU/GPU/throughput measurements and negative-transfer evidence.
Neither P6 nor the P5 cell-split gate is promoted by these statistics.
