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

## P0/P5/P6 reproducible build identity and resource Pareto gate (source-only)

In addition to frozen Git SHA **commit and tree**, every A/B/C arm must
declare a unique-content-addressed build/configuration manifest in
`mode_build_digests`. Each observation must bind the three source trees,
the exact mode's build manifest, and a nonzero unique observation digest.
This catches structural substitution and receipt reuse; it does **not**
authenticate the submitter, binary or run. The actual build and physical
tool/model traces still require independently verified evidence.

A/B/C observations must now carry `cpu_ms`, `peak_gpu_memory_bytes`
(zero is valid for a CPU-only run), `active_concurrency`, and the
pre-registered resource limits, in addition to RSS, wall time, token and
tool metrics. Both historic pooled summaries and four per-scale summaries
remain. `scale_deltas` describes B−A / C−A success, recovery, p99 wall,
CPU, RSS and GPU differences. Neither per-task measurements nor these
deltas establish concurrent 4096-Cell throughput:
`concurrent_throughput_proven=false` remains unconditional.

Six-strategy Cell-split scoring now requires three frozen tolerances in its
plan (`max_cpu_overhead_fraction`, `max_rss_overhead_fraction`,
`max_p99_overhead_fraction`). For **every** scale, the split's measured
end-to-end cost must be within those limits against the cheaper of the
same-budget shared-head and sparse-MoE controls. The original
future-family independence, holdout, and old-task negative-transfer
checks remain mandatory. Reused observation digests or a claimed task
success paired with `tool_correct=false` are rejected before scoring.

The committed `BASELINE.json` explicitly leaves all missing physical
build/resource pins as null and has no actual task/target/model observations;
it MUST fail closed. The Python tests are synthetic contract tests, not
real model training or physical acceptance. Model/host attestation, signed
receipts, real 64/256/1024/4096 load, CI and P7 canary remain OPEN.

## P0 physical source checkout guard (integrated from #3546)

`source_guard.py` checks the **actual** three local Git source
repositories against frozen HEAD commit/tree identities, rejects dirty
tracked/staged/untracked/ignored files, hidden index skip flags, gitlinks
without independent submodule pins, incorrect repository roots and unsafe
`GIT_*` overrides. The reused source implementation originated in
#3546 and its temporary-real-Git-repository adversarial tests now run
in the same exact-head Python gate as A/B/C and Cell-split tests.

Usage from a review-controlled verification machine:

`python3 qualification/native-agent-comparison/source_guard.py --baseline qualification/native-agent-comparison/BASELINE.json --hepta /verified/hepta --runtime /verified/runtime --codex /verified/codex`

Paths above are **examples**, not evidence those repositories or a
target machine are present. Do not run against mutated build directories.
This guard does not inspect binary reproducibility, external dependencies,
signed model artifacts, true task results or any physical effects. In
particular the current committed incomplete baseline must still exit
nonzero even when all source checkouts match.
