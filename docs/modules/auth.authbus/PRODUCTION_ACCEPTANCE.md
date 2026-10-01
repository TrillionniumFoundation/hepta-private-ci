# AuthBus production acceptance

Production acceptance is a three-phase, fail-closed process. Repository source
never claims activation merely because implementation or CI exists.

## Evidence inputs

One unchanged candidate must provide:

- successful exact-head and deterministic synthetic-merge receipts;
- protected target-host crash-consistency and performance manifests;
- real KMS/HSM composition evidence;
- key rotation, revocation and recovery exercise evidence;
- matched backup/restore evidence;
- dual-owner and wrong-mount exercise evidence;
- candidate- and target-bound canary and rollback plans.

The machine contract is `PRODUCTION_ACCEPTANCE.json`. External drill receipts
use `hepta.authbus.external-drill.v1` and name the candidate SHA, target
identity, provider identity, retained evidence SHA-256 and observed result.

## Independent signatures

The protected `AuthBus production acceptance` workflow downloads immutable
artifacts by workflow run ID. It does not trust copied status text. The process
has three phases:

1. `security-payload` validates every input and emits canonical compact JSON for
   the independent security reviewer to sign with Ed25519.
2. `operator-payload` verifies that signature and emits the canonical operator
   payload. It includes the security signature digest, activation plan and
   rollback plan.
3. `verify` verifies a distinct operator's Ed25519 signature and emits
   `hepta.authbus.production-acceptance.v1`.

Reviewer and operator public keys come from separately protected environment
secrets. The principals must differ. The generated acceptance decision is
`approved_for_canary`; it deliberately keeps `productionActivated`,
`canaryPromotion` and `release` false.

## Promotion and rollback

Canary promotion requires a later observation receipt showing that the named SLO
thresholds held throughout the observation window, no unresolved critical
AuthBus alert existed, and the tested rollback remained executable. The
promotion owner signs that later receipt. Rollback restores only a matched
database/checkpoint/trust generation; a convenient older database or witness is
never accepted independently.

Missing signatures, stale run IDs, mismatched target identities, untested
rollback, skipped jobs or evidence from another candidate fail closed.
