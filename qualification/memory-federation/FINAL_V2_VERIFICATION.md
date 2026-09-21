# memory.federation V2 final verification

- branch: `fix/memory-federation-v2-closure-20260920`
- base main: `a74246c4d7657d4c6b09fc50c41f1d715ace5e0e`
- frozen candidate implementation head: `1644afc86fb50a572cd7d89d10a7d9a75c9f607f`
- frozen candidate implementation tree: `0c09497880937437dbc655b79e21f0015106ede3`
- status: `pending_exact_current_head_and_merge_candidate_execution`
- current main parent: `a74246c4d7657d4c6b09fc50c41f1d715ace5e0e`
- claim boundary: source/product-composition candidate only; `productionImplementation`, `productExecutionProved`, activation, independent acceptance, promotion and release remain false.

## Candidate boundary

The frozen candidate is the last non-metadata commit and includes the physical HTTP regression proving a rejecting final-use guard runs after provider-policy admission but before provider dispatch. Commits after it may modify only:

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
- concurrent bounded peer fan-out under one global horizon with deterministic post-aggregation ordering;
- explicit requested/completed/failed peers, peer truncation, owner-candidate omission, item truncation and typed discovery/deadline-authority/integrity/transport failure coverage;
- bounded fail-closed final model-input revalidation, with same-owner/capability bindings sharing one SQLite read snapshot under one total final-use deadline, a fresh post-batch wall-clock check that rejects capability expiry crossing or clock regression before provider transport entry, plus an HTTP-path regression proving a rejecting final-use guard prevents physical provider dispatch;
- final-use revocation semantics aligned to the repository-wide dispatch contract: the guard fences source currentness before transport entry but does not claim retroactive cancellation authority over an already admitted provider attempt;
- one-peer ownership in the canonical checked engine, with <=16-peer discovery/aggregation owned by the product orchestrator;
- documentation truth that the current V2 structs are in-process Rust contracts, not a registered authenticated cross-host wire protocol.
- local `observed_frontier` is an exact-scope append-only memory-revision count from the same retrieval snapshot, not an authenticated cut digest or rollback witness.

The module implementation map uses `sourceIdentityPolicy = candidate_or_exact_observation_v1`: its `sourceBase` and `observedAtHead` are the frozen current-main merge candidate above, and the declared federation source root must remain byte-unchanged through metadata-only receipt commits. The candidate tree is built from current main plus only the reviewed #935 file set; overlapping generated indexes, Cargo lock state and the implementation-map verifier were forward-ported before the merge.

## Required executable checks

The current PR head must pass `.github/workflows/memory-federation-v2-final-verify.yml` plus the normal exact-current-head and deterministic merge-candidate gates before `productExecutionProved` can change. The merge job resolves `origin/main` at execution time and must not use the PR object's frozen creation-time `base.sha` as current-main evidence.

Focused execution must cover:

- formatting;
- `codex-hepta-memory-federation` contract and adversarial/race tests;
- `codex-hepta-memory` product runtime and legacy-downgrade regression;
- Memory extension federation attachment, structured coverage propagation and physical-send revalidation;
- concurrent product peer orchestration plus peer-truncation/owner-omission regressions;
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

The current frozen candidate also removes the stale per-binding extension final-use path: direct federated proposals now delegate to the same batch revalidation helper used by combined proposals, so same-owner/capability bindings share one SQLite snapshot and the source compiles against the canonical `revalidate_many` surface. A subsequent security review found that the batch originally reused its start-time wall clock for the whole bounded operation; the candidate now samples the wall clock again after batch revalidation and rejects capability expiry crossing or clock regression before physical provider dispatch.

## Remaining repository-controlled observability gap

Product turn cancellation currently inherits the host's future-drop semantics: Core wraps turn-input contribution in the turn cancellation token and drops the federation future when cancellation wins, which drops in-flight authority/transport futures and prevents attachment. The canonical engine also supports `FederationStopReasonV2::Cancelled`, but the product caller does not currently attribute that outer drop to an observable canonical cancellation receipt. This gap does not authorize post-cancel attachment or retry; it remains explicit until a product-level receipt path is wired without making the generic extension API tokio-specific.
