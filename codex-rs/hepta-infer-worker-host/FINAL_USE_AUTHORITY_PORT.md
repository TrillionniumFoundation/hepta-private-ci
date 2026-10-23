# runtime.codex final-use authority port

This document describes the concrete final-use authority boundary used by the
native `runtime.codex` App Server caller. It is repository source design, not
proof of a deployed approval service, target-host trust, activation, promotion,
or release.

The existing PN3/PN4 work also has an authority-free
`OrdinaryCpuRegistration` prerequisite. It derives one exact bounded payload and
the complete canonical `OperationIntentV1` from trusted host metadata: subject,
scope, policy generation, source/profile/worker identity, fixed program/arguments/cwd
and an observer deadline of at most eight seconds. Requests carry that fixed
payload rather than an executable path or argument list. Registration and
semantic validation do not enter a worker or consume FinalUse authority. The
source digest is a declared binding; deployment must separately authenticate the
immutable executable.

The internal ordinary CPU owner adds a storage prerequisite in the destination's
trusted, already-migrated SQLite pool. One original `BEGIN IMMEDIATE` transaction
commits both the exact semantic dedupe record and a permanent entry from sixteen
lifetime slots; terminal tombstones consume those slots. Every new entry checks
its actual connection for WAL and synchronous FULL. Replay never admits another
entry, and an error or ambiguous commit cannot return a new-entry decision. This
storage stage does not start a Child or issue terminal authority. Its fixture
replaces all physical connections in the same pool and rebuilds the owner; it
does not qualify pool/process cold recovery or change the disabled production
recovery APIs. Actual Child ownership, the signed source route and the original
U/C/A resource qualification remain required parts of the same PN3/PN4 work.

The ordinary target retains the original sealed dispatch through destination
admission and consumes its claim at synchronous fixed-program/arguments/cwd
spawn. It clears inherited environment and retains the original Child in a
permanent slot. Only that Child's timely `try_wait` exit zero plus durable
terminal storage establishes an ordinary exit fact; the eight-second observation
bound does not bound the later storage settlement. Missing Child, late or nonzero
exit, and uncertain durability remain indeterminate. Source-route tests use the
original production writer/outbox, real signed FinalUse grants and a signed exact
fixture lease verifier; they do not qualify production key custody or cold
recovery. Ordinary exit is not wait4/cgroup accounting, resource retirement or
model acceptance.

The source-route race controls hold the real destination SQLite write lock while
the original sealed claim waits. Expiry or revocation then prevents spawn while
the committed entry stays permanent. Cancelling a delivery future after an
actual worker effect never enables a second spawn: its original Child remains
observable, or loss of that owner leaves source reconciliation indeterminate.

## 1. Ownership and effect boundary

The named caller in
[`native_app_server.rs`](src/native_app_server.rs) freezes the exact v2
`TurnStartParams` only after Agent identity/generation, App Server transport
identity, session/thread, model/provider, context attachment, stable
`client_user_message_id`, and the absolute runtime deadline are known.

The runtime.codex adapter computes the exact request digest over that frozen
request and its transport/session correlation. The caller then derives a
`FinalUseBinding` whose subject is the owning Agent and whose destination is
the Codex App Server provider boundary. The binding commits to the exact
runtime.codex request, scope, and serialized `TurnStartParams` payload.

No physical `turn/start` await is entered without a non-constructible
`VerifiedUseToken` for that exact binding. The worker never owns the issuer
private key and cannot turn a boolean, unsigned proposal, adapter receipt, or
model output into final-use authority.

## 2. Durable prepare and one-entry semantics

The ordering is deliberate:

1. request the exact signed grant from the configured authority endpoint;
2. verify its signer, signature, binding, time window, authority epoch,
   revocation head, and nonce through the shared final-use authority;
3. persist the runtime.codex dispatch identity, request/payload correlation, and
   authority-witness digest in the native journal before the external
   `turn/start` await;
4. retain a non-cloneable, non-serializable in-memory pre-effect abort proof for
   that exact durable dispatch revision;
5. recheck Agent readiness/generation/ingress, cancellation, and the absolute
   deadline after authority acquisition and durable write-ahead;
6. call `VerifiedUseToken::enter(expected_binding)` immediately before the
   first effectful App Server await;
7. consume the resulting private `EnteredUseToken` as proof of exactly one
   effect entry. It does not authorize retry.

