# Continuous task boundaries and dual feedback on the actual Hepta neuron

**Completed result: 0/3 registered benefit gates passed.** See [the Chinese research report](REPORT.zh.md), [all outcome and cost tables](results/RESULTS.md), and [complete evidence reproduction](REPRODUCE.md). The original strict audit rejection and the explicitly cost-normalized passing view are both retained.

This experiment adds a task-value boundary and continuous features to the
existing first-passage cell, then lets **the original Rust sparse neuron and
NDU choose actions in a closed-loop maintenance task**. It separates three
questions: boundary value, dual-channel representation, and expected-flow
versus event feedback. It does not modify or admit a production neuron.

The scientific base is `5898cd8b0f724c3152b6cc52856721f72e5e08be`
on `research/first-passage-cell-20261028`. All new code and evidence are scoped
to this directory. See `MATH.md`, `PROTOCOL.json`, `PROTOCOL_REVIEW.md`, and
`native/README.md` for the mathematical, statistical, and native contracts.

## What is actually compared

| Panel | Arms | Common information and mechanism |
|---|---|---|
| Boundary | `fixed_margin`, `learned_margin`, `value_margin` | Same state, costs, deadline, dynamics, past action-conditioned risk flow, head-fitting data and objective; C/P/current risk channels masked |
| Channels | `value_margin`, `value_call`, `value_dual`, `generic_gate` | Same value-derived boundary; progressively expose continuation and intervention values; generic gate gets the full derived inputs |
| Dynamics | `value_dual`, `event_reset`, `native_sparse`, `dense_recurrent` | Same full inputs, same original native sparse substrate; compare the additional input-state recurrence |
| References | `dp`, `always_keep`, `always_repair`, `always_stop` | Same physical task, public parameters and paired innovations; references bypass learned native processing |

Every learned arm has a common frozen 20-by-20 encoder, original width-20
sparse recurrence with top-k 4, and **42 active fitted readout scalars**.
`learned_margin` additionally fits 20 boundary coefficients. Generic gating
and the dense recurrent adapter use fixed random mixing matrices, not a
fully trained GRU/LSTM. Parameter and input budgets must therefore be read
as the explicit counts in `models.py`, not as a claim of identical total
stored scalar counts or full recurrent training. Twelve development
candidates are evaluated per arm/seed; all coefficients and candidates are
frozen before any confirmation environment is created.

The DP action-value teacher is available equally to every learned arm on
training contexts. At execution, value-based arms solve the known public
model for their context; fixed/direct boundaries do not read DP values.
That planning cost is measured, never treated as an information-free gain.
The model is known; OOD changes public task parameters, not the laws secretly.

## Preconfirmation deadline amendment

Revision 2 replaces `remaining / initial_horizon` by `remaining / 16` in
the shared public input and direct-boundary regressor. Together with public
`dt`, every arm can recover the same absolute remaining task time. The first
run was stopped during training; no confirmation contexts or outcomes existed.
Its partial training artifacts and costs are retained separately. Seeds,
objectives, dimensions, candidates and acceptance thresholds are unchanged.
See `preflight/DEADLINE_AMENDMENT.json` and the preserved first source seal.

## Registered experiment

Eight independent training/environment seeds, nine learned arms, and four
reference policies. Each seed/arm has 128 ID plus 128 OOD episodes, giving
26,624 registered episodes. The primary sample unit is the **seed**, not a
tick or individual episode. Common Philox uniforms use six fixed slots per
window, so different actions and STOP times never consume different streams.

Primary paired comparisons:

1. `value_margin - learned_margin`: value-derived boundary.
2. `value_dual - value_call`: additional risk/intervention representation.
3. `value_dual - event_reset`: expected probability flow versus realized events.

The registered net objective is task utility minus `1e-6` times transmitted
numeric payload bytes. All neural arms actually transmit 20 i64 Q24 values
(160 logical bytes per tick); JSON wire bytes are also measured. CPU, boundary
planning, build, owner journal and replay costs are reported separately. This
is **not** an all-cost utility or an energy measurement.

