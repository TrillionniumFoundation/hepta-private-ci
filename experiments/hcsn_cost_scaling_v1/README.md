# Trained CPU size and quality/cost extension

This independent, post-baseline study addresses the cost of the complete
distributional HCSN encoder, including its local free boundary, value equations,
matrix propagation and ordinary neural layers. It does not change CONTENT002.

The registered matrix contains 72 trained candidates: selective copying and
MQAR; widths/depths 16×1, 32×1 and 64×2; distributional HCSN, ordinary dual gates,
hard-forward LIF SNN with surrogate-gradient training, and a Transformer;
three paired initialization seeds. Every candidate gets one fixed learning
rate, a 20 process-CPU-second optimizer budget and the same 15/20-second
validation checkpoints. The optional update-128 snapshot is not another
selection opportunity. Physical HCSN channels stay at eight per layer as
content width increases; this is a small-encoder scale study, not LLM scaling.

The source preflight initially rejected the smallest Transformer: its nearest
available architecture has 7,422 backbone parameters versus HCSN's 7,200, a
3.0833% gap. That train-only failure is retained. The final protocol keeps the
three power-of-two sizes, declares a 3.5% maximum gap and reports exact active
parameter counts; it does not introduce parameter padding. All common
frontends/readouts use identical weights within a paired seed and size.

## Quality qualification

Before any heldout access, select the earliest eligible CPU checkpoint reaching
each validation accuracy target: 50%, 75% and 90%. A pair qualifies only when
both corresponding test accuracies reach that target and differ by at most
two percentage points. A task/size/control/target comparison qualifies for an
aggregate report only when all three paired seeds qualify. Missing or failed
models remain incomplete. This descriptive gate is not a statistical test of
equivalence, and passing a lower threshold alone does not make two model
qualities equal. No retuning, interpolation, replacement seeds or extra
training is permitted to complete a gate.

## Cost and provenance

The scheduler records whole isolated-worker `os.wait4` CPU, wall time and peak
RSS, including imports, architecture matching, training, validation, heldout
evaluation, checkpoint I/O and timing. Failed work remains in the central
ledger even if a worker dies before creating its output directory. Optimizer
CPU is a nested component and is not added to the whole-worker total again.

Each selected or target-qualified checkpoint receives a complete 32-token
forward benchmark at batch 1 and batch 32: one warmup, five measured repetitions
and deterministic-output checks. Inputs are already decoded, in-memory feature
tensors. Boundary and analytic/grid calculations are included; media decoding
and cached autoregressive decoding are outside this measurement. Timing
repetitions are not independent training replicates.

This is a shared CPU host. Wall latency is affected by contention; peak RSS
includes the complete process and is not isolated model allocation. No GPU
memory or joules are measured. Initial uninstrumented engineering preflights
are separately identified; their unknown CPU is never reported as zero.

The analyzer verifies source/data/checkpoint identities, recomputes prediction
coordinates, labels, accuracy and CE, loads every selected checkpoint for a
four-sample inference replay, verifies the durable selection locks, recomputes
timing medians and executes every quality gate. Only a complete, integrity-
passing analysis may support an aggregate comparison.

## Reproduction

Use the repository's pinned CPU dependencies and one Torch/BLAS thread. Run
`study preflight`, `study register`, `study run`, then `analyze`, all as modules
under `experiments.hcsn_cost_scaling_v1`. Each execution requires a new output
directory; existing evidence is never overwritten. The exact invocations,
source hashes and data hashes are recorded in the protocol and process ledger.
