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

> deterministic NDU / preference-utility source candidate with stochastic numerical building blocks.

The repository contains a deterministic policy-bound evaluator, bounded preference solver, recursive utility support, owner-local protocol binding, conditional covariance/backward-regression numerical support, and an owner-local projection journal. The stochastic/FBSDE material remains a separately qualified candidate design and numerical substrate; this page does not claim a production learned-FBSDE policy.

Preference fixed-point exhaustion is unavailable after the registered 64-iteration bound. A bounded solver may publish a successful local termination receipt only when it converges within that bound.

Staged hierarchy validation is identity-based: parent/child conflicts are determined from explicit subject and parent identities, while unrelated hierarchies may update in the same generation. Reusing one subject/generation for a different artifact is a conflict.

The owner-local projection journal is a durability reference. Reopen must replay the journal state machine, not only verify the hash chain; a correctly rehashed but semantically invalid selection or revocation is rejected. Revocation is scoped by objective and subject.

## Production closure is not established

The following remain separate gates and must stay false/not-established until evidence exists:

- authenticated production product caller;
- selected production writer/store for NDU preference and utility projections;
- deterministic migration and schema-open evidence;
- fsync/durability profile on the selected host;
- retention, deletion, backup, restore, and non-resurrection evidence;
- independent semantic/convergence acceptance;
- named-host capacity and recovery measurements;
- activation/canary/promotion/release authority;
- production stochastic coefficient/profile admission and independent FBSDE/convergence qualification.

The owner-local `NduProjectionJournalV1` must not be relabeled as the production writer merely because it has deterministic reopen and corruption checks.

## Qualification interpretation

The dedicated NDU workflow qualifies both source-head and synthetic-merge candidates for pull requests and is also able to execute on pushes to `main` and manual dispatch. This closes the previous trigger gap, but a workflow definition is not itself a qualification receipt.

`exactHeadSourceQualification` remains pending until the exact candidate/head named by the maturity claim has a passing workflow result. Do not promote that field merely because an older source base passed scoped tests or because the NDU source files were unchanged between two commits.

## Safe claim language

Use `source candidate`, `deterministic kernel candidate`, or `deterministic NDU + stochastic numerical building blocks` while the production composition and independent gates above remain open.

Do not use `production complete`, `fully activated NDU`, `production writer established`, or `learned FBSDE NDU complete` without the corresponding repository and external evidence.
