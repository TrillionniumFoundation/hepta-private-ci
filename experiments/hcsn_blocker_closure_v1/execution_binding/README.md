# Preselected trained HCSN execution binding

This package is separate from the frozen content study and the analytical task
oracle/native study. It binds one **preselected trained content checkpoint** to
persistent inference and the actual pinned native owner. No formal test or OOD
score is used to select the checkpoint, calibration states, or sequence lengths.

## Required restored evidence

The study root must contain its exact `PROTOCOL.json`, and the following files:

```text
data/selective_copy_train.npz
fixed/selective_copy__value_jg__seed881101/job.json
fixed/selective_copy__value_jg__seed881101/selection.json
fixed/selective_copy__value_jg__seed881101/selected_state.npz
fixed/selective_copy__value_jg__seed881101/validation_000048.npz
fixed/selective_copy__value_jg__seed881101/validation_000096.npz
```

All registered source files must exist at their recorded repository paths and
hashes. The registered preflight file must also be restored at the path in
`PROTOCOL.json`; for the hosted run this is
`experiments/hcsn_blocker_closure_v1/content/results/hosted_preflight001.json`.
Its byte hash, passing status and complete source map must match registration.

Before execution, independently verify the hosted publication and extract the
training execution commit, the study protocol SHA256 and the preselected weight
archive SHA256 from its verified metadata/member manifest. Pass those three
values to the launcher. Computing arbitrary input hashes without first verifying
their published origin does not establish provenance. The driver requires exact
design, complete source-map and fixed-worker schedule equality as well.

The driver recomputes FP64 validation cross entropy from both raw validation
snapshots and checks the chosen step, tie rule, snapshot hash, weight archive
hash and tensor hash. It does not read the worker `RESULT.json`, test arrays or
OOD arrays. The public training execution commit and registered source/data
identities are retained in `BINDING.json`.

## Execution

From the repository root, with the CPU PyTorch/NumPy/SciPy environment active:

```bash
python -m experiments.hcsn_blocker_closure_v1.execution_binding.measure \
  --study /absolute/path/to/restored/study \
  --output /absolute/path/to/new/binding-attempt \
  --binary /absolute/path/to/pinned/native-owner \
  --expected-study-commit VERIFIED_TRAINING_COMMIT \
  --expected-study-protocol-sha256 VERIFIED_PROTOCOL_SHA256 \
  --expected-checkpoint-sha256 VERIFIED_SELECTED_STATE_SHA256
```

The output directory must not exist. A failed attempt retains its logs and cost
receipt; a retry needs a new output directory. The native binary must match the
unchanged vendor manifest. All owner authority remains `DENY_ALL`.

The first formal-training episode's `x` and `dt` are repeated without changing
the durations. This is an execution probe, not a new content-quality benchmark.

## Gates and scope

1. A length-128 stream is cut after token 37. A fresh Python interpreter reloads
   the weights and full numeric state. Suffix logits and final state must be
   bitwise equal; batch and streaming inference must agree within the frozen
   tolerance and have identical argmax predictions.
2. Actual native execution is compared across an uninterrupted run and a
   prefix/new-process resume. Both must execute `KEEP` five times then `STOP`.
   Signals, neural logits/state and native semantic checkpoints/readouts must
   match. Physical timing fields remain recorded but are not expected equal.
   The neural read entry point and native owner both reject post-STOP reads.
3. Four native interventions use the trained network's actual low/high `J-G`
   states: natural low, natural high, high state with low message, low state
   with high message. All other message fields and the native prefix are fixed.
   The midpoint is calibrated only on the first unlabeled training episode;
   this proves an engineering causal route, not useful classification stopping.
4. Fresh workers measure lengths 32, 128 and 512, including batch and streaming
   inference, CPU/wall time, read latency and persistent state size. Weights,
   inputs, outputs, temporary batch tensors, journals and BPTT are excluded from
   the fixed-state statistic and are not described as constant total memory.
5. The outer launcher records exact `wait4` cost through process exit, including
   imports, verification, all resume/scaling/native descendants, IPC and evidence
   writes. Inner measurements are components, not additive totals.

`HARDWARE.json` records read-only CUDA/device/cgroup/power-counter availability
on the execution host. A missing GPU or energy counter remains an evidence
limitation. Event counts and CPU seconds are never converted into Joules.

The neural kernel executes in Python/PyTorch. The native owner performs real
message validation, persistence, KEEP/STOP and terminal enforcement. Its profile
is bound to an explicit engineering objective digest, not mislabeled as the
analytical posterior task's optimal policy or a learned classification utility.

The source package was prepared before the preselected hosted checkpoint was
restored. An import-only review found an unrelated transitive training dependency;
the failed import and original driver are retained in
`audits/execution_binding_preflight001`. Local numeric serializers now preserve
the same state fields without that dependency. Synthetic import, serializer and
provenance checks do not establish trained execution; numerical/runtime claims
require the resulting `RESULT.json` and `WHOLE_WORKER_COST.json`.
