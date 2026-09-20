# `learning.ledger` native implementation mapping

This file maps the stable module guide and implementation dossier to concrete
Rust symbols. It does not grant a production writer, authenticate a real
credential issuer or prove future outcomes.

## Compatibility and state ownership

The existing V1 `LearningLedger` and `DurableLedger` event/chain encoding is
unchanged and remains readable. The additive `causal_v2` layer represents facts
that V1 cannot safely compress into a plain identity or opaque support digest.
No automatic V1-to-V2 reinterpretation is permitted.

Owned logical domains remain:

- causal decision and episode facts;
- independently observed outcome facts;
- conserved credit facts;
- correction and revocation lineage;
- immutable dataset-freeze receipts.

The pure core has no ambient I/O. `DurableLedger` writes only through a
host-supplied file capability and the host remains responsible for trusted path
opening, directory durability, writer fencing and publication of an independent
anchor.

## Design operation to Rust symbol

| Design operation | Native symbol | Source | Status |
|---|---|---|---|
| append a validated V1 event | `LearningLedger::append` | `src/ledger.rs` | retained |
| durable append and anchored reopen | `DurableLedger`, `LedgerAnchor`, `LedgerRecovery` | `src/durable.rs` | retained |
| map a deny-all intuition decision | `prepare_shadow_decision`, `append_shadow_decision` | `src/shadow.rs` | implemented |
| authenticate generator/observer separation | `verify_independent_roles` | `src/causal_v2.rs` | implemented |
| validate delayed/corrected outcome | `validate_authenticated_outcome` | `src/causal_v2.rs` | implemented |
| prove generator-relative candidate completeness | `validate_candidate_set_completeness` | `src/causal_v2.rs` | implemented |
| finalize conserved credit | `finalize_credit_batch` | `src/causal_v2.rs` | implemented |
| freeze immutable dataset | `freeze_dataset` | `src/causal_v2.rs` | implemented |

The V2 identity check compares principal ID, credential-chain digest and
signing-key digest, and validates authority epoch and expiry. It is stronger
than string inequality but is not a cryptographic verifier: a product host must
supply receipts already authenticated against the current trust root.

`OutcomeWatermarkV1` distinguishes pending, censored and terminal observations.
Terminal records require an observed value and finalization time; censored
records require a censoring reason and carry no invented value. Corrections bind
a predecessor.

`CreditAllocationBatchV1` is the publication unit for causal credit. Allocation
rows are sorted and deduplicated, and `sum(allocations) + residual` must equal
the terminal outcome exactly in raw Q32 units before a receipt is emitted.

`DatasetSnapshotV2` binds the exact ledger head, eligible frontier, outcome
watermark, correction cut, revocation cut, inclusion policy and canonical source
record digest set. It carries pending and censored counts and has `DENY_ALL`
authority.

## Host and caller obligations

A product integration receipt must name all of the following:

1. the process and callsite invoking each operation;
2. the current credential/trust-root verifier;
3. the exclusive writer fence and durable file/store identity;
4. the source of independent terminal observations;
5. the acknowledgement witness retained outside the ledger file;
6. the revocation and correction frontier used for dataset freeze;
7. target-host latency, storage-growth and crash/reopen measurements;
8. the exact commit, tree, binary and configuration generation.

A test caller or source-path inventory is not a production caller. A different
`StableId` without credential and signing-key separation is not independent.

## Failure and retry rules

- semantic identity reuse with changed content conflicts;
- missing/stale authentication fails before a causal receipt is emitted;
- acknowledgement loss retries the original identity and semantic digest;
- pending or censored outcomes never become zero reward;
- a failed anchored reopen never silently retries unanchored;
- dataset source digests are sorted and duplicate source records reject;
- every exported V2 receipt remains deny-all and cannot select or activate an
  artifact.

## Qualification mapping

Focused tests live in:

- `src/durable_tests.rs`;
- `src/causal_v2_tests.rs`;
- `src/shadow_tests.rs`.

Cross-crate composition is exercised by
`../hepta-shadow-qualification/src/lane_e_closure_tests.rs`. Exact dossier IDs,
test functions and CI jobs are registered in
`../../qualification/lane-e/TEST_TRACEABILITY.json`.
