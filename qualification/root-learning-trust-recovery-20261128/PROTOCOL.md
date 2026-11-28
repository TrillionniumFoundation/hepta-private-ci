# Root LearningTrust recovery: prospective contract

Status: source design and staged implementation only. No real provisioning,
Ledger recovery, training, native gate, or scientific run is authorized by this
document. The original shared native budget and all earlier outcomes remain
unchanged. The source base is `85ccf3305e34c90d3d10bdb1a6294d4e6adcf893`.

## Existing owners and the missing input

The original Ledger API consumes owned files, an independently acknowledged
nonzero `LedgerAnchor`, a separate witness, held directories, and an opaque
`ActivatedLearningTrustV1`. Its activation API validates the complete pinned
root, signed distribution, evidence verifier and validity windows. Rotation from
an existing Activated value requires exactly the next generation.

A signature does not say which valid distribution the deployment currently
selects. Replaying an older signed distribution together with older ledger and
witness bytes can present the same local inputs as an earlier valid deployment.
An independent current owner is therefore required. A caller's
`expected_generation`, a digest, a sealed bootstrap, a writer lease, or the
CognitiveStore checkpoint cannot substitute for that owner.

The fixed source inspection is recorded in SOURCE_EVIDENCE.json and
READ_ONLY_SEARCH.json.gz. The original production consumers found for
DurableLedger do not construct the production LedgerWriter with root-activated
trust. The existing terminal launch already accepts an embedding's real
`Arc<Mutex<LedgerWriter>>`; the default CLI does not possess one.

## Threat model and initial administrative choice

Reuse the same original Root authority service, required bind, registered
writer, protected issuer, clock, policy and pidfd/logind context. No key, issuer,
policy, empty ledger, empty witness, reset frontier or signing authority is
created. Runtime peer requests cannot select the current record.

The original Root frontier backend protects its state from an unprivileged
Agent replacing Agent-writable files. It explicitly does not protect against
Root or whole-host rollback. This proposal preserves that limit.

A new, explicit Root administrative intent may select an already supplied full
root-signed distribution as the deployment's initial current distribution.
This is a trusted administrator's selection. Signature verification is not a
cryptographic proof that the selected distribution is globally newest.

The root pin and external acknowledgement must be separately supplied through
the original Root configuration/custody boundary. They are not reconstructed
from the suspect ledger, witness, peer bundle or distribution. An acknowledgement
accepted in that way is an independently Root-configured acknowledgement
declaration. Until an actual original consumer is observed, it proves no useful
work, user event, training gain or real-world acknowledgement.

## Three implementation stages

1. Extract the original complete signature/time/scope/evidence validation into
   a signature-only verifier. Existing activation calls it and retains the
   original monotonic rotation check. Its result exposes only non-authorizing
   identity metadata, with no public conversion to Activated trust.
2. Add the actual Root CLI/Prepared-session caller for current registration and
   monotonic rotation. It consumes the explicit intent and external original
   inputs through the original service. It publishes a real durable current
   record and binds that record to a stable ID in the original authority
   registry. It never accepts a current record supplied by the runtime bundle.
3. Add a recovery-only consumer of that live current owner and actual held files.
   It verifies the full distribution again at the original current time,
   acquires genuine file custody, recovers with the external acknowledgement,
   and supplies the resulting single Ledger Arc to the existing terminal launch.

Each stage must remain reviewable under the original 800-line change limit.
No stage inherits native qualification from an earlier source. Stage 1 has its
own exact source scope below; stages 2 and 3 require their concrete source and
caller contracts to be frozen before any execution.

## Current record and publication requirements

The stable current identity binds the logical ledger, root identity and scope.
It must not vary with a generation or caller-provided path, so an old generation
cannot acquire a separate apparently fresh slot.

The record binds the validated full root/distribution identity, generation,
effective time, authority epoch, validity window, independently configured
acknowledgement, and original registered owner context. Its exact canonical bytes
are committed by the original registry binding. The runtime accepts only a
live observation through that same original owner; serialized metadata cannot
be converted back into an opaque live-use capability.

Initial registration requires the original absence/CAS0 contract, including
retired and revoked ID refusal. Rotation reads the actual existing record,
checks its original registry binding, and requires the same root, generation +1,
nondecreasing effective time and authority epoch. These checks use the verified
new signature and actual old owner state. No caller-provided expected generation
establishes freshness.

The existing authority registry advances its independent durable frontier
before persisting local state. A failure fences the owner; reopening a mismatch
refuses. A new typed current record and its registry binding are two records.
Their publication must not claim cross-record atomicity: an interrupted or
inconsistent transition refuses runtime use and reports an uncertain
administrative outcome. No fallback to an older record or reset is permitted.

## File custody and recovery

The future consumer requires the original held ledger, separate witness and
their directory handles, plus fixed device/inode identities and logical binding.
Regular file type, ownership, permissions, link count, access flags, distinct
ledger/witness inodes and directory identity must be checked on held handles.

The original LockedFile API explicitly excludes cloned/inherited handles
already locked elsewhere. A clone or transferred shared open-file-description
lock cannot be relabeled as new exclusive custody. The recovery boundary must
open a genuinely independent description through the trusted held directory,
verify the same inode, and let the original owner acquire its own exclusive
lock. A still-held original/contending writer is a refusal.

Recovery remains `LedgerRecovery::Acknowledged` with a nonzero external anchor.
No `Unacknowledged`, `create`, `previous=None`, digest-to-Activated constructor
or test-fixture fallback is permitted. Full corruption, missing history,
wrong current generation, scope/root drift and absent ownership are refusals.

Recovery can repair an incomplete tail and synchronize files. Once such I/O
may have occurred, a later authority/deadline failure is uncertain; it is not
proof that no mutation happened. Directory synchronization and actual witness
checks remain part of the original LedgerWriter construction.

## Runtime validity and lifetime

A startup observation is insufficient for continued use. The actual original
current owner must remain reachable and be checked at each relevant admission,
before native work and before a successful receipt is exposed. A newer
generation, revocation, expiry, wrong process lifetime or unavailable current
owner closes new admission.

Already admitted atomic native work is not made preemptible by this contract.
Existing native-worker lifetime/drain accounting must retain it until actual
exit; post-boundary loss of authority yields an uncertain result. The original
absolute session end, cancellation and one-time owner claim remain mandatory.

## Stage 1 source scope and unexecuted controls

Stage 1 changes only the original learning-ledger trust module, a new signature
child, its dedicated tests, exports and exact source guards. It preserves all
existing public activation signatures, digest domains, signature bytes, error
variants and rotation rules. The verifier itself neither reads a current
record nor returns Activated trust.

Two prospective synthetic controls cover signed-content tampering plus the
original root/time/scope constraints, and demonstrate that independent
signature validity does not establish current-generation ordering. Existing
activation tests remain unchanged. These controls are source-only until a
separately allocated native or natural hosted gate actually runs them.

Unresolved real inputs remain explicit: the deployment's original root pin,
full externally signed distribution, independently Root-configured
acknowledgement, genuine file custody, and original Evaluator/Memory permission.
No such real inputs are fabricated or provisioned by this work.

