# kernel.evidence architecture

## 1. Ownership and boundaries

`codex-hepta-evidence` owns append-only qualification evidence, accepted recovery
frontiers, authenticated admission commitments, publication intent and local
reconciliation state. Agentd owns product configuration, owner-file admission,
current trust loading, backup/build verification and external CAS invocation.
Neither component owns independent review, deployment, promotion or release.

The principal layers are:

- canonical typed records and digest domains;
- SQLite authoritative state and migrations;
- owner-controlled verification profiles and sealed trust snapshots;
- recovery-frontier V2 signatures and external monotonic storage;
- durable publication prepare → dispatch → reconcile → acknowledge state;
- bounded Agentd append, query, verification and operations surfaces;
- runtime readiness and crash-consistency receipts.

One logical mutation uses one SQLite transaction. External work begins only after
an immutable local intent/fence is durable. An uncertain external result is
`indeterminate`, never `not_started`, and is reconciled by exact operation
identity.

## 2. Frontier merge state machine

`classify_frontier_merge` is the closed-world comparison contract. It is not a
general ordering and never chooses a lexical winner for competing identities.

| Decision | DB write | External overwrite | Audit | Epoch advance | Repair authority | Automatic retry |
| --- | --- | --- | --- | --- | --- | --- |
| `ExactDuplicate` | no new row | no | no new commit | no | no | verified no-op only |
| `IncomingStale` | no | no | rejection diagnostic | no | no | no |
| `IncomingWins` | exact successor transaction | normal CAS only | required | exactly +1 | no | same durable operation only |
| `ConflictSameOrderDifferentIdentity` | no | no | incident diagnostic | no | cannot repair in place | no |
| `InvalidIncoming` | no | no | rejection diagnostic | no | no | no |
| `InvalidCurrent` | no | no | incident diagnostic | no | external recovery required | no |
| `RepairRequired` | no through normal admission | no through normal CAS | authorization/incident evidence only | no implicit advance | exact signed authorization required | no blind retry |

Automatic successors require the same store and backend, generation `current+1`,
non-regressing timestamps, qualification sequence and signer-policy generation,
and stable source/build/qualification/migration/issuer-authority identities.
Signer-registry rotation requires a strict signer-policy generation increase.
A source, backend, build, qualification, migration or issuer-authority change is
an explicit transition, not an incidental overwrite.

Both external backend implementations reclassify the proposed transition while
holding their serialization lock and before writing an audit byte. On reopen,
the single-file journal and the production segmented backend replay the same
state machine. Segmented replay walks the immutable predecessor chain from
genesis, validates every segment and record in order, then validates the
archive-to-active boundary. Recomputing record, metadata or latest-index hashes
cannot turn a semantic `RepairRequired` transition into an automatic successor.

## 3. Repair transition

`FrontierRepairAuthorizationV1` binds one current digest and generation to one
target digest and higher generation. It also binds reason, operator, issuance,
expiry, nonce, authority key ID and epoch, algorithm and trust-root generation.
The Ed25519 key must be independently admitted, valid for the current time and
not revoked. Changing any bound field invalidates the signature. A same-
generation split must be resolved by producing a new generation; it is never
rewritten in place.

The repository implements and tests the exact authorization verifier. The
ordinary legacy and segmented backend CAS surfaces intentionally reject
`RepairRequired`; they do not reinterpret a signed document as permission to use
the normal publication path. A production repair publisher must additionally
retain the authorization and one-time nonce in its durable external audit
record, execute only the signed current→target transition, and be independently
qualified and activated. Until that separately governed path exists,
`RepairRequired` remains a stop condition rather than an online overwrite.

## 4. Qualification identity

The following are distinct objects and are recorded separately:

- source head and source tree;
- immutable base;
- deterministic two-parent merge;
- GitHub pull-request synthetic merge;
- workflow definition SHA;
- final real merge SHA.

The four required candidate receipts and the crash-matrix summary must also
match one workflow run ID, attempt, runner image and target triple. A receipt
from another attempt, tree, base, merge object, workflow object, runner or target
is non-success even when its command passed. No successful status is copied
between candidates. After merge, the real merge commit is rerun and
`final_merge_sha` is populated by that run only.
