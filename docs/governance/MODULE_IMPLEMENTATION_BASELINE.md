# Module implementation baseline

This document is the shared engineering baseline for module-specific technical guides and implementation maps. It removes repeated boilerplate without changing canonical ownership, authority, contracts, data domains, work-package DAGs or capability claims.

## 1. Record classes remain separate

The following states are independent and must not share one `complete` flag:

1. **Specification** — reviewed behavior, interfaces, algorithms, bounds and failure semantics.
2. **Source materialization** — code exists in the declared root at an exact commit/tree.
3. **Native mapping** — every advertised operation maps to a native symbol and test.
4. **Durability reference** — append/reopen/rollback semantics exist in bounded source fixtures.
5. **Product composition** — a named product caller and, where applicable, production writer are wired.
6. **Qualification** — exact-head, target-profile and independently observed checks pass.
7. **Acceptance** — the designated independent owner accepts the evidence.
8. **Activation** — a selected generation is loaded under current authority.
9. **Release** — signing and release governance complete.

A source directory or green unit test proves none of the later states. Each module records the dimensions in a machine-readable maturity projection.

## 2. Deterministic kernel and bounded adapters

Module computation follows:

```text
bounded bytes or typed inputs
-> structural validation
-> authentication/authority validation where applicable
-> immutable profile binding
-> deterministic owner-local kernel
-> typed output validation and semantic digest
-> append-only owner store or explicit stateless publication
-> independent downstream observation
```

All payloads, arrays, queues, loops, retries, allocations and journal files have explicit ceilings. Unknown critical fields, units, profiles, identities and generations fail closed. Missing facts are unavailable or uncertain, never silently zero.

## 3. Ownership and authority

One owner writes each authoritative domain. A module does not issue authority it later consumes, evaluate its own production promotion, write another owner’s terminal outcome or broaden scope through fallback.

Cross-owner work uses a named integration package with explicit co-owners and narrow paths. A broad historical work package may be superseded by an owner-safe overlay, but the overlay grants no new runtime or release authority.

Every effect request binds operation identity, final payload digest, scope, expiry and current revocation frontier. Queue admission or handler return is not terminal external success. Unknown terminal effects remain indeterminate until reconciled by the designated observer.

## 4. State and durability

Stateless modules explicitly identify the owning caller that persists immutable outputs. Stateful modules define:

- authoritative versus rebuildable domains;
- schema and migration ownership;
- append, idempotency and conflict identity;
- crash-before and crash-after-publication behavior;
- hash or checksum integrity;
- reopen and reconciliation;
- correction, deletion and revocation lineage;
- selected-pointer publication;
- retention and backup/restore semantics.

An owner-local in-memory or byte-journal reference proves only the encoded transition and reopen logic. It does not prove filesystem durability, fsync, production writer exclusivity or operational retention.

## 5. Compatibility and protocol admission

Rust owner-local types do not become external wire protocols by name alone. External admission requires:

- canonical contract/protocol registry entry;
- owner and consumer list;
- exact field semantics and bounds;
- canonical encoding and digest scope;
- compatibility and unknown-field policy;
- generated/native producer and consumer compilation;
- round-trip and golden-vector tests.

Compatibility APIs retain a named immutable semantic profile. A new policy or receipt version binds every changed aggregation, tolerance, normalization or authority interpretation.

## 6. Error semantics

Stable errors are owned by one machine-readable registry. Each code binds one stable meaning, outcome class, retry posture and native variants. Markdown, Rust, SDKs and observability adapters must agree. Typed non-error outcomes such as conflict receipts, explicit abstain or unresolved Pareto sets are not overloaded onto unrelated error numbers.

## 7. Testing and evidence

Every implemented operation maps to:

- source path and public/native symbol;
- input and output types;
- authority posture;
- focused native tests;
- fault and boundary tests;
- exact source workflow;
- product caller when composed.

Critical numerical kernels require an analytic or independent oracle. Golden fixtures include normal, maximum-bound, rejection, unsupported, timeout, crash/reopen, tamper, revocation and rollback cases. The evaluated writer cannot be the sole independent evaluator.

Exact-head evidence cannot be transplanted to a later commit. Synthetic-merge evidence binds the unchanged base/head pair. Failed, cancelled or skipped required checks remain failures.

## 8. Performance and observability

Complexity and latency are specified per path. Normal success, conflict extraction, recovery, rebuild and slow numerical solvers have separate budgets. A p95/p99 claim binds exact source, host, compiler, flags, device, thread count, fixture, data size and observation time.

Structured events contain safe identities, revisions, generations, outcome classes, durations, bounded resource use and digest references. Raw credentials, unrestricted private payloads and consumable grants do not enter general logs or learning data.

## 9. Fallback and rollback

Fallback cannot widen authority, candidate set, resource budget, risk ceiling or effect scope. It consumes only compatible, current and non-revoked predecessors. Rollback is a newly authorized transition; it does not replay stale grants, reset epochs or resurrect deleted lineage.

Local safety, watchdog and emergency-stop loops remain independent of synchronous central planning. Central degradation reduces capability or invokes a qualified fallback; it never disables an external stop.

## 10. Implementation map and maturity projection

Every module with source implementation maintains `docs/modules/<module>/IMPLEMENTATION_MAP.json`. The map records operation-to-symbol-to-test linkage and truthful product/activation state. A lane maturity file projects the independent dimensions without replacing canonical registries.

Semantic CI validates maps, source symbols, tests, authority ceilings, owner-safe paths and document consistency. Generated module-guide hashes remain untouched unless the guide and its canonical metadata are deliberately regenerated together.
