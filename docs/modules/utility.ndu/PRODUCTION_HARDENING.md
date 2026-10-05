# utility.ndu production hardening

Status: source candidate; production activation remains gated.

This document is normative for the hardening layer added after the V1 projection journal. It distinguishes repository-controlled source obligations from external evidence that cannot be inferred from source presence.

## Qualification order

The module is qualified in this order:

1. exact-source and synthetic-merge compilation and regression tests;
2. strict Clippy and formatting on the same source SHA;
3. named-host qualification receipt on that same SHA;
4. production-filesystem crash/recovery qualification;
5. authenticated production owner and writer composition;
6. learned FBSDE shadow evidence and staged promotion.

A later item never compensates for a missing earlier item.

## Authority and hierarchy

`NduHierarchySnapshotProofV1` binds every staged update to:

- one hierarchy identifier;
- one canonical root-to-subject path;
- one authoritative snapshot digest;
- one proof digest over those values.

`validate_authoritative_staged_updates` rejects any ancestor/descendant pair in the same generation, including a grandparent/grandchild pair for which the intermediate node is not in the batch. Siblings remain independently admissible. Different snapshots for one hierarchy in one generation fail closed.

The legacy direct-parent helper remains available only for compatibility. Production admission must use the snapshot-proof API.

## Projection catalog V2

`NduProjectionCatalogV2` separates event action from projection type. The selection key is:

```text
(objective_digest, subject_digest, projection_kind)
```

The closed projection-kind set is:

- preference;
- utility;
- coefficient.

Publishing requires `NduDurableProjectionArtifactV2`, which binds the projection digest to an immutable locator, byte size, schema revision, policy digest, provenance digest and retention epoch. Its fields are private and the binding digest is recomputed by validation.

Operation identity is resolved before current-state checks. Therefore:

- replay of an already successful selection returns its original terminal entry even after a later revocation;
- a new selection operation against the same revoked artifact is rejected;
- reuse of an operation identity for different semantics is an identity conflict.

V1 migration requires an explicit resolver that maps every legacy preference or utility payload to a validated durable artifact. Migration does not invent an artifact locator. A legacy selected/revoked digest that is absent or ambiguous across projection kinds fails closed. Coefficient projection has no implicit V1 migration because V1 did not represent that kind.

### Rollback rule

A V2 production writer must preserve an immutable V1 backup before its first V2 commit. A V1 binary must not open or truncate a V2 image. Rollback is permitted only before any V2 mutation is acknowledged; after acknowledgement, recovery is forward-only from the V2 snapshot/WAL or its externally acknowledged backup. The source-level catalog and migration fixture do not by themselves establish that production backup transport exists.

## Evidence sealing

`NduIterationReceiptV1`, `NduSolverIterationReceipt` and `ZQ24ConversionReceiptV1` do not expose externally constructible evidence fields. Canonical iteration receipts provide validation and read-only accessors. Z-conversion receipts expose read-only accessors and validate dimensions, Q24 reconstruction, profile binding, digest presence and deny-all authority posture.

Floating-point digest inputs normalize negative zero before hashing. Non-finite values remain rejected.

## Production capabilities

The hardening layer defines minimal ports for:

- grant refresh;
- revocation frontier reads;
- trusted-time receipts;
- durable artifact availability verification.

These ports do not mint authority. The production owner must be the only holder of the mutable journal/store capability. Read-only planner code may consume a validated selected artifact but must not receive a store handle, journal mutation API or authority-administration capability.

## Required operational metrics

`NduAuditMetricsV1` carries the following bounded observations:

- oldest pending operation age;
- journal utilization;
- compaction duration;
- replay duration;
- poisoned owner count;
- indeterminate commit count;
- revocation lag;
- artifact unavailable count;
- grant refresh failure count;
- restore monotonicity failure count.

The presence of the metric type is not evidence that a production exporter or alert route is deployed.

## Persistence completion gate

Production persistence is not complete until one exact source SHA has evidence for all of the following:

- private directory ownership and mode;
- no-follow/dirfd-safe path handling appropriate to the target operating system;
- stage-classified I/O failures;
- process kill before and after write, file sync, rename and directory sync;
- disk-full and quota exhaustion;
- rename and sync failure injection;
- recovery from valid snapshot plus bounded WAL;
- index reconstruction and bounded compaction;
- encrypted backup transport, retention and external acknowledgement;
- monotonic restore drill on the target filesystem;
- a retained recovery receipt naming source SHA, source tree, host and filesystem profile.

The repository V1 store remains a bounded source candidate. It must not be described as production-qualified merely because injected persistence tests pass.

## Learned FBSDE gate

The following source contracts exist without claiming model efficacy:

- `NduImmutableTrainingDataBindingV1` for immutable data, provenance and authorization;
- `NduFiltrationContractV1` for trusted time, information set and a no-future-data receipt;
- `NduShadowPromotionPolicyV1` for minimum shadow samples and independent runs, with mandatory convergence, calibration, utility-improvement and regression acceptance.

Promotion requires independent reference implementations for covariance, Z conversion and recursive utility, plus retained evidence for convergence, calibration, utility improvement and regressions. Shadow numerical primitives are not a learned production model. Advice-only, restricted-write and production-use stages must be separate and monotone.

## External evidence still required

The following cannot be closed by this source change and remain explicit activation blockers:

- selection of the actual production owner and writer;
- deployment of the four capability-port adapters;
- target production filesystem recovery qualification;
- backup transport, encryption, retention and restore monitoring;
- production metric export and alerting;
- immutable training dataset registration;
- complete time discretization and training loop;
- independent numerical reference runs;
- convergence, calibration and utility-improvement acceptance;
- sufficient shadow sample volume and staged promotion approval.

No readiness document or CI receipt may convert one of these external blockers to complete without the named retained evidence.
