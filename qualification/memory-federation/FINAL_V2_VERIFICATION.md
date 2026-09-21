# memory.federation V2 final verification

- branch: `fix/memory-federation-v2-closure-20260920`
- base main: `331b81d385a88837e252bd80fda8b8ac35ea4191`
- frozen candidate implementation head: `8d582460929283a89d7d93809ed82ae44d32ae1f`
- frozen candidate implementation tree: `c0dc897bc9114be5526578e2ce925376389461e3`
- status: `pending_exact_current_head_and_merge_candidate_execution`
- claim boundary: source/product-composition candidate only; `productionImplementation`, `productExecutionProved`, activation, independent acceptance, promotion and release remain false.

## Candidate boundary

The frozen candidate is the last non-metadata commit. Commits after it may modify only:

- `docs/modules/memory.federation/IMPLEMENTATION_MAP.json`
- `qualification/memory-federation/FINAL_V2_VERIFICATION.md`

Any later change to code, tests, product composition, technical documentation, dossier/profile truth, Cargo state or derived document indexes invalidates this receipt and requires a new candidate head/tree.

The candidate establishes the following source-level properties without promoting them to executed qualification. The canonical implementation profile intentionally remains `specified_not_product_evidence`, as required by the closed-world profile validator:

- exact query-bound and domain-separated remote response digest verification;
- prefix-sensitive evidence ordering for bounded selection;
- `Partial + []` preservation;
- live capability/revocation/generation observation before dispatch and after I/O;
- result lifetime bounded by response, lease, query and live-authority horizons;
- interruptible single-attempt async transport with no engine-owned retry;
- exact-scope owner data frontier acquired from the same SQLite snapshot as candidates;
- Agentd composition through `CognitiveRuntime::AvailableFederatedV2`;
- V2-only product retrieval/revalidation APIs and a regression preventing `with_federation()` from downgrading an already-composed V2 runtime;
- explicit requested/completed/failed/truncated aggregate coverage;
- bounded fail-closed final model-input revalidation, with same-owner/capability bindings sharing one SQLite read snapshot under one total final-use deadline;
- one-peer ownership in the canonical checked engine, with <=16-peer discovery/aggregation owned by the product orchestrator;
- documentation truth that the current V2 structs are in-process Rust contracts, not a registered authenticated cross-host wire protocol.
- local `observed_frontier` is an exact-scope append-only memory-revision count from the same retrieval snapshot, not an authenticated cut digest or rollback witness.

## Required executable checks

The current PR head must pass `.github/workflows/memory-federation-v2-final-verify.yml` plus the normal exact-current-head and deterministic merge-candidate gates before `productExecutionProved` can change.

Focused execution must cover:

- formatting;
- `codex-hepta-memory-federation` contract and adversarial/race tests;
- `codex-hepta-memory` product runtime and legacy-downgrade regression;
- Memory extension federation attachment and physical-send revalidation;
- Agentd product composition;
- implementation-map/source-attestation verification;
- all-target compilation and strict Clippy;
- clean tracked-source/diff checks.

A queued workflow, source presence, test source identity, or a PASS on an older commit is not acceptance evidence for this candidate.

## External gates

This receipt does not satisfy or waive:

- independent semantic/security review;
- authenticated cross-process or multi-host peer transport;
- remote peer identity, credential/grant binding and coherent remote data-frontier evidence;
- two-real-host fault E2E;
- target-host capacity/latency/backpressure qualification;
- operator acceptance, canary, promotion or release.

The current product composition remains the existing in-process/read-only owner-store path. A response digest proves integrity of the bound response fields; it does not authenticate a remote host identity.

## Historical note

The earlier `fix/memory-federation-v2-hardening-final` receipt was a failing development receipt, not acceptance evidence. Its actionable federation-local failures (authority-horizon fixture inconsistency, missing extension test import, and strict Clippy enum-size lint) were repaired before this frozen candidate.

This candidate additionally closes a compatibility split-brain edge found during security review: the legacy `with_federation()` helper now preserves `AvailableFederatedV2` rather than replacing it with `AvailableFederated`. The canonical V2 product APIs still reject the legacy variant.

The current frozen candidate also removes the stale per-binding extension final-use path: direct federated proposals now delegate to the same batch revalidation helper used by combined proposals, so same-owner/capability bindings share one SQLite snapshot and the source compiles against the canonical `revalidate_many` surface.
