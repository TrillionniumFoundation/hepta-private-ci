# C2 terminal event corroboration

The exit-zero terminal gate now reads the exact hash-bound producer event bytes
and requires the recorded resume witness, contiguous epoch boundaries, one
update/start/completion sequence per claimed main optimizer step, matching
logical and continuation counters, identical epoch summary rows, and one final
completed-development record. Empty, torn, ambiguous, nonfinite, oversized,
reordered, duplicated and incomplete journals fail closed. Rejection retains the
separately measured process CPU and wall fields.

Review hardening additionally requires exact integer counters, actual epoch-cap
completion for an epoch-cap stop reason, and each shuffled epoch's full training
roster from the hash-bound parent plan and data manifest. Main batches must be
the exact successive slices of that order. Each complete epoch must have a real,
hash-bound commit with the previous commit, exact epoch row and logical update
count, plus a nonempty matching checkpoint. The final commit's checkpoint digest
must match the final last.pt alias and report. The ID and batch schemas were
verified against the actual episode producer and study helper, not inferred
from the synthetic test fixture.

This is producer-journal consistency, not independent training replay or
checkpoint/optimizer tensor validation. Synthetic test checkpoint bytes are
deliberately opaque and are never loaded. Failure-result counter semantics are
unchanged; the new corroboration only admits claimed exit-zero completions.
The patch does not rerun optimizer steps, independently authenticate a producer,
recompute plateau stopping or reselect the best checkpoint from development
metrics. Hash-bound epoch checkpoint bytes are not tensor semantic evidence.

The exact parent is #6028 source `a83b2ecda37b0e18b05e7fedcaee0a63037c464f`.
An actual-source AST RED run admits all twelve malformed-journal counterexamples;
after the fix, all thirteen new controls and six existing terminal JSON controls
pass. Raw attempts and source digests are retained in
`evidence/c2-terminal-events-20261112/`.

The review successor preserves all those earlier logs. Its separate RED on the
first published controller runs 27 tests and emits 18 failure records (including
integer-counter subtests); final new and existing terminal controls pass
33/33, zero failures/errors/skips. The same-session independent reviewer
confirmed the previously accepted counterexamples now reject. New raw logs,
producer schema identities and scope are retained separately in
`../evidence/c2-terminal-events-review-20261112/`. The exact existing HCSN workflow
explicitly runs both terminal test files; repository-wide success is not claimed.

The original C2 job was not restarted or changed. Its retained independent
inventory still reports four of six producer results, two zero-byte interrupted
checkpoints, a torn command journal, absent controller RESULT, and zero of six
independently complete training replays. No new model execution is added here.
All scientific and production gates remain HOLD_NO_GO. A new source freeze and
bound decision are required before any prospective successor can execute these
changed controller bytes; historical manifests are untouched.
