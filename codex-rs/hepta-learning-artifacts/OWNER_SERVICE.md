# Artifact owner service operating contract

This guide describes the source service in `src/owner_service.rs`, the fenced
filesystem host in `src/owner_host.rs`, and their independently verified read and
selection boundaries. The canonical module/contract registries and
[`TECHNICAL.md`](../../docs/modules/learning.artifacts/TECHNICAL.md) remain
authoritative for ownership and completion claims.

`LearningArtifactOwnerService` is a library service composed over
`LearningArtifactOwnerHost`. `CALLERS.toml` closes the service-to-host caller
set. It does not prove that an executable constructs or operates that service.
The repository currently provides an explicit Agentd ranker attachment API and
qualification consumers; normal Agentd startup does not provision Owner
signed-head trust, construct the writer service, install a current-registry provider, or
attach a selected learned ranker. Production execution, independent acceptance,
canary, promotion and release therefore remain open.

## 1. Ownership and dependencies

The artifact service owns one in-process compatibility registry, immutable full
admission sidecars, one installed withdrawal frontier, and a serialized
publication protocol under an exclusive
OS file lock. Sensor cores share that physical artifact registry. The host
verifies externally signed writer leases and CURRENT heads; it has no signing
private key. The independent selector verifier admits exact load eligibility
and returns `AuthorityPosture::DENY_ALL`.

The deployment supplies the protected root, authenticated public-key trust,
signed lease/head/selection values, trustworthy time, independently retained
restart anchors, and authenticated withdrawal snapshots. Dataset producers own
source membership. Evaluation and operator acceptance are owned independently;
this service does not infer them from stored bytes or model scores.

The writer fence coordinates processes that use this namespace and lock. It
does not defend against hostile filesystem writers, a copied namespace, or a
second host writing another root. Those deployments need independently enforced
namespace and authority ownership.

## 2. Configuration and request bindings

`LearningArtifactOwnerServiceConfigV1` is supplied by an embedding host. There is
no environment or CLI default that manufactures this configuration.

| Field | Required meaning |
|---|---|
| `root` | Host-authorized filesystem namespace; trusted ancestors must remain protected throughout use. |
| `trust` | `ArtifactOwnerTrustV1` binding registry identity, withdrawal scope, genesis predecessor, generation/epoch floors and enrolled public keys. |
| `writer_lease` | Signed producer lease for that registry and scope; every new host mutation rechecks its signer context, authority epoch and time validity. |
| `required_current_head` | Independently retained signed restart floor; `Some(anchor)` is required when the local namespace has a published CURRENT head. |
| `withdrawal_registry` | Authenticated, scoped current withdrawal history; its scope digest must equal the owner trust scope. |
| `storage_binding` | Nonzero storage identity used by exact registry and head receipts; publication signatures must bind the same value. |
| `now` | Host time used for credential/admission checks; it is not taken from the candidate's prose or payload. |

The trust snapshot admits at most 32 writer signers and 32 head signers. Each
`TrustedArtifactSignerV1` binds its public key to signer identity, epoch range,
validity interval and optional revocation time. A signed writer lease additionally
binds lease ID/generation, producer, registry/scope and signing-key digest.
Changing an enrolled key or authority floor is a new externally provisioned
trust/configuration generation, not an artifact-driven override.

`LearningArtifactPublishRequestV1` binds operation ID, complete scoped V3
admission, exact payload bytes, signed next CURRENT head, exact predecessor
registry head and current time. The external head signer must sign the intended
registry result; the service cannot issue that signature itself. Operation IDs
are retry identities, so retain the complete original request until reconciliation
and apply byte/admission/head identity checks before accepting a terminal retry.

Writer/head keys authenticate storage authority. Selector trust is a separate
domain: `ArtifactSelectionVerifierV1` binds it to the owner trust snapshot and
rejects selector keys colliding with writer/head keys, and selector identity
colliding with the candidate producer. A different display name is insufficient
to create an independent authority.

## 3. Cold bootstrap and anchored restart

