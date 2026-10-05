# control.engineering external production integration

The repository can verify external facts; it cannot manufacture them. `production_adapters.py` defines the bounded transport and receipt format for the services that remain outside the module.

## Required external roles

One complete bundle contains exactly one fresh, externally signed receipt for each role:

- `distributed_lease_fence`;
- `immutable_audit_anchor`;
- role-separated key custody for `source_authority`, `ci_executor`, `independent_evaluator`, and `integration_terminal_observer`;
- `independent_ci_completion`;
- `integration_terminal_observer`;
- `target_deployment_observer`;
- `backup_restore_rehearsal_observer`;
- `rollback_rehearsal_observer`;
- `operator_acceptance`.

Every receipt binds the exact source commit/tree, deployment-target digest, evidence digest, provider instance, signing identity, nonce and validity window. Provider/signing identities must be distinct across roles. The production public-key manifest also normalizes every PEM public key to DER and rejects reused cryptographic key material under different logical identities. Any fixture, mock, reference or test-only evidence is rejected.

## Transport

`HttpsJsonReceiptProvider` permits HTTPS only, an explicit host allowlist, normal TLS certificate verification, no redirects, a bounded timeout and a bounded JSON response. Duplicate JSON keys are rejected. The local receipt-bundle loader applies the same duplicate-key rule and rejects symlink inputs. Optional bearer credentials are read from a named environment variable and never embedded in repository content.

The transport fetches evidence; it does not trust it. A fetched receipt must still pass the role, identity, source, target, time and signature checks.

## Key verification

`OpenSslPublicKeyTrustStore` is read-only. It accepts PEM public keys for Ed25519, RSA-PSS/SHA-256 or ECDSA/SHA-256 verification and has no signing implementation. Private keys remain in the external HSM/KMS boundary.

The public-key manifest is an operator-controlled, non-symlink input with rows containing absolute public-key paths:

```json
{
  "issuer": "external-role-authority",
  "signingIdentity": "kms-key-version",
  "publicKeyPath": "/runner/secrets/public.pem",
  "algorithm": "ed25519"
}
```

Manifest loading rejects duplicate JSON keys, duplicate logical identities, invalid public keys and identical normalized public-key material reused by separate identities.

## Acceptance workflow

`control-engineering-production-acceptance.yml` is manually dispatched against an exact `main` SHA and a protected GitHub environment. It reads externally supplied receipt and public-key bundles, verifies them, runs recovery/stress checks and uploads a verification artifact. It does not edit source, change `production_implementation`, deploy, activate or release.

Absent external endpoints, public keys, receipts, target identity, backup/restore rehearsal, rollback rehearsal and operator approval leave every external gate false in `STATUS.json`. This is the expected fail-closed state.
