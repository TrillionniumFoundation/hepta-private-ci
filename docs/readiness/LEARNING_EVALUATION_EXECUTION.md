# Causal and longitudinal evaluation execution specification

**Overlay:** `HEPTA-V8-PRECODING-READINESS` v8.2.0-readiness
**Bound modules:** `learning.ledger`, `learning.eval`, `learning.artifacts`, `learning.operator`, `learning.plasticity`, `kernel.evidence`

## 1. Scope and authority boundary

This document defines the executable separation between experience recording, candidate generation, evaluation, selection and promotion. A policy cannot write its own terminal outcome, issue the sole evaluation receipt or select the artifact it generated. Memory persistence, offline loss and replay accuracy are not longitudinal learning.

`learning.ledger` owns immutable decisions and outcomes, `learning.eval` owns analysis, `learning.artifacts` owns candidate bytes and lineage, and `kernel.evidence` verifies identity separation. All modules retain zero production selection, merge, promotion and release authority.

## 2. Preregistered evaluation plan

Before candidate outcomes are inspected, `EvaluationPlanV1` freezes objective class, candidate, baseline, estimators, clipping policy, future windows, retention slices, multiplicity correction, minimum samples and decision thresholds. Any semantic change creates a new plan and invalidates prior partial results.

The plan names the unit of analysis, cluster unit, terminal outcome definition, delayed-outcome distribution, censoring rule, support floor, subgroup privacy rule and sequential-monitoring boundary. Exploratory analyses are labeled and cannot issue an acceptance decision.

## 3. Candidate support and propensity integrity

Every adaptive decision records the generator-relative complete legal candidate set, canonical order, chosen item, behavior propensity, random stream and omitted-count bound. Truncation happens deterministically before assignment. The chosen propensity must be positive and probabilities sum to one within one fixed-point unit.

Evaluation computes support intersection, effective sample size, maximum importance weight and subgroup coverage before efficacy. Unsupported rows are not repaired by a learned model. Weight clipping is preregistered and both clipped and unclipped diagnostics are published.

## 4. Delayed outcomes and independent observation

The effect owner or trusted observer emits terminal outcomes. Dispatch acknowledgement, model confidence and policy self-report are non-terminal. Each episode carries an outcome watermark with latest observable time, expected delay, terminality and censoring reason. Missing outcome is censored or pending, never zero reward.

Corrections append superseding receipts. Identity separation is verified through `EvaluatorIndependenceReceiptV1`; shared principal, credential chain or signing key across generator and evaluator is a role collision.

## 5. Estimation, confidence and multiplicity

The mandatory baseline evaluator computes IPS, SNIPS and cross-fitted doubly robust estimates in deterministic order. Outcome models use episode-, principal- and future-window separation. Confidence intervals cluster repeated decisions and use preregistered counter-based bootstrap or conservative exact intervals.

Multiple objectives, prompt factors, timing arms, models and subgroups use declared correction. A candidate passes efficacy only when its lower confidence bound exceeds the baseline upper bound and every safety, support, privacy, resource and retention floor passes. An average cannot compensate for a protected-slice failure.

## 6. Future windows and retention

Longitudinal evidence requires at least three independently identified snapshots across at least two future calendar windows. Training and validation never share an episode or principal lineage. Change points split windows rather than being averaged away.

`RetentionSliceReceiptV1` reports baseline, candidate, relative regression, confidence and sample count for old tasks, objective classes, devices, locales and privacy-approved groups. Default maximum regression is `2%` per registered slice; profiles may be stricter.

## 7. Unlearning and non-resurrection

Deletion traverses source rows, projections, candidate caches, replay, datasets, checkpoints, prompt graphs, sensor cores when derived, artifacts, evaluations and backups. A successor artifact is rebuilt without revoked rows or the predecessor is revoked. Restore rehearsals must produce zero deleted or derived records.

The unlearning receipt binds source tombstone, affected lineage, rebuild/revocation decisions, cache invalidation, backup results and independent evaluator. A stale artifact or projection cannot be selected after the cutoff.

