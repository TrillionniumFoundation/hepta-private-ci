# Proposed artifact-selector currentness contract

**Status: PROPOSED / NOT IMPLEMENTED. Overall qualification remains HOLD.**
This document specifies a reviewable follow-up boundary; it adds no executable check,
production root, service configuration, wire format, or production qualification.
All source references are fixed at `1993db5510afb9764a4a4a60e5bd0f48862411ab`.
Logical fields below are requirements for review, not a finalized byte encoding.

## 1. Existing ordinary path and missing authority

The existing path is [artifact selection verification][selection] →
[opaque initial material][material] → [public-initial host preparation][initial-host] →
[ordinary Agentd attachment][initial-agentd] → [ranker material use][ranker].
Selection verifies a supplied selector trust snapshot against authenticated CURRENT.
Initial material retains its original lifetime, known revocation time, and owner-trust
binding; each use rechecks those values and fresh CURRENT. It does not fetch new
selector revocations, removals, key rotations, or changes to the selector trust root.

[CURRENT's reader][current-reader] authenticates the artifact registry using pinned
writer/head trust. Its current registry is not a current selector roster.
The selector trust digest is distinct from the CURRENT owner trust digest; the former
is not retained in the initial material's currentness contract.
[FinalUse initial-read binding][initial-query] already commits to the selection digest,
which covers the original selector key identity and epoch. Its issuer/feed/frontier
authorizes FinalUse grants and consumption, not the selector's current role.
A valid signature or an unchanged selection digest therefore cannot fill this gap.

[Learning activation][learning-activation] already retains an external distribution
floor in [opaque learning evidence][learning-frontier]. That mechanism is a useful
precedent, but its `LearningEvidenceRoleV1::Selector` is a different trust domain.
No implicit conversion from that role, CURRENT signer, or FinalUse issuer is proposed.

## 2. Proposed minimum invariant

An initial material must retain an authenticated artifact-selector admission state.
At each ordinary use, a fresh authenticated observation must match that admitted state
and still satisfy its scope, role, key, time, revocation, and recovery constraints.
The conservative minimum rejects retained material after any selector-trust state
change; continued use requires explicit reselection under current authorized trust.
A refresh must not extend the original selection lifetime or adopt a new root silently.
Signature verification may be cached; current authorization must be observed again.
This invariant covers observed currentness, not a transaction with a remote effect.

## 3. Logical signed fields and separation of purposes

Updates, current-state responses, selection admission, rotation, and recovery need
distinct purposes/domains and permission checks. They need not share one envelope.
The following fields must be bound wherever that operation relies on their meaning:

| Field group | Required logical binding |
| --- | --- |
| Protocol context | Network and genesis identity, protocol version, cryptographic profile, purpose/domain. |
| Authority | Approved artifact-selector root identity/digest and key generation; issuer identity, delegated role, permitted action, delegation scope. |
| Target and audience | Exact authority namespace, registry, withdrawal/permission scope, intended recipient; relevant CURRENT-owner trust binding. |
| Trust object | Complete selector-trust digest, including selector identities, keys, key epochs, roles/scopes, validity and revocation constraints. |
| State transition | Distribution generation, authority epoch, resulting state digest, and exact expected predecessor/current-state digest. |
| Operation identity | Operation ID and replay-resistant nonce; update retry/consumption rules must be explicit. |
| Time | Issued-at, effective-at and expiry, evaluated against a protected clock with defined units and bounds. |
| Revocation/recovery | Current revocation state commitment, recovery generation/state and authorized recovery/rotation transition. |
| Current observation | Fresh request challenge, bound consumer/namespace, observed state and retained floor; a reply cannot cross requests or domains. |
| Material admission | Exact selection digest, selector/key identity and epoch, admitted trust state, load/use purpose and original window; artifact ID, manifest/content/compatibility digests, artifact generation and parent. |

Trust-root selection, delegation ceremony, canonical encoding, digest construction,
algorithm identifiers, clock units, and schema/version migration remain design decisions.
No production key, endpoint, namespace value, or root-rotation policy is chosen here.
FinalUse nonces and authority epochs remain separate from selector-update equivalents.
Artifact generation, selector-trust generation, and selector key generation are distinct.

## 4. Real update producer, external current state, and cold-start floor

Design review must identify the actual artifact-selector authority and update producer.
Its production operation must authenticate the proper root/delegation, validate the
expected predecessor and operation nonce, and durably commit before acknowledging.
A reader-only API with manually altered test state does not establish this producer.
Duplicate exact operations must have explicit retry semantics; conflicting reuse,
rollback, and unauthorized role/root substitution must fail closed.

The current state and monotonic floor require an identified, authorized writer and
durable custody outside the initial host, cache and restorable local history/config.
A consumer must not initialize its trusted floor from the submitted selection/proof.
Current responses bind namespace, complete state and fresh challenge; a new challenge
cannot make an old snapshot current. Unavailable, stale or conflicting state denies use.
Cold start must compare restored admission with that floor before model load/use;
valid historical signatures cannot lower it or restore former root/key rights.
Root rotation/recovery requires an explicit authorized transition and retained floor.
Existing signed transport/CAS may be reused only with a reviewed artifact-selector
binding and permission domain, never by substituting an unrelated root.

## 5. Proposed wiring into existing ordinary entry points

The selection verifier must obtain authenticated current selector authority and retain
its binding in the opaque material, alongside the existing selection and owner pins.
The host must supply a real authority provider through its normal installation/config
path. Caller booleans, unverified roster bytes, and test-only providers are insufficient.
[Public initial preparation][initial-host] must check before parameter/model admission.
Material `with_current`, [ordinary initial Agentd use][initial-agentd], and
[ranker use][ranker] must preserve the same guard, checking before execution and before
making the result visible. Existing CURRENT, FinalUse and resource gates remain required.
A failed refresh must close the retained material/owner according to existing cleanup
semantics; no retry may revive it, refund a FinalUse nonce, or skip settled-load cleanup.
An after-use rejection must not claim to undo an effect already admitted.
External state can advance after observation: cross-provider atomic admission remains
a separate HOLD gate unless a real shared lease/transaction is designed and qualified.

## 6. Ordinary business acceptance controls

Extend the existing [initial Agentd controls][agentd-controls] and
[actual-forward/cleanup controls][query-controls], exercising their ordinary entry
points with the original model/worker, bounded resources, claim accounting and cleanup.
These are proposed acceptance requirements; no new pass result is asserted here.

| Control | Required observation through the ordinary path |
| --- | --- |
| Normal use | Valid current selector authority permits real preparation and an ordinary task/forward; retain actual journal and FinalUse evidence. |
| Warm-cache revocation | Execute once, update selector authority through its authenticated producer, then reject the next ordinary use despite a valid cached signature. |
| Key/epoch change | Rotate/remove the admitted key, including same selector ID with a different key or tightened epoch; retained material must reject. |
| Wrong domain/scope | Reject a valid signature from learning Selector, CURRENT or FinalUse authority, wrong registry/audience, or mismatched root/distribution. |
| Service failure/replay | Reject unavailable current state, stale/challenge-mismatched responses and conflicting floors; recovery of service must not revive a closed owner. |
| Cold-start rollback | Restore old material/config/history after authority advancement and reject before load/use; preserve consumed FinalUse nonce evidence. |
| Rotation/recovery | Exercise the authorized transition and explicit reselection; prove old roots/keys cannot regain current rights through historical replay. |

In selector-negative controls, keep artifact CURRENT, model bytes, resources and
FinalUse authorization otherwise valid, and isolate the selector-state rejection.
Observe the actual denied dispatch/forward boundary and unchanged relevant journal
counts; a failure caused solely by another gate is not evidence of this contract.
Keep cancellation, expiry, panic and retained-session cleanup controls intact.
Tests must drive the real update and observation paths; fixtures do not establish
independent production custody. All six authorization surfaces retain their own gates.

[selection]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1993db5510afb9764a4a4a60e5bd0f48862411ab/codex-rs/hepta-learning-artifacts/src/selection.rs
[material]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1993db5510afb9764a4a4a60e5bd0f48862411ab/codex-rs/hepta-learning-artifacts/src/selected_initial_smollm.rs
[current-reader]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1993db5510afb9764a4a4a60e5bd0f48862411ab/codex-rs/hepta-learning-artifacts/src/owner_current_reader.rs
[initial-host]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1993db5510afb9764a4a4a60e5bd0f48862411ab/codex-rs/hepta-infer-worker-host/src/smollm_initial_host.rs
[initial-agentd]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1993db5510afb9764a4a4a60e5bd0f48862411ab/codex-rs/hepta-infer-worker-host/src/smollm_initial_agentd.rs
[initial-query]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1993db5510afb9764a4a4a60e5bd0f48862411ab/codex-rs/hepta-infer-worker-host/src/smollm_neural_query.rs
[ranker]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1993db5510afb9764a4a4a60e5bd0f48862411ab/codex-rs/hepta-agentd/src/cognitive_ranker.rs
[learning-activation]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1993db5510afb9764a4a4a60e5bd0f48862411ab/codex-rs/hepta-agentd/src/cognitive_process_pq_trust.rs
[learning-frontier]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1993db5510afb9764a4a4a60e5bd0f48862411ab/codex-rs/hepta-learning-ledger/src/evidence_trust_frontier.rs
[agentd-controls]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1993db5510afb9764a4a4a60e5bd0f48862411ab/codex-rs/hepta-infer-worker-host/src/smollm_initial_agentd_tests.rs
[query-controls]: https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1993db5510afb9764a4a4a60e5bd0f48862411ab/codex-rs/hepta-infer-worker-host/src/smollm_initial_query_tests.rs
