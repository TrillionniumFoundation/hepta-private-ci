# channel.matrix convergence checkpoint — 2026-09-25

Status: **DRAFT / NOT QUALIFIED / DO NOT MERGE OR ACTIVATE**.

This checkpoint preserves the Matrix-only recovery stage of the user-authorized five-step convergence. It is not a completion receipt and is not a substitute for the canonical module guide, implementation map or qualification workflow.

## Exact source provenance

- Current integration baseline: `7ddbfac88525196e7a4b31387ceae194958275f5`, tree `d478d12adc75dd58a2814d45e804662d9ea2d0c2`.
- Historical #938 base: `331b81d385a88837e252bd80fda8b8ac35ea4191`.
- Historical #938 head: `ceaf0266a384543ab978d9ceedd84300abc85eef`.
- Local Git comparison found no changes between the historical base and the integration baseline in the four Matrix crates. The scoped base-to-#938 patch applied cleanly to the integration baseline: 23 files, 4,349 insertions and 571 deletions.
- This recovery commit copies only those four Matrix subtrees. It does not restore the historical workspace, contracts, lockfiles, unrelated module implementations, global documentation or workflow configuration.
- Historical test results do not qualify this new candidate. The actual candidate SHA is the commit containing this checkpoint; record validation against that immutable SHA, not the mutable branch name.

## Recovered source, not accepted execution

| Requirement | Recovered implementation | Recovered test sources | Current claim |
|---|---|---|---|
| One durable Matrix terminal owner | `hepta-matrix-store/src/dispatch.rs`; migration `0006_matrix_dispatch_ledger.sql` | `hepta-matrix-store/tests/sync_mutation_v2.rs` | Source restored; not qualified on current dependencies |
| Per-attempt signed final-use request | `hepta-matrix-sdk/src/authority.rs`; `hepta-matrixd/src/final_use.rs` | `hepta-matrix-sdk/tests/durable_transport.rs` | Requires current kernel API adaptation and boundary hardening |
| Stable transaction and uncertain outcomes | `hepta-matrix-sdk/src/outbound.rs`; durable dispatch observations | `pre_io_crash_cuts_never_cross_network_and_retry_uses_fresh_grant` and transport tests | Source restored; remaining false-terminal and identity cases below |
| Real daemon composition | `hepta-matrixd/src/runner.rs` constructs the grant broker and supplies it to the outbox sender | `hepta-matrixd/tests/real_synapse_e2e.rs` | Source callsite restored, not a successful daemon/E2EE run |
| Qualified versus unqualified observation | SDK sync composer and store dispatch reconciliation | `qualified_success_requires_matching_durable_final_use_claim`, legacy and retry tests | Raw claim metadata still needs non-forgeable verification binding |

All crate-relative paths in this table are under `codex-rs/`.

## Blocking work remaining on this same candidate

1. Replace historical `with_verified_use_at_frontier` calls with the current kernel API without weakening revocation or expiry checks. The current main contract does not expose this historical method. Do not restore old shared contracts over newer owners merely to make the call compile.
2. Require an opaque, non-cloneable permit at the physical SDK send entry and remove any raw-client escape that bypasses it. Persist the claim before network contact, but keep the kernel token unentered until after asynchronous persistence; refresh trusted revocations and validate at actual adapter polling.
3. Sign the complete canonical Matrix event content, including replacement target and event semantics, not only raw message text. Recheck authenticated homeserver/user/device/session, room, revision, attempt and actual payload at send entry. Reject or quarantine scope changes across recovery rather than reusing a transaction in a different idempotency domain.
4. Bind durable authority claims to a genuine kernel-verified token. Caller-filled strings must not certify `Succeeded`. Preserve old remotely observed effects as unqualified when the necessary proof is absent. A claim committed before the first network poll is not, on its own, proof that network entry occurred.
5. Preserve prior uncertainty if a later retry is rejected: a lost response with no accepted event ID cannot become proven failure merely because a later attempt fails. Reconcile immutable terminal observations without reopening them.
6. Validate migrations and required database objects on startup; cover exact replay, missing proof, identity drift, acknowledgement loss, rollback/restore, observation commit failure, process loss, and more than 4,096 lifetime completed sends. Capacity is active/unresolved work, while retained anti-replay evidence needs an explicit bounded storage/retention policy.
7. Adapt all existing callers and test fixtures, refresh Cargo/Bazel dependency lockfiles and module source mappings, run strict lint, focused tests, actual daemon/Synapse qualification, and applicable exact-head plus deterministic merge-candidate checks. Do not weaken or bypass the gates.

## Execution evidence boundary

A local continuation began API hardening and build preparation, but the authorized build host stopped responding, including to small read and ping requests. No candidate build or test completion was obtained. The API-hardening edits are **uncommitted, unfinished local work** and are deliberately not represented by this recovery checkpoint. They require reconciliation with this checkpoint before any later commit; preserve them rather than overwriting the worktree.

No new Rust pass receipt, strict lint result, real Synapse result, merge-candidate result or independent review is claimed. The six observer tests and three review probes from the earlier mainline audit concern the old mainline component, not this candidate. They must not be reused as candidate qualification.

`productionImplementation`, product execution proof, deployment qualification, independent acceptance, activation and release remain **false / not established**. This draft preserves progress and the unresolved acceptance boundary only.
