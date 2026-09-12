# Lane E version compatibility

This matrix is normative for source compatibility inside Lane E. It does not authorize migration, activation or release.

| Area | Historical form | Current additive form | Read rule | Write rule | Downgrade / rollback rule |
|---|---|---|---|---|---|
| Learning ledger events | V1 `LearningLedger` / `DurableLedger` frames | V2 causal validators | V1 remains readable with its original meaning | New causal facts use registered V2 types | Never relabel a V1 identity or opaque digest as authenticated V2 evidence |
| Frozen datasets | `DatasetSnapshotV1`, then `DatasetSnapshotV2` | `DatasetSnapshotReceiptV3` | V2 snapshots remain readable by compatible legacy callers | Cross-module publication uses V3 so every V2 digest-preimage field is retained | Rollback may expose V2 only to a caller explicitly registered for V2; no detached digest may satisfy a V3 consumer |
| Operator target builder | `train(TrainingRequest)` | `build_targets` | Both names retain identical target-builder behavior | New code calls `build_targets` | Neither name may be described as a neural trainer |
| Learned operator | V1 complete-grid tabular fit/predict | strict V2 fit and indexed predict | V1 artifacts remain inspectable | New qualification uses strict V2 evidence uniqueness and canonical indexed lookup | A strict V2 artifact may use V1 prediction only for compatibility testing, not to bypass strict admission |
| World model | V1 action-conditioned tabular model | unchanged | Exact supported pairs only | Predictions remain synthetic and deny-all | No version may convert prediction into independent factual outcome |
| Evaluation estimators | V1 point, cluster, sequential and temporal receipts | complete cross-fold and independent-decision composition | Historical receipts retain estimator and digest version | New claims bind estimand and complete plan/use receipts | A point estimate cannot be upgraded by reinterpretation into longitudinal evidence |
| Evidence identity | caller-constructed `AuthenticatedPrincipalV1` | `LearningEvidenceVerifierV1` and private `VerifiedLearningEvidenceV1` | Legacy validation remains structural, not cryptographic | External admission uses host-trusted Ed25519 keys and signed evaluation entry points | Replacing the verifier epoch invalidates previous trust bindings; reverify after revocation |
| Metric eligibility | V1 strict superiority for every metric | frozen V2 primary / noninferiority / absolute roles | V1 semantics remain unchanged | Register all roles and margins before holdout consumption; use matching V2 evaluator | V2 metric/plan digests cannot be interpreted with V1 gates or altered roles |
| Final holdout | in-memory `FinalHoldoutRegistry` | predecessor-bound `FinalHoldoutJournalV1` | Existing typed registry semantics remain readable | Product adapters persist/replay the journal and compare expected head | Restarting with an empty registry is not a valid rollback |
| Artifact registry | V1 create-only registry and pinned loader | V2 complete manifest and withdrawal state | V1 records remain readable under their original schema | Dataset-derived candidates use V2 provenance | V1 support digests cannot be reinterpreted as complete V2 lineage |
| Artifact admission | snapshot-local V2 withdrawal check | withdrawal-bound V3 admission | V2 validation remains available for legacy callers | Publication uses V3 and rechecks the same withdrawal head under the writer fence | A stale V3 admission or older backup marker cannot reactivate a withdrawn artifact |
| Registry-head evidence | V1 typed witness fields | unchanged | Validator checks binding, epoch, predecessor and time | Host authenticates signature before constructing the typed witness | An old self-consistent head is not proof of the newest head |
| Lifecycle | V1 transition validator | predecessor-bound lifecycle journal profile | Historical transition evidence remains interpretable | Product publication appends against current artifact state/head | Rollback is a new authorized transition; mandatory states cannot be skipped |

The signed evidence APIs are additive. Their presence does not establish that
all host callers have migrated, that a signature authenticates an estimate's
scientific validity, or that the system has demonstrated longitudinal learning.
See [evaluation admission](../../codex-rs/hepta-intelligence-eval/EVIDENCE_ADMISSION.md)
for the exact host boundary, claim limitations and capacity behavior.

## Canonical encoding policy

Every digest domain carries an explicit version. Lengths use checked big-endian integer encoding; IDs use exact UTF-8 bytes with a checked length prefix; digest values use 32 raw bytes; fixed-point values use the registered signed Q32 representation. A stored top-level digest is excluded from its own preimage unless a versioned schema explicitly says otherwise.

Golden vectors must be produced independently of the implementation under test. Adding a field requires a new digest domain or an explicitly registered backward-compatible envelope. Removing, reordering or changing the meaning of a bound field is never an in-place change.

## Mixed-version process rules

A process declares the exact contract versions it consumes and produces at startup. Unsupported pairs fail readiness rather than falling back implicitly. A generation change freezes existing run snapshots; new runs use the newly selected complete tuple. Current correction, revocation and withdrawal frontiers are overlaid before any historical artifact or backup becomes readable.
