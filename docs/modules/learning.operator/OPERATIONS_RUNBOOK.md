# `learning.operator` operations runbook

## Trust rotation and revocation

Every selection must pin the trust digest and authority epoch used to verify its generator, observer, evaluator, and selector evidence. A key rotation creates a new immutable trust snapshot; it never rewrites old evidence. At or after a signer's `revoked_at`, re-verification must fail and the candidate must leave the eligible shadow set.

Trust material comes from the host authority store. Candidate payloads, manifests, receipts, and remote callers may not supply or replace the verifier's keys, controller mapping, scope, objective, or epoch.

## Registry movement

Before each read-only use, verify a signed current-registry view and exact predecessor/head binding. A stale registry head, generation regression, predecessor mismatch, revocation, or unavailable witness closes the consumer. Do not fall back to an unverified baseline while retaining learned-policy observability claims.

## Rollback

Rollback selects an already persisted immutable predecessor payload and its original complete pin. Do not retrain, rewrite, re-sign, or recompute the predecessor. Verify artifact ID, producer ID, generation, artifact and payload schema versions, runtime profile, trust digest, authority epoch, and registry head before opening bytes.

Rollback success requires a fresh process load and a read-only prediction smoke test. Failure to reopen the exact predecessor is a stop condition, not permission to synthesize a replacement.

## Incident stop conditions

Stop candidate admission and preserve evidence on any of the following:

- ledger replay or dataset-source-set mismatch;
- signature, controller-separation, trust-epoch, or revocation failure;
- canonical row-semantics digest drift;
- registry-head or immutable artifact identity mismatch;
- unsupported-cell, OOD, calibration, subgroup-coverage, or resource-budget breach;
- missing independent evaluation or selector evidence;
- any attempted production write by the shadow consumer.

Production writes remain disabled throughout qualification. Recovery must produce a new evidence chain; operators must not edit receipts in place.
