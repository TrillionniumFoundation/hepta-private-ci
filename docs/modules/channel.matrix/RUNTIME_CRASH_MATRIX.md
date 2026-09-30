# channel.matrix runtime crash matrix

This profile closes the evidence contract for process-level failure qualification. It does not claim that the target executions have occurred.

## Canonical persistence boundary

`MatrixDurableStore` is the sole per-Agent SQLite owner. PostgreSQL is not a substitute for this module's persistence model: a PostgreSQL run may be useful for another module, but it cannot satisfy a `channel.matrix` runtime row. The validator rejects `postgresqlSubstitutionUsed=true`.

## Evidence classes

The closed profile combines distinct evidence rather than promoting one broad test log into every claim:

- `real_synapse`: the pinned encrypted Synapse/dual-agent product fixture on the protected Mac runner;
- `native_process`: an exact native testcase with its own retained process/JUnit artifact;
- `multi_process_native`: a process-level writer-contention artifact;
- `process_fault_injection`: storage availability/failure injection with durable before/after state.

Every scenario receives one distinct canonical artifact. An artifact binds the exact candidate, canonical SQLite owner, evidence class and a closed set of true oracles. Missing, duplicate, failed, cross-candidate, symlinked or reused artifacts fail the validation command.

## Required invariants

The complete target must prove:

1. a non-idempotent effect is not duplicated;
2. unknown is never downgraded to not-started;
3. a stale generation cannot commit;
4. durable active state and in-memory active state cannot silently diverge;
5. a worker that lost its lease/capability cannot continue;
6. only the current recovery writer progresses after restart;
7. reconciliation remains bounded and fair;
8. journal bounds retain the evidence needed to classify outcomes.

The machine inventory is [`RUNTIME_CRASH_MATRIX.json`](RUNTIME_CRASH_MATRIX.json). Validate a protected evidence directory with `scripts/channel_matrix_runtime_matrix.py`. A passed runtime matrix remains narrower than deployment qualification and independent acceptance; activation, promotion and release stay false.
