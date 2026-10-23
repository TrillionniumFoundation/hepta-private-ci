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

## P0 exact local Git source guard (shadow / non-authorizing)

Use the source checker before invoking an A/B/C comparison on a named, locally
available trio of repositories:

```sh
python3 qualification/native-agent-comparison/source_guard.py \
  --baseline qualification/native-agent-comparison/BASELINE.json \
  --hepta /path/to/hepta-private-ci \
  --runtime /path/to/hepta-runtime \
  --codex /path/to/codex
```

It matches **HEAD commit and tree** against the frozen P0 manifest for all
three repositories, rejects dirty/staged/untracked (including ignored) worktrees,
assume-unchanged/skip-worktree index entries, unpinned submodule gitlinks,
environment-level Git overrides and wrong repository roots. It calls the
existing strict baseline validator for model, host, task and budget pins.
If the frozen plan still contains missing fields, the command exits nonzero.

```sh
python3 -m unittest discover -s qualification/native-agent-comparison -p 'test_*.py' -v
```

**Nonclaims:** Git source matching cannot attest the *built* executable, the
dependency cache, generated inputs outside the checkout, model weights, source of
task/oracle data, independent result provenance, machine resource usage or
physical effects. The receipt explicitly retains false values for
`actual_built_source_attested`, `independent_acceptance`
and `physical_execution_proven`. It is diagnostic source
qualification only. Real A/B/C runs still require signed host/build attestations,
independent outcomes, actual matched-budget measurements and effect reconciliation.
