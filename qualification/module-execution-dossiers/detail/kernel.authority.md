# kernel.authority: implementation design

Parent: `docs/modules/kernel.authority/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: durable authority leases/revocations, signed final-use verification,
independent approval, authenticated revocation ingestion and a registered Bao
consumer host are source-implemented. Product-process activation and independent
acceptance remain separate gates. Common requirements: `../EXECUTION_SEMANTICS.md`
and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-contracts`.
Packages: `P0.7B-B0-VERIFIED-USE`, `P0.7B-B4-CALLSITE-PROOF`.

The owner-native implementation is in `codex-rs/hepta-contracts`; the Bao host
is an integration consumer in the separately owned `secrets.heptabao` module.
Preserve existing stores and APIs; do not create another authority or execution
spine.

## 2. Public operations and contract details

The native general capability owner is split by type-level least authority:

- `AuthorityLeaseRegistry` is the non-cloneable administrative owner;
- `AuthorityLeaseVerifier` is the cloneable read/verify attenuation;
- `put_lease(lease, expected_revision)` performs bounded owner-CAS create/update;
  an identical retry succeeds only with the original predecessor revision;
  identical content with any other predecessor is `RevisionMismatch`;
- `read_lease(lease_id)` and `read_revocation(lease_id)` publish the current
  `authority_lease` / `capability_revocation` values;
- `AuthorityLeaseVerifier::verify_use(lease_id, expected_revision, binding)`
  checks principal, operation class, scope, payload/destination binding, epoch,
  revision, expiry and revocation using the clock already bound to the owner;
- `revoke(lease_id, expected_revision, reason_digest)` performs one durable
  owner-CAS revocation. The authority clock creates the revocation timestamp;
  an exact retry returns the original receipt;
- `prune_expired_leases(max_to_prune)` reclaims a bounded batch of expired,
  unrevoked live leases only after recording each lease ID's last revision in
  the durable retired-lineage map; same-epoch reuse must continue at revision
  `retired + 1`, and neither retired lineage nor revocation tombstones are
  collected inside an epoch;
- `advance_epoch(expected_store_revision, new_epoch)` durably fences old
  authority and clears bounded old-epoch history only as part of the epoch
  transition.

The narrower signed final-use path remains `FinalUseAuthority::claim` followed
by `FinalUseAuthority::with_verified_use`. The token is opaque, non-cloneable
and non-serializable. `FinalUseApprovalVerifier` can require an independently
signed operator approval of the exact grant semantics, while
`FinalUseRevocationFeedVerifier` authenticates one complete revocation head
before handing it to the durable authority owner.

## 3. State records and transaction design

`authority_lease` contains lease identity, principal, operation class,
scope/payload/destination binding, issued/expiry time, authority epoch and lease
revision. `capability_revocation` binds lease/epoch/revision, a reason digest,
revocation time and the authoritative store frontier. No raw signing key is
stored in general receipts.

Lease/revocation mutation is serialized by the owner mutex and durably persisted
through an owner-only Unix directory, process lock, complete next-state write,
file fsync, same-directory rename and directory fsync. Storage uncertainty fences
the live handle. A host-supplied trusted frontier rejects rollback or an
initialized-but-missing store above genesis.

The authority-lease image is canonical store schema V2; retired revision lineage
participates in the state digest/frontier. No schema-V1 authority-lease image
has been activated or released, so V1 is not silently accepted as V2. Any future
predecessor migration must be explicit and frontier-bound.

The final-use nonce/revocation store remains separate because signed one-shot
grants and general durable leases have different lifecycle semantics.

## 4. Deterministic algorithm and scheduling

For a general lease, resolve the authenticated caller and exact binding, inspect
one coherent lease/revocation state under the owner lock and return an opaque
verified-use token. Recheck the current state at the final synchronous boundary.
The final check acquires the owner lock before sampling the bound clock; a lease
that expires while waiting for the lock is rejected rather than admitted with a
stale timestamp.

For signed final-use, `claim` verifies the owner signature and exact binding,
durably consumes the nonce, then the adapter may perform bounded asynchronous
work. At final entry `with_verified_use` revalidates live authority under the
mutex and releases the mutex before invoking the already selected trusted
callback. The successful recheck is the dispatch-entry linearization point: a
revocation committed before it denies entry; a revocation committed after it is
ordered after entry and cannot retroactively undo the effect.

The registered Bao host resolves the signed `consumer_id` against a closed
process-local registry. It verifies independent operator approval and current
signed-feed freshness before provider dispatch. After provider I/O, exact
version and secret-digest validation, it checks feed freshness again at the
registered consumer boundary before releasing secret bytes. A feed that expires
in flight therefore fails with `StaleRevocationFeed` without invoking the
consumer. Revocation updates enter through a separately pinned signed feed.

