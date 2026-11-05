# Pocket4: current adapter identity and isolated head execution

## Outcome

The current six-tensor Laya adapter was bound to the live trainer's effective
configuration, candidate manifest, parent adapter and complete base-checkpoint
hash. It has 2,379 finite F32 parameters. The independently constructed effective
head matrices respect the declared masks, and restoring the parent inside the
isolated CPU objects reproduces the parent's probe outputs byte for byte.

**The original forward tolerance gate failed and remains failed.** On the one
prespecified 1,000-scale synthetic input, scorer.1 has five coordinates exceeding
atol=rtol=0.00002 for each of parent and child. Both attempts and their complete
child-process costs are retained. This is neither a qualified model improvement
nor proof of a defective candidate weight. No private rows or raw weights are
published, and no production parameters, services, admission settings or orders
were changed.

## Current observation, rather than a cumulative training claim

The bound status was written at **2026-11-05 03:29:57.869 UTC**
(2026-11-04 22:29:57.869 America/New_York); the read-only capture finished at
03:30:17 UTC. The later head probe completed at 03:43:32 UTC.

| Item | Observed value |
|---|---|
| State | CANDIDATE_READY_AWAITING_FORWARD_ADMISSION |
| Job counts | RUNNING 0; COMPLETED 114; FAILED 2; ADMITTED 0 |
| Pending evaluations | 0 |
| Candidate | 8fe51f354c8a75001b0948c3588cab7d62dcb54c90f932f32e7bf9eb1505bf5a |
| Candidate adapter SHA256 | 94a8a2275e92fa6343b5c2b662c3a440c3cc870f067d73e86bb1c0069b880ee0 |
| Parent adapter SHA256 | 52adec4b889f2898d554877e3534f3121503f88850920868e9adc5b6547a7a73 |
| Base checkpoint SHA256 | 9d628fd971b700382ac6f65920a86f149777b2e748e0c955fb3b19695aa8f204 |
| Base checkpoint size | 643,835,514 bytes, fully streamed for hashing |

The trainer and evaluator services were active. A running service is not a
running optimizer job. The 114 completed jobs are not 114 cumulative epochs:
each bounded episode starts from its configured parent, with optimizer state
continuous inside the episode and reset between jobs.

The source guard withheld a forward evaluation because the latest original
quote was not fresh, source continuity was not ready, and source quality was
held without refresh authority. This is missing prospective evidence, not a
negative performance result. No evaluation, live quote or admission was fabricated.

The candidate manifest reports 32 training rows, CE 2.352705989 to 2.350429371
and Brier 0.983678963 to 0.982979106. These are training-only measurements and
were not independently repeated here. It also reports 80 action update steps
and 40 unique action labels. Repeated presentations do not add independent
labels. The action head predicts **ACT versus ESCALATE based on frozen-parent
answer correctness**, not BUY versus SELL, Call versus Put, trade permission,
future PnL or an NDU admission decision. Its training-only temperature calibration
and the price calibration's approximately 0.03975 model weight are not forward
efficacy.

The execution-service log classification at 03:39 UTC covers only 120 retained
journal entries from approximately 03:31:38 to 03:38:49 UTC. The service was in
auto-restart with exit status 6 and restart count 3,941; the trainer still had
zero restarts. The classifier does not bind the installed binary to source and
does not establish the root cause. No old catch-up diagnosis is promoted to an
explanation of this current window.

## What was actually executed

The script extracted the two actual adapter classes from the source used by the
live trainer, bound their raw source and AST hashes, and executed those classes
on six real base-head tensors. The 643 MB base was hashed, but the encoder was
not loaded or executed. The three layers are:

| Layer | Base weight shape | Permitted effective coordinates | Actual F32 coordinates changed | Relative L2 versus bound parent |
|---|---|---|---:|---:|
| scorer.1 | 768 by 768 | rows 0 through 3, rank 2 | 3,072 | 0.000308449493 |
| scorer.3 | 1 by 768 | row 0, rank 1 | 768 | 0.004688384129 |
| act_head.2 | 2 by 256 | columns 0 through 63, rank 1 | 128 | 0.001662790762 |

The combined relative L2 is 0.000331335034, or 0.0331335034%. Its denominator
contains **only these three head weight matrices**, not the full pretrained
model or the adapter factors. This is a measured CPU-F32 effective-matrix norm,
not an exact-real norm proof or an original ROCm mixed-precision replay.

