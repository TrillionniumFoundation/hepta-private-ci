# Serializable no-reservation recovery

The original read-only operation lookup is not a negative execution proof. A
reserve can commit after an absence query, including after cancellation of its
calling future. Recovery must use `seal_unreserved_operation(operation, effect)`:
one AuthBus `BEGIN IMMEDIATE` transaction either returns the existing hot/archive
reservation or persists an immutable non-admission fence. Reserve checks that
fence under its write transaction; a SQL trigger independently rejects insertion.
A seal never cancels or refunds an existing reservation.

The seal binds the original operation ID and effect digest, is idempotent for
that identity, conflicts on semantic drift, participates in the authority
checkpoint digest and dirty publication protocol, survives reopen and cannot be
updated/deleted. The 65,536-seal ceiling rejects new seals; it must never evict
identities. Restoring a database still requires the existing independent AuthBus
checkpoint. No new signing keys or authorization paths are introduced.

All hosts sharing the JSON reference registry also share a bounded in-flight
operation set. Dispatch and reconciliation cannot concurrently enter the same
operation. Dropping/cancelling/panicking unwinds the guard without retaining a
mutex across an await. This live-process fence is not a substitute for the
persistent AuthBus seal: a cancelled SQLite request can still finish its commit.

Recovery is observer-only. Unknown observations remain unknown, and an observer
must be registered for the original configuration. No missing row, lost reply,
clock timeout or legacy NotApplied flag authorizes redispatch or an invented
success. The supported provider remains the fixed exact KV-v2 read profile;
dynamic lease mutation, production activation and external acceptance are not
established by this change.

Native regression cases cover original reservation preservation, late reserve
after restart, same/different semantic seal replay, concurrent seal/reserve,
checkpoint digest inclusion, direct SQL mutation denial and live operation guard
unwind. The SQLite migration can also be exercised independently in a Python
sqlite3 database; that is schema evidence, not execution of Rust/HTTP/consumer.
