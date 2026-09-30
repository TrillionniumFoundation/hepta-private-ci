# Learning artifact reference host protocol

## Status and authority

`DurableInstrumentedLearningArtifactReferenceHostV1` is the repository-owned
product composition for the existing artifact owner. It is a thin fail-closed
composition over `InstrumentedLearningArtifactReferenceHostV1`,
`LearningArtifactReferenceHostV1` and the single
`LearningArtifactOwnerService`; it does not create a second writer or state
machine. Direct use of `LearningArtifactReferenceHostV1` remains a compatibility
surface and does not satisfy the durable-shutdown or operational-evidence
contract in this document.

The host does not select a model, approve a release, provision production
identities or self-certify target-host power-loss behavior. Every public response
retains `AuthorityPosture::DENY_ALL` at the owner boundary.

The protocol is local-first and intentionally narrow. The reference listener may
bind only a loopback address. A non-loopback deployment requires an independently
reviewed transport proxy that preserves the exact request bytes and does not
invent caller identity.

## Request envelope

The canonical envelope is `HEPTA-LEARNING-ARTIFACTD-REQUEST-V1` and contains:

1. keyring generation;
2. request ID;
3. client ID;
4. action;
5. issued and expiry timestamps;
6. nonce, which must equal the request ID;
7. payload bytes;
8. Ed25519 signature.

The signature covers the keyring generation, request/client/action, complete
validity interval, nonce, payload length and payload digest. Requests live for at
most 120 seconds, may be at most five seconds in the future, and are accepted
only by a current or explicitly retained previous keyring generation. Client
grants are action-scoped and independently revocable.

Request IDs are idempotency identities. Before execution the host creates a
synchronized `host/requests/<id>.prepared` record. Completion creates an
immutable `host/results/<id>.result` and `host/audit/<id>.audit`. An exact retry
returns the original response. Reuse with a different signed digest is a
`replay_conflict`; it never creates a new operation identity or re-executes the
command.

The publication service additionally checks one canonical digest over the full
publication request. Terminal and non-terminal retry use the same identity
contract. Payload, manifest, signed head, predecessor, withdrawal scope/head and
operation drift cannot reuse a completed receipt.

## Actions

| Action | Meaning | Readiness rule |
| --- | --- | --- |
| `health` | Authenticated liveness | Allowed while starting, recovering, ready or draining |
| `ready` | Authenticated readiness | True only in `ready` |
| `status` | Current phase, heads, keyring and recovery operation | Always authenticated |
| `metrics` | Bounded base counters | Always authenticated |
| `publish` | New publication through `LearningArtifactOwnerService` | `ready` only and denied after durable drain |
| `recover_publish` | Exact replay of the persisted recovery operation | `recovering` only |
| `install_withdrawal_frontier` | Install a witnessed newer withdrawal snapshot | Serialized owner command; durable floor precedes success |
| `reload_authz` | Load a strictly newer keyring generation | Serialized owner command |
| `backup` | Produce and verify an immutable backup | Serialized owner command |
| `shutdown` | Persist one-way drain intent and stop accepting new work | Authenticated, action-scoped |

`publish` payloads use the canonical
`hepta.learning-artifactd.publish.v1` key/value encoding. The payload binds the
V2 manifest, complete bytes, expected withdrawal head, expected registry
predecessor and the independently signed current-head witness. The command
recomputes the payload digest before constructing a typed V3 admission.

## Startup, recovery and durable shutdown

The process validates the root, configuration permissions, authz keyring,
writer lease, trust registry, withdrawal scope and optional signed restart
anchor before binding the listener. If prior `.head` records exist, startup
without a required current-head anchor fails closed.

Opening the owner obtains the existing OS writer fence and replays durable owner
state. The route is not ready while an incomplete publication requires recovery.
Only `recover_publish` with the exact operation ID may cross that fence. A
successful recovery transitions to ready; a new publication is rejected until
then.

Shutdown uses the same scope-, registry- and storage-bound `writer/DRAIN.v1`
record consumed by `LearningArtifactOwnerService`. The durable composition does
not return an accepted shutdown until the record and containing directories are
synchronized. If a process dies after the authenticated request journal records
success but before the caller receives it, startup scans the bounded request and
result journals, validates the exact accepted shutdown response and recreates or
re-synchronizes the drain record **before** the owner service opens. Restart
therefore cannot silently restore new-publication admission.

The drain record is one-way. Exact terminal retry and recovery of an already
prepared operation remain distinct from admission of new work. There is no
online clear/resume operation; replacement deployment requires an independently
governed new store/generation decision.

Status transitions are append-only under `host/status`. A status file is an
operational observation, not an activation or release receipt.

## Stable failure and retry contract

`ArtifactOwnerFailureClassV1` separates:

- `identity_conflict`;
- `stale_owner`;
- `withdrawal_frontier_insufficient`;
- `persistence_outcome_unknown`;
- `capacity_exhausted`;
- `recovery_required`;
- `draining`;
- authorization, corruption, availability, configuration and internal failures.

Each class has an explicit `ArtifactOwnerRetryDispositionV1`. Identity or corrupt
state requires operator intervention; stale owner/authorization requires fresh
authority; withdrawal conflict requires a newer authenticated frontier;
indeterminate persistence and recovery-required outcomes require exact-identity
reconciliation; capacity requires bounded reclamation; drain requires a
replacement owner. Hosts must not translate every error into immediate retry.

## Operational evidence

`ArtifactOwnerOperationalMetricsV1` projects actionable state without changing
owner authority. It includes:

- oldest pending attempt age;
- durable-drain age;
- recovery reconciliation failures;
- withdrawal blocks;
- identity conflicts;
- stale-owner rejections;
- persistence-unknown and capacity rejections;
- bounded latency summaries for request, publication, recovery, withdrawal,
  backup and shutdown paths.

Pinned bytes and pending physical-erasure bytes are accepted only as a
digest-bound `ArtifactRetentionObservationV1` from the owning consumer/retention
system. Until such an observation is supplied, the JSON value is `null`, not a
fabricated zero.

`ArtifactOwnerStageV1` and the measurement helpers separately measure payload
encode/hash, payload write+sync, registry write+sync, current-head switch,
checkpoint sync, startup recovery scan and pinned load. Measurements are
observations; they cannot bypass fsync, identity, current-head, withdrawal or
recovery checks. Qualification and target-host runs must retain the exact source
commit/tree, host/filesystem profile, input sizes, sample counts and raw
summaries before proposing cache, checkpoint-index or catalog changes.

## Failure rules

- Authentication errors do not execute or create an operation.
- A prepared request with no result is retried under its exact signed digest.
- A durable publication phase failure moves the host to `recovering`.
- A result-write or directory-sync failure is indeterminate and must be
  reconciled from the final path; the same path is never truncated or reused.
- A poisoned owner mutex or corrupt record fails closed.
- Response errors are persisted exactly like successes, so repeated commands do
  not observe changing outcomes.
- An accepted shutdown is never returned before durable drain synchronization.
- Unknown pin/erasure observations remain unknown; metrics do not infer them from
  registry reachability or cache eviction.

## Versioning

The transport, request, command, result, audit, status, backup, operational
metrics, stage-sample and schema markers are independent versioned formats. A
decoder rejects unknown schema identifiers, duplicate fields, noncanonical line
endings and oversized input. Incompatible changes require a new schema and an
explicit migration; they must not silently reinterpret V1 bytes.