Each layer received the same fixed 16 synthetic inputs with seed 20261105:
zero, one, minus one, alternating signs, seeded Gaussian inputs including one
scaled by 0.001 and one by 1,000, and an action-mask-specific input. The worker
used one CPU thread and did not initialize GPU state. The declared forward
reference is an independently evaluated NumPy F64 expression; the effective
matrix reference separately accumulates the F32 rank terms and has its own
atol=1e-7, rtol=2e-6 gate.

The first attempt stopped at HEAD_FORWARD_REFERENCE_MISMATCH. It therefore did
not reach the final live-binding checks or the complete restore report. A
second diagnostic attempt used unchanged identities, inputs and tolerances and
continued through all three heads. It confirmed:

- scorer.1: parent and child each fail five elements, all on probe index 5,
  the prespecified 1,000-scale input. The maximum absolute difference is
  0.0007302586382, and the largest error-to-allowed ratio is 3.319938143.
- The other 15 scorer.1 inputs and all 16 inputs for scorer.3 and act_head.2 pass.
- All three effective-matrix reference gates and exact mask checks pass.
- Frozen base weights and biases are unchanged; in-memory parent restoration
  reproduces the original outputs byte for byte.
- The live binding, original adapter/source bytes and base metadata are stable
  through the second execution.

The diagnostic also evaluates a conservative standard-F32 rounding estimate.
All errors lie inside it, which is consistent with accumulation/cancellation.
The bound is computed in F64, without outward rounding, and is **not** a formal
certificate of the hardware arithmetic. The failing coordinate identities were
not retained, so equal counts and maxima are not proof that parent and child
failed at exactly the same coordinates. This post-failure diagnostic does not
change the frozen gate or prove a candidate-independent numerical cause.

The parent contains no action adapter. The bound constructor initializes its B
factor to exact zeros; hence the initialized parent action wrapper has exactly
the base effective matrix despite its seeded A factor. This was checked in the
preserved source, not inferred from the absence of factor names.

## Resource accounting

| Attempt | Complete child CPU seconds | Child wall seconds | Peak child RSS bytes | Child exit |
|---|---:|---:|---:|---:|
| Original fixed gate | 2.011968 | 4.171219 | 654,192,640 | 2 |
| Explanatory diagnostic | 2.046843 | 4.151250 | 684,548,096 | 2 |
| Sum | 4.058811 | 8.322470 | Not additive | Both failed |

Each worker ran under the remote job's 50% CPU quota, nice 15 and 2 GiB memory
limit, with a 150-second supervisor timeout. The supervisors themselves exited
successfully after preserving the failed children; a successful outer process
must not be confused with a passing model check. Their CPU windows are separately
retained. Do not add worker-internal timers to the complete child totals. These
numbers exclude transfer, reasoning, historical model training and energy.

## Reproduction and retained evidence

Run the public record verifier with Python 3:

    python -B verify_records.py

It checks original-byte hashes, source identities, protocol consistency, error
gates, aggregate arithmetic and failure accounting. It does not rerun private
weights or certify public records as a substitute for a model execution.

The actual probe needs the authorized Pocket4 installation, the bound trainer
configuration and matching private candidate/parent files. Run either preserved
probe source with --output pointing to a new absent directory using the trainer's
configured Python, with one-thread numerical environment variables. It refuses
a changed live candidate or content binding. Exact reproduction against the
frozen private snapshot additionally requires restoring its source configuration
in an isolated environment; the live-discovery script must not silently switch
to another candidate. Never run the included supervisor twice with its original
exclusive output directory.

PRIVATE_INPUT_SNAPSHOT_RECEIPT.json records exclusive owner-only preservation of
the two small adapters, three manifests and two source files on the authorized
host. The copies and originals were hash-checked before and after capture. This
is not a transactional cross-file snapshot. The large base checkpoint is not
duplicated and must still be obtained with the recorded full SHA256. The public
receipt contains hashes and sizes only. No private raw inputs are in this package.

INDEPENDENT_PROBE_REVIEW.json records a separate source/record review, including
its limitations and the parent-constructor confirmation. The static snapshot,
execution-log classifier, both failed probes and private preservation are
different observations with their own timestamps; none is silently represented
as an atomic snapshot or prospective trading experiment.

## Remaining acceptance boundary

Finite synthetic head inputs cannot establish behavior on real encoder
activations. CPU-F32 qualification cannot establish original accelerator
semantics. Restoring an isolated object cannot establish deployment rollback,
power-loss recovery or live-trainer recovery. The trader-to-Hepta-Neuron mapping,
causal feature/value labels, prospective held-out task value and production
admission remain unqualified. A concrete live weight repair requires those
bindings and a fresh original source window before an efficacy claim.
