# prompt.registry operations and recovery

Applies to the committed strict-V4 semantic owner with V4/V5 payload storage. This is a developer
and operator runbook, not permission to deploy, release, switch owners, delete
backups, or emit external effects. The actual API contract is
[API_CONTRACT.md](API_CONTRACT.md); measurements are described in
[PERFORMANCE.md](PERFORMANCE.md).

## 1. Open and inspect

Use a private, same-user state directory and exactly one `DurablePromptRegistry`
writer. Never remove `registry.lock` to bypass a live owner. The selected image
consists of `registry.json` and the exact immutable payload slot it selects
(`registry.payloads` or V5 `registry.payloads.alternate`); `registry.next` is an unselected temporary metadata image. Missing or
modified committed data is corruption, not an invitation to start a new store.
Normal owner open can migrate legacy V1/V2/V3/transitional-V4 data and trim an
unselected payload tail after validating the complete semantic image.

`operational_metrics()` reports logical record capacity, active and inactive
payload records/bytes, physical file bytes including its header, metadata bytes,
remaining capacity and high-water basis points. It also reports lifecycle-event
count and revocation frontier. These diagnostics remain available after an
indeterminate commit when possible, but then `authoritative=false` and logical
values refer to the last acknowledged in-process predecessor, not necessarily
the disk-selected image. A filesystem diagnostic error must itself be surfaced.

`oldest_reclaimable_age_ms` is currently `None`: strict V4 does not persist the
moment a payload first becomes reclaimable. Do not coerce missing age to zero.
Persisting such timestamps requires an explicitly versioned schema and clock
policy. Final-use counters are owner-local/process-generation statistics;
restart resets them. They are not a durable count of all historical failures.

## 2. Incident decision table

| Observation | Immediate action | Safe continuation condition |
| --- | --- | --- |
| Invalid shape, digest, grant, scope or model binding | Reject the operation and retain redacted evidence | Corrected input with independently valid authority |
| Revoked, retired or non-admitted selection | Do not deliver or retry the same selection | A fresh eligible portfolio/compilation; never un-revoke the old factor |
| Expired or changed snapshot | Discard stale compilation, not audit history | Re-enumerate and compile against current owner/configuration |
| Logical or byte quota exceeded | Apply admission backpressure; inspect capacity classes | Sufficient authorized capacity; do not loop immediate retries |
| `StateLocked` | Locate the existing owner | Its deliberate stop and lock release, not lock-file deletion |
| Pre-publication I/O failure | Preserve predecessor, inspect space/permissions | Storage healthy, original outcome reconciled where grants were consumed |
| `IndeterminateDurability` / `ReopenRequired` | Stop authoritative reads, publication and delivery | Reopen, validate selected image, determine whether intended mutation committed |
| Corrupt selected metadata or extent | Quarantine, preserve diagnostic bytes | Independently verified restore under an external owner recovery decision |
| Checkpoint identity/tail mismatch | Reject candidate without repair | A new exact checkpoint matching the trusted current receipt |

An unresolved provider attempt is not `NotDispatched`. Preserve the existing
attempt/request/provider digest and reconcile the real terminal outcome before
retrying. Revoking a selection does not erase an already observed delivery.

## 3. Checkpoint and compaction protocol

Take the owner guard and call `export_consistent_checkpoint(destination)` for an
exact copy, or `checkpoint_compacted(destination)` to omit inactive realization
payloads. The destination must not be a live owner's directory. Atomic private
directory creation prevents two writers from independently treating it as a new
destination. Payloads are synchronized before metadata publication. The result
is reopened, semantically compared, synchronized with its parent directory and
returned with source/checkpoint identities and a retained-history digest pair.

The source registry, its lifecycle events, and its grant history are not changed
by either operation. A compacted checkpoint retains factor and realization
identities, bindings, relations, supersession and complete lifecycle events;
only payload bytes belonging to inactive realizations are omitted.

