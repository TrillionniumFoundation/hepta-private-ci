# Registered trained-checkpoint numerical appendix

This package is outside the immutable `call_put_stable_flow` production package.
It audits **new** selected checkpoints and does not recover, repair, or reproduce
the unavailable older checkpoints. It never alters production source, weights,
selection, primary test scores, or training hyperparameters.

## Frozen scope

The specification is in `PROTOCOL_SPEC.json`; the actual immutable registration
is under
`research_evidence/hepta_stable_flow_20261029/trained_numerics_appendix001/`.
Registration occurred after the core study freeze/prepare and before candidate
training, validation selection and test scoring. It binds the core protocol,
freeze seal, complete production source hashes, appendix implementation and
specification, and byte-identical copies of the first four training episodes.

Registered protocol SHA-256:

```text
5d22bec38799f63e10a58b7bc8ff91feb179a4c0108ddc9272a07dbf4b1d9934
```

Registration seal SHA-256:

```text
24eab192f72d0ac836e3ec74cbb075622e1dbff5c95ccb4f7c2fc4530eb06a85
```

The scope is 24 validation-selected aliases: analytic and matched_c1, both
tasks, all three training seeds, and the `cpu30` and `updates384` regimes.
Repeated physical checkpoints are computed once per `(task, arm, checkpoint
SHA-256)` and every alias is retained. Duplicate aliases are not additional
independent evidence.

## Two separate numerical questions

### End-to-end CE diagnostics

Every selected physical checkpoint is evaluated on the same first four training
episodes, with all 32 ticks and query-masked mean cross entropy. Gradients are
unclipped and no optimizer runs. Initial states remain parameter-dependent.
The stored float32 weights, inputs and times are exactly promoted to float64.

Four evaluations are fixed in advance:

1. Registered step in float32.
2. The same registered step in float64.
3. Half that step in float64.
4. One quarter of that step in float64.

The first pair isolates arithmetic precision. The double-precision evaluations
separately measure finite-step sensitivity. The quarter-step result is **not**
declared a continuous-time ground truth.

| Comparison | Maximum scaled logit difference | Relative gradient L2 difference |
| --- | ---: | ---: |
| Same step, float32 versus float64 | 1e-5 | 1e-4 |
| Half versus quarter step: reference consistency | 2.5e-4 | 2.5e-3 |
| Registered versus quarter step | 1e-3 | 1e-2 |

Each gradient threshold applies to the complete gradient and separately to
`content`, `boundary_input`, `boundary_dynamics`, and `rate_head`. This prevents
the larger content block from hiding an inaccurate boundary gradient. Relative
error uses `max(1e-8, reference L2 norm)` as its denominator; raw reference and
observed norms, absolute errors and eligible cosines are also retained.

If half-versus-quarter consistency fails, the result is
`reference_unresolved`, not a precision certificate. No additional adaptive
meshes, retraining or checkpoint replacements follow from this diagnostic.

### Independent continuous-time flow diagnostics

The preselected subset is seed 81301 for both modes, tasks and regimes: eight
aliases before physical deduplication. It uses the complete first training
episode and learned flow parameters, with an independently recomputed initial
equilibrium. The independent NumPy/SciPy oracle is the source-bound audit module
from the core package; it does not call production `rhs` or production kernels.

This probe uses a fixed scalar function of the whole v/q/z trace and four fixed
unit parameter directions. Its gradients are **not** the end-to-end CE gradient
or the full continuous-time Jacobian. DOP853 tolerance refinement and two finite
difference epsilon values check the reference before qualification is reported.
The registered state, direction-gradient and reference-stability gates are
listed verbatim in `PROTOCOL_SPEC.json`.

All raw logits, CE, flow features, final states/memory, named parameter gradients,
reference traces, parameter directions and finite-difference outputs are saved.
Failures and unresolved references remain in the evidence. They do not exclude
checkpoints from the formal study or change validation selections or test scores.

## Commands

Run from the repository root with the pinned study Python environment. The
registration command below has already been executed for `appendix001`; it is
shown for reproducibility and refuses to overwrite existing output.

```sh
python -m experiments.call_put_stable_flow_appendix.checkpoints register \
  --study research_evidence/hepta_stable_flow_20261029/formal_run001 \
  --output research_evidence/hepta_stable_flow_20261029/trained_numerics_appendix001
```

After all training finishes and validation selection has been sealed, run the
appendix, preferably before formal test scoring:

```sh
python -m experiments.call_put_stable_flow_appendix.checkpoints run \
  --study research_evidence/hepta_stable_flow_20261029/formal_run001 \
  --output research_evidence/hepta_stable_flow_20261029/trained_numerics_appendix001
```

The runner does not load validation or test examples or scores. It records
whether a test-results file already existed when it started, without reading
that file. It verifies the registered source/data hashes and selection seal,
then writes a new `execution/` directory. Each physical checkpoint has raw NPZ
files and a receipt; `execution/summary.json` preserves the alias map and flags.

The development pipeline was exercised before training results existed using
newly generated MQAR episodes and a fresh **untrained** analytic model. All
numerical stages executed and passed their frozen gates. Evidence is at
`development/appendix_pipeline_smoke001/`; it is not a trained result. Its coarse
mesh gradient discrepancy was about 1.26e-5 overall but 1.30e-3 for boundary
dynamics, illustrating why group-level reporting is included.
