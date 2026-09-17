# memory.federation: implementation design

Parent: `docs/modules/memory.federation/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.
Status: authenticated capability-scoped V3 source boundary and concrete pinned-HTTPS product client implemented on the candidate branch; named upstream host activation and independent acceptance remain external claim gates. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-memory-federation`.
Packages: `MEM-3-FEDERATION`.

The V3 protocol is specified in [docs/modules/memory.federation/V3_PROTOCOL.md](../../../docs/modules/memory.federation/V3_PROTOCOL.md). Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

Implemented source operations now include:

- `FederationClientV3::query(FederatedReadPlanV3) -> FederatedAggregateResultV3`;
- `FederationClientV3::revalidate_remote(...) -> FederatedPeerResultV3`;
- `FederationClientV3::cancel_query(query_id)`;
- `ProductionFederationClientV3::new_pinned_https(...)` for the concrete authenticated HTTPS composition;
- the compatibility `execute_once` and `observe_cancellation` V2 entrypoints.

Remote results include source owner, observed frontier, capability-bounded expiry, completeness, per-peer coverage and uncertainty. No remote mutation or host enrollment is implied by a query.

## 3. State records and transaction design

No authoritative remote facts, remote writer or peer-consent store are owned by this module. `FederationResultCacheV3` is a bounded non-authoritative projection. It stores only sealed valid peer results and indexes them by grant ID, peer response key ID and peer ID so current revocation/key/enrollment observations can invalidate affected entries precisely.

Peer enrollment remains an owner-supplied immutable snapshot. Local authorization remains owned by `kernel.authority`; V3 consumes `FinalUseAuthority` rather than defining a competing grant verifier.

## 4. Deterministic algorithm and scheduling

For each peer, V3 validates the immutable enrollment and a signed final-use grant, consumes the authority nonce immediately before dispatch, executes one bounded transport attempt, samples a fresh clock after I/O, rechecks the enrollment, verifies canonical remote payload digest plus Ed25519 peer signature, caps lifetime by response/grant/query/enrollment expiry and finally calls the kernel-owned post-I/O authority fence before evidence is released.

Fan-out supports one through sixteen unique peers with explicit concurrency bounds. Merge order is deterministic. Conflicting evidence with the same owner/record/revision identity fails closed. A failed/partial/stale peer cannot be collapsed into global `Empty` or `Complete`.

## 5. Capacity and performance profile

Enforced source ceilings:

- <=16 queried peers per request;
- <=512 returned evidence IDs after aggregate truncation;
- <=4 MiB concrete HTTPS response body;
- <=60 seconds V3 query lifetime;
- <=4096 in-process cache entries;
- explicit caller-selected concurrency no greater than peer count or 16.

There is no blind retry. An explicit retry requires a newly issuer-signed final-use grant and a new request nonce because the original authority nonce is durably consumed before transport.

Target-host latency/throughput figures remain measurements to be established by the selected product host, not source claims.

## 6. Concrete verification cases

Source tests implement the following cases:

- FED-01: scope/principal/query/grant/key mismatch fails closed through V3 binding and signature checks.
- FED-02: peer failure yields explicit partial or indeterminate coverage and never fabricated empty data.
- FED-03: revocation racing asynchronous I/O is caught by the final authority fence; cache purge is indexed by grant/key/peer and revocation head.
- FED-04: only host-supplied enrolled peers can be resolved; discovery does not imply enrollment or credential release.
- FED-05: a signed response modified after signing is rejected without evidence release.
- FED-06: a fresh post-I/O clock rejects deadline TOCTOU.
- FED-07: fan-out obeys the configured concurrency bound and merge output is deterministic.
- FED-08: query cancellation signals in-flight transport and produces explicit indeterminate coverage.

These source test identities are not independent deployment receipts until exact-candidate CI and target-host execution complete.

## 7. Integration, rollback and capability ceiling

The concrete `PinnedHttpsFederationTransportV3` uses the repository-owned HTTP client with an enrolled pinned CA, one bounded POST, a bounded response body and no retry. Remote evidence retains provenance and carries `AuthorityPosture::DENY_ALL`.

Rollback can discard incompatible V3 cache entries because they are projections. It must never restore a revoked authority grant, peer enrollment or remote-data authority.

Immediate revocation remains effective across network I/O because final evidence release passes through `FinalUseAuthority::with_verified_use` after response validation.

## 8. Current native implementation

- **Authenticated V3 entrypoints:** `FederationClientV3::query`, `revalidate_remote`, `cancel_query`; concrete `ProductionFederationClientV3` / `new_pinned_https` composition in `codex-rs/hepta-memory-federation/src/v3/`.
- **Authority boundary:** signed final-use grants are verified and consumed by `codex-hepta-contracts::FinalUseAuthority`; `memory.federation` emits only a non-authoritative `VerifiedFederationAuthorityReceiptV3`.
- **Remote authenticity:** `RemoteFederatedEnvelopeV3` recomputes canonical payload bytes and validates the enrolled peer Ed25519 signature, exact query binding, grant/epoch, request nonce and peer key identity.
- **State/recovery:** `FederationResultCacheV3` is bounded and purgeable; no peer registry authority, remote writer, retry queue or durable remote truth is owned here.
- **Compatibility:** root V2 `execute_once` now preserves zero-item `Partial` semantics and caps result lifetime by lease/query lifetime. V2 remains a compatibility path; it is not the authenticated V3 production security model.
- **Source tests:** `src/v3_tests.rs`, `src/v3/tests/fixtures.rs`, `src/v3/tests/cases.rs`, existing `src/v2_tests.rs`, and `src/lib_tests.rs`.
- **Implementation/operating references:** [V3 protocol](../../../docs/modules/memory.federation/V3_PROTOCOL.md) and [module guide](../../../docs/modules/memory.federation/TECHNICAL.md).
- **Concrete transport:** `PinnedHttpsFederationTransportV3` is implemented. A product host supplies the kernel authority instance plus owner-approved peer enrollment snapshot; the federation module does not self-enroll peers or mint grants.
- **Remaining repository composition:** bind a named non-test upstream product caller to `ProductionFederationClientV3` only in the owning product-host package and record that callsite in the implementation map. This is a composition/activation fact, not a missing cryptographic or federation-core primitive.
- **Remaining external gates:** target-host execution/measurements, independent semantic/security review, operator acceptance, canary, promotion and release.
