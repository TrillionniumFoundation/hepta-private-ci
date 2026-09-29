
# `learning.operator` operations runbook

State and error semantics are defined in
[ADMISSION_CONTRACT.md](ADMISSION_CONTRACT.md).

## Trust rotation and revocation

Every selection pins the trust digest and authority epoch used for
generator, observer, evaluator, and selector evidence. Rotation creates
a new immutable trust snapshot; it never rewrites old evidence. At or
after `revoked_at`, re-verification fails and the candidate leaves the
eligible shadow set.

Trust material comes from the host authority store. Candidate payloads,
manifests, receipts, and remote callers cannot replace verifier keys,
controller mapping, scope, objective, or epoch.

## Actionable failure handling

- `CorrectRequest`: reject the unchanged request; do not busy-retry.
- `ObtainFreshOwnerEvidence`: rebuild the freeze/attestation chain
  against the current owner.
- `RejectCandidate`: quarantine the immutable candidate identity and
  preserve its evidence.
- `ReloadSelectedCandidate`: reopen the independently selected bytes and
  complete pin; never synthesize a replacement.
- `AbstainUnsupportedCell`: leave the candidate loaded and abstain for
  that decision.
- `StopConsumer`: stop reads and preserve diagnostics until explicit
  operator recovery.

Owner failures include the exact failed operation (`FreezeDataset`,
`ReadDatasetRecords`, `Snapshot`, or `EncodeFreezePayload`).

## Registry movement

Before each read-only use, verify a signed current-registry view and
exact predecessor/head binding. A stale head, generation regression,
predecessor mismatch, revocation, or unavailable witness closes the
consumer. Do not fall back while retaining learned-policy claims.

## Rollback

Reopen an already persisted immutable predecessor and its original
complete pin. Verify artifact/producer identity, generations, schemas,
runtime profile, trust digest, authority epoch, and registry head.

Success requires a fresh-process load and read-only prediction smoke
test. Failure to reopen the exact predecessor is a stop condition.

## Incident stop conditions

Stop admission and preserve evidence on ledger/source-set mismatch,
signature/controller/trust/revocation failure, row-semantics drift,
registry or immutable identity mismatch, calibration/coverage/resource
breach, missing independent evaluation/selection, or any attempted
production write by the shadow consumer.
