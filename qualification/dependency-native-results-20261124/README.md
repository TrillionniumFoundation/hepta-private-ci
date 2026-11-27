# Exact-source dependency interoperability results

These public CI artifacts bind to source
`fb00e4422c293ffb318c9d7535e1991a3bbac707` and contain synthetic fixtures only.
Their ZIP digests were compared with GitHub's artifact digests before extraction.
`receipt.json` records every extracted member's size and SHA256. Recheck the
archive and outcome markers with `python verify_receipt.py` from this directory.

## Keyring: real Linux interoperability passed

Run `45434905989`, job `138594123698`, completed successfully. The registry
keyring 3.6.3 baseline and the backport using secret-service 6.0.0 / zbus 6.5.0
performed all 11 client steps against the synthetic encrypted Secret Service:
both directions of create, update, read and delete, plus the candidate keyutils
cycle and rollback checks. The server recorded 49 encrypted sessions; the
session driver exited zero in 45.675 seconds. The ordinary locked workspace
`codex-secrets` suite then ran 9 tests: 9 passed, 0 skipped.

This qualifies the exercised Linux client behavior. It does not substitute for
all operating systems, desktop Secret Service implementations, or full CI on a
later source head. The artifact records exact binary, source and dependency pins.

## Matrix: encrypted-store migration passed; consumer compile failed

Run `45434905910`, job `138594217616`, failed at the final consumer build.
Before that failure, the real 0.18 baseline created and reopened an encrypted
store. The 0.19.1 candidate upgraded it and reopened it a second time, retaining
the device's Curve25519/Ed25519 keys and custom state. A separate wrong-passphrase
copy was rejected. Each successful operation has its own saved log.

The subsequent `just test` compiled zero consumer tests because the old test
fixture assigned to `TimelineEvent.bundled_latest_thread_event`; SDK 0.19 exposes
that as a method which reads the raw unsigned relations. The fixture correction
preserves the distinction between auxiliary SDK data outside the raw byte budget
and bundled events inside it. A large push-action value must still be dropped
without changing the accepted transcript. A small raw bundle is retained and
counted, while an oversized raw bundle must return `Bounds` without changing the
accumulator. Production validation is unchanged. That correction still requires
execution on its new source head.

Both results predate the new Windows private-owner SQLite VFS. They do not claim
that the new C implementation or its SQLx consumers have passed native tests.
