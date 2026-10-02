# Ledger persisted-format convergence: bounded migration proposal

Status: Stage A/B are implemented as pure codecs; Stage C/D remain proposed. No migration is activated. This is a separate stage from the
operator artifact JSON adapter. No historical tags, files, witnesses or branches
have been rewritten or merged.

## Verified collision

- Runtime integration source `6000e4068ce9c3c215346cd81686a37932fa53a1`,
  `hepta-learning-ledger/src/durable_codec.rs`, decodes `9 | 10` as the old
  RetrievalAssignmentFact layout, then interprets 10 as RetrievalPrepared.
- Operator source `c3228764172df19e37894053b54d3a8b5a1a6520`, retained in
  adapter source `86eb13b802ea9b269a30d0c941edc74b8d0e4312`, decodes 10 as
  RetrievalAssignmentIntentV2 and 11 as publication confirmation.
- Both retain event domain `hepta.learning-ledger.event.v1`, journal magic
  `HEPTLR01` and segment magic `HEPTLS02`. Neither enclosing header identifies
  which tag-10 grammar was used. Shape rejection is not a semantic discriminator.
- Ledger audit source `d4211b98f1026ae44d9c0469b0adba52bff98f13` independently
  identifies the same collision and separate post-expiry exact-retry limitation.

## Invariants

1. Never infer format from branch name, filenames, a matching decoder, payload
   length, a successful checksum or a process's current version.
2. Never rewrite old event bytes, renumber old tags, recalculate old event/chain
   identities, drop unknown rows, truncate complete rows or reset a witness.
3. A checksummed new discriminator identifies syntax, not authorization. Its
   binding must be covered by the independently authenticated owner configuration
   and minimum acknowledged-history witness.
4. Historical preparation is not publication intent, host-write confirmation,
   model consumption or an external effect. Preserve those different facts.
5. Migration requires an exclusively fenced, witnessed, immutable source cut.
   No automatic fallback from failed migration to a newly initialized store.

## New format

Reserve journal magic `HEPTLR02`, segmented-container magic `HEPTLS03`, and
an event domain `hepta.learning-ledger.event.v2`. Confirm these reservations
against the integration branch before implementation. These are additive formats;
legacy creation/recovery remains explicitly named and separately tested.

The new checksummed header contains format version, event-codec version, store
binding, owner generation/fence, genesis-or-migration discriminator, and an
optional immutable migration-manifest digest. Segment headers additionally bind
index, predecessor anchor and existing bounded segment limits. Unknown versions,
profiles, reserved bits and inconsistent header/event combinations reject.

The V2 event prefix explicitly identifies the registered event kind before its
bounded body. Allocate disjoint V2 kinds for retrieval preparation, assignment
intent and publication confirmation. This does not change the tag inside any
legacy byte stream. V2 event/chain digest construction includes the event domain
and kind. Each reader uses exactly the indicated codec, with no trial decoding.

## Legacy import, without rewriting

An external owner-authorized migration plan must bind:
- logical store/scope and source owner generation/fence;
- one exact legacy profile, `integration-preparation-v1` or
  `operator-publication-v1`, supported by independent deployment provenance;
- original file/segment ordered inventory, length and content digest;
- original ledger frontier and independently witnessed frontier;
- target owner generation/fence, target format and bounded destination;
- current authorization/trust identity and migration expiry.

Profile selection applies to the complete authenticated source inventory. It
cannot be supplied opportunistically per ambiguous row. A missing, conflicting or
unavailable provenance proof yields `LegacyProfileRequired`/`LegacyProfileMismatch`
and no writes. Mixed histories with no single authenticated profile are quarantined
for owner investigation. An all-common-tag history is not a reason to guess the
future writer's profile.

Preserve the original files byte-for-byte in an immutable source inventory. The
new store starts as a continuation referencing that inventory and its final
witnessed anchor. Historical reads use the selected legacy reader and retain
original event/authentication/chain digests and record IDs. New records use V2
bytes, continue sequence after the legacy cut and bind the predecessor anchor.
A migration record is metadata linking the two encodings, not a replacement
Decision/Outcome or a fabricated learning observation. Queries expose provenance
explicitly, so consumers cannot mistake a legacy preparation for confirmation.

