# kernel.authority: implementation design

Parent: `docs/modules/kernel.authority/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: specified target, not implemented or independently accepted. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-contracts`.
Packages: `P0.7B-B0-VERIFIED-USE`, `P0.7B-B4-CALLSITE-PROOF`.

Operation signatures below are design contracts, not assertions of existing native symbols. Bind each to an existing or planned symbol and consumer inside the owner envelope. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`verify_use(principal, operation, final_payload_digest, destination, epoch, now) -> VerifiedUseToken<C> | Denied` checks the current lease, operation class, scope, expiry, revocation epoch and payload. `revoke(lease_id, expected_revision) -> RevocationReceipt` is an owner-only durable operation. Only an authority owner constructs the opaque consumable token; an adapter consumes it immediately before the effect call and cannot serialize/recreate it.

## 3. State records and transaction design

`authority_lease`: lease ID, principal, operation class, scope digest, payload/destination binding, issued/expiry time, epoch, predecessor revision and signature/key reference. `capability_revocation`: lease/epoch, monotonically ordered revocation event, reason digest and authoritative frontier. No raw signing key is stored in general receipts. Lease/revocation transitions are atomic within the authority store; replicas/cache readers cannot issue grants.

## 4. Deterministic algorithm and scheduling

Resolve authenticated caller; read a coherent current lease/revocation snapshot; validate all bindings; issue a short-lived typed token for one adapter entry. Recheck revocation at the final gate. The host must define how a concurrent revocation and dispatch are ordered; a stale cached lease alone is insufficient. Key rotation carries an explicit overlap/revocation policy and never resets epochs.

## 5. Capacity and performance profile

Pilot verified-use request <= 16 KiB; bounded scope predicates <= 64; no unbounded grant chain. Measure final-gate p99 separately from remote identity lookup; local safety gates must have a qualified cached/fail-closed design.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- AUTH-01: a higher-utility action with revoked authority is denied before adapter entry.
- AUTH-02: payload/destination change after planning fails the final gate.
- AUTH-03: dispatch racing revocation follows the declared linearization rule; no stale epoch is silently accepted.
- AUTH-04: crash after durable revoke preserves revoke after reopen and old-backup restore.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

B4 call-site proof covers every effect adapter, not just the validator unit test. This module is outside the NDU learnable surface. Rollback cannot restore revoked leases or old key authority; uncertain epoch state stops affected effects.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.