The named Agentd automation host composes the same native FinalUse owner through
`open_state_dir_with_issuer_keys`, using `AgentdFinalUseTrustStore` as both the
bound clock and exact external frontier. It verifies a separately signed
revocation feed at startup and refreshes that file before every provider effect.
The trust state is owner-locked, lives outside Agent home, persists a monotonic
clock floor and fails closed on CAS conflict, missing frontier, clock rollback
or restored local authority state. This is a repository source composition; it
is not a target attestation or HSM/KMS claim.

Guarded provider effects publish an active-effect fence. If a newer trusted
revocation arrives during the effect, update returns `DispatchInProgress` and
sets `revocation_pending`. New claims and entries then reject with
`RevocationPending`; the exact update is retried after the effect drains. The
pending bit is process-local, so restart safety comes from re-reading the signed
feed, not from assuming the interrupted update disappeared.

The revocation control protocol caps signed-feed lifetime at 300,000 ms and
supports node-signed exact-update acknowledgements. A successful local apply
returns an opaque `FinalUseRevocationReceipt` bound to the exact update digest;
the node-ack constructor requires that receipt, so an acknowledgement cannot be
created through the public API from an unapplied raw update or a receipt for a
different update. Convergence verification then requires the pinned feed
verifier plus the exact `SignedFinalUseRevocationUpdate`; it authenticates
distributor identity, freshness, active epoch key and signature before accepting
any receipt-bound node acknowledgement. The report binds the distributor
trust-key id and selected key id for every acknowledged node. Missing,
duplicate, unknown, forged, wrong-head, stale and future-dated acknowledgements
fail closed. This proves an authenticated repository-level apply→ack chain but
does not perform fleet transport.

## 5. Capacity and performance profile

Both current owner stores are bounded; there is no silent eviction. The general
lease registry exposes current/max live-lease, revocation and retired-ID counts,
bounded online pruning of expired unrevoked leases (maximum 1,024 per call,
limited by remaining retired-lineage capacity), and explicit durable epoch
rollover. Prune never resets identity lineage inside the epoch. A selected deployment must alert before exhaustion and
coordinate the trusted epoch/frontier transition before admitting new work.

Pilot verified-use request <= 16 KiB; bounded scope predicates <= 64; no
unbounded grant chain. Measure final-gate p99 separately from remote identity or
revocation transport. FinalUse local claims append fixed frames, while a
production frontier digest still covers the complete nonce/revocation state and
therefore must be measured at history load points. Pilot ceilings are design
targets, not measurements. Production evidence schema v2 requires the complete
5-by-11 numerical matrix, structured fault outcomes and demonstrated reserve
alert; prose-only pass flags are rejected.

## 6. Concrete verification cases

- AUTH-01: a higher-utility action with revoked authority is denied before adapter entry.
- AUTH-02: payload/destination change after planning fails the final gate.
- AUTH-03: dispatch racing revocation follows the declared linearization rule; no stale epoch is silently accepted.
- AUTH-04: crash after durable revoke preserves revoke after reopen; an external frontier detects local rollback/reset.
- AUTH-05: an independently signed approval fails after any grant semantic drift.
- AUTH-06: forged or stale revocation-feed updates never change live authority.
- AUTH-07: a callback that re-enters revocation does not deadlock or poison the authority mutex.
- AUTH-08: an unregistered signed consumer id cannot select an arbitrary callback.
- AUTH-09: an identical lease mutation with the wrong predecessor revision is not an idempotent retry.
- AUTH-10: a revocation acknowledgement dated after verifier current time is rejected.
- AUTH-11: if signed-feed freshness expires during Bao provider I/O, final consumer entry is denied and no secret is released.
- AUTH-12: otherwise valid node acknowledgements over an unsigned or forged distributor update cannot produce a convergence report.
- AUTH-13: a node acknowledgement cannot be constructed with an apply receipt from a semantically different revocation update.
- AUTH-14: an identical lease put with a different predecessor revision is rejected.
- AUTH-15: lease expiry while waiting for the owner lock denies both consumer and dispatch entry.
- AUTH-16: a blocked revocation stops new claims until the exact signed update is retried after drain.
- AUTH-17: Agentd trust ownership hands off only after the old owner exits, and a restored local authority snapshot is rejected by the external frontier.
- AUTH-18: the TaskFlow attempt and canonical authority witness survive provider response loss and restart; the same attempt is reconciled rather than redispatched.

Source tests implement the native cases above. Exact-candidate workflow receipts,
not test-file existence, establish execution for one candidate.

## 7. Integration, rollback and capability ceiling

B4 call-site proof now inventories final-use claim, final delivery, independent
approval verification, revocation-feed application, the raw Bao consumer and the
registered Bao host. Method-call patterns are scanned across non-test/non-example
Rust sources; unexpected product callers fail the closed-set check. The public
raw `BaoClient::consume_kv_v2` closure path has an empty product-caller set;
the registered host uses a crate-private typed final-delivery gate instead.

The local filesystem remains insufficient as an external anti-rollback oracle.
The host must provide a protected monotonic frontier and trusted time. Signed
revocation authentication/ingestion are source-implemented, while fleet fanout,
freshness SLA and consensus remain deployment responsibilities. HSM/KMS and
operator ceremony are also target-host evidence gates.