Both legacy codecs must coexist as separate bounded modules before the unified
writer is enabled. A shared `LedgerEvent` enum with one ambiguous encoder cannot
serve as the migration substrate. Use a validated event representation carrying
its immutable original codec/profile and bytes, or an equivalent private typed
record that cannot be re-encoded under a different profile by callers.

## Transaction and recovery protocol

1. Acquire exclusive writer/fence ownership. Authenticate migration plan and the
   independent witness; inspect all source bytes read-only. Require an equal
   witnessed cut before switching. Preserve all existing capacity limits.
2. Write a create-only prepared migration descriptor binding the exact inventory,
   target identity and witness cut. Sync it and its containing directory.
3. Initialize the new target/header and migration link in a new directory. Sync
   target files and directory, then independently verify their exact bytes.
4. Revalidate current authority/fence and source identity immediately before the
   owner-controlled activation record. Commit the new active-store identity with
   an independently retained acknowledgement; do not change it based solely on a
   locally present target file.
5. Before activation, restart may resume the same prepared migration or abandon
   only an unacknowledged target. After activation, recovery must require the new
   witness/target and the unchanged retained legacy inventory. Missing new state
   fails closed; it never silently resumes the old writer.
6. Preserve the original store read-only. Reverting serving software does not
   authorize writing legacy events after V2 activation. Recovery is forward under
   a newer owner fence, not a witness reset or history rewrite.

The existing one-event-lag exact retry is a distinct dependency. If its original
attestation has expired and cannot be retried with the same authentication digest,
migration stops at the witnessed prefix. Do not re-sign the historical event and
pretend it is the same record. Any future current-authorized reconciliation API
must bind the exact immutable unwitnessed event and both frontiers, advance only
the independent acknowledgement, and preserve original bytes/authentication.
That API needs its own owner-authority design and adversarial review; it is not
implicitly authorized by the format migration.

## Reviewable implementation stages

A. Read-only inspection/profile types and frozen fixtures from both actual legacy
writers. Reject absent profile, unknown version and cross-profile substitution.
No writer/activation path changes.

B. New V2 event/container codec, independent canonical vectors and exact digest
semantics. Add distinct representations for all three retrieval facts; keep legacy
encoders unchanged. No default runtime selection.

C. Create-only migration descriptor/target preparation, external-witness binding,
exclusive fencing, and fault-injected crash recovery at every sync/activation cut.
No live-store migration without authenticated owner inputs.

D. Integrate the actual owner bootstrap and readers. Runtime worker retains the
Agentd V2 actor/typed bridge; integration occurs only after the ledger format
and semantic compatibility matrix pass independently.

## Required acceptance tests

- Real source-generated `HEPTLR01` and `HEPTLS02` fixtures for both historical
  profiles, including common records, preparation, intent and confirmation.
- No-profile and wrong-profile rejection without file or witness mutation,
  including a fixture intentionally valid under both parsers if one can be built.
- Unknown new versions/kinds, mixed-profile inventory, changed source bytes,
  reordered/missing segment, altered discriminator and independently pinned
  witness mismatch all fail closed.
- Exact original byte/digest/sequence preservation, and distinct observable
  semantics for preparation versus intent versus confirmation.
- Full create/sync/descriptor/activation crash matrix, duplicate request,
  concurrent writer, fence rollover, directory-loss and target-rollback cases.
- Current authority expiry/revocation between preparation and activation; no
  activation after deadline. Post-expiry legacy one-event-lag remains blocked.
- Reopen both before and after activation, old-software refusal of new magic,
  no silent downgrade, maximum bounded inventories, and target-host durability.

Structural codec tests are not deployment evidence. Production rollout still
requires independently authenticated legacy provenance, a witnessed equal cut,
physical rollback-domain separation and operator recovery acceptance.
