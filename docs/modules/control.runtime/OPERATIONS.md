# control.runtime operations

## Startup

1. Resolve the approved owner identity, generation, policy epoch, and policy digest.
2. Read the trusted external current-generation anchor.
3. Open the owner with `ControlRuntimeOwnerV1::open_fenced`.
4. Reopen and structurally validate the durable store.
5. Replay the exact-attempt execution state machine.
6. Reject startup on unsupported legacy product records, semantic ordering failure, generation rollback, skipped generation, or anchor mismatch.
7. Admit canonical producer ports only after the owner is ready.

## Restart

A same-generation restart supplies a zero predecessor anchor and the exact stored current anchor. Requests, authorizations, dispatch state, terminal state, and `Indeterminate` attempts are reconstructed from durable records. Restart does not convert unknown outcomes to failure or success and does not automatically resend them.

## Generation advance

A strict `N → N+1` advance supplies:

- the external anchor recorded for `N` as predecessor anchor;
- the new non-zero anchor for `N+1`;
- the new approved policy epoch and digest.

Rewind, skipped generation, owner drift, policy drift, missing predecessor anchor, or predecessor-anchor mismatch fail closed.

## Backup and restore

Backups are accepted only after complete store validation. Before restore, retain and compare the external checkpoint/generation anchor. Restoring a byte-valid but stale local snapshot without matching external evidence is prohibited.

## Indeterminate attempts

Do not retry automatically. Query the effect owner or physical system for an observed terminal result, construct an exact-attempt reconciliation receipt, and append it through `reconcile_indeterminate`.

## OrganHost incidents

Panic or post-return deadline/output-budget violations poison the production host. Stop routing new work, preserve the per-target receipt, reconcile potentially delivered targets, and replace the host under a new reviewed generation. A poisoned host is not retried in place.

## Qualification and release

A source candidate requires both source-head and synthetic-merge lanes. HIL, physical-device, independent security, activation, and release evidence are separate signed artifacts; source CI does not synthesize them.
