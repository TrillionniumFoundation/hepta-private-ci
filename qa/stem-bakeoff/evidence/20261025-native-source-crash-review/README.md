# Source-owner WAL crash boundary: read-only review

**The initial-generation risk remains; the clean prepare fix does not close all unclean source-owner recovery claims.** This review uses 15 exact files from executed commit `3a1431c5879d084bf49b9df67f9792af8f3acbc7`, all SHA-matched to native-build002. The currently formatted copies of these particular files were also identical at review time. No SQLite connection, test, model, source edit or remote write was performed.

## Confirmed mechanism

`CognitiveStore::open` creates the private directory, opens SQLx in WAL/FULL mode and runs migrations before protecting the main database as0600. It does not protect sidecars. The locked libsqlite3-sys0.37.0 bundle contains SQLite3.51.3; its Unix code creates the main file with default0644 masked by the ambient umask, and makes WAL/SHM inherit the main file's mode at their creation. The original failed run's main0600, WAL0644 and SHM0644 are directly retained evidence of this ordering. The ordinary Agentd runtime also calls this initializer when no production writer host is attached.

A first-generation process that terminates before normal connection cleanup can therefore leave0644 sidecars that exact-cut recovery correctly rejects before WAL replay. The creation bug and rejected mode predicate are confirmed; this review did not execute a new forced-crash experiment. This is a recovery-availability gap, not proof that the committed data has been permanently lost. The production host has no legacy ordinary-open fallback.

## Existing protection and the actual limit

Recovery materialization creates the new candidate database and copied WAL/journal with `create_new`, `mode(0600)` and `O_NOFOLLOW`. Exact-cut/integrity validation, checkpointing and main-file protection precede the active candidate's WAL reopen. Its new sidecars inherit0600. Both main and live recovered WAL/SHM in the actual successful v1 run are0600. Consequently this permission finding cannot be generalized to every crash of an already admitted recovered production generation.

The passing writable exact-cut test explicitly closes the seed store. The product-host fixture also closes before recovery. The passing child-exit test is `cold_read_only::crash_reopen_refuses_pending_wal`: it deliberately proves that a cold reader refuses WAL, and starts its child from an already clean-seeded store. It does not qualify writable recovery after a source-owner crash. The v2 probe's two Recover operations are same-process shadow-owner recovery while the SQLite host stays alive.

## Smallest proposed implementation and qualification

For genuinely new initial databases, atomically establish the owned0600 main file before SQLite can create WAL/SHM, under the existing private-root/store guard; preserve no-follow/create-new and race handling. Keep strict0600 admission. Avoid global umask mutation, replacing existing files, chmodding suspect crash evidence or changing the already frozen failed run. Existing0644 sidecars require separately authorized handling.

Before closing the crash claim, use a child with a known ordinary creation mask, commit and externally retain the real current cut, then terminate without close. In another fresh process, verify the remaining actual WAL modes, recover with the correct current authority/fence, assert the full logical cut and make a new durable write while preserving original source bytes. Repeat for a recovered generation. These are proposed gates, not tests performed here.

`review.json` separates confirmed facts, observed artifacts, inference, untested scope and the minimal proposal. Source pins, exact reviewed source, relevant SQLite Unix excerpts, cached-crate/build binding evidence, prior test-log excerpts and actual file metadata are retained. This review changes neither the published success package nor the separately prepared final CI.
