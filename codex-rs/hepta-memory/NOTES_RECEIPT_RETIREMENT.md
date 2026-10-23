# Managed Notes receipt retirement

**Concurrency qualification reopened on 2026-10-23.** A later actual
competitor returned `Ok(ProductionQueuedReceipt)` and committed SQLite changes
while the metadata-retirement callback was still held. The read-only pool's
`BEGIN IMMEDIATE` did not provide the intended writer exclusion. The earlier
59/59 and 33/33 results remain historical test results; their short pending
observation does not prove mutual exclusion. Notes retirement and the HOS2 and
pre-effect paths sharing this barrier remain blockers pending a real fix and
actual competing-writer acceptance. No physical Current/recovery safety is
claimed from this barrier.

The [actual competing-writer counterexample](acceptance/2026-10-23-retirement-counterexample/README.md)
retains both failing phases, original source deltas and exact binary hashes.

The managed durable writer must retain an application receipt until the exact
terminal operation and its whole-owner recovery cut have been acknowledged as
Current. Losing that receipt earlier could make a recoverable local operation
lose its only application outcome evidence.

`cognitive_checkpoint_bind.rs` installs one private `BoundOwnerPublication`
capability during consuming bind. `cognitive_checkpoint_publication.rs` erases
only the original coordinator's transport type; it owns no store handle, key,
Objective sender, operation ticket or additional journal. All cleanup uses
that same coordinator and the original whole-pool commit gate.

`production_notes_owner.rs` starts the original read-only BEGIN IMMEDIATE
transaction, revalidates the exact terminal outbox operation and calls
`acknowledge_bound_owner_transaction` in `production_owner_publication.rs`.
The intended contract requires actual SQLite writer exclusion across complete
anchor capture, Root Current acknowledgement and synchronous application
metadata retirement. The current read-only transaction does not establish
that exclusion, so another writer may insert an unacknowledged mutation between
those steps. The original authority and live verifier are checked
immediately after the final await and before metadata retirement. Polling and
read-only lease queries use the original read path rather than changing the
owner from Current to Dirty merely to observe it.

The managed path never falls back when the bound capability is missing. The
original checkpoint-attempt guard fences the whole pool if acknowledgement
fails, is Unknown, times out or is cancelled. An exact terminal readback may
still settle application metadata independently while a writer is fenced;
it does not reopen the writer. Unmanaged legacy fixtures retain their original
contract. HOS2 retirement and the separate pre-effect entered-state publication
must be qualified on their own paths.

[The retained acceptance records](acceptance/2026-10-23-notes-retirement/README.md)
include the original premature-retirement failure, the invalid stale-binary
run, the fresh 59-case owner run, 33 shared regressions and finish checks. These
component fixtures do not qualify the physical Root store or crash recovery.
