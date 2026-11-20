# Original lease owner concurrency

The registry remains the sole owner of lease revisions, revocations, epoch and
the protected durable frontier. Only its administrative handle can mutate them.
Verifier handles retain the same original owner identity and complete token
checks. Serializable witnesses remain audit metadata rather than capabilities.

`LeaseState` separates shared verification/dispatch admission from exclusive
administration. A final dispatch keeps a shared guard through its already
selected local callback. Revoke, replacement, pruning, epoch rollover and all
other registry operations acquire the exclusive guard. A mutation cannot cross
any active dispatch, including when one of two concurrent dispatches has already
finished. Each concrete effect owner still supplies its own transaction/lock;
the lease fence does not serialize unrelated device and checkpoint operations.

Time is sampled after acquiring the final guard. Lease, binding, revision,
revocation, epoch and frontier validation are unchanged. Existing callers must
not recursively enter this registry or wait for remote completion in a callback.
The controlled expiry tests now hold the administrative exclusive guard to
represent an actual owner mutation; their clocks and expiry assertions remain
unchanged. A verifier's shared guard no longer represents such an exclusive wait.

Rust's `RwLock` poisons only after writer panics. A separate one-way atomic flag
therefore fences both later verification and administration when any shared
guard unwinds. Ordinary errors retain their original classifications. Persistent
write failures keep the original `State.failed` fence and durable store behavior.

The test-only predecessor reproduces independent dispatch blocking with the
original Mutex. The same simultaneous-entry case also requires revocation to
wait for every active reader. Existing joint/predecessor retirement and
controlled expiry cases remain required, alongside the panic fence test.

This change does not establish a new latency bound or scheduler fairness policy.
The clock and concrete durable stores retain their own serialization and may
still stall. The actual 3bae/final1138 guest failed at `writer_open_initial` on
Current request 87 with a 501252347ns stream timeout; that result does not
distinguish registry wait, store I/O or scheduling. The producer Mutex is a
confirmed blocking mechanism, not a proven unique cause of that guest failure.
The original 500ms total exchange limit, cache freshness, protected clock,
Unknown/no-replay rules and all production trust requirements are unchanged.
Fresh full owning tests and a new original native qualification are required;
host concurrency tests cannot supply native or production qualification.