For an authorized first publication, supply the externally provisioned trust,
lease, scoped withdrawal frontier and storage binding. The unanchored
`LearningArtifactOwnerHost::open` path cannot establish that a local directory
is the newest copy of an existing namespace. Reserve unanchored startup for
initial/qualification use; do not use it as a production backup-restore policy.
The owner service rejects `required_current_head: None` when it discovers a
published local CURRENT head. A partial first publication before CURRENT exists
can resume unanchored, under the checkpoint recovery fence. Complete erasure or
restoration of a pre-CURRENT namespace is not locally distinguishable from first
bootstrap; the deployment must independently prevent treating that event as a
new namespace.

After a head has been published, retain its signed value outside the artifact
namespace and restart with `required_current_head: Some(anchor)`. The service
uses `open_with_required_current_head`, authenticates the anchor and requires
the local head chain to contain and extend it. A self-consistent older backup
that lacks the anchor is rejected. Losing the external floor requires an
independent recovery decision; choosing an older local head is not recovery.

CURRENT discovery validates a single signed predecessor chain from the trusted
genesis, strictly increasing generations, non-regressing authority epochs and
issue times, and each enrolled key's original signature/epoch/time context. Global trust
generation/epoch floors apply to the newest CURRENT, not every historical link
or retained restart anchor. Publish a valid replacement CURRENT before raising
those floors; an old latest head still fails the advanced floor. Valid
historical heads may remain replayable after signer rotation/revocation, while
the newest head requires a currently admissible signer and unexpired witness.
CURRENT is a verified chain over immutable `.head` records, not a mutable file
whose basename establishes freshness.

A valid terminal CURRENT at generation `u64::MAX` remains discoverable and readable
and can be acknowledged/reopened normally. A new operation requires a checked
next CURRENT generation; overflow rejects before admission-sidecar or Prepared
publication and does not make the existing signed head unreadable.

`open` then recovers the exact registry supporting CURRENT and inspects durable
publication checkpoints. One non-terminal operation becomes a recovery fence;
unrelated publication is rejected until that operation is reconciled. Multiple
non-terminal operations produce `RecoveryConflict`. An absent CURRENT view
does not authorize a read consumer to invent one from local snapshots.

Upgrading an older owner namespace is not a transparent reopen when its
checkpoints lack complete admission sidecars. Before restarting the service,
independently recover the full original V2/V3 admission and authenticate its
manifest/admission commitments, then perform a separately trusted backfill or
reprovisioning operation with the protected writer namespace and exact restart
floor. If that full source record is unavailable, fail closed. A V1 compatibility
manifest, its support digest or a checkpoint's hashes cannot reconstruct missing
V2 datasets, lineage or predecessor semantics. Do not synthesize a sidecar from
the V1 projection merely to pass recovery.

## 4. Files, formats and publication order

The host creates these bounded domains beneath the trusted root:

| Directory | Immutable content and naming |
|---|---|
| `writer/` | `owner.lock`, the process-held writer fence; not a signing authority. |
| `payloads/` | `<artifact-id>-<payload-digest>.bin`, exact immutable candidate bytes. |
| `registries/` | `<head-digest>-<file-digest>.snapshot`, canonical V1 compatibility history. |
| `witnesses/` | `<generation>-<witness-digest>.witness`, canonical head-witness bytes. |
| `heads/` | `<generation>-<signing-bytes-digest>.head`, externally signed CURRENT records. |
| `transactions/` | `<operation-id-digest>-<phase-code>.checkpoint`, immutable phase checkpoints. |
| `admissions/` | `<admission-digest>.bin`, complete canonical V3 admission, with `<manifest-digest>.manifest` as its immutable parent-provenance index. |

V1 registry/witness formats remain `HEPTAR01` and `HEPTAH01`, described in
[`STORAGE.md`](STORAGE.md). Host records use
`HEPTA-ARTIFACT-CURRENT-HEAD-V1` and
`HEPTA-ARTIFACT-CHECKPOINT-V1`. Canonical readers reject alternate integer
spellings, malformed shape and byte/digest drift. Signing uses domain-separated
binary `signing_bytes()` encodings; never sign a pretty-printed representation
or silently redefine a V1 encoding.

