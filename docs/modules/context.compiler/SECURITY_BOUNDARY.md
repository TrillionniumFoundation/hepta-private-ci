# context.compiler external security boundary

This document is normative for product composition. Source presence, a passing
unit test, or a locally generated signature never grants activation authority.
The V3 product path fails closed unless every capability below is supplied by a
separate host trust domain and its evidence is bound to the exact attempt.

## 1. Trust domains

| Capability | Product process may do | Product process must not do |
|---|---|---|
| Context admission authority | Verify an externally signed snapshot envelope | Hold signing keys, sign its own snapshot, lower key epoch or revocation frontier |
| Tokenizer custody | Execute an immutable, content-addressed tokenizer bundle through a host executor | Resolve an unpinned model-name tokenizer, reopen mutable paths, use estimates or provider usage |
| Attempt lease/idempotency | Acquire and settle a deployment-owned lease bound to attempt and exact body | Fall back to a process-local mutex for production uniqueness |
| Recovery journal | Append monotone records through a deployment-owned append-only journal | Rewrite history, delete unresolved intent, restore an older generation as current |
| Provider terminal attestation | Verify an independently authenticated terminal acknowledgement | Treat callback arrival, HTTP success, or local receipt construction as independent acknowledgement |
| Activation/release | Consume an operator-approved activation receipt | Mint approval, bypass environment protection, or infer release from source qualification |

## 2. External authority envelope

Every accepted authority envelope binds all of the following:

- `key_id`;
- monotonically nondecreasing key epoch;
- issuer and product audience;
- signature algorithm;
- issued and exclusive expiry timestamps;
- revocation frontier;
- exact authority-snapshot payload digest;
- bounded external signature bytes;
- verifier identity and verification digest.

The product crate exposes verification only. A concrete KMS/HSM integration is a
host capability and must not expose signing operations or key bytes to Agentd,
context.compiler, prompt.registry, the model runtime, logs, or qualification
artifacts.

## 3. Immutable tokenizer bundle

A production tokenizer identity is not only a path and a pair of hashes. The
host custody receipt must bind:

- provider, model, and tokenizer profile;
- executable object digest;
- vocabulary object digest;
- normalization and template revisions;
- content-addressed object identifiers;
- immutable mount/object generation;
- host resolver/attestor identity;
- execution receipt over the exact encoded provider-body digest and token count.

Path-based pre/post hashing remains a compatibility diagnostic, not production
custody evidence. The selected host must execute already opened or otherwise
immutably addressed objects and prove that no mutable-path reopen occurred.

## 4. Distributed attempt uniqueness

The lease request binds thread, turn, attempt, owner generation, idempotency
key, exact body digest, provider wire-semantic digest, and exclusive expiry.
The external lease authority returns a grant bound to that exact request and is
settled only with an exact-body-bound terminal receipt. Reusing an attempt or
idempotency key with changed semantics is a conflict.

No in-memory fallback is permitted for the production V3 owner. Failure or
uncertainty of the lease authority blocks transport.

## 5. Recovery and rollback resistance

Each attempt has an append-only sequence:

```text
Prepared
  -> LeaseAcquired
  -> DurableIntentCommitted
  -> TransportCommitted
  -> TerminalObserved
  -> LeaseSettled
```

Records bind the previous-record digest, attempt, exact body, owner generation,
event payload, and time. A deployment-owned generation anchor rejects backup
restore or filesystem rollback below the accepted generation. Unresolved intent
is never deleted to regain availability.

Filesystem implementations must use descriptor-relative traversal and no-follow
semantics at every security-sensitive component, reject non-regular files and
ownership/mode drift, fsync the written file and containing directory, and fence
the writer after uncertain durability.

## 6. Independent terminal acknowledgement

The external terminal attestation binds:

- attestor `key_id` and epoch;
- issuer and product audience;
- exact `attempt_id`;
- exact encoded provider-body digest;
- canonical provider receipt digest;
- normalized terminal observation digest;
- observation time, expiry, and revocation frontier.

A local provider callback may populate provisional evidence, but an unresolved
post-crash attempt becomes final only after this independently authenticated
binding or an explicitly governed `NotDispatched` reconciliation.

## 7. Acceptance evidence

Independent security acceptance must include, for one immutable source and
merge tree:

1. external signer/KMS/HSM configuration and key-rotation exercise;
2. tokenizer custody and semantic golden-vector receipt;
3. multi-process or multi-host duplicate-send denial;
4. append-only journal and generation-anchor rollback exercise;
5. provider terminal reconciliation after process death;
6. symlink, path substitution, backup restore, and stale-generation negatives;
7. target-host latency, memory, backlog, and recovery-capacity results;
8. operator canary, rollback, and independent approval receipts.

Until those external receipts exist, `independentAcceptance`, `activation`, and
`release` remain `false` regardless of source or CI status.
