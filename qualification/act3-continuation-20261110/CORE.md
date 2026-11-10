# ACT3 stage 2: procedural continuation implementation

This review stage contains the research continuation and six behavioral rejection
tests. The separate qualification stage adds the subprocess campaign and its
complete raw evidence, keeping the implementation independently reviewable.

The private GRU state, exact pending action, original invocation identity, task,
model bytes, feature/model/provider/continuation sources and budgets are bound
into a strict checkpoint. The fixture SQLite owner atomically stores its current
checkpoint head. A stale exported snapshot cannot replace the owner's head.
Post-inference hidden state is committed before applying the primitive. Restoring
a pending operation reconciles original identity before continuing and does not
evaluate the GRU a second time for the same decision.

The implementation retains the original model's choices, including premature
termination failures. It qualifies continuation correctness, not a policy fix.
The shared stop guard has separate retrospective evidence in the preceding stage.

Six tests cover corruption, invalid hidden values/counters, exact version/task/
model binding, old checkpoints, call-ledger rewind, missing/mismatched effect
owners and unavailable observations. One rejection uses an actual new process
importing changed provider source bytes, rather than merely editing a label.

```sh
python3 scripts/act2_learning/test_continuation.py \
  --model qualification/act2-learning-20261110/run2/B4_gru-seed-700.npz -v
```

These are same-UID, single-writer SQLite research fixtures. They are not production
CellStateOwnerV1/FinalUse authorization, independent trust-domain enforcement,
concurrent writer qualification or host power-loss recovery. Durable primitive
reservations, owner reads and restoration metadata reads are metered; checkpoint
SQL commits are reported separately. Surviving-process scorer queries are named
as such. Complete lifetime cost remains unqualified, including killed-process
internal scoring/setup work and all metering/checkpoint I/O. No efficiency or
learning improvement is claimed. Fixed skills remain the reference, NoUpdate.
