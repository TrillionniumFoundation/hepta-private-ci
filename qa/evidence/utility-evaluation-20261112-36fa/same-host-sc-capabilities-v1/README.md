# Same-host original S/C capabilities — production preparation v1

This is an isolated source proposal, not an activated source tree or a qualification result. All 14 complete afterimages and the full before/after packet were created as immutable Git blobs and read back in full. Workspace execution was unavailable; no shell, Rust formatter, compiler, tests, native host, or source/reference mutation was used.

## Why this work is necessary

The unchanged original owner channel rejects a peer with the caller's UID or PID. The proposed public process graph therefore uses three non-root identities: 60001 for A/Material/Version/S/C, 60002 for Trainer/Model, and 60003 for independent B/retention/E. This layout still cannot use a fake socket to make colocated Version/S/C appear remote. The same-host paths here consume capabilities exported by the original concrete owners. They do not relax the peer guard.

The independently authored Version local read backend remains a required dependency. Its agreed interface returns the existing purpose-fixed read client with a private local backend, so the old remote source structs and old by-value parameter types remain intact. Its S read holds one Version permit, and its C read plus readiness share one other Version permit, counter, deadline and read state. With the existing Root Version and FinalUse connections, this is the original four Version permits, not a fifth connection.

## S capability and lifecycle

OriginalCircuitSelectionCommandOwnerV1::open_original_evaluated_local_readback exports OriginalCircuitSelectionLocalReadbackV1 only from the evaluated/shared profile with the actual local Version Selection purpose. It first reads that same original S journal and its actual predecessors, then performs the existing complete wire authentication and opaque conversion. Missing, pending, invalid, withdrawn, expired or legacy S cannot satisfy this export.

The private capability retains one Arc to that same command owner through an internal trait implemented only for the concrete original command owner. No caller can supply an implementation or callback. The public capability exposes Clone and read_original_selection; it has no owner, key, file descriptor, Execute, reconnect, or raw-receipt constructor.

All clones share one original S permit, one slot, one 128-request counter, one maximum 500 ms exchange bound, and one absolute monotonic end. The end is bounded by the Version's original end and the original 300 second maximum. Neither cloning nor a read restarts the lifetime. A slot is taken before dispatch and restored only after successful full authentication, full opaque equality and deadline checks. A loser in a concurrent read receives Unavailable. Cancellation, timeout or failed authentication leaves the slot absent.

Already-dispatched blocking owner I/O may continue after a caller drops its await or receives a timeout. That caller's delivery remains unknown. The permit remains owned by the actual blocking operation until its terminal, and an alias cannot launch replacement I/O because its shared slot is absent. This is not an operation-abort or remote-effect-rollback promise.

The pre-existing direct local S delivery now delegates to one private helper. Its exact authentication → same owner Readback → wire authentication → opaque conversion → authentication body is moved intact; the sole receiver adaptation is Arc<Self>::as_ref() to the already borrowed &Self. That direct method keeps its previous per-call permit behavior. The sealed capability already holds its permit, so it calls the same helper without acquiring a second permit per read.

## C consumes the same capabilities

The new into_evaluated_local_shared_command_owner entry point consumes the original Observer receipt owner, the original local Version NextUse client, the already-sealed shared T/E bundle and the original S local capability.

The factory and each source preparation validate the full opaque S cut and context. They also require pointer identity of both actual T/E clients between the S capability and the C shared bundle. Equal signed summaries from different client instances do not satisfy this particular same-slot sharing contract.

The original private NextUseSources selector dispatch gains a concrete local variant. Existing remote structs still carry the existing evidence client type; their private trait implementation wraps that same reference. The original C owner core still controls prepare, claim, journal read/write, completion fencing, original signatures and final current checks. Its predecessor order remains actual T/E first, then actual S, then the final actual C/Source observation in the evaluated-owner branch. No cached S signature substitutes for a read.

The old remote and by-value factories keep their input types and validation bodies. Their internal selector storage is wrapped in a private enum. A local value cannot satisfy an old remote branch; a remote value cannot satisfy the explicit new local branch.

## Exact composition

The packet is based on exact cc57 sources plus the already-frozen shared T/E, UFCS and local-S increments. Eleven existing files change; three production files are added. Every before and after has its complete bytes, SHA-256 and Git blob identity.

LIB_INTEGRATION.json gives the one independent Linux-guarded S export to merge with evaluation_audit's Version local capability export. Root remains the sole combined-source writer; neither independently prepared lib.rs afterimage may overwrite the other's export.

No test source is included in this production packet. The next isolated test increment must exercise completed and recovered S, missing/uncompleted export, wrong full S/context, different client-instance rejection, aliases and cancellation, original permit saturation, deadline expiry, and actual C/current withdrawal behavior. Actual aggregate budgets and public process execution remain unmeasured.

## Remaining work and evidence boundary

The Version local backend, combined registration/protection, normal and negative mechanism tests, actual formatter/compiler and full original source/native gates remain required. The full fresh three-UID/Root fixture is still being completed. The existing strict ParentMaterialControl codec only replays already-held typed originals; it does not establish first admission from child summaries, create a trusted verifier, sign A on Root's behalf, or reopen the active LedgerWriter.

No real independent B, real successful C, model utility, end-to-end task success or new qualification PASS is asserted by this proposal.