If cancellation, deadline expiry, owner loss, or ingress drift is observed
before effect entry, the same live process may consume the pre-effect abort
proof and durably release a definitely-unsent dispatch. If the process dies,
that proof disappears and cannot be reconstructed from disk. Reopening such a
dispatch is therefore accepted-or-unknown and reconcile-only; recovery must
never infer "not sent" from process loss.

Once `enter()` succeeds, later timeout, cancellation, transport loss, or
process death cannot refund the grant or prove that the App Server did not
receive the request.

## 3. Authority endpoint and protected configuration

`hepta-infer-worker --profile native-app-server` requires an explicit
final-use authority configuration. The current Unix implementation pins:

- an absolute Unix socket path;
- the expected issuer UID, checked both on socket metadata and the connected
  peer credentials;
- one signer identity and Ed25519 verifying key;
- an owner-private durable final-use state directory;
- a nonzero authority epoch and monotonic revocation revision;
- the configured revoked grant set;
- a bounded issuer request timeout.

Unsafe paths, symlinks, unsafe ownership/permissions, wrong peer identity,
malformed or oversized frames, unknown fields, signer/key mismatch, invalid
signature, wrong binding, expiry, revoked grant, nonce replay, stale revocation
head, or durable-store failure fail closed before physical `turn/start`.

The wire exchange is bounded and length framed. The request carries schema
version, operation `runtime.codex.turn_start`, and the complete
`FinalUseBinding`. The response carries exactly one signed grant or an
explicit denial plus the issuer's revocation head.

## 4. Revocation freshness boundary

The endpoint response can advance the worker's durable monotonic revocation
head before the grant is claimed. `VerifiedUseToken::enter()` then rechecks
expiry and that locally trusted head at effect entry.

This does **not** make the worker an independent revocation-distribution
service. A revocation that exists upstream but has not yet reached the worker
cannot be discovered by `enter()` on its own. Production qualification must
therefore establish the deployed issuer/revocation distribution, trusted time,
peer/socket ACLs, key custody, and an external anti-rollback recovery
procedure. Restoring or relocating the local authority store is not an
independent anti-rollback oracle.

## 5. Tool/effect ceiling

The native runtime.codex client is model-only. Core tool planning recognizes
the deny-only `hepta-infer-worker` client identity and replaces its tool
router with an empty registry and empty model-visible tool set before MCP,
connector, dynamic-tool, extension-tool, or core-tool planning.

This identity is intentionally capability reducing: spoofing it can only remove
tools, not grant an effect. External tool execution therefore requires a
different governed boundary and its own final-use authority; authorizing the
model `turn/start` does not authorize an arbitrary tool effect.

## 6. Lost acknowledgement and replay

The native journal commits the exact runtime.codex request/correlation before
`turn/start`. A transport error, timeout, unknown App Server JSON-RPC error,
or process death after that point is not safe-to-retry evidence.

While the original connection is alive, the caller may recover an exact
`turn/started` event for the same request. After reopen, recovery uses only
the original durable operation identity and exact App Server history; it
requires the same stable client-message identity and original user input.
Mismatch, duplicate matching turns, session/provider drift, or ambiguous
history are hard conflicts or remain indeterminate. No recovery path creates a
new `turn/start` for the same durable operation.

The current native caller uses an ephemeral App Server thread. If App Server
history is no longer available after process loss, repository source cannot
manufacture terminality: the operation remains indeterminate and requires an
independently qualified quarantine/resolution policy. Changing to a persistent
thread/queue admission protocol would be a distinct retention and lifecycle
contract and must be qualified rather than silently substituted.

## 7. Verification boundary

Focused source tests cover exact signed grants, forged grants, explicit denial,
peer identity, revocation rollback, durable write-ahead, pre-effect abort
proof, terminal/correlation semantics, cancellation/deadline behavior, and
restart no-replay behavior.

The Agentd product E2E starts the real Agentd/App Server process composition,
uses the named `AppServerModelDriver`, obtains an independently signed test
grant, drives one controlled mock Responses provider request, and verifies the
durable terminal correlation. That is repository product-composition evidence,
not real-provider or target-host qualification.

Before production activation, independently establish the deployed issuer,
signing-key custody, socket/peer ACLs, trusted time and revocation distribution,
target-host Agentd/App Server identity, real provider terminal stream, any
delegated tool terminal observation, indeterminate-effect operations, canary,
rollback, independent acceptance, promotion, and release.