No source or qualification artifact self-grants activation, operator acceptance,
promotion or release.

## 8. Current native implementation

- **General authority owner:** `AuthorityLeaseRegistry` in
  [codex-rs/hepta-contracts/src/authority_lease.rs](../../../codex-rs/hepta-contracts/src/authority_lease.rs),
  including durable lease/revocation state, CAS semantics, trusted time/frontier,
  capacity reporting and epoch rollover.
- **Signed final-use owner:** `FinalUseAuthority` in
  [codex-rs/hepta-contracts/src/final_use.rs](../../../codex-rs/hepta-contracts/src/final_use.rs)
  and `Store` in
  [codex-rs/hepta-contracts/src/final_use_store.rs](../../../codex-rs/hepta-contracts/src/final_use_store.rs).
- **Independent controls:** `FinalUseApprovalVerifier`,
  `FinalUseRevocationFeedVerifier` and
  `FinalUseRevocationConvergenceVerifier` in
  [codex-rs/hepta-contracts/src/final_use_control.rs](../../../codex-rs/hepta-contracts/src/final_use_control.rs).
- **Registered integration hosts:** `BaoFinalUseHost` in
  [codex-rs/hepta-bao-adapter/src/final_use_host.rs](../../../codex-rs/hepta-bao-adapter/src/final_use_host.rs),
  and the named Agentd automation host in
  `codex-rs/hepta-agentd/src/automation_effect_host.rs` plus
  `authority_trust_host.rs`. Agentd binds rotating issuer keys, signed feed,
  protected host state, durable TaskFlow attempt/witness and the concrete HTTP
  provider adapter. Neither source host is a selected or independently accepted
  deployment merely because it compiles.
- **Operator utilities:** `hepta-final-use-signer`,
  `hepta-final-use-approver` and `hepta-final-use-revocation-signer` in
  `codex-rs/hepta-supervisor`, gated by the explicit `production-authority`
  feature and using externally provisioned owner-only keys.
- **Source tests:** `src/final_use_tests.rs`, inline authority-lease/control tests,
  `tests/final_use_linearization.rs`, Bao HTTPS tests and registered-host tests.
  These are identities, not exact-candidate pass receipts by themselves.
- **Operating references:**
  [codex-rs/hepta-contracts/FINAL_USE.md](../../../codex-rs/hepta-contracts/FINAL_USE.md),
  [codex-rs/hepta-contracts/FINAL_USE_CONTROL.md](../../../codex-rs/hepta-contracts/FINAL_USE_CONTROL.md),
  [codex-rs/hepta-supervisor/EXTERNAL_AUTHORITY_SIGNER.md](../../../codex-rs/hepta-supervisor/EXTERNAL_AUTHORITY_SIGNER.md).
- **External evidence admission:** `qualification/kernel-authority/verify.py`
  fail-closed validates exact-candidate production bundles covering protected
  time, rollback-independent CAS, deployed revocation convergence scenarios,
  three-role key custody/rotation/compromise evidence, capacity/fault
  qualification and independent operator acceptance. Bundle admission is not
  activation or release.
- **Remaining gates:** selected product-process activation, real fleet revocation
  fanout/freshness measurements, concrete rollback-independent frontier and
  protected-time backends, HSM/KMS custody receipts, equivalent non-Unix storage,
  independent semantic acceptance, canary, promotion and release.

## Integrated Agentd Browser consumer

`hepta-agentd-browser` opens the durable FinalUse owner. `BrowserServoPort::call`
claims the exact grant and crosses the bounded dispatch fence around durable
Browser intent and local worker dispatch. The Browser child receives no
serializable authority token. These non-test callers remain registered in
`CALLERS.toml`; their source composition does not establish product execution
or activation. Fleet mutation uses `dispatch_authority_lease_with_witness` at
the concrete owner boundary, retaining its canonical audit witness.

## Integrated runtime.codex entry

Runtime Codex obtains an opaque final-use token from the host-owned verifier, binds its exact claim-time head into the durable dispatch witness, and calls `VerifiedUseToken::enter` at its first effectful boundary. Entry rechecks the same protected clock and requires an unchanged head. This source integration does not qualify a concrete deployed clock, rollback frontier or revocation-distribution backend.

## Durable Agentd automation evidence chain

For one authorized TaskFlow effect, the product source path is: validated durable effect intent → exact FinalUse binding → durable nonce claim → active-effect/final-entry check → immutable `VerifiedUseTokenWitnessV1` plus attempt row → physical provider call → durable observation or indeterminate recovery. The SQL witness table rejects update/delete and exact replay with semantic drift. Crash after provider contact, lost acknowledgement and an indeterminate result reopen the same attempt; provider-owned lookup/reconciliation is required before a terminal transition.

The canonical witness is evidence only. It cannot be deserialized into authority, reissue a grant or authorize retry.
