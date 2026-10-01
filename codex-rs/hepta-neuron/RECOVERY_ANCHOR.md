# Acknowledged-history recovery anchor

This bounded NEU-2 hardening extends `SparseJournal` and its owner integration.
The on-disk HPTNSJ01 format and the existing successful-commit byte vectors are
unchanged. Successor segments use the separately versioned HPTNSJ02 header.

## Failure being closed

Checksums verify the bytes still present. They cannot prove that a complete,
previously acknowledged suffix has not disappeared. An internally valid prefix
or an empty replacement can therefore pass unanchored recovery. This is an
information boundary, not a checksum algorithm defect.

`SparseJournal::open_anchored` requires a `JournalAnchor` with a positive sequence
and its checkpoint digest. The host must retain this witness separately from the
journal, bind it to the same scope and generation, authenticate it, and enforce
its freshness and revocation. Reading the anchor back from the suspect journal
or accepting an arbitrary model-supplied digest supplies no rollback protection.

## Algorithm and transaction ordering

The existing open path and the anchored path share one parser and replay engine.
For a root segment, an anchor is valid only for sequence 1 through the declared
segment quota and a nonzero checkpoint digest. For a successor, its global
sequence must lie between the seed sequence and seed plus the segment quota;
an anchor at the seed must match the exact seed digest. Before any file
initialization or repair, anchored
recovery requires the acknowledged sequence to be present. It then validates
all complete frames and reconstructs their checkpoint/receipt chain. The exact
checkpoint at the anchor sequence must match the external witness.

Only after that comparison may a later incomplete frame be truncated and synced.
A valid later complete frame is preserved and synced before exposure, allowing
reconciliation of a write whose acknowledgement was lost. An earlier anchor is
a minimum retained-history requirement, not an instruction to roll back later
valid commits. Corruption after the anchor still rejects the entire open.

`InvalidAnchor`, `AcknowledgedHistoryMissing`, and `AnchorMismatch` are separate
errors. These errors do not initialize, truncate, rewrite, or silently choose a
new predecessor. The handle closes normally on rejection. Normal clock, scope,
configuration, replay, quota, and cooperating-writer fencing checks remain intact.

For a chain whose witness lies beyond the segment being recovered, that segment
was already sealed and acknowledged. The owner uses a locked complete-segment
recovery policy: its length must exactly equal its header plus its full frame
quota before initialization or tail repair can occur. An empty root, a torn last
acknowledged frame, or an extra partial tail rejects while preserving the bytes.
The successor header still verifies the exact predecessor checkpoint, and state
publication remains blocked until the chain reaches the independent witness.

## Recovery before the first acknowledgement

Successful bootstrap enrolls a root header before it acknowledges any tick. A
restart at that point must not repeat bootstrap or invent an external anchor.
`NeuronRuntime::recover_unacknowledged` accepts the existing nonempty root only
when the authenticated, independently enrolled witness has no acknowledged
frontier. It verifies the complete runtime configuration, scope and generation
before root parsing or repair. A header-only root retains no checkpoint or
anchor; a partial first frame is discarded and synced; a complete first frame is replayed,
synced and independently acknowledged through `compare_and_swap(None, anchor)`.
Recovery invokes no model and does not repeat the committed tick.
Multiple complete ticks or any bytes of a second frame with an empty witness
are rejected before repair: a canonical owner cannot advance past its first
tick before that first acknowledgement succeeds.

This entry point rejects empty/missing files, successor segments and a witness
that already contains acknowledgement history. An existing witness must never
be replaced with an empty witness to qualify for this path. Once any anchor is
acknowledged, use anchored root or chain recovery. Bootstrap and fresh rollover
also verify emptiness under the acquired journal lock, so their initial metadata
checks cannot accidentally become recovery of a concurrently populated file.

## Host integration boundary

