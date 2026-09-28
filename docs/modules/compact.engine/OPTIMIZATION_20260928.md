# compact.engine convergence and measurement contract — 2026-09-28

This document belongs to PR #993 and the canonical `compact.engine` convergence line. It records source-level engineering changes only. It does not assert production activation, independent semantic acceptance, promotion or release.

## 1. Transaction and state boundaries

The durable checkpoint owner is converged around four internal responsibilities:

1. deterministic candidate/proof construction;
2. current trust and owner admission;
3. transaction-owned durable mutation;
4. restart/reconciliation.

The durable store owns `BEGIN IMMEDIATE` transactions through SQLx transaction objects. A future cancelled before commit drops an unfinished transaction rather than returning a pooled connection with a caller-managed transaction still open. A commit error is classified as an indeterminate result and must be reconciled under the same operation identity; it is never permission to invent a new idempotency key.

Every durable mutation must verify the current owner/root/lease/manifest fence in the transaction that performs the mutation. Historical event time is not a substitute for the host's current execution time.

## 2. End-to-end measurements

Agentd records bounded process-local samples for the full publication and reopen calls, starting before the serialized coordinator wait and ending after the final authority check. The snapshot exposes:

- sample, success and failure counts;
- queue-wait p50, p95, p99 and maximum;
- end-to-end p50, p95, p99 and maximum.

These samples are diagnostics for the current process generation. They are not durable receipts and are not a production SLO. Exact-source capacity evidence must additionally retain host identity, peak RSS, database/WAL growth, archive bytes and raw command output.

Core receipt fields that estimate clone or hash work must be labelled as estimates. Timing only the final SQLite publication transaction is not an end-to-end request measurement.

## 3. Copy and integrity policy

Request identity excludes semantic payload bytes while binding the signed payload digest, tokenization receipt and all metadata. Its metadata view is built without cloning the semantic payload buffer merely to clear it.

Normal checkpoint selection validates the selected immutable objects and current admission. It must not run a database-wide integrity scan or reset unrelated outbox claims. Full SQLite/schema/cross-object verification belongs to open/startup, explicit operator verification and bounded deep-scrub paths.

No cache may bypass current trust, source deletion/revocation or writer-authority admission. Cached results are keyed by immutable object identity and validation revision.

## 4. Independent resource ceilings

The protocol uses separate ceilings for:

- semantic payload bytes;
- publication archive metadata and receipts;
- total full publication archive bytes;
- compact durable archive/artifact bytes.

The full archive may carry a maximum semantic payload plus bounded metadata. A pure 64 MiB kernel payload result does not establish that a complete signed publication, durable write and cryptographic reopen fit a target host. Tests cover `limit - 1`, `limit`, and `limit + 1` at each layer.

## 5. Actionable failures

The Agentd boundary preserves stable compact-engine error code, recovery action and commit-state fields. The minimum actions are:

- correct the request;
- retry the same operation identity;
- backpressure;
- reopen the owner;
- reconcile the same operation because commit state is unknown;
- stop writes on corruption.

Callers must not parse error prose and must not map an unknown durable outcome to an immediate new attempt.

## 6. Qualification boundary

The final candidate requires terminal success for exact head and deterministic synthetic merge on:

- locked all-target compilation;
- native package and Agentd tests;
- strict Clippy;
- committed formatting and clean source;
- cancellation, lease takeover, manifest rotation, response-loss and read/outbox interleaving regressions;
- full publish/reopen capacity and storage-growth evidence.

Queued, pending, skipped, cancelled, failed, historical-head or patch-only results are not pass receipts.
