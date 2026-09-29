# utility.ndu production hardening

Status: unified source candidate; production selection, activation and release remain gated.

This document is normative for the hardening layer of the unified `utility.ndu` candidate. It distinguishes repository-controlled source obligations from external deployment evidence that cannot be inferred from source presence.

## 1. Qualification order

Qualification is monotone and ordered:

1. exact-head source policy, format, lockfile and closed-world object validation;
2. deterministic core, authority, migration, replay and public-API tests;
3. real Control and Agentd product caller regressions;
4. strict Clippy and all-target compilation;
5. deterministic synthetic-merge repetition of the same gates;
6. named-host fault, capacity and recovery receipts on the same source identity;
7. target production filesystem and shared-volume qualification;
8. authenticated production composition and external service enrollment;
9. independent stochastic acceptance and staged rollout.

A later item never compensates for a missing earlier item. Parent-branch receipts do not qualify a descendant.

## 2. Authority and authenticity

The deterministic V1 hierarchy proof remains a path/snapshot consistency object. Authenticated use requires `NduSignedHierarchyProofV2`, which binds:

- hierarchy identifier and complete canonical path;
- snapshot and proof digests;
- subject, parent, class and generation;
- issuance and expiry;
- revocation epoch and current frontier digest;
- policy digest and signer key identity;
- Ed25519 signature and canonical receipt digest.

The signer is admitted only through `NduAuthorityTrustBindingV2`, which binds the exact verifying key, validity interval, trust revision and policy. Trusted time, key identity, policy, epoch and frontier are checked at verification time. Source code never mints an external authority.

## 3. Immutable artifact location

Production admission uses `NduImmutableLocatorV2`. The accepted closed schemes are:

- `artifact://sha256/<digest>`;
- `s3+version://<bucket>/<key>?versionId=<exact-version>#sha256=<digest>`;
- `https+sha256://<address>#sha256=<digest>`;
- `file+sha256:///<absolute-path>#sha256=<digest>`.

A plain mutable URL, missing content digest, missing S3 object version, path traversal, locator/content mismatch or object-version mismatch fails closed.

`NduAuthenticatedProjectionArtifactV3` signs the validated durable artifact binding and immutable-locator binding together. A valid signature cannot authorize different bytes, a different locator or a different durable binding.

## 4. Projection catalog and migration

`NduProjectionCatalogV2` separates event action from the closed artifact kinds `preference`, `utility` and `coefficient`. The selection key is:

```text
(objective_digest, subject_digest, projection_kind)
```

Operation identity is resolved before mutable current-state checks. Therefore an identical replay returns the original terminal entry after a later revocation, while a new selection against the revoked artifact is rejected.

V1 migration requires an explicit resolver for every legacy preference or utility payload. Migration never invents an immutable locator. Missing, conflicting or ambiguous legacy kind fails closed. Coefficient has no implicit V1 migration.

Before the first acknowledged V2 store mutation, the production writer must retain an immutable, externally acknowledged V1 backup. A V1 binary must never open or truncate a V2 image. After any V2 acknowledgement, recovery is forward-only from the V2 snapshot/WAL or its acknowledged backup.

## 5. Evidence compatibility and sealing

V1 receipt source compatibility is frozen by `PUBLIC_API_BASELINE_V1.json` and an external-crate compile fixture.

`NduIterationReceiptV2` and `ZQ24ConversionReceiptV2` are sealed additive types. Migration requires independent V1 canonical recomputation. The Z migration also requires the original source matrix and admitted conversion profile; the implementation does not infer missing source input from converted output.

Every V2 receipt digest is recomputed from the complete canonical field set. Floating-point digest inputs normalize negative zero and reject non-finite values.

## 6. Historical replay versus current use

Historical operation outcome is not present authorization.

`NduHistoricalReplayReceiptV2` is deny-all evidence of a previous terminal catalog entry. It permits lost-response reconciliation.

Current use requires a separate `validate_current_use_v2` call that revalidates:

