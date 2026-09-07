# learning.ledger: implementation design

Parent: `docs/modules/learning.ledger/TECHNICAL.md`. Lane: `LANE-E-LEARNING`.
Status: specified target, not implemented or independently accepted. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-learning-ledger`.
Packages: `LRN-0-CAUSAL-LEARNING-CONTRACTS`, `LRN-1-DURABLE-EPISODE-LEDGER`.

Operation signatures below are design contracts, not assertions of existing native symbols. Bind each to an existing or planned symbol and consumer inside the owner envelope. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`append_decision(run_snapshot, legal_set, assignment, expected_anchor) -> DecisionCommit`; `append_outcome(decision, authenticated_observer, watermark) -> OutcomeCommit`; `append_correction_or_revoke(source, cutoff) -> LineageCommit`; `freeze_dataset(plan, eligible_frontier) -> DatasetSnapshotV1`. Use the existing DurableLedger/native admission and anchored recovery surfaces; do not create a parallel Python product ledger.

## 3. State records and transaction design

Own learning_episode_ledger, learning_credit_ledger and learning_unlearning_lineage. Decision rows bind principal/episode/boundary, objective/artifact/model/body, full generator-relative legal candidates, chosen action, propensity and delivery. Outcome rows bind independent observer, exact action, reward units, delay/watermark and correction predecessor. Credit rows conserve terminal outcome; lineage rows track source->dataset->artifact revocation. Large payloads remain outside general receipts.

## 4. Deterministic algorithm and scheduling

Host authenticates observer/scope/handles; validate and prepare; predecessor CAS; encode canonical frame; sync; publish core state; persist an independent acknowledgement witness; then acknowledge externally. A retry after sync must use the original ID/predecessor/digest. Failed anchored recovery cannot retry unanchored. Unknown outcome stays pending/censored, never zero reward. Physical erasure and model unlearning are distinct from logical exclusion.

## 5. Capacity and performance profile

Pilot <=128 candidates, <=4096 episode events, <=256 KiB row and bounded record/segment sizes as enforced by native storage. Rotation is a separately tested migration. Measure sync, reopened-history validation, correction/revocation traversal, storage growth and pending watermark age.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- LEDGER-01: acknowledgement loss reconciles the committed event from its original identity and anchor.
- LEDGER-02: truncating acknowledged history fails anchored recovery.
- LEDGER-03: generator posing as an independent observer is rejected by real host authentication, not string comparison.
- LEDGER-04: delayed/corrected outcomes and revoked ancestry change dataset eligibility without rewriting history.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

Compose native DurableLedger, dataset and artifact consumers in C1. Future-time labels generated inside one fixture do not qualify longitudinal efficacy. Rollback restores compatible formats and current revoke cutoffs; it never drops a durable acknowledgement frontier.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.
