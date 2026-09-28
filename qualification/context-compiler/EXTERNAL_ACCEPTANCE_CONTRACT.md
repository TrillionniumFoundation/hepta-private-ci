# context.compiler external acceptance contract

This contract defines the only repository-supported route from source qualification to independent acceptance, activation, or release. It does **not** grant any of those states by itself. `CURRENT_STATE.json` remains false for `independentAcceptance`, `activation`, and `release` until an operator-controlled process consumes a valid, externally signed receipt for one immutable source and deterministic merge tree.

## Immutable identity

Every receipt binds all of the following full object identities:

- source commit and source tree;
- reviewed base commit;
- deterministic synthetic-merge commit and merge tree;
- named host image digest and runner identity;
- non-production provider tenant used for reconciliation exercises.

Changing any identity requires a new receipt. A receipt for a previous source, merge tree, workflow, host image, tokenizer object, or provider tenant cannot be promoted.

## Required independent evidence

The signed receipt contains passing, digest-addressed evidence for:

1. exact source-head qualification;
2. deterministic synthetic-merge qualification;
3. external authority signer and key-rotation exercise;
4. immutable tokenizer custody and semantic golden vectors;
5. distributed attempt lease/idempotency;
6. append-only journal and monotonic generation anchor;
7. exact-attempt/exact-body terminal attestation;
8. filesystem substitution, rollback, and restore exercises;
9. multi-process or multi-host duplicate-send denial;
10. real provider framing and post-crash terminal reconciliation;
11. named-host latency, memory, concurrency, backlog, and recovery capacity;
12. the complete deterministic failpoint matrix in `FAILPOINT_MATRIX.json`;
13. independent security review;
14. operator-controlled shadow, canary, and rollback evidence before activation or release.

Every evidence record is bound to the same immutable source and merge identities and has an exclusive expiry. Missing, expired, skipped, queued, cancelled, digest-mismatched, or identity-drifted records fail closed.

## Detached signature and trust root

`external-acceptance.json` is accompanied by `external-acceptance.sig`. The manual validation workflow runs only on the named self-hosted acceptance pool and fixed protected environment. It verifies the detached SHA-256 signature with the environment-owned public trust root and verifies the configured trust-root digest before parsing the receipt.

The repository stores neither a private signing key nor a fallback trust root. A missing environment secret, missing trust-root digest, invalid signature, or unavailable named runner blocks validation.

## Modes

- `independent` requires all source, security, host, recovery, provider, and failpoint evidence plus independent security approval. It does not authorize activation.
- `activation` additionally requires canary/rollback evidence and an operator approval bound to the same source and merge tree.
- `release` additionally requires a release approval. It never follows automatically from a merged pull request or a passing source workflow.

The validator emits a read-only validation report. It never edits source, updates canonical state, activates a feature, releases an artifact, or deletes unresolved recovery evidence.
