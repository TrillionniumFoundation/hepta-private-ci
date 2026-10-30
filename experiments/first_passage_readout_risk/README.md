# One bounded readout-risk comparison

This package implements the previously proposed diagnostic comparison for the three
frozen **order-task** encoders. It does not retrain those encoders or change the
original confirmation result of **0/6 advantage gates**. A positive result would
concern only the effect of the two diagnostic readout objectives on these retained
representations. The original native head already used single-rollout BCE during
joint training; this study is not a repair of that training objective.

`PROTOCOL.json` specifies six four-parameter heads, 43,008 native trajectories,
training-only shared standardization, the exact optimizer, one paired 4,000-replica
bootstrap and the 0.02-nat practical margin. Development is descriptive only. Every
head and numerical failure is retained. No tuning, replacement fit, encoder
selection, extra confirmation or automatic retry is provided.

## Freeze before execution

From the repository root, this command only hashes source and existing checkpoint
bytes. It imports no numerical libraries and creates no new random identities,
examples, trajectories or fitted parameters:

```sh
python -m experiments.first_passage_readout_risk.study freeze
```

Review and publish the package plus `FREEZE.json` in an immutable protocol commit.
The freeze includes the complete local native research import chain, the original
task distribution source and three checkpoint files, the proposal, this package,
the CI workflow and exact numerical dependency requirements. It excludes all original train,
development and confirmation data. `RUN_REQUEST.json` does not exist at freeze time.

The next, dedicated execution commit must have that protocol commit as its sole
parent, the exact subject `research: execute frozen readout-risk v2`, and only a new
`RUN_REQUEST.json` with exactly these four fields:

```json
{
  "schema": "hepta.readout-risk.v2-run-request.v1",
  "namespace": "hepta.network.readout-risk.v2.20261030",
  "freeze_commit": "<published full 40-character protocol commit>",
  "one_shot": true
}
```

The independent CI job must additionally require the designated synchronize event
and `run_attempt=1`. A later repair commit must not rerun the experiment. The CLI
verifies the parent, a sole added request, frozen Git bytes, installed versions and
threads before generating data. Publication/one-shot authorization is owned by the
root workflow; local script guards are not a distributed execution ledger.

## Fixed runtime and invocation

Use Python 3.12.14 and `requirements.txt`. Retain the pip installation report with
wheel hashes. Export all six variables below **before** starting Python:

```sh
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 BLIS_NUM_THREADS=1
python -m experiments.first_passage_readout_risk.study execute \
  --freeze-commit <published-protocol-commit> --output <new-output-directory>
```

The untouched native forward runs once per registered example/rollout identity.
Captured counts reconstruct its final three-dimensional trace; every reconstructed
affine score is checked against the native score. Both heads use the same cache and
perform single-trajectory predictions. Confirmation repeats estimate expected risk;
they are not deployed ensembles. Cache generation time/events and fitting time are
reported separately.

NPZ cache shards and gzip stream manifests cover 64 examples each. The final
`ARTIFACT_MANIFEST.json` includes all outputs and failures, with every blob below
480,000 bytes. `COMPARISON.json` distinguishes `pass`, `negative_result` and
`numerically_incomplete`. A completed CI command is not a scientific advantage gate.

## Reproduction without simulation or refitting

```sh
python -m experiments.first_passage_readout_risk.study reproduce \
  --run-dir <retained-run-directory> --output <new-reproduction-json>
python -m unittest experiments.first_passage_readout_risk.test_math
```

Reproduction verifies retained artifact hashes, the source freeze and the
pre-confirmation six-head freeze, then recomputes the same risks and same bootstrap
from saved traces and heads. The three mathematical unit checks use
only fixed small arrays: they make no random draws, call no encoder and fit no head.
Neither command substitutes for native feature validation in the registered run.