Full admission sidecars use the canonical binary `HEPTAA03` encoding, capped at
128 KiB. `write_artifact_admission_beneath` validates before creating a target;
`read_artifact_admission` verifies an independently retained
`ArtifactAdmissionReceiptV3` binding manifest/admission digests, withdrawal
scope/head, file digest and byte count. The digest-pinned readers instead use an
independent checkpoint admission commitment or a registered parent's V1 support
commitment. Recovery validates historical admission at its original admitted
time, so later expiry does not destroy recoverability; new publication and use
separately validate current expiry and withdrawal state.

A CURRENT record binds withdrawal scope, storage binding and the witness's
registry/generation/head/predecessor, authority epoch, signer/key digest and
validity interval, plus the Ed25519 signature. A checkpoint binds operation and
phase, intent/admission/withdrawal digests, expected predecessor, transaction
state, original writer lease digest, optional exact registry/witness receipts and
acknowledgement time. Checkpoints retain commitments and receipts; the complete
V2 manifest and V3 admission reside in the durable admission sidecar, published
atomically before Prepared. Recovery verifies that file against the checkpoint's
admission commitment. The manifest index supports exact inherited-provenance
checks; a registered parent with a missing legacy sidecar cannot be silently
adopted as complete V2 provenance. The embedding retains the original complete
request for payload and signed-head reconciliation. The full
`ArtifactPublicationTransactionSnapshotV1` is also available for an embedding's
separately retained transaction store.

The ordered phases are `Prepared -> PayloadDurable -> RegistryDurable ->
WitnessDurable -> Acknowledged` (phase codes 0 through 4). A durable checkpoint
must follow the corresponding successful immutable file publication. The
complete scoped admission is checked against the installed withdrawal frontier
at registry, witness and acknowledgement boundaries. Validate the exact witness
and transaction before publishing a CURRENT side effect; rejected input cannot
make a candidate visible by advancing CURRENT.

File synchronization and parent-directory synchronization are distinct. On Unix
the owner-host publication path synchronizes its files and containing directories
before phase checkpoints. Other targets retain the deployment's qualified
directory-durability obligation; the source does not supply an equivalent
non-Unix directory primitive. The lower-level storage APIs still require their caller to perform
the relevant directory synchronization. This source ordering is not target-host
power-loss qualification or a multi-file atomic transaction. Root/ancestor
protection, filesystem-specific durability and external head distribution remain
deployment obligations.

Owner-host payload, registry, witness, admission, signed-head and checkpoint
publication uses a new temporary record, file synchronization, a no-replace
hard link to the final name, and containing-directory synchronization on Unix.
Incomplete temporary records do not reserve final names; ignored pending records
never establish CURRENT or a durable phase. An existing final record is accepted
only after exact expected-byte verification and synchronization. Phase semantics
are validated before final-name publication, and the in-memory transaction
advances after its corresponding complete file becomes durable. This owner path
is stronger than the retained low-level final-path capability writer, whose
indeterminate failures still require orphan reconciliation.

## 5. Reconciliation and failures

`publish` validates or recreates the exact operation's checkpoint sequence,
rebuilds its transaction from the verified durable admission and predecessor registry,
and continues from the last proven phase. Existing immutable files can satisfy
retry only after exact expected-content verification. Preserve the operation's
original lease commitment during recovery; a new valid lease authorizes present
work but does not rewrite historical phase identity.

These bindings are enforced by the public Owner host as well as its service.
Before payload, registry, witness or acknowledgement effects, and before
`resume_publication`, the host verifies a live writer lease for the transaction's
producer/scope and reconstructs its latest durable operation checkpoint. The
supplied transaction snapshot must equal that complete checkpoint using its
original lease commitment. Missing Prepared state, an older phase, semantic or
receipt drift, or a producer change rejects before filesystem effects. Pure
transaction constructors and snapshots cannot substitute for this host-owned
durable admission; a legitimate same-producer lease rotation preserves the
original phase identity.

