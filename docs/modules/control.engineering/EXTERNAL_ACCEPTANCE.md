# control.engineering external acceptance contract

This document defines evidence that must be produced by systems outside
`control.engineering`. Repository source, CI fixtures, local HMAC keys, digest-shaped
strings and author assertions cannot satisfy these gates. The canonical repository
fact `production_implementation` concerns exact-source native product composition
and executable product qualification, as defined in
[IMPLEMENTATION_BINDING.md](IMPLEMENTATION_BINDING.md). Deployment readiness and
external acceptance additionally require the evidence below to be current,
independently verified and bound to one exact target and source identity. This
contract does not promote either fact merely because its source is present.

## Required independent providers

Production composition uses five separately identified provider ports:

1. a distributed lease/fence authority with a signed revocation frontier;
2. an immutable external audit service anchoring both audit head and durable owner
   state;
3. an external hardware key-custody authority with separate keys for critical roles;
4. an independent completion observer; and
5. an integration terminal observer.

`ProductionProviderSet` rejects missing provider identities, fixture/test/mock or
`local-hmac` identities and provider-role collisions. Passing this structural check
is not proof that a provider is live.

## Deployment and recovery evidence

A target-host rehearsal must produce all four receipts below. Each receipt is signed
by a distinct identity and has a bounded observation window.

- `TargetDeploymentReceipt`: exact target/environment, source commit/tree, artifact
  digest, owner-state snapshot digest and observed deployment result.
- `BackupRecoveryReceipt`: backup digest, exact source, expected snapshot, restored
  snapshot and integrity result.
- `RollbackRehearsalReceipt`: deployed source, compatible predecessor commit/tree,
  restored snapshot and observed rollback result.
- `OperatorAcceptanceReceipt`: target/operator identity and the exact three receipt
  digests accepted by the operator authority.

`verify_production_acceptance_evidence` rejects target/source/snapshot drift, stale
windows, invalid signatures, negative observations, receipt substitution and signer
collisions. A positive decision deliberately retains `production_implementation`,
runtime, merge and release authority as false; an external release authority must
consume that evidence under its own policy.

## Protected target rehearsal

`.github/workflows/control-engineering-production-rehearsal.yml` is a manual,
protected-environment workflow. It requires:

- an exact 40-character source SHA;
- a self-hosted Linux runner labelled `control-engineering-target`;
- a real strong-sandbox host;
- an externally managed verifier executable;
- an externally supplied evidence bundle;
- focused source/gap tests, target-host profile and bounded stress profile; and
- retained deployment/recovery/rollback/operator evidence.

The workflow fails closed when the runner, verifier, evidence bundle or any required
observation is absent. Repository maintainers must configure the protected
environment, runner and secret mounts outside this change.

## Deployment-readiness and external-acceptance rule

Deployment readiness requires, at minimum:

- exact source-head and deterministic base-merge product receipts;
- an exact post-merge main product receipt;
- an independent semantic review submission bound to the current head;
- live distributed-fence, external-audit and HSM/KMS custody evidence;
- target deployment, backup recovery and rollback rehearsal receipts;
- operator acceptance; and
- a clean canonical status projection showing no missing mandatory gate.

No repository-controlled test may manufacture these facts or convert fixture success
into external acceptance.
