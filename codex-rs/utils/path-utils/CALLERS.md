# Windows retained-artifact callers

The single native backend and complete State-compatible predicate live in this
crate. No dependency points back into a consumer.

| Consumer | Entry adapter | Retained capability |
| --- | --- | --- |
| State recovery | `sqlite_recovery_io` and Windows identity/security facades | Verified new output and original-directory sync; borrowed source inspection only |
| Operator acceptance | `durable_windows_artifacts` | Bounded private read/hash, private new/replace, native sidecar exclusion |
| Shadow qualification | `durable_windows` | Exclusive private bootstrap, file I/O, full-inventory read-only custody and sync |

[Development, technical contract, bootstrap and failure rules](PRIVATE_ARTIFACTS_WINDOWS.md)
apply to every caller. Existing unsafe directories are not repaired or migrated.
Legacy `open_private_state_*` consumers retain their existing API contract; they
are not converted into writable `RetainedPrivateDirectory` by a borrowed handle.