For a new operation, `begin_publication` requires its predecessor to be the
discovered signed CURRENT head, or the trusted genesis when no CURRENT exists,
before persisting admissions/Prepared. An existing exact operation retains its
original predecessor during recovery after an uncertain CURRENT publication;
changing its intent rejects. Each phase publishes its checkpoint before
advancing the supplied in-memory transaction. If checkpoint I/O is
indeterminate, recover the proven durable phase rather than treating local
phase advancement as evidence.

Recovery verifies every checkpoint's canonical bytes, phase shape, complete
transaction intent/state digests, nonzero receipt commitments and common storage
binding. A later phase must retain the exact registry/witness receipts introduced
by an earlier phase. Terminal acknowledgement is checked at its historical time,
so subsequent source withdrawal blocks current use without destroying a valid
historical acknowledgement. CURRENT reads and registry-by-head recovery validate
the same complete checkpoint inventory; an acknowledged label cannot bypass
semantic replay. Corrupt terminal retries close the service's recovery gate.

Checkpoint hashes alone do not authenticate an operation name. Owner
registration uses the canonical event ID
`artifact-publication:<intent_digest>`, committing the operation, full admission
and predecessor into the signed registry chain. Registry publication and
recovery require that exact event/projection; coherent checkpoint renaming and
recomputed local hashes cannot rebind an acknowledged operation. Current-view
inventory verifies historical operation associations against the actual signed
CURRENT prefix, while allowing at most one unfinished RegistryDurable operation
outside that prefix. Public single-operation recovery verifies its exact
snapshot. Current-view acquisition does not replay every historical snapshot.

The pending RegistryDurable operation must extend the actual CURRENT (or trusted
genesis). A stale/forked pending snapshot cannot become another recovery root.

Historical receipt fields are checked for canonical shape, nonzero commitments,
bounded record counts and unchanged phase progression; operation associations bind their
head/sequence to the CURRENT records' exact intent, V1 projection and predecessor.
Each current read verifies the actual current snapshot's complete file receipt,
and requested single-operation recovery verifies that operation's snapshot.
Every historical snapshot's file digest/byte count is not reauthenticated on
every current read; the signed prefix association avoids quadratic historical
snapshot I/O without claiming that additional verification.

If a failed publication recovers an already durable Acknowledged checkpoint,
the service reloads the authenticated live CURRENT registry before clearing its
recovery fence. An indeterminate acknowledgement can precede the in-memory
cache update; terminal checkpoint recovery alone cannot make that stale cache
the baseline for unrelated work. Exact successful historical terminal retries
retain their original receipt semantics.

Before returning an exact terminal retry receipt, the host rereads the exact
Acknowledged checkpoint, synchronizes its existing file, and synchronizes its
parent directory on Unix. A visible no-replace link after a failed directory
sync therefore cannot bypass the original acknowledgement durability boundary.
This reconciliation changes no historical metadata or lease commitment and
preserves valid exact retries after the original admission/head expires.

| Observation | Required behavior |
|---|---|
| Invalid scope, signature, manifest, predecessor or withdrawal frontier | Reject; do not publish a new CURRENT head. |
| Payload or snapshot durable, later phase absent | Reconcile the same operation; do not infer acknowledgement. |
| CURRENT visible but witness phase checkpoint absent | Reopen against authenticated CURRENT, verify the operation's exact files and resume; block unrelated publication. |
| Gap, shape drift, conflicting receipt or changed retry request | Fail closed; no automatic overwrite or force-repair. |
| Writer lock busy | Another owner holds the cooperative fence; return the explicit fence error. |
| Write/sync failure | Treat the result as indeterminate and inspect exact durable state before retry. |
| Acknowledged operation retried exactly | Return its stable original terminal receipt; no new artifact authority. |

The service exposes `registry`, `withdrawal_registry`, `recovery_required` and
`current_registry_view` for inspection. `ArtifactPublicationTransactionV1::status`
is a read-only DENY_ALL projection. No public force-select, overwrite, promote or
release recovery path exists. Orphan deletion, retention and physical cleanup
need a separately authorized host operation with exact identity/reachability
checks.

## 6. Withdrawal, revocation and non-resurrection

