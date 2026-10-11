# Module engineering standard

This document contains implementation requirements shared by every Hepta module. Module guides state only their deltas, owned facts, algorithms, limits and adapters. Canonical registries remain authoritative for identity, ownership, contracts and delivery dependencies.

## 1. Authority and trust

Inputs are bounded, versioned and scope checked. Unknown critical fields, stale revisions, missing authority, digest drift and revoked credentials fail closed. A typed value named `Authenticated`, `Verified` or `Accepted` must either be constructible only by the responsible verifier or be documented explicitly as a preverified host input. An unkeyed digest detects mutation but is not a signature, identity proof or trust-root check.

No module may convert source compilation, a fixture, queue acceptance or handler completion into production, physical-effect, independent-acceptance, selection, promotion or release authority. Authority-bearing outputs name their issuer, scope, epoch, validity window and exact payload, and are checked immediately before the protected boundary.

## 2. State and persistence

Each authoritative domain has one named writer. Mutations use an exact operation identity, semantic digest and predecessor/head compare-and-swap. Identical retry is idempotent; identity reuse with changed semantics conflicts. Last-write-wins is forbidden for authoritative facts.

A durable adapter defines canonical encoding, checksum or digest framing, file/store identity, exclusive-writer fencing, synchronization order, containing-directory durability where applicable, acknowledgement, reopen validation and quarantine behavior. Snapshot replay must reproduce the exact head and records. In-memory state machines are never described as physically durable without the host adapter and target-host evidence.

## 3. Transactions, crashes and retries

Every state-changing flow identifies its linearization point. Tests inject failure before validation, after validation, before durable write, after synchronization, before publication, after publication, before acknowledgement and during recovery. Unknown external effects become pending, indeterminate or quarantined; they are never relabelled success.

Retries use the original identity, predecessor, authority epoch and payload digest. Reconciliation is fenced. Cancellation cannot erase a terminal state already being committed. Rollback is a new authorized transition and overlays current correction, revocation, withdrawal and stop frontiers.

## 4. Contracts and compatibility

Public contracts have stable identifiers, canonical field order, bounds, digest domains, numeric profiles and golden vectors. Compatibility is additive only when registered. Historical records retain their original version; no V1 object is silently reinterpreted as V2 or V3. Adapters state every accepted source/target version pair and whether downgrade is forbidden.

Rust types and canonical wire encodings represent identical semantics. Tests cover round trip, maximum bounds, missing and unknown fields, invalid enums, overflow, ordering, duplicate identities and digest stability.

## 5. Resources and concurrency

Modules enforce payload, row, element, encoded-byte, memory, CPU, queue, concurrency and deadline limits. Per-vector limits do not replace an aggregate request limit. Expensive verification uses bounded indexes or staged slow paths. Backpressure rejects explicitly and cannot create unbounded retry or task growth.

Configuration is immutable for a process generation. Caches bind revision and expiry and invalidate on correction, revocation, deletion, withdrawal or generation change. Hot paths avoid global locks, central synchronous control and full-store scans.

## 6. Observability and operations

Structured events contain module, operation/attempt identity, source revision, outcome class, duration, bounded resource use and safe digest references. Credentials, secrets, raw provider payloads and untrusted content do not enter general logs.

Readiness requires configuration, dependencies, schema, current frontiers and integrity to be verified. Liveness only indicates possible progress. Alerts cover saturation, retry storms, aged pending/indeterminate state, integrity failure, projection lag, stale heads and rollback failure.

## 7. Qualification

Repository-controlled completion requires an immutable base/head/tree tuple, closed-world source inventory, public API linkage from another crate, attributed native tests, all-target compilation, strict lint, format cleanliness and an ordered-base synthetic merge repeating the same checks. A mutable branch name cannot be a qualification target.

External product, target-host, future-calendar, consent, hardware, independent-acceptance, canary, selection, promotion and release evidence stays open until its responsible owner issues an immutable receipt for the exact candidate. Repository code and documentation cannot self-issue those receipts.
