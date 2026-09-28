# control.engineering external production integration

The repository can verify external facts; it cannot manufacture them. The production path is deliberately split into two layers so that a generic signed JSON receipt cannot stand in for current durable owner state.

1. `external_controls.verify_production_controls` verifies the current local lease and envelope against an admitted distributed fence and revocation frontier, recomputes the current durable-owner snapshot for the immutable external audit anchor, and verifies role-separated HSM/KMS custody.
2. `production_adapters.verify_external_production_bundle` accepts the resulting typed `ProductionControlDecision` and then verifies separately signed completion, terminal, deployment, backup/restore, rollback, and operator observations.

Neither layer activates, deploys, merges, releases, or changes `production_implementation`.

## Typed production controls

The typed control bundle supplied to `production_acceptance.py` contains:

- `DistributedFenceReceipt`;
- `DistributedRevocationFrontierReceipt`;
- `AuditAnchorAttestation` bound to the current audit head and current owner-table snapshot digest;
- one or more `KeyCustodyReceipt` values proving hardware-backed, external, role-separated custody.

The verifier reopens the supplied SQLite owner database and reconstructs the exact persisted `WorkEnvelope` and `LeaseReceipt`. A fresh signature is insufficient when the local lease has been released, revoked, superseded, expired, or rebound to another source. A previously valid audit receipt is also rejected after owner-state drift.

Critical custody roles remain separated under the existing typed verifier. In particular, one provider key or one subject signing identity cannot satisfy multiple critical roles. Private keys remain outside this repository and outside candidate sandboxes.

## Required external operational roles

After typed controls pass, one complete operational bundle contains exactly one fresh, externally signed receipt for each role:

- `independent_ci_completion`;
- `integration_terminal_observer`;
- `target_deployment_observer`;
- `backup_restore_rehearsal_observer`;
- `rollback_rehearsal_observer`;
- `operator_acceptance`.

Every receipt binds the exact source commit/tree, deployment-target digest, evidence digest, provider instance, signing identity, nonce, role-specific evidence class, and validity window. Provider/signing identities must be distinct across roles. Any fixture, mock, reference, or test-only evidence is rejected.

The generic operational bundle intentionally does **not** contain `distributed_lease_fence`, `immutable_audit_anchor`, or generic `key_custody:*` roles. Those claims require typed verification against the current durable owner and cannot be replaced by a role string plus a signature.

## Transport

`HttpsJsonReceiptProvider` permits HTTPS only, an explicit host allowlist, normal TLS certificate verification, no redirects, a bounded timeout, and a bounded JSON response. Duplicate JSON keys are rejected. Optional bearer credentials are read from a named environment variable and never embedded in repository content.

The transport fetches evidence; it does not trust it. A fetched receipt must still pass role, identity, source, target, time, evidence-class, and signature checks.

## Key verification

`OpenSslPublicKeyTrustStore` is read-only. It accepts PEM public keys for Ed25519, RSA-PSS/SHA-256, or ECDSA/SHA-256 verification and has no signing implementation. Private keys remain in the external HSM/KMS boundary.

The public-key manifest is an operator-controlled input with rows containing:

```json
{
  "issuer": "external-role-authority",
  "signingIdentity": "kms-key-version",
  "publicKeyPath": "public-keys/operator.pem",
  "algorithm": "ed25519"
}
```

Paths are resolved inside the downloaded evidence artifact. The acceptance workflow rejects symbolic links and records a SHA-256 manifest over every supplied evidence file.

## Evidence artifact

An authorized upstream workflow supplies a retained artifact containing at least:

```text
engineering.sqlite3
typed-controls.json
external-observations.json
public-keys.json
public-keys/*.pem
```

The artifact must originate from an explicit historical workflow run. The repository-side verifier receives the run ID and artifact name, downloads it read-only, hashes every regular file, and records those hashes with the verification output. The upstream producer remains responsible for source authenticity, protected environment policy, target access, backup/restore execution, rollback execution, and operator identity.

## Acceptance workflow

`.github/workflows/control-engineering-production-acceptance.yml` is manually dispatched against an exact merged `main` SHA and the `control-engineering-production-acceptance` GitHub environment. It:

1. validates the exact source commit/tree and requires the commit to be an ancestor of current `origin/main`;
2. downloads one named evidence artifact from one named historical run;
3. rejects unsafe paths and symbolic links and emits a complete file-hash manifest;
4. verifies the canonical repository projection;
5. reopens the supplied SQLite owner and invokes the typed production-control verifier;
6. verifies all external operational observations;
7. uploads only the verification result and evidence hashes.

The workflow does not edit source, change `production_implementation`, deploy, activate, promote, release, or perform an external effect. The named environment should require independently controlled approvers before dispatch execution.

Absent a real distributed fence provider, immutable audit service, role-separated HSM/KMS receipts, independent completion and terminal observers, target deployment, backup/restore rehearsal, rollback rehearsal, and operator approval, every corresponding external gate remains false in `STATUS.json`. This is the expected fail-closed state.
