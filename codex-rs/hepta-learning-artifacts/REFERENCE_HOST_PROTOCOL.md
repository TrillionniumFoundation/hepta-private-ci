# Learning artifact reference host protocol

## Status and authority

`LearningArtifactReferenceHostV1` and the `hepta-learning-artifactd` reference
binary are the repository-owned composition for the existing artifact owner.
They do not select a model, approve a release, provision production identities or
self-certify target-host power-loss behavior. Every public response retains
`AuthorityPosture::DENY_ALL` at the owner boundary.

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

## Actions

| Action | Meaning | Readiness rule |
| --- | --- | --- |
| `health` | Authenticated liveness | Allowed while starting, recovering, ready or draining |
| `ready` | Authenticated readiness | True only in `ready` |
| `status` | Current phase, heads, keyring and recovery operation | Always authenticated |
| `metrics` | Bounded counters | Always authenticated |
| `publish` | New publication through `LearningArtifactOwnerService` | `ready` only |
| `recover_publish` | Exact replay of the persisted recovery operation | `recovering` only |
| `install_withdrawal_frontier` | Install a witnessed newer withdrawal snapshot | Serialized owner command |
| `reload_authz` | Load a strictly newer keyring generation | Serialized owner command |
| `backup` | Produce and verify an immutable backup | Serialized owner command |
| `shutdown` | Enter draining and stop accepting new connections | Authenticated, action-scoped |

`publish` payloads use the canonical
`hepta.learning-artifactd.publish.v1` key/value encoding. The payload binds the
V2 manifest, complete bytes, expected withdrawal head, expected registry
predecessor and the independently signed current-head witness. The command
recomputes the payload digest before constructing a typed V3 admission.

## Startup and recovery

The process validates the root, configuration permissions, authz keyring,
writer lease, trust registry, withdrawal scope and optional signed restart
anchor before binding the listener. If prior `.head` records exist, startup
without a required current-head anchor fails closed.

Opening the owner obtains the existing OS writer fence and replays durable owner
state. The route is not ready while an incomplete publication requires recovery.
Only `recover_publish` with the exact operation ID may cross that fence. A
successful recovery transitions to ready; a new publication is rejected until
then.

Status transitions are append-only under `host/status`. A status file is an
operational observation, not an activation or release receipt.

## Failure rules

- Authentication errors do not execute or create an operation.
- A prepared request with no result is retried under its exact signed digest.
- A durable publication phase failure moves the host to `recovering`.
- A result-write or directory-sync failure is indeterminate and must be
  reconciled from the final path; the same path is never truncated or reused.
- A poisoned owner mutex or corrupt record fails closed.
- Response errors are persisted exactly like successes, so repeated commands do
  not observe changing outcomes.

## Versioning

The transport, request, command, result, audit, status, backup and schema markers
are independent versioned formats. A decoder rejects unknown schema identifiers,
duplicate fields, noncanonical line endings and oversized input. Incompatible
changes require a new schema and an explicit migration; they must not silently
reinterpret V1 bytes.