A three-comparison Bonferroni family uses paired seed Student-t intervals
(individual 98.3333% confidence, familywise 95%). A benefit gate requires the
lower endpoint to exceed 0.005 task units. Descriptive seed-bootstrap intervals
are secondary. No extra seeds, candidate tuning, or episode deletion is allowed
after confirmation. An exception preserves the incomplete run and prevents a
complete-study claim; the auditor requires every registered episode.

## Actual execution and durable integration

The primary evaluation uses a persistent Rust host invoking unmodified
`sparse_tick` and original NDU for every learned action. It is a bounded pure
execution path without per-tick disk journals. Native checkpoints, activations,
Q24 head scores, action digests and source execution counts are recorded.
The mathematical adapter remains Python research code.

A separate engineering study re-executes 96 preselected existing confirmation
cases through the original Agentd owner, durable journal and witness. It saves
the **whole task** (physical state, six adapter states, preceding risk/event,
clock and utility), closes the process, resumes from disk in a new process,
and continues using newly generated features and actual Rust decisions.
These are zero additional scientific samples. STOP rejection, tampered events,
profile mismatch, and exact retry behavior also have native checks.

The owner clock advances 10,000 microseconds per tick; task time advances by
the public physical `dt`. The clocks are recorded separately. Repair resets
the task environment; the native sparse recurrent state continues.

## Reproduction

Use Python 3.11+ with the exact numerical package versions in
`requirements.txt`. The recorded environment identifies the Python version.
The native builder uses Rust 1.95.0 and the original lockfile dependency
identities; no scientific results depend on a Python sparse-kernel emulator.

```sh
python -m experiments.continuous_boundary_flow.native.build \
  --repository "$PWD" --destination /absolute/path/native-build \
  --compiler /absolute/path/rust-1.95.0/bin \
  --vendor-cache /absolute/path/cargo/registry/src/index

python -m unittest experiments.continuous_boundary_flow.test_math \
  experiments.continuous_boundary_flow.test_models \
  experiments.continuous_boundary_flow.test_audit

python -m experiments.continuous_boundary_flow.native.test_native \
  --binary /absolute/path/continuous_host --output /absolute/path/native-checks

CONTINUOUS_NATIVE_BINARY=/absolute/path/continuous_host \
  python -m unittest experiments.continuous_boundary_flow.test_integration

python -m experiments.continuous_boundary_flow.smoke \
  --binary /absolute/path/continuous_host --output /absolute/path/smoke
```

The source/protocol seal is published before formal training. Formal phases
verify the seal, protocol, selected profiles and native binary at each stage:

```sh
python -m experiments.continuous_boundary_flow.study initialize \
  --binary /absolute/path/continuous_host --output /absolute/path/study
python -m experiments.continuous_boundary_flow.study train \
  --binary /absolute/path/continuous_host --output /absolute/path/study
python -m experiments.continuous_boundary_flow.study confirm \
  --binary /absolute/path/continuous_host --output /absolute/path/study
python -m experiments.continuous_boundary_flow.audit /absolute/path/study \
  --output /absolute/path/study/AUDIT.json
```

Run the owner integration with
`integration.run_owner_study(study_dir, binary, engineering_dir)`.
The audit independently reconstructs physical utility, ABM first-hit forecasts
and conditional hit times, quantized head scores, actions, state chains,
paired innovations, record completeness and seed-level inference.

## Scope of the claim

This is a finite-window sampled task with a numerically solved intervention
boundary. It is not the complete financial He–Xiong equilibrium, an exact
continuous-time impulse-control solver, or a proof of smooth fit. C/P are
objective-linked continuation and failure/intervention components.

The full execution chain retains clipping, Q24 quantization, hard sparse
selection and discrete NDU actions. Training fits readouts and selects feedback;
it does not perform end-to-end gradient training. A favorable result would
support these state representations and this task implementation, not prove
that a globally differentiable continuous spiking network has been established.

Risk probabilities are analytic forecasts under the known task model; their
calibration is evaluated on each policy's visited states. Lower Brier score
alone does not establish a superior learned risk estimator. Bounded long-run
engineering probes are not an infinite-horizon stability proof. No energy or
neuromorphic hardware advantage is inferred from sparse events or closed forms.