The legacy `open` method remains available for bootstrap and explicitly
unanchored qualification use. It is not an anti-rollback API. A host that has
acknowledged history must call the anchored method and must never retry a failed
anchored open through the unanchored method. The closure line now provides `FileAnchorWitnessStore` as a separate locked and synced witness store and `NeuronRuntime` orders journal commit before witness compare-and-swap. The store itself does not authenticate selected-artifact/current-owner truth or grant freshness/revocation authority; those facts still belong to the composing host.

The host transaction order is: durably commit the journal, durably retain its
acknowledgement witness, then acknowledge externally. If witness publication is
uncertain, reconcile the already committed tick before retrying. An anchor cannot
protect acknowledgements that the host failed to retain. The file-backed witness
fences cooperating writers and records consecutive compare-and-swap updates;
bounded segment rotation and deletion-generation rebuild have native owner
surfaces. Their target-host qualification, backup erasure, physical power loss
and target latency remain separate evidence work.

## File-backed witness recovery

`FileAnchorWitnessStore` requires a fresh read/write handle in an independent
rollback domain. The legacy low-level `open` API uses HPTNWA01: its 112-byte
header binds scope, objective and generation. Canonical `NeuronRuntime` owners
require `open_bound` and HPTNWA02: the 144-byte header additionally binds the
complete runtime configuration semantic digest before its checksum. Both
versions use the same 112-byte records binding the previous and next anchor plus
a checksum. The quota is 1..4096 records. Recovery checks the full-width file
record count against that quota before converting it to the platform's index
width, validates every record and syncs complete recovered history.

The native journal config identifies the Q24 mechanism but does not cover every
owner setting, such as the encoder/head/runtime binding, calibration or resource
envelope. The canonical owner compares its complete configuration digest with
the independently retained witness binding before initializing or recovering a
journal. It also calls `verify_context` against the witness's enrolled scope,
objective and generation; the correct configuration digest cannot authorize a
witness enrolled for another context. Recovery cannot therefore attach changed
owner semantics to an already acknowledged native checkpoint. Legacy HPTNWA01 witnesses return
`UnboundRuntimeConfig` to canonical owners, and `open_bound` does not upgrade or
rewrite them. A trusted host must authenticate any migration from prior owner
evidence or start an explicitly fresh generation; supplying a configuration at
recovery time alone cannot authenticate the old configuration.

The owner calls `check_capacity` before executing a new model tick or appending
its journal frame. The file-backed store rejects a known full or poisoned
witness there, so a known quota exhaustion cannot strand another journal tick.
This precheck is not a reservation or durability guarantee; the subsequent
compare-and-swap still decides whether publication succeeds. Custom stores may
have unknown capacity, and publication failures still require reconciliation.
The witness retains at most 4096 acknowledgements over its lifetime; journal
rollover does not reset or extend that budget. Authenticated witness rotation or
compaction requires a separately specified migration, never an empty-file reset.

An empty file enrolls a new witness. The host must distinguish enrollment from
recovery and must never replace a missing, damaged or rejected existing witness
with an empty file. Directory synchronization and authentication of the owner,
scope, generation and current witness identity remain host obligations.

Unlike an incomplete journal suffix protected by an external anchor, an
incomplete witness record is rejected without truncation. The witness is the
minimum retained history, so it has no independent lower bound here from which
to prove repair safe. Preserve damaged bytes and use authenticated recovery of
the independent witness store; do not fabricate its frontier from the journal.
Uncertain writes poison the live store. Dropping it releases its acquired lock,
including constructor/recovery failures; reopen reconciles a complete valid
record, while corruption remains fail-closed.

## Regression coverage

Nine new tests cover exact anchored replay, loss of a whole acknowledged frame,
empty replacement, every partial acknowledged-frame boundary, anchor mismatch
before tail repair, preservation of later complete frames, rehashed alternate
history, malformed anchors, and corruption after a matching anchor. Missing or
mismatched history is checked to leave the file bytes untouched. Existing tests
and golden digests are retained. Test source is not proof of execution; exact
candidate compilation, tests, strict lint and both source/merge checks are required.