A completed identical retry verifies the existing checkpoint and returns the
same semantic receipt without allocating a registry revision. A different
existing image, empty directory, partial checkpoint, symlink, unselected tail
or unsafe permissions is rejected, never overwritten or automatically repaired.
After interrupted construction, retain the partial directory for investigation
and use a fresh destination name. Explicitly disposing of a partial destination
is an operator action after proving it has no selected/live consumer.

`reclaimed_payload_bytes` counts bytes omitted from the destination.
**`source_erased=false` always:** the original store and pre-existing backups
still contain their original bytes. Copy-compaction is not secure erasure and
is not a statement about physical storage remanence.

## 4. Verify a restore without mutating it

Obtain the expected checkpoint revision and digest from the trusted current
owner/checkpoint decision. Supply both values to:

```rust
DurablePromptRegistry::verify_restore_checkpoint(
    checkpoint_path,
    configured_record_limit,
    Some(receipt.checkpoint_revision),
    Some(receipt.checkpoint_registry_digest),
)?;
```

The verifier does not initialize missing directories or locks, migrate legacy
schemas, republish metadata, or truncate orphan tails. It validates existing
strict-V4 semantic bytes in a V4 or V5 storage envelope under the existing lock and rejects any identity mismatch.
It must not extract the expected digest from the very candidate it is deciding
to trust. A pre-revocation backup pinned against a current post-revocation
identity is rejected. A valid old receipt alone does not prove that an old
backup is current enough to activate.

Activation requires a separate quiescent owner protocol: freeze admissions,
resolve or explicitly quarantine in-flight attempts, capture the latest source
identity and revocation frontier, create/verify the checkpoint, recheck that the
source has not advanced, stop the old owner, atomically select the new owner
under the deployment's existing fencing mechanism, then rebuild all derived
context and require fresh current-use checks. No module API here automatically
switches a live owner, fences a remote host epoch, or grants provider authority.
Do not copy files over a live registry or reactivate a revoked predecessor as a
rollback shortcut.

## 5. Retention classes

| Class | Retention and use rule |
| --- | --- |
| Active payload | Keep exact digest-bound bytes while eligible and referenced |
| Retired/revoked or superseded payload | No new use; eligible for owner-local GC or copy-compaction when realization is inactive |
| Factor/binding/relation/supersession identity | Retain interpretation and provenance; not raw-payload use permission |
| Lifecycle/audit history | Retain under the current strict V4 contract; do not prune events to manufacture capacity |
| Original store after checkpoint creation | Still contains bytes; delete only after externally fenced handoff and approved retention decision |
| Existing backups | Not erased by compaction; track independently and enforce restore freshness |
| Partial checkpoint | Never activate; preserve until safe disposal is explicitly authorized |

Lifecycle-history pruning is not implemented by this change. Metadata can
therefore still reach its independent ceiling. Increasing a ceiling, discarding
history, or changing retention semantics is a separately reviewed policy/schema
change, not an automatic response to a capacity error. Secrets and raw payloads
must not be copied into normal CI logs, metrics or receipts.

## 6. Crash/recovery regression coverage

Named registry regressions exercise unrenamed metadata, orphan-tail recovery,
post-rename directory-sync poisoning, pre-rename storage-full failure, partial
checkpoint preservation, idempotent checkpoint retry, committed-extent
corruption, strict-restore non-mutation and stale-backup rejection after
revocation. Agentd regressions exercise preparation and dispatch rejection
before/after restart with the same stale lease and no inserted dispatch claim.
The actual extension tests exercise cached-owner withdrawal before provider
policy begin and reject silent replacement of an already injected payload.

These tests are not a complete power-loss/filesystem/device fault campaign.
Target-host fsync semantics, actual provider/network cancellation and every
streaming/final-output consumer require independent integration validation.
The final-use linearization boundary and non-claims are in API_CONTRACT.md.

## 7. Delivery discipline