## 8. State machine and failure taxonomy

```text
planned -> collecting -> watermark_pending -> analyzable
        -> evaluated -> independently_reviewed -> accepted_candidate
        -> insufficient_evidence | rejected | quarantined | revoked
```

Hard failures include missing candidate set, zero propensity, support breach, unresolved correction, evaluator collision, future leakage, stale artifact, undeclared censoring, multiplicity drift, deletion resurrection and altered analysis plan. The fallback is `insufficient_evidence` or the deterministic baseline, never assumed safety.

## 9. Performance envelope

Evaluation is streaming `O(n*k)` with candidate count `<=128`, episode events `<=4096`, batch rows `<=1,000,000`, row bytes `<=256 KiB` and bounded bootstrap replicates. Resource, incomplete-row and censoring counts accompany every result. No evaluation job may starve foreground operation or hold an unbounded in-memory episode set.

## 10. Golden fixtures and tests

The canonical OPE fixture retains exact IPS, SNIPS, DR and ESS outputs. Additional fixtures cover zero support, extreme weights, candidate-order permutation, delayed watermark, corrected outcome, role collision, cross-fit leakage, future-window leakage, retention failure, subgroup suppression and restored deleted data.

Property tests enforce immutable plans, chosen membership, probability normalization, deterministic estimates, credit conservation, no evaluator authority, exact artifact lineage and rollback equivalence. Fault tests kill the process between each ledger append, index update and evaluation publication.

## 11. Implementation sequence

Implement append-only decision/outcome protocols, plan freezing, candidate/support validation, deterministic OPE, watermarks and corrections, immutable datasets, cross-fitting, confidence/multiplicity, future windows, retention slices, unlearning, artifact reload and independent decision adapters. Learned outcome models are optional and follow the tabular/linear baseline.

## 12. Coding-entry checklist

Coding may start when evaluation plan, independence and retention protocols compile, ledger writers are exclusive, outcome observers are named, all estimators have scalar or tabular oracles, future splits are deterministic, deletion lineage is complete, and no package grants selection, promotion or release authority.

## Appendix A. Closed gap and protocol mapping

This appendix is a closed-world traceability projection. Each identifier is normative in `READINESS.json`, `PROTOCOLS.json` or `GAPS.json`; this Markdown file does not redefine the registry record.

Protocols:

- `EvaluationPlanV1`
- `EvaluatorIndependenceReceiptV1`
- `RetentionSliceReceiptV1`

Closed documentation gaps:

- `RDY-GAP-LRN-001`
- `RDY-GAP-LRN-002`
- `RDY-GAP-LRN-003`
- `RDY-GAP-LRN-004`
- `RDY-GAP-LRN-005`
- `RDY-GAP-LRN-006`
- `RDY-GAP-LRN-007`

Bound work packages:

- `ART-1-LEARNING-ARTIFACT-REGISTRY`
- `ART-2-NEXT-SNAPSHOT-RELOAD-ROLLBACK`
- `BIO-2-REPLAY-CONSOLIDATION`
- `BIO-3-WORLD-MODEL-PREDICTION-ERROR`
- `DOC-3E-PRECODING-READINESS-CLOSED-WORLD`
- `HBO-0-BELLMAN-OPERATOR-CONTRACTS`
- `HBO-1-OPERATOR-SENSOR-CORE`
- `HBO-2-BELLMAN-OPERATOR-SHADOW`
- `LONG-1-TEMPORAL-HOLDOUT`
- `LONG-2-RETENTION-FORGETTING`
- `LONG-3-UNLEARNING-NON-RESURRECTION`
- `LRN-0-CAUSAL-LEARNING-CONTRACTS`
- `LRN-1-DURABLE-EPISODE-LEDGER`
- `LRN-2-CAUSAL-EVALUATION`
- `P0.9-EXTERNAL-GATES`
- `PLS-1-PARAMETER-PLASTICITY`
- `PLS-2-TOPOLOGY-PROPOSAL`
- `PLS-3-BOUNDED-STRUCTURAL-CANARY`
