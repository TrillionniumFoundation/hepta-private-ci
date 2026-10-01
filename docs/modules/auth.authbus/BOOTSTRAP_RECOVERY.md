# AuthBus retry-safe bootstrap

## Scope

`bootstrap_retryable` is the public bootstrap entrypoint. It treats the
authority database and independently retained checkpoint as one pair without
pretending that two filesystem domains can be installed in a single atomic
rename.

The state machine is:

| Database | Checkpoint | Action |
| --- | --- | --- |
| absent | absent | create the first pair |
| present | present | open and reconcile the exact pair |
| absent | present | fail closed as rollback/drift |
| present | absent | repair only when the database is provably pristine |

## Pristine-orphan proof

A database-only state is removable only while the normal owner fence is held
and all of the following are true:

- SQLite `quick_check` succeeds;
- exactly migrations 1 through 7 are present and successful;
- every trusted-time, policy/history/archive, quota, reservation/archive and
  issuer table is empty;
- no local authority checkpoint exists;
- no pending incremental-frontier event exists;
- the dirty and recovery singletons are both false;
- the frontier accumulator is the single v1 row at sequence zero;
- reopening through `AuthBusAuthorityStore` passes exact schema/checksum/file
  hardening and still reports no local checkpoint or recovery work.

Only then are WAL/SHM/journal sidecars and the empty database removed, followed
by a parent-directory fsync and a normal first bootstrap. A failure after that
point remains retryable through the same entrypoint.

## Non-repairable states

The function never reconstructs a checkpoint for an existing authoritative
database. Any business row, dirty frontier, recovery marker, local checkpoint,
pending journal event, unknown migration or checkpoint-only state requires a
matched restore or an explicit incident decision. The operator tool uses this
entrypoint; the raw first-bootstrap constructor is crate-private.

This source behavior does not substitute for target-host ENOSPC, fsync, rename,
power-loss and mount-isolation evidence. Those remain required before canary
approval.
