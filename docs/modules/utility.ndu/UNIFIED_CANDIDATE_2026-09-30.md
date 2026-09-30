# utility.ndu unified candidate — 2026-09-30

This document defines the single integration and qualification line for `utility.ndu`. It is a source and evidence plan, not activation authority.

## 1. Integration order

The unified candidate is constructed in this dependency order:

1. latest repository `main` baseline;
2. the A-D engineering, persistence, recovery, observability and bounded-history convergence line;
3. the bounded FBSDE training/publication closure stacked on that line;
4. the authority, replay, artifact, compatibility and production-composition hardening developed on the separate production-hardening line;
5. candidate-specific documentation and closed-world implementation mapping.

The candidate retains one first-parent development line. The separately developed changes are integrated by reviewed source semantics, not by treating three PR heads as additive qualification evidence.

## 2. Conflict resolutions

### V1 and V2 protocol receipts

V1 public fields and entry points remain source-compatible. `NduIterationReceiptV2` is sealed and is produced only by a validated binder or explicit V1 migration. Both V1 validation and V2 construction recompute the canonical digest from the complete field set. All receipts remain `DENY_ALL`.

### Z coordinate and Q24 evidence

V1 conversion remains available. V2 retains the exact canonicalized source matrix and validates by rerunning the admitted conversion, comparing the original-coordinate matrix, every Q24 integer, the exact maximum error and the complete receipt digest. V1-to-V2 migration succeeds only when the supplied source matrix reproduces the complete V1 receipt.

### Historical replay and current use

Historical replay is represented by `NduHistoricalProjectionReplayV1`. It reports a previously completed operation and the observed journal head; it cannot be passed to the final-use validator.

`NduCurrentUseReceiptV2` is created only after checking the current selected projection and binding the immutable artifact, current final-use grant, revocation frontier, trusted-time receipt, owner fence, production policy and adapter manifest. Revocation after a historical success therefore cannot be mistaken for fresh authorization.

### Hierarchy authority

`NduSignedHierarchyProofV2` uses Ed25519 over canonical claims. Verification binds:

- hierarchy and root-to-subject path;
- subject/parent/class and generation;
- authority key ID and key epoch;
- issued-at and expiry times;
- trust-root revision;
- revocation-frontier digest;
- active key state and key validity interval.

The result is a validated hierarchy snapshot proof only. It grants no mutation or use authority.

### Artifact identity

`NduImmutableArtifactLocatorV2` admits only registered immutable schemes. It rejects mutable query/fragment locators and path traversal, and binds an object locator to the expected content digest and an immutable version/generation/digest. `NduDurableProjectionArtifactV3` requires the locator content digest to equal the projection digest. V2 migration requires an explicit resolver and never invents a missing version.

### Production composition

`NduProductionCompositionReceiptV1` names exactly one adapter for each required role:

- persistent projection store;
- authenticated owner/writer;
- process/cross-host fence;
- trusted time;
- revocation frontier;
- artifact registry;
- encrypted remote backup;
- restore executor;
- metrics exporter;
- product caller.

Each binding records adapter identity, implementation digest, configuration digest, policy revision and qualification state. The receipt also binds source commit/tree, target triple, runner/host, test set, `Cargo.lock` and documentation-map digests. A complete source-bound composition remains ineligible for activation. Eligibility becomes true only when every adapter carries a retained host-qualified receipt.

### FBSDE independent acceptance

`NduFbsdeAcceptanceReceiptV1` binds immutable dataset registration, filtration and leakage audits, independent evaluator identity and receipt, trusted time, an independent numerical oracle, convergence envelope, calibration, utility-improvement lower bound, regressions, rollback trigger and a real stage runtime receipt.

Stages are monotone:

```text
shadow -> advisory -> restricted-write
```

A later stage requires an eligible predecessor for the identical candidate, production policy and acceptance policy. Every receipt remains `DENY_ALL`; production selection and activation stay outside this module.

## 3. Exact-candidate qualification

No predecessor result is inherited. The exact candidate head and its deterministic merge candidate must independently execute and retain:

- source/lexical/inventory checks;
- `cargo test -p codex-hepta-ndu --locked`;
- public V1 consumer compile and pinned `cargo-semver-checks`;
- independent reference and FBSDE acceptance tests;
- Control caller and normal Agentd process tests;
- all targets, strict Clippy and rustfmt;
- development-document and semantic-conformance gates;
- projection state-machine, migration and rollback tests;
- process kill, restart/reopen, truncated/corrupt journal and indeterminate-commit tests;
- ENOSPC, EDQUOT, EROFS, write/file-sync/rename/directory-sync failures where supported;
- named-host capacity and recovery measurements;
- clean-source checks;
- immutable aggregate receipts containing command, exit status and log hashes.

The evidence identity must include commit SHA, tree SHA, base SHA, deterministic merge SHA and ordered parents, target triple, runner image/host fingerprint, test-set hash, `Cargo.lock` hash and implementation/documentation-map hashes.

## 4. External acceptance

The repository can define adapters and evidence formats but cannot fabricate external production facts. The production owner must supply current receipts for real fencing, trusted time, revocation, immutable artifact storage, encrypted backup, restore execution, metrics/alerts, product caller deployment and target-host filesystem behavior.

FBSDE progression additionally requires a registered immutable dataset, independent leakage/filtration review, independent numerical runs, measured convergence/calibration/utility improvement, real shadow volume and executed rollback criteria.

Until those receipts are present and separately approved, production activation is false.
