# utility.ndu status and claim boundary

This page is the short interpretation guide for the status fields used by the `utility.ndu` documentation set. It does not grant activation, effect authority, production acceptance, promotion, signing, or release authority.

## Status axes are intentionally independent

`docs/modules/utility.ndu/TECHNICAL.md` contains canonical work-package execution envelopes such as `NDU-0`, `NDU-1`, and `NDU-2`. Their `State: planned` values describe the lifecycle of those canonical packages and their predecessor/evidence envelopes. They are not a statement that no source has been implemented.

`docs/modules/utility.ndu/IMPLEMENTATION_MAP.json` records native source bindings and source-candidate maturity. A value such as `candidate_implemented` means that the bounded source candidate exists and is mapped to tests; it does not establish a product caller, production writer, independent acceptance, activation, or release.

`docs/readiness/LANE_D_MATURITY.json` is the cross-module maturity view. Its dimensions are independent. In particular, source materialization and deterministic-kernel maturity must not be read as production composition or release readiness.

When these files are read together, use the following interpretation:

1. work-package lifecycle answers which canonical delivery envelope is planned/active/completed;
2. implementation-map state answers which bounded source operations exist in the candidate;
3. Lane-D maturity answers which qualification, composition, activation, and release gates are established.

## Current bounded capability

The accurate capability description is:

> deterministic NDU / preference-utility candidate with a named Agentd local-deterministic writer entry and stochastic numerical building blocks.

The repository contains a deterministic policy-bound evaluator, bounded preference solver, recursive utility support, owner-local protocol binding, conditional covariance/backward-regression numerical support, semantic projection journal, crash-bounded `NduProjectionStoreV1` durable-writer source candidate, and explicit original/whitened Z-coordinate to signed-Q24 conversion evidence. A real request-local read-only call chain is established through Agentd and Control. The stochastic/FBSDE material remains a separately qualified candidate design and numerical substrate; this page does not claim a production learned-FBSDE policy.

Preference fixed-point exhaustion is unavailable after the registered 64-iteration bound. A bounded solver may publish a successful local termination receipt only when it converges within that bound. For a run that emits iterations, `maximum_residual_raw` is the maximum over those emitted iteration receipts and does not silently mix in the pre-iteration residual; a zero-iteration no-op reports its validated initial residual as both terminal and maximum.

Staged hierarchy validation is identity-based: parent/child conflicts are determined from explicit subject and parent identities, while unrelated hierarchies may update in the same generation. Reusing one subject/generation for a different artifact is a conflict.

The owner-local projection journal is a durability reference. Reopen must replay the journal state machine, not only verify the hash chain; a correctly rehashed but semantically invalid selection or revocation is rejected. Selection replacement requires the exact currently selected predecessor, and the authenticated owner binds that predecessor into the final-use grant payload. Revocation is scoped by objective and subject. Non-revocation history reserves enough capacity to revoke every live projection, while oversized persistent images are rejected before unbounded allocation or read.

`sourceBase`, `sourceObjects` and `currentSourceEvidence` identify the exact source candidate and mapped objects described by the implementation map. They are regenerated when mapped source changes; none of them substitutes for a passing exact-head and synthetic-merge qualification receipt.

## Named process composition and its limits

The canonical follow-up remains PR #997 (`codex/utility-ndu-deterministic-closure`). The temporary patch-application workflow and staged Python parts have been replaced with reviewed source in that same candidate; they are not a second implementation or release path.

Normal Agentd accepts `--ndu-bootstrap-descriptor` together with `--ndu-bootstrap-descriptor-digest`. `load_ndu_process_bootstrap_v1` checks the descriptor digest, registered Agent identity, private owner paths, bounded frozen policy and independent issuer/revocation keys. `AgentdNduOwnerHostV1` is attached during normal startup and exposes `utility.ndu.control` on the existing owner-private control socket. No new network listener or signing key is created.

The explicit `local-deterministic` profile consumes a freshly authenticated signed revocation file for every control operation. It persists one owner/policy binding under the writer lock, and rejects silent adoption of an unbound historical store. Generation changes may recover the same stable owner/policy; substituting the principal, policy or configured trust fails closed. Product preparation and mutation bind the complete committed journal head as well as the selected-content predecessor. This closes ABA races; the older content-only local API does not claim that stronger property. A lost response is reconciled through the historical `Outcome` query, which is not fresh-use authorization and never blindly replays a mutation.

`ndu_process_e2e` is the normal-binary/UDS/real-filesystem regression for signed writes, one writer, discarded acknowledgement, ABA rejection, live grant revocation, projection revocation and kill/restart recovery. Existence of this test is not a passing receipt. Current exact-candidate execution must be checked in retained suite logs.

This local profile deliberately does **not** assert a protected authority clock or an independent off-host anti-rollback frontier. A descriptor asking for another trust profile is rejected rather than silently downgraded. Production enrollment, external trust composition and operator activation remain open.

## Production closure is not established

The following remain separate gates and must stay false/not-established until evidence exists:

- authenticated production NDU owner/caller beyond the established request-local read-only caller;
- governed selection and activation of the `NduProjectionStoreV1` writer candidate on the target host;
- target-host filesystem/fsync/directory-durability and recovery qualification;
- explicit future-schema migration policy (V1 is the initial on-disk schema and rejects unknown/corrupt images rather than silently migrating them);
- production retention/deletion, encrypted off-host backup transport, restore drills, monitoring and independent anti-rollback/non-resurrection evidence;
- independent semantic/convergence acceptance;
- named-host capacity and recovery measurements;
- activation/canary/promotion/release authority;
- production stochastic coefficient/profile admission and independent FBSDE/convergence qualification.

`NduProjectionJournalV1` is the semantic journal and `NduProjectionStoreV1` is now a durable-writer **source candidate**. Neither may be relabeled as the selected/activated production writer merely because the source implements deterministic reopen, locking, sync/rename, indeterminate fencing and monotonic restore.

## Qualification interpretation

The dedicated NDU workflow independently executes source checks, core tests, Control callers, normal Agentd product tests, strict lint and host qualification for both source-head and deterministic synthetic-merge candidates. It runs on relevant pushes to `main` and manual dispatch. One red suite cannot suppress execution of the others; both aggregate NDU gates require every suite to pass. A workflow definition is not itself a qualification receipt. The runner retains command lines, exit codes, log hashes, SHA/tree/parents, host/kernel and source-cleanliness checks.

`exactHeadSourceQualification` remains pending until the exact candidate/head named by the maturity claim has a passing workflow result. Do not promote that field merely because an older source base passed scoped tests or because the NDU source files were unchanged between two commits.

## Safe claim language

Use `source candidate`, `deterministic kernel candidate`, `durable-writer source candidate`, or `deterministic NDU + stochastic numerical building blocks` while authenticated production composition, writer selection/activation and independent stochastic gates above remain open.

Do not use `production complete`, `fully activated NDU`, `production writer established`, or `learned FBSDE NDU complete` without the corresponding repository and external evidence.
