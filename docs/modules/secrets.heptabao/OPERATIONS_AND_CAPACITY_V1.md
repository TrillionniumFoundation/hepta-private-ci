# `secrets.heptabao` operations and capacity contract V1

This document describes the executable diagnostics and measurement surfaces for
the registered exact KV-v2 consumption path. It is subordinate to
`CONSUMPTION_SAGA_V4.md` for state semantics and to `LEASE_OWNER_V3.md` for the
reference owner's persistence protocol. It does not activate a product process,
qualify a production store, or authorize provider-native dynamic leases.

## 1. One durable phase model

`BaoConsumptionStateV1` is the single source for three derived decisions:

- `phase()` identifies whether the operation is unreserved, reserved,
  dispatch-fenced, holding immutable terminal evidence, or fully terminal;
- `recovery_action()` identifies the only safe next action;
- `requires_future_capacity()` determines whether the bounded owner must retain
  room for a larger future result.

Callers must not recreate these decisions with independent `match` statements.
An operation that has crossed the dispatch fence is never redispatched. A
terminal `Succeeded` or `Failed` row retains its identity and immutable history,
but no longer reserves bytes for a future result that cannot exist.

## 2. Full-operation latency

`BaoFinalUseHost::operation_metrics()` returns bounded, process-local snapshots
for forward execution and recovery. Each series retains at most 256 duration
samples and reports attempts, success, p50/p95/p99 and the last/maximum duration.
The measurement starts at the public host entry and ends after the local result
is classified, so it includes admission, durable state transitions, AuthBus,
provider I/O, consumer observation and settlement reached by that invocation.

Failure counters distinguish:

- admission rejection;
- ordinary reconciliation work;
- waiting for original-effect evidence;
- waiting for settlement;
- immutable historical failure;
- identity/observation conflict;
- capacity rejection;
- an already-active operation;
- indeterminate durable commit;
- other durable-owner failure;
- external authority, AuthBus or provider-control failure.

These counters reset on process restart and are not an audit log. A selected
product host must export them through its approved metrics system and bind that
export to the selected binary and configuration.

## 3. Reference-owner diagnostics

`DurableLeaseRegistryV1::diagnostics()` returns a secret-free snapshot containing:

- operation, lease and consumption counts;
- consumption counts by durable state and pending recovery action;
- quota amount associated with nonterminal local rows;
- dispatch-fenced rows that lack a provider receipt;
- rows waiting for a registered observer and rows waiting for settlement;
- oldest pending age measured in store revisions;
- encoded bytes, lease-result reserve, consumption-result reserve and remaining
  bounded capacity;
- writer fencing and commit attempts, outcomes, bytes and p50/p95/p99 latency.

Revision age is intentionally not presented as wall-clock age. A deployment that
requires elapsed-time alerts must combine the durable operation identity with an
independently trusted time source; it must not reinterpret local wall time as
authority time.

The snapshot excludes provider tokens, raw secret bytes, request/response/secret
digests and secret path components. The `Debug` implementations for requests,
receipts and durable consumption rows redact those values. Diagnostic structs do
not weaken access control: secret size and version are still sensitive metadata
and require bounded retention and restricted access.

## 4. Reference-owner cost boundary

The JSON owner is a bounded migration oracle, not a high-throughput production
ledger. Each successful logical mutation validates the full state, encodes the
full snapshot, writes and synchronizes a replacement, renames it and synchronizes
the parent directory. Commit metrics therefore measure the real current cost;
they are not a claim that the design scales linearly with traffic.

Before replacing this owner, qualification must measure complete requests and
recovery operations rather than isolated SQL statements. At minimum, retain:

- p50/p95/p99 forward and recovery latency;
- commit count and synchronized bytes per logical operation;
- owner/operation contention and active-operation rejection;
- recovery scan and reconciliation batch duration;
- encoded bytes, future-result reserve and archive growth;
- peak process memory and target-host storage latency.

## 5. Production-store replacement gate

A transactional SQLite owner/runtime source is present, but exact-head, storage-profile, target-host and product-composition qualification remain open. Merely storing one JSON blob in a
SQLite row does not satisfy this gate. A replacement must preserve:

- exact operation deduplication and semantic-conflict rejection;
- immutable historical results and negative evidence;
- compare-and-swap state transitions and single-writer fencing;
- a bounded, fair recovery queue with explicit retry/stop classifications;
- transactional event history and non-resurrecting archive/retention rules;
- an externally retained monotonic anti-rollback checkpoint;
- migration and rollback from the schema-4 JSON reference model;
- nonblocking integration with the async host;
- target-host crash, power-loss, backup/restore and long-history qualification.

The repository's truncated phase-three staging payload is not executable source
and must not be applied or cited as completion. Until a complete implementation
passes the gates above, production-writer and activation claims remain false.

## 6. Crash and recovery qualification

The Unix native test fixture defines 26 named SIGKILL cuts around claim, trusted
time, authorization, quota reserve, reservation binding, AuthBus dispatch fence,
local fence publication, provider response, delivery preparation, consumer entry,
consumer acknowledgement, settlement and local terminal publication.

The recovery oracle proves more than the absence of a duplicate receipt:

- no blind provider read or consumer re-entry;
- no orphaned reservation when a terminal fact is provable;
- no invented success, failure or refund;
- stable semantic identity across retries;
- explicit pending state when post-dispatch original-effect evidence does not
  exist;
- idempotent repeated reconciliation.

The fixture uses synthetic loopback TLS and process termination. It is not an
external HeptaBao dynamic-lease test or storage-device power-loss qualification.

<!-- secrets-heptabao-sqlite-source-status:v1 -->
## SQLite source and qualification status

The current source candidate contains `SqliteBaoOwnerV1` and
`SqliteBaoProductRuntimeV1`, including revision-CAS transitions, generation-
fenced recovery claims, schema-4 reference import, immutable terminal archive
and external-checkpoint hashing/publication hooks. This is a **source-presence**
fact only. Exact-head compilation/qualification, storage-profile qualification,
a named product caller, target-host qualification, activation, operator
acceptance and release remain false until independently proved for one exact
SHA. The fixed provider remains KV-v2-read-only; generic dynamic issue, renew
and revoke remain fail-closed.
<!-- /secrets-heptabao-sqlite-source-status:v1 -->
