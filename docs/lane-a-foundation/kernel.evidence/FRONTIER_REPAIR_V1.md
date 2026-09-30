# Frontier repair protocol V1

This document specifies the repository implementation for an explicitly authorized `kernel.evidence` recovery-frontier repair. It is separate from ordinary monotonic publication and does not grant deployment, operator, promotion or release authority.

## 1. Capability separation

Ordinary `EvidenceFrontierBackend::compare_and_swap` accepts only a transition classified `IncomingWins`. It cannot consume repair authorization and cannot overwrite a `RepairRequired` or equal-generation conflicting frontier.

Repair uses the distinct `EvidenceFrontierRepairBackend` capability. A caller must first persist an exact signed authorization in the local evidence store, obtain a durable dispatch fence, then carry that same operation identity through external acknowledgement, indeterminate recovery or conflict.

## 2. Exact authorization binding

`FrontierRepairAuthorizationV1` binds:

- store identity;
- current and target canonical frontier digests;
- current and target generations;
- reason code and operator principal;
- issuance, expiry and one-time nonce;
- authority key ID, key epoch, algorithm and trust-root generation;
- authority signature.

The ledger accepts only transitions that the closed-world merge classifier returns as `RepairRequired`. A normal automatic successor must use ordinary CAS instead. Same-generation different-identity inputs remain conflicts rather than acquiring an arbitrary winner.

## 3. Durable nonce and operation identity

Migration `0017_frontier_repair_publication.sql` stores one canonical operation row and an immutable event chain. The tuple `(authority_key_id, authority_key_epoch, nonce_hex)` is globally unique. Exact retries return the existing operation; reuse with different canonical current, target, authorization or authority bytes is an identity conflict.

Only one unresolved repair may exist for one store. Terminal acknowledgement or terminal conflict releases that slot for a separately authorized later repair.

## 4. State machine

The persistent states are:

```text
prepared
  -> dispatching
       -> indeterminate -> acknowledged | conflicted
       -> acknowledged
       -> conflicted
```

Semantic fields are immutable. `prepared -> dispatching` binds one stable dispatch token and the exact target backend identity. Later transitions must retain both. No terminal state can reopen.

An acknowledgement is accepted only when its store, backend identity, target generation, target digest and durable audit sequence match the authorized target. A conflict records the actually observed generation and frontier digest. Unknown external outcomes become `indeterminate`; they are reconciled by observing the same repair ID and dispatch token, never by dispatching a new operation.

## 5. Audit and reopen verification

Every state transition appends a canonical event whose digest commits the previous event digest. Event rows cannot be updated or deleted. Verification reconstructs canonical current/target/authorization/authority objects, checks their stored digests and projections, revalidates the original signature at preparation time, confirms the transition still classifies `RepairRequired`, and verifies the complete bounded event sequence.

`HeptaEvidenceStore::verify_frontier_repair_ledger` is the product attachment gate for a repair publisher. A caller must invoke it before exposing external repair operations. Store migration and ordinary frontier APIs alone do not activate repair.

## 6. Remaining external gates

Repository source does not prove that an external repair backend is independently operated, monotonic or deployed. Production activation still requires independently pinned authority material, a qualified backend implementation, target-host crash and restore evidence, operator acceptance and retained external receipts. Until then the runtime readiness fields for external anchor, operator activation, promotion and release remain false.