Build checked-in source directly. Do not run an `apply-prompt-*` script to make
qualification compile; these historical patchers are removed from the delivery
candidate once their reviewed changes are conventional source commits.
Developer-only source authoring history is retained in Git/isolated operations
branches, not consumed by runtime or qualification.

Generate the implementation map deliberately with
`python3 scripts/hepta-prompt-registry-map.py --write` after committing source
and documentation, then commit the map. Qualification uses `--check` only.
Every required check writes an exit status, log digest, source/base/tested SHA,
tree and runner attempt. Failure, timeout, missing dependency and zero matched
tests are not success. Source archives and bootstrap edits are not test passes.

## 8. Owner-local raw payload GC (storage envelope V5)

`collect_payload_garbage(&mut self)` is a synchronous operation of the existing
exclusive owner. It does not introduce a second runtime, authority, or writer.
It removes only raw payloads of inactive realizations; factors, realization
bindings, relations, supersession, lifecycle events and terminal revocation are
retained. Each nonempty collection allocates one revision/lifecycle frontier,
invalidating old snapshot-bound uses. A no-change cleanup retry does not
allocate another revision. The host must hold the same registry guard used by
publication and final-use dispatch. Run collection outside a provider send
critical section, with admission backpressure while the owner is busy.

The first nonempty collection publishes a V5 outer storage envelope containing
unchanged strict V4 semantic metadata and a closed enum `payload_slot` (primary
or alternate). No on-disk string is interpreted as an arbitrary path. The two
fixed private payload slots alternate. The new slot is written and synced while
the selected predecessor remains intact. Only after metadata fsync, atomic
rename and directory fsync may the unselected predecessor be unlinked. A further
directory sync acknowledges namespace removal. At most two payload generations
are needed: budget up to two times the 32 MiB selected payload limit plus headers,
metadata and temporary metadata. Do not reduce reserved GC staging space to zero
when the selected live set is full.

| Failure point | Selected image / action |
| --- | --- |
| Before metadata rename | Predecessor remains authoritative; no predecessor unlink |
| After rename, before acknowledged directory sync | `IndeterminateDurability`; stop authoritative access, keep both slots, reopen and reconcile |
| Reopen after unknown publication | Validate the selected manifest and selected slot only; never fall back to a different slot to hide corruption |
| After durable publication, unlink or cleanup sync fails | Return a committed receipt with `cleanup_pending=true`; retry cleanup without replaying publication |
| Retry with no newly inactive payload | Stabilize selected metadata, unlink only the other safe slot; no extra revision |
| Unexpected symlink/hardlink/unsafe other slot | Leave it untouched and report cleanup pending; investigate permissions and ownership |

`collected_payload_bytes` is the raw content omitted from the selected new
image. `unlinked_file_bytes` is the predecessor file size removed from the
namespace, including retained bytes that were copied and its header. They are
not interchangeable measures. Neither means secure device erasure, removal of
already-cloned in-memory buffers, or erasure of separately retained backups.
Before using an exported checkpoint as a new live owner, follow the externally
fenced handoff in section 4. Old binaries reject V5; rollback must restore a
compatible binary without resurrecting an older revocation frontier.

Current I/O counters report publication attempts, successes, failures, capacity
failures and unknown outcomes, metadata bytes written, actual file/directory
sync calls and elapsed nanoseconds. They reset on owner reopen and include
initial/migration publication when it occurs. Partial failed writes are not
counted as fully written metadata. `payload_stage_nanos` includes the complete
payload-stage operation, not an invented count of individual disk writes.
Selected and unselected file sizes remain separately visible for cleanup
incidents. Missing or unsafe storage produces a diagnostic error, never zero
capacity usage.


The additional `gc_process_exit_after_unknown_commit_reconciles` test launches a
separate test process that exits without running owner destructors after the
post-rename fault. The parent opens the same directory, verifies retirement is
still effective and completes only unselected-slot cleanup. This is an actual
process-exit/restart test, not a claim to simulate a device losing persisted
sectors or a complete target-filesystem power-cut campaign.
