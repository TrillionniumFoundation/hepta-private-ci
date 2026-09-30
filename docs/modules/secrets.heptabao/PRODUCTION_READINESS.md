# `secrets.heptabao` production readiness boundary

This file is the human-readable companion to `READINESS_POLICY_V1.json` and the
CI-generated `hepta.secrets-heptabao-readiness.v2` receipt.

## Exact candidate rule

A qualification result is valid only when the candidate, tested source,
documentation, source artifact and qualification result refer to one Git object
and one workflow attempt. Results from different SHAs or attempts are never
combined. The development materializer may create a new commit, but only the
subsequent read-only qualification of that commit is evidence.

Qualification workflows use `contents: read`, disable checkout credentials,
perform full tracked and untracked cleanliness checks before and after execution,
and never invoke a generator, commit or push operation.

## Build surface

`codex-hepta-bao-adapter` is one complete Cargo build surface. The SQLite owner,
AuthBus admission, durable operations and registered final-use host are
unconditional parts of that surface. Historical undeclared feature names are
not a product boundary and are rejected by `validate_build_contract.py`.
Qualification records `cargo metadata --locked` before native execution.

## Independent readiness dimensions

The module reports the following dimensions independently:

| Dimension | Current state |
|---|---|
| sourcePresent | true |
| sourceCompiled | unproved until exact-head CI succeeds |
| sourceQualified | false until source and deterministic merge both succeed |
| storageProfileQualified | false |
| productComposed | false |
| targetHostQualified | false |
| activated | false |
| operatorAccepted | false |
| released | false |

SQLite owner/runtime source presence is recorded without claiming product
composition or deployment qualification.

## Current composition boundary

The library contains `SqliteBaoOwnerV1` and `SqliteBaoProductRuntimeV1`, but the
candidate contains no named non-test Agentd or App Server process that owns their
lifecycle. A future product caller must declare the binary, database identity,
startup import policy, forward and recovery worker identities, shutdown drain,
protected provider and trust configuration, checkpoint service, metrics sink,
rollback procedure and supported topology.

## Durable-writer deployment support

| Deployment | State | Required proof |
|---|---|---|
| One process, local filesystem | source candidate | exact-head tests, owner file checks and checkpoint operation |
| Multiple processes, one host | qualification required | stale-writer exclusion and crash takeover |
| Multiple pods sharing one volume | denied by default | certified lock semantics and fencing |
| Multiple hosts or network filesystem | denied by default | independent storage qualification |
| Active/passive failover | target-only | owner epoch and stale-writer rejection |
| Restored database copy | target-only | anti-rollback and explicit identity recovery |

Runtime diagnostics must remain non-secret and include database identity,
checkpoint generation, writer identity and whether the storage profile was
independently qualified. Secret bytes, provider tokens and authorization headers
never enter diagnostics or evidence.
