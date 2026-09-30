# Durable restart predecessor and replacement lineage

## Scope and claim boundary

This amendment records the current `runtime.supervisor` restart repair on the
existing remediation branch. It does not create a second lifecycle owner, a
second restart budget, or a new product control plane. The existing durable
restart budget continues to bound attempts and backoff. A private, checksum-bound
lineage record now supplies the process identity proof that the budget previously
lacked.

This is repository source and test design. It is not evidence that the exact
candidate compiled, passed native tests, ran on selected Linux/macOS hosts, or
received independent operational acceptance. Those facts require current
execution receipts.

## Failure addressed

The previous recovery path restored a pending restart with this inference:

```text
an adopted runtime exists
    -> the pending restart already has a replacement
    -> a later healthy observation may complete the restart
```

That inference is unsafe. A daemon can fail after durably claiming a restart but
before the predecessor exits. Recovery can then adopt the predecessor. Process
existence or health does not prove that a new process generation was created.
The predecessor could therefore consume the pending restart and prevent the
requested replacement.

Attempt numbers also repeat after a restart window rolls over. An attempt number
alone is not a stable operation identity.

## Durable identity model

`restart_budget::RestartClaim` now exposes both:

- `window_started_unix_ms`;
- `attempt`.

The pair identifies one durable restart operation. The private
`restart_lineage` owner records:

- Agent identity;
- exact predecessor spawn generation, process identity and release identity;
- whether the predecessor exit was exactly observed and its lease was removed by
  the same owner;
- exact replacement spawn generation, process identity and release identity;
- one bounded phase: `predecessor_owned`, `replacement_pending`,
  `replacement_started`, `completed`, or `cancelled`;
- a domain-separated SHA-256 digest over the complete semantic record.

The file is a bounded owner-only regular file below the Agent run root. Reads
reject symlinks, unsafe permissions, multiple links, file substitution and
concurrent mutation. Publication uses a same-directory create-new temporary file,
file sync, atomic replacement and directory sync through the existing durable
publisher.

## State transitions

The required ordering is:

```text
claim restart budget
    -> bind exact predecessor, or prove that no predecessor exists
    -> retain original drain/stop/kill control and deadline
    -> exactly observe predecessor exit
    -> finish same-owner lease cleanup
    -> mark replacement pending
    -> spawn and durably lease a strictly newer same-release process
    -> bind exact replacement
    -> observe readiness for that replacement
    -> mark lineage completed
    -> clear the pending restart budget
```

A daemon failure at any arrow replays the same transition. The exit,
replacement-binding and completion writes are idempotent for identical evidence
and conflicting for changed evidence.

## Recovery rules

A pending budget and an owned process are reconciled as follows:

- exact predecessor: retain the restart and continue the original termination;
- no process and no lease after exact predecessor cleanup: queue the replacement;
- exact replacement: wait for that replacement's health; do not queue another;
- completed lineage with a still-pending budget: clear the budget idempotently;
- cancelled lineage: keep the attempt/window history and suppress restart;
- any unrelated process, stale lease or changed release/generation: fence the
  retained owner, attempt termination and leave the lineage unresolved.

A missing sidecar after the budget write is handled conservatively. If an exact
process is owned it becomes the predecessor, never an assumed replacement. If no
process and no lease exist, recovery begins at `replacement_pending`.

## Stop and Kill dominance

Operator Stop/Kill first persist their exact target identity and original
deadline. They then cancel both the lineage and the pending bit in the shared
restart journal while preserving attempts and window origin. Failure of either
write is reported. Emergency termination of already-owned main and Matrix
processes is still attempted even when persistence fails.

## Source and regression bindings

Primary source paths:

- `codex-rs/hepta-supervisor/src/restart_lineage.rs`;
- `codex-rs/hepta-supervisor/src/restart_budget.rs`;
- `codex-rs/hepta-supervisor/src/control.rs`;
- `codex-rs/hepta-supervisor/src/recovery.rs`;
- `codex-rs/hepta-supervisor/src/tick.rs`.

The focused lineage tests cover:

- a predecessor cannot complete its own restart;
- exact predecessor exit, fresh replacement and completion;
- replay of exit, replacement binding and completion;
- reconstruction after the budget/lineage publication cut;
- rejection of a changed live process identity.

The existing full Supervisor library, default daemon product,
`production-authority` profile, source-head lane and deterministic ordered-parent
merge lane remain mandatory. Test source is not a passing receipt.

## Remaining gates

This repair does not by itself close:

- final compilation, formatting and strict lint for the exact source/merge
  candidates;
- durable Matrix quarantine and terminal reconciliation;
- the complete release-change/no-runtime Stop/Kill supersession matrix;
- selected-host SIGKILL, storage, PID, drain, service-manager and soak runs;
- 256 real Agent/Matrix pairs under mixed slow/failing load;
- external key custody, real production control-chain execution, security review,
  operator acceptance, activation or release.
