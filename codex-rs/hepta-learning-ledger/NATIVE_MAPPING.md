# `learning.ledger` native implementation mapping

This file maps the stable module guide and implementation dossier to concrete
Rust symbols. It does not grant a deployed production writer, authenticate a real
credential issuer, prove physical erasure or prove future outcomes.

## Compatibility and state ownership

The existing V1 `LearningLedger` / `DurableLedger` event domain and tags `0..=3`
are unchanged and remain readable. The additive V2 durable records use tags
`4..=6`; no V1 record is automatically reinterpreted as V2. A binary that does
not understand the additive tags must not open a journal after V2 facts have been
acknowledged.

Owned logical domains remain:

- causal decision and episode facts;
- independently observed outcome facts;
- conserved credit facts;
- correction and revocation lineage;
- immutable dataset-freeze receipts.

The pure core has no ambient I/O. `DurableLedger` and `SegmentedLedger` write only
through host-supplied file capabilities. `ProductionLearningLedger` is the
repository-owned authenticated composition gate; the host still owns trusted path
opening, directory durability, product enrollment and physical writer exclusivity.

## Design operation to Rust symbol

| Design operation | Native symbol | Source | Status |
|---|---|---|---|
| append a validated V1 event | `LearningLedger::append` | `src/ledger.rs` | retained |
| durable append and anchored reopen | `DurableLedger`, `LedgerAnchor`, `LedgerRecovery` | `src/durable.rs` | retained |
| segmented durable append/rotation | `SegmentedLedger` | `src/segments.rs` | retained |
| map a deny-all intuition decision | `prepare_shadow_decision`, `append_shadow_decision` | `src/shadow.rs` | implemented |
| authenticate generator/observer separation | `verify_independent_roles` | `src/causal_v2.rs` | implemented |
| validate delayed/corrected outcome | `validate_authenticated_outcome` | `src/causal_v2.rs` | implemented |
| prove generator-relative candidate completeness | `validate_candidate_set_completeness` | `src/causal_v2.rs` | implemented |
| finalize conserved credit | `finalize_credit_batch` | `src/causal_v2.rs` | implemented |
| freeze immutable dataset receipt | `freeze_dataset`, `freeze_dataset_receipt_v3` | `src/causal_v2.rs`, `src/dataset_receipt_v3.rs` | implemented |
| authenticated durable decision/outcome/credit path | `ProductionLearningLedger` | `src/production.rs` | source implemented, product binding pending |
| durable acknowledgement witness mechanics | `FileLearningWitnessStore` | `src/witness.rs` | source implemented, administrative independence pending |
| ledger-derived dataset membership and cuts | `ProductionLearningLedger::freeze_dataset` | `src/production.rs` | source implemented, live product evidence pending |

## Authenticated durable V2 records

`AuthenticatedDecisionRecordV2`, `AuthenticatedOutcomeRecordV2` and
`ConservedCreditBatchRecordV2` live in the same causal hash chain as retained V1
records. Recovery decodes and replay-validates them before exposing state.

The decision record carries the authenticated generator identity and complete
candidate receipt. The outcome record retains delayed/censored/terminal state and
correction predecessor. The credit record contains the entire finalized
allocation batch plus its independently recomputable conservation digest, so a
production V2 credit publication is one durable event rather than a partially
acknowledged sequence of target rows.

The V2 identity checks compare principal ID, credential-chain digest and signing
key digest, with authority epoch/validity checks. Product admission additionally
uses `LearningEvidenceVerifierV1` for Ed25519 verification against host-owned
trust state and compares controller identities for role separation.

## Production commit and witness order

`ProductionLearningLedger` requires the journal head and witness frontier to
match at construction. Each new mutation must name the witnessed predecessor,
then follows:

1. signed evidence verification and causal validation;
2. durable journal append and `sync_all`;
3. independent `LedgerAnchor` witness persistence and `sync_all`;
4. external acknowledgement.

If journal durability succeeds but witness persistence is uncertain, the operation
is not acknowledged and later mutations cannot step over the unwitnessed tail.
Recovery must reconcile that exact durable suffix.

`FileLearningWitnessStore` supplies concrete `HEPTLW01` append-only witness
mechanics with chained frame digests, monotonic sequence, idempotent exact replay,
gap/regression rejection and partial-tail recovery. A deployment must still place
this witness on a separately governed rollback/durability path; source code cannot
self-prove administrative independence.

## Conserved credit and ledger-derived freeze

The safe production path does not expose V2 causal credit as a series of ordinary
legacy `CreditAssignment` calls. It verifies `CreditAllocationBatchV1`, binds the
allocator/evaluator signature, requires a durable terminal outcome with the exact
same value and writes the bounded batch atomically. The durable batch profile is
capped at 224 allocations to remain inside the existing 32 KiB event frame.

`ProductionLearningLedger::freeze_dataset` does not trust caller-provided record
membership or lineage counters. It takes a signed exact frontier/head, replays
that prefix, derives active objective-bound records, excludes revoked causal
descendants, supersedes corrected predecessor outcomes and tied credits, derives
correction/revocation cut digests plus pending/censored counts, then emits the
self-verifying V3 receipt.

## Host and caller obligations

A product integration receipt must name all of the following:

1. the deployed process and exact callsite invoking `ProductionLearningLedger`;
2. the current credential/trust-root source and authority generation;
3. the exclusive writer fence plus ledger/segment directory identity;
4. the independently governed witness store/controller;
5. the source of independent terminal observations;
6. the backup/restore and revocation/correction recovery procedure;
7. target-host latency, storage-growth, process-kill and physical power-loss evidence;
8. the exact commit, tree, binary and configuration generation.

A test caller, shadow caller or source-path inventory is not a production caller.
A separate file on the same rollback domain is not by itself evidence of an
independent witness.

## Failure and retry rules

- semantic identity reuse with changed content conflicts;
- missing/stale authentication fails before a production causal write;
- production signing payloads bind the expected durable predecessor;
- acknowledgement loss retains and reconciles the original durable identity;
- a failed anchored reopen never silently retries unanchored;
- pending or censored outcomes never become zero reward;
- correction predecessors must exist in the same episode;
- conserved V2 credit is atomic and must match the durable terminal outcome;
- ledger-derived dataset source digests are canonical and duplicate-free;
- every exported causal receipt remains deny-all and cannot select, activate,
  promote or release an artifact.

## Qualification mapping

Focused tests live in:

- `src/durable_tests.rs`;
- `src/causal_v2_tests.rs`;
- `src/signed_evidence_tests.rs`;
- `src/witness_tests.rs`;
- `src/production_tests.rs`;
- `src/shadow_tests.rs`.

Cross-crate composition remains exercised by
`../hepta-shadow-qualification/src/lane_e_closure_tests.rs`. Exact dossier IDs,
test functions and CI jobs are registered in
`../../qualification/lane-e/TEST_TRACEABILITY.json`.

See [`PRODUCTION.md`](PRODUCTION.md) for the commit order, witness trust boundary,
dataset derivation policy and explicit external non-claims.