- current catalog selection;
- authenticated artifact and durable binding equality;
- authenticated artifact expiry;
- trusted-time receipt;
- current revocation frontier;
- artifact availability receipt;
- final-use grant binding;
- current production policy.

Revocation removes the current selection. The historical outcome remains queryable but cannot be consumed as a final-use grant.

## 7. Production composition

The production composition is incomplete unless concrete bindings exist for every role:

- persistent projection store;
- authenticated owner/writer;
- process fence;
- cross-host fence;
- trusted time;
- revocation frontier;
- artifact registry;
- encrypted remote backup;
- restore executor;
- metrics exporter;
- real product caller.

Each binding includes adapter identity, implementation/configuration digest, policy digest and revision, deployment-instance digest and capability receipt. Duplicate identity, duplicate role or missing role is rejected.

A readiness receipt additionally binds exact-head and synthetic-merge qualification, target host/filesystem, shared-volume fence, backup readback, restore drill, metrics delivery, real caller and independent stochastic acceptance. The receipt remains `DENY_ALL`; it is not activation authority.

## 8. Persistence completion gate

Production persistence is not complete until one exact source identity has retained evidence for:

- private directory ownership and mode;
- no-follow/dirfd-safe handling appropriate to the target OS;
- root, lock and state device/inode stability;
- single writer and cross-host fencing;
- write, file-sync, rename and directory-sync cuts;
- SIGKILL before and after every durability boundary;
- ENOSPC, EDQUOT, EROFS, permission, symlink and hard-link failures;
- indeterminate-commit poisoning and reconciliation;
- valid snapshot plus bounded WAL recovery;
- index reconstruction, checkpoint and bounded compaction;
- archive-before-rotation and non-resurrection;
- encrypted off-host copy, immutable version and exact readback;
- monotonic restore drill;
- retained host/kernel/filesystem/source receipt.

Hosted CI and mounted fault fixtures do not prove physical power-loss behavior on the production filesystem.

## 9. Operational evidence

The source defines bounded observations for evaluation, uncertainty, rejections, persistence stages, lock/fence behavior, corruption, recovery, replay, capacity, revocation lag, artifact availability, grant refresh and restore monotonicity.

Production closure additionally requires:

- a named exporter adapter and deployment instance;
- bounded labels and stable metric schema;
- dashboards and SLO thresholds;
- alert delivery receipt;
- operator runbook acceptance;
- paging tests for corruption, poisoned owner, stale fence, backup age and restore failure.

A metric type in source is not proof that monitoring is deployed.

## 10. Independent FBSDE gate

The bounded FBSDE candidate includes dataset admission, filtration/leakage rejection, fixed-horizon backward training, Q24 artifact sealing, independent reference recomputation and shadow stages.

Independent acceptance requires candidate-bound evidence for:

- registered immutable dataset and locator binding;
- filtration and leakage audit;
- independent numerical oracle;
- convergence envelope;
- calibration, utility-improvement and regression acceptance;
- sufficient shadow episode and decision volume;
- advisory and restricted-write runtime receipts;
- target-host receipt;
- deterministic rollback policy and current non-triggered rollback receipt.

Rollback thresholds cover holdout RMSE, calibration error, utility improvement, failure count and minimum decision count. Any violation blocks acceptance. Independent acceptance remains deny-all and does not register, select, promote, activate or release a model.

## 11. External activation blockers

The following cannot be closed by source changes alone:

- enrollment of the actual production host, filesystem and shared volume;
- selected production owner/writer and all concrete adapter deployments;
- protected clock and independent anti-rollback/revocation provider;
- approved cloud account, bucket, KMS policy, immutable object version and readback;
- off-host copy count, restore, retention and deletion execution;
- monitoring and operator-response installation;
- registered production dataset and independent model-governance approval;
- canary, promotion, activation and release authority.

No document, source type or hosted-CI result may convert these external gates to complete without the named retained evidence.
