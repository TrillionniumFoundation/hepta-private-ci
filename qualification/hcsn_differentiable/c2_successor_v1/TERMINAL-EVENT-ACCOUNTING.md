# C2 terminal event corroboration

The exit-zero terminal gate now reads the exact hash-bound producer event bytes
and requires the recorded resume witness, contiguous epoch boundaries, one
update/start/completion sequence per claimed main optimizer step, matching
logical and continuation counters, identical epoch summary rows, and one final
completed-development record. Empty, torn, ambiguous, nonfinite, oversized,
reordered, duplicated and incomplete journals fail closed. Rejection retains the
separately measured process CPU and wall fields.

This is producer-journal consistency, not independent training replay or
checkpoint/optimizer tensor validation. Synthetic test checkpoint bytes are
deliberately opaque and are never loaded. Failure-result counter semantics are
unchanged; the new corroboration only admits claimed exit-zero completions.

The exact parent is #6028 source `a83b2ecda37b0e18b05e7fedcaee0a63037c464f`.
An actual-source AST RED run admits all twelve malformed-journal counterexamples;
after the fix, all thirteen new controls and six existing terminal JSON controls
pass. Raw attempts and source digests are retained in
`evidence/c2-terminal-events-20261112/`.

The original C2 job was not restarted or changed. Its retained independent
inventory still reports four of six producer results, two zero-byte interrupted
checkpoints, a torn command journal, absent controller RESULT, and zero of six
independently complete training replays. No new model execution is added here.
All scientific and production gates remain HOLD_NO_GO. A new source freeze and
bound decision are required before any prospective successor can execute these
changed controller bytes; historical manifests are untouched.
