# learning.eval target-host acceptance

This checklist defines the evidence required to change
`CURRENT_STATE.json.sourceState.productionImplementation` or any external gate
to true. Repository source, fixtures and GitHub Actions cannot self-issue these
facts.

A completed review must include a machine-readable profile conforming to
`TARGET_HOST_PROFILE.schema.json`, signed receipts from the named owners and an
immutable candidate SHA/tree. Missing, expired, synthetic or self-issued
evidence fails closed.

## 1. Host and authority identity

The profile must bind:

- target host ID, environment, deployment generation and binary/image digest;
- immutable source commit and tree;
- authority-store revision, trust digest and revocation frontier;
- generator, evaluator, observer, evidence-owner, selector, operator and release
  principals;
- principal, credential-chain, signing-key and controller separation;
- clock source, time profile and expiry;
- exact objective, dataset, estimand and policy/candidate identities.

The request payload must not construct its own verifier or authority state.

## 2. Durable namespaces

Separate authenticated namespaces are required for:

- frozen evaluation plans;
- final-holdout CAS and independently retained minimum anchor;
- evaluation-attempt CAS;
- qualification evidence publication and reconciliation;
- outcome/snapshot evidence;
- retention, privacy and unlearning evidence;
- operator acceptance and release records.

For each namespace, provide owner identity, storage implementation, fencing,
idempotency key, backup policy, restoration procedure, retention, deletion and
non-resurrection controls.

## 3. Storage qualification

The target host must demonstrate:

- linearizable CAS for final-holdout and attempt state;
- monotonic fence takeover with stale-writer rejection;
- committed-or-indeterminate error mapping;
- crash recovery after short write, partial frame, lost response and process
  termination at every durability boundary;
- directory and data fsync semantics;
- independent anchor survival across backup restore;
- checkpoint compaction installation without state drift;
- measured recovery time and disk use at the declared maximum operating profile;
- cross-host lock/fsync qualification when a shared filesystem is used.

A local unit test does not qualify a production filesystem.

## 4. Evidence publication qualification

The evidence owner must implement
`IdempotentQualificationEvidenceSinkV1`. Acceptance evidence must show:

- exact retry returns the original publication digest without another append;
- the same execution key with different decision semantics conflicts;
- accepted-but-response-lost reconciles by read;
- missing or unreadable state after an uncertain write remains indeterminate;
- the publication binds execution, decision, trust, authentication and current
  evidence-frontier digests;
- target-host retention and audit retrieval meet the declared service profile.

## 5. Live evaluation evidence

A production or system-longitudinal claim additionally requires independently
issued evidence for:

- authenticated outcomes and immutable snapshots;
- the exact final-holdout manifest and one-use receipt;
- support, censoring, missingness, clustering, multiplicity and power;
- at least the preregistered real future-calendar windows;
- retention and change-point behavior;
- subgroup and privacy review;
- unlearning and backup non-resurrection;
- resource use, incomplete attempts and operator-visible failure states.

Virtual clocks, synthetic future IDs and repository fixtures cannot satisfy
future-calendar efficacy.

## 6. Independent acceptance and effect authority

The following remain distinct signed gates:

1. semantic/statistical acceptance;
2. operator acceptance for the named host and generation;
3. selector decision;
4. canary admission and observation;
5. promotion/activation authorization;
6. release authorization and rollback readiness.

No `learning.eval` receipt grants any of these. Every evaluator output remains
`DENY_ALL`.

## 7. Required acceptance bundle

The final bundle must contain:

- `target-host-profile.json` conforming to the schema;
- exact source and build provenance;
- current trust/revocation receipts;
- final-holdout, attempt-journal and evidence-sink qualification receipts;
- checkpoint capacity/compaction measurements;
- fault-injection logs and terminal reconciliation records;
- live outcome/future-window/retention/privacy/unlearning receipts where claimed;
- independent semantic, operator, selector, canary, promotion and release
  receipts where applicable;
- creation time, expiry and revocation instructions.

Until that bundle is independently verified, the authoritative state is:

```text
productionImplementation = false
targetHostQualified = false
independentAcceptance = false
activation = false
release = false
```
