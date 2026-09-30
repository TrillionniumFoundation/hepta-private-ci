# `secrets.heptabao` production-readiness boundary

This document accompanies `READINESS_POLICY_V1.json` and the read-only
CI-generated `hepta.secrets-heptabao-readiness.v3` receipt.

## Exact-candidate rule

Source, tests, documentation, artifacts and qualification must refer to one Git
commit and one workflow attempt. Results from another SHA or attempt cannot be
combined. Qualification checks out the exact review object with persisted Git
credentials disabled and must leave the complete worktree unchanged. A qualified readiness receipt must
load the current role's retained native receipt and all nine gate logs, verify
the executed Rust toolchain, commit/tree and current workflow run/attempt, and
reject a dirty worktree. Synthetic-merge readiness also binds the exact ordered
base/source parents. Retained local logs do not constitute independently signed
operator acceptance.

## Build surface

`codex-hepta-bao-adapter` is one complete Cargo build surface. SQLite, AuthBus,
HTTPS and registered-host code are not represented by undeclared synthetic
feature names. The qualifier runs `cargo metadata --locked --no-deps` and the
normal full package targets.

## Current source truth

`SqliteBaoOwnerV1` and `SqliteBaoProductRuntimeV1` are source-present. The owner
contains revision CAS, append-only transitions, bounded generation-fenced
recovery claims, schema-4 import, immutable terminal archival and checkpoint
hashing/publication hooks. The exported `product_bootstrap` library constructor binds a registered
`hepta-secrets-runtime` binary source. The binary currently describes and
validates configuration; no normal process constructs its trusted dependencies
and starts the provider, consumers, recovery worker or metrics export.
A constructor helper is therefore source-bound, while `productComposed` remains
false.

Consequently source presence is true while source qualification,
storage-profile qualification, product composition, target-host qualification,
activation, operator acceptance and release remain false until independently
proved for one exact SHA.

## Deployment topology

| Deployment | Current state | Required proof |
|---|---|---|
| One process, local filesystem | source candidate | exact-head tests, schema verification, anti-rollback operation |
| Multiple processes, one host | unqualified | writer exclusion, stale-claim takeover and shutdown drain |
| Multiple pods on one volume | denied by default | independently qualified filesystem lock and fencing semantics |
| Multiple hosts/network filesystem | denied | independent storage qualification |
| Active/passive failover | target-only | owner epoch and stale-writer rejection |
| Restored database copy | target-only | checkpoint CAS, rollback detection and explicit recovery ceremony |

The fixed HeptaBao provider remains qualified only for exact KV-v2 reads.
Generic dynamic issue, renew and revoke remain fail-closed.
