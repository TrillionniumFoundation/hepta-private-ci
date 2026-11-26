# Concrete streaming HCSN research backend

`StreamingRidge` executes the existing `BatchedFlow` kernel with a frozen encoder
and a linear readout. Observations advance the actual population, signed content,
boundary and integer-microsecond clock. Optional supervised observations update
bounded ridge sufficient statistics. `propose()` solves the regularized readout
problem and returns separate candidate weights; it does not replace the active
readout. This is a CPU FP64 research profile, not a production adoption path.

## Complete state and exact numerical continuation

The backend schema is
`hepta.hcsn.streaming-ridge-state.v1.cpu-f64.erlang.population`.
It is carried inside the existing `hepta.hcsn.complete-research-state.v2`
envelope. FP64 tensors are represented as shape plus unsigned IEEE bit patterns,
so JSON float parsing cannot alter their numerical bytes.

| Section | Concrete contents |
| --- | --- |
| parameters | Drive/writer weights and biases, active readout weights and bias |
| backend | Full flow configuration, probability and signed-content populations, all refractory phases, upper account, boundary, clock, batch and output sizes |
| optimizer | Explicit `NotUsed`: this profile uses a closed-form readout |
| controller | Ridge coefficient, completed observation/example/solve counts and separately retained discarded-work counts |
| RNG | Explicit `not_used`: no stochastic future transition or learner draw |
| cost ledger | Every original reservation and settlement, including failure, in a hash-linked journal bound to the request and budget |
| history | Gram and feature-target cross matrices; no past autograd tape |

Positive-observation snapshots require a positive-definite regularized normal
matrix. With no supervised observations, both sufficient-statistic matrices must
be zero. Merely symmetric matrices with nonnegative diagonal are insufficient.

The three geometry buffers must exactly equal the configuration-derived grid,
centers and reset distribution. The constructor rejects a changed buffer or a
bias-free readout and rebuilds standard modules from the declared parameters;
incidental hooks and Python attributes do not become hidden state. Snapshot
creation checks geometry again. A backend with custom geometry needs another
schema, not reinterpretation of this one.

The Erlang phase populations are the complete renewal state for this profile.
They are not a fixed-delay cohort queue, and this codec cannot restore a
`PopulationAge` backend or reinterpret sparse/Q24 snapshots. The flow's Call
feature remains finite frozen-policy continuation; this module does not turn it
into full He–Xiong equity or an optimal stopping value.

## Recovery and costs

The caller must retain the expected checkpoint digest and the admitted request,
dataset, source/runtime, schema, parameter-mask and learning-rule bindings
independently. The backend validates byte identity and schema semantics;
agreement does not authenticate an untrusted producer's source/runtime claims.
The host remains responsible for freezing and verifying the actual worker.
The streaming update bridge fixes `request_digest` to the canonical complete
`CellUpdateRequestV1`, including scope, source frontier, base bundle, generations,
all resource caps and ordered parameter IDs. `request.py` and the native digest
function implement the same versioned encoding; the host supplies it before work.

The live durable `CostLedger` must contain the checkpoint's exact settled prefix.
Work performed after a retained checkpoint is not refunded. Recovery records it
as discarded work, preserves its cost, and resumes the numerical state from the
acknowledged checkpoint. An unfinished reservation retains unknown cost and
blocks recovery through the existing journal policy. Candidate construction and
tensor copies occur inside the same charged operation as the ridge solve.

`snapshot()` produces bounded envelope bytes; durable file publication and
independent acknowledgement remain the caller's responsibility. A streaming
tensor state is bounded by configuration, while the audit journal has an
explicit 64 MiB complete-envelope cap. Reaching the cap is a rejection, not
silent truncation. No checkpoint claims to retain the old autograd graph.

## Native research bridge

`HcsnStreamingCodecV1` implements the existing native complete-state codec. It
decodes actual parameters, populations, signed-content bounds, clock, statistics,
controller and cost records, and returns a concrete state that can re-emit the
exact admitted bytes. It requires a `PopulationGrid` clock profile and checks
the recovered clock/grid agreement; the owner must still admit the actual
interval plan. Rust does not run the PyTorch matrix-exponential kernel.

`HcsnStreamingUpdatePortV1` validates the real readout proposal against the
regularized normal equation, verifies the frozen parameter mask and independent
admission, and exposes an immutable parameter artifact and lineage to
`CellUpdatePortV1`. The host must supply measured peak process memory. The port
checks the complete recorded wall cost and generation/budget constraints, grants
no authority, changes no live model/state, and does not replace independent task
evaluation or artifact-owner publication. The residual tolerance belongs to this
new consistency check; it does not relax any existing HCSN qualification gate.
The step budget and receipt count all charged proposals, including failed and
discarded work. Costs and lineage are read-only views of the sealed snapshot,
which is revalidated at preparation; the clock's scope/generation must agree
with the update request. Lineage also binds the full request, clock checkpoint
and final parameter artifact, in addition to the source checkpoint and journal.

## Verification commands

Use the pinned PyTorch runtime with one CPU compute thread:

```sh
python -m unittest qualification.hcsn_streaming.backend_tests -v
python -m qualification.hcsn_streaming.backend_tests --fixture codex-rs/hepta-neuron/tests/fixtures/hcsn-streaming-ridge-v1.json
```

The Python tests include a fresh-process checkpoint continuation and exact next
population/statistics/candidate equality, recovery without refunding discarded
work, invalid-state rejection, unsupported-geometry rejection and charged copy
failure. The generated fixture contains actual BatchedFlow transitions and a
PyTorch solve using small unit inputs; it is not a task holdout or a performance
benchmark. Native verification follows the repository's `just test` workflow,
then scoped fix/format. Unit host memory values are explicitly fixtures and must
not be reported as measured task costs.
