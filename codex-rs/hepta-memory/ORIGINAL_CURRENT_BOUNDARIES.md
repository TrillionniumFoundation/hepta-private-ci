# Original Current boundaries for external effects

A protected original CognitiveStore keeps the same checkpoint coordinator that
was bound during exclusive exact-cut recovery. No runtime caller can install a
replacement publisher. Legacy stores without that binding retain their existing
behavior and acquire no protected-current guarantee from this module.

The original FinalUse dispatch first retains the ambiguous dispatch and Entered
claim in SQLite. It then holds the original database-wide `BEGIN IMMEDIATE`
serialization lock on the physically read-only observation pool, validates the
live writer and original local lease, captures the complete cut, and asks the
bound Root checkpoint to acknowledge it. Only the original Root Current ACK for
that exact cut allows FinalUse claim and immediate target entry. A local hash,
transport send, or timeout is not Current.

After target settlement, the writer publishes the complete original cut again,
including any successfully retained secondary settled marker. Recovery batches
also publish their final cut before returning or attempting receipt retirement.
Notes retirement revalidates and acknowledges Current while the same original
read transaction remains held through the metadata-only application ACK. Native
HOS2 prefix retirement separately publishes the original terminal-prefix cut
before entering the original kernel history capability. Read-only discovery,
operation binding, and retirement queries use the observation pool and roll back
read transactions rather than invalidating a valid Current head.

The existing whole-pool SQLite commit hook remains mandatory. Publication closes
commits and leaves them closed after success; the next writable checkout must
obtain a fresh Root Dirty ACK. A stale checked-out connection cannot commit
behind Current. Unknown or cancelled Root publication permanently fences every
clone of this owner generation before the SQLite serialization lock is released.
A later Root response cannot reopen it. The effect is never automatically sent
again, even if publication failed before the destination was entered.

The protocol does not make two independent stores one atomic transaction. A
crash between local commit and Root publication can leave Dirty or Publishing;
normal exact-Current recovery refuses that state. No local re-hash, fabricated
checkpoint, or implicit administrator repair promotes it to Current. Cross-boot
publisher changes require their own original Root administrative policy and
qualification. Host tests do not establish native Asterinas execution or power
loss durability.

Development checks exercise the original FinalUse authority and original SQLite
owner with an explicit checkpoint transport fixture: withheld effect reply is
observed without redispatch, terminal Current precedes receipt retirement, lost
entry Current causes no effect, and lost terminal Current preserves the local
terminal row while withholding retirement and fencing subsequent writes. The
fixture signer and checkpoint are explicitly not production authorities. Run
`just test -p codex-hepta-memory --lib` and the owning Agentd integration suite
before scoped `just fix` and `just fmt` for an affected stage.

Recorded stage validation: the complete owning memory library passed 353 tests
with 10 intentionally skipped qualifications. This includes four new original
FinalUse/SQLite cases covering reply loss, both publication-loss boundaries, and
synchronous FinalUse rejection with an independently acknowledged terminal cut.
The retained run is `current-boundary-owning-tests-03.log`; no production Root,
real application, or native kernel is substituted by its explicit peer fixture.