`install_withdrawal_frontier` accepts only a same-scope monotonic history prefix
extension. Its typed input is not signature authentication: the embedding
authenticates the notice/actor and recovers its independently witnessed durable
withdrawal snapshot first. Installing it changes in-process state; the embedding
must durably preserve and re-provide the current frontier on restart. A stale
restore of that input cannot be repaired by the artifact registry's own hashes.

V3 admission rejects withdrawn source datasets. Snapshot-local
`prepare_dataset_revocation` separately stages existing direct artifact
revocations; ancestry eligibility blocks descendants in the V1 registry. The
dataset owner must supply complete source membership and derived-artifact
lineage, including multiple datasets and predecessors carried by V2 admission.
V1 compatibility fields cannot establish that complete mapping. The owner checks
parent provenance through its independently committed full manifest sidecar and
requires inherited source-dataset closure in the new candidate. Current owner
publication rejects a V2 manifest with more than one predecessor using
`UnsupportedMultiPredecessorLineage` before a Prepared checkpoint, because the V1
registry/read path cannot enforce multi-parent final-use ancestry. Full V2
validation/admission can still represent multiple predecessors; enabling their
publication needs a versioned registry/reader that enforces every ancestor.

`LearningArtifactOwnerService::current_registry_view` additionally checks every
currently eligible V2 artifact's full admission, manifest expiry, parent
provenance and source datasets against the service's current withdrawal frontier.
It places expired/withdrawn artifacts and their single-parent descendants in an
internal read-eligibility overlay while preserving the signed V1 history. A
valid unrelated artifact stays readable. Missing/corrupt admission or provenance
still closes view acquisition. Selector verification and cached use honor the
overlay through `view.is_eligible`; it does not mint a durable revocation or
rewrite CURRENT. Durable quarantine/revocation remains a separately authorized
publication. The low-level owner/verifier view only proves signed V1
compatibility-registry currentness and is not this complete V2 use check.

Existing active/cached reads need a provider performing these full service-level
checks, together with current-view revalidation before use. Withdrawal does not
erase every previously published external copy. Cache invalidation, rebuild/unlearning, backups,
external model stores and physical media erasure require independent evidence;
logical revocation is not a physical deletion receipt. See
[`DATASET_REVOCATION.md`](DATASET_REVOCATION.md) and
[`PINNED_LOAD.md`](PINNED_LOAD.md).

## 7. Independent selection and the Agentd route

`LearningArtifactOwnerService::current_registry_view(now)` returns opaque `VerifiedCurrentRegistryViewV1`
only after signed CURRENT and exact snapshot verification. A read-only proxy can
use `ArtifactOwnerVerifierV1::verify_current_registry_view` against independently
obtained current evidence, but must additionally enforce the service's full V2
admission/withdrawal/expiry/provenance boundary before product use. A bare
`File + RegistrySnapshotReceipt` is not this
interface, and one previously verified view is not a future freshness guarantee.

Open each reader `File` independently, with no preexisting lock or concurrent
alias use. A cloned/inherited descriptor can share the same Linux open file
description and lock state; it is not an independent reader capability. On a
current-view acquisition error, the embedding must discard its cached candidate
before returning or falling back; it must not reuse a prior opaque view. A failed
`RevalidatingCandidate::with_current` refresh also closes that candidate.
Agentd's ranker removes its cache before obtaining a current view and restores
it only after successful validation/consumption. Explicit re-admission is
required after either failure.

`ArtifactSelectionVerifierV1::verify` checks the independently signed selection
against that exact view and candidate manifest. `record_verified_selection`
records only `OperatorAccepted -> Selected`; `load_selected_candidate` returns
a read consumer whose uses remain guarded by current-view revalidation. Neither
operation trains, selects on its own behalf, or changes an active process route.

