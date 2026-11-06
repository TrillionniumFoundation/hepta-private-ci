# Canonical writer rotation qualification

Source `035d67e99dcbe1243718d8f9e2b4efffcaa6b54b` passed the original
Rust1.96 owner/service/wire/proof/sender scope: 46/46, 60.339s, 271 filtered.
Five new cases exercise original canonical revocation versus a foreign registry,
expired and pruned exact signed predecessors, complete successor binding,
concurrent lost-ACK reconciliation and post-I/O expiry without counter refund.
The same issuer key, original head, shared sequence and retained writer proof
remain. Spawn generation must increase; it is independent of the local lease's
exact one-step generation. No additional issuer or operation ledger is created.

The original compile-only failure for a missing nested assertion import is
retained. Initial Clippy reused stale check-only contracts metadata and failed;
only this lane's derived contracts artifacts were invalidated. Original scoped
fix then passed in184.884s and final fmt passed in0.375s. Source snapshots bind
all stages; the tested-to-finished changes are mechanical formatting. No tests
followed the finish phase. This was a warm isolated cache, not a cold build.

This trusted administrative API authenticates the predecessor through the same
canonical verifier and exact signed identity. The launcher must separately prove
old process quiescence, capture the actual successor identity and legally retire
the original local writer lease. Checkpoint adoption is another durable CAS;
uncertainty requires exact retained-state reconciliation, never reset or rollback.
These controlled owner tests do not qualify Root service deployment, two actual
writer generations, Dirty recovery, reboot or native execution.

[Original stage records, source digests and complete logs](publication.json)
include both initial failures. No key material or private fixture disk is included.