Agentd exposes `PinnedCognitiveRanker::load_evaluated` and rollback loading using
independent evaluation/selection tokens, followed by `AgentdConfig::with_cognitive_ranker`.
Its `CurrentCognitiveRegistry` trait requires authenticated views. The ranker can
only reorder already admitted records for its exact Agentd owner/body generation;
failed currentness closes it, and model replacement requires a new explicit host
configuration. These library seams and qualification tests exist. The repository
does not yet supply a normal executable bootstrap connecting the owner service,
current-view provider, independent selected ranker and route policy. All such
composition must preserve the separate evaluator/selector/producer authorities.

The V1 support digest of an owner-published candidate commits the complete V2
manifest; it is not its training dataset digest. The ranker uses
`VerifiedCurrentRegistryViewV1::supports_dataset` to bind its evaluation/model
dataset to the exact eligible manifest's retained full source membership. An
explicitly empty dataset set remains empty. Raw V1 views support only the legacy
direct support-digest profile and cannot establish the owner's complete V2
binding. Owner-published rankers therefore require full service views.

Selected cached consumers inherit the selection's owner-trust digest and full
provenance requirement. Other explicitly host-pinned consumers bind the first
accepted view. Once complete provenance is accepted, a same-trust raw V1 view
cannot downgrade that consumer. Trust substitution or provenance downgrade
permanently closes it; trusted configuration rotation requires a new explicit
admission. These checks preserve provider obligations to acquire the latest
authenticated view and installed withdrawal frontier for every use.

### Existing plasticity snapshot consumer

Agentd's explicit `--plasticity-bootstrap-descriptor` composes a plasticity
runtime using a receipt-pinned V1 `ArtifactRegistry`. Its parameter/topology
baseline checks, UpdateRule/MutationPolicy resolver and modulator-broadcast
resolver inspect that retained registry's eligibility. They do not obtain the
Owner service's full current view, complete admissions or installed withdrawal
frontier. Recomputing the same in-memory snapshot head before a request proves
consistency with that snapshot, not continuing external currentness. Descriptor
and evidence expiry bounds do not detect a source withdrawal within their
validity interval.

This is an existing compatibility consumer, distinct from the absent normal
Owner/current-provider/selected-ranker bootstrap. It must not be described as
enforcing full V2 expiry/source-withdrawal guarantees. An opaque V1 support
digest cannot discriminate a legacy dataset pin from a complete V2 manifest
commitment. A supported product profile must be explicit and authenticate the
relevant source semantics; adopting owner-published V2 artifacts requires full
current provenance and eligibility checks before baseline or policy use. Wiring
that provider, preserving trust across refresh, and adding withdrawal/expiry
integration tests remain repository work.

## 8. Bounded qualification and operating evidence

Candidate bytes are capped at 64 MiB; V1 snapshots and auxiliary durable histories
are bounded at 8 MiB/4,096 records. CURRENT discovery admits at most 4,096 head
records and bounds all head-directory entries, including pending files, at 8,192.
Transaction-directory scans count all entries against a 24,576-entry
ceiling, host small records are capped at 16 KiB, and full admission sidecars are
capped at 128 KiB. Capacity exhaustion is an
explicit rejection, not a reason to truncate history or choose an older head.
Retention/compaction requires a versioned format and independent rollback floor.

From the repository root, check caller and Lane E source closure:

```bash
python3 scripts/verify_hepta_callers.py verify
python3 scripts/hepta-lane-e-closure.py verify
```

From `codex-rs`, run the focused package checks using the repository test driver:

```bash
cargo check --locked -p codex-hepta-learning-artifacts --all-targets
just test --locked -p codex-hepta-learning-artifacts
```

After committing and rebinding exact source identities, run
`python3 scripts/hepta-implementation-maps.py verify` from the repository root.
The Lane E workflow also qualifies the actual-base synthetic merge, cross-crate
reload/rollback and strict lint/format. Source-navigation and caller proofs do
not prove executable bootstrap, target-host behavior or operator acceptance.

Before claiming target-host execution, retain exact commit/configuration and
trust digests, signed restart anchors, all phase/retry/kill-and-reopen results,
filesystem/power-loss evidence, withdrawal/revocation restore results and bounded
write/hash/replay/current-view latency and resource measurements. These records
must distinguish source qualification, deployment composition, independent
acceptance, selection, canary, promotion and release.
