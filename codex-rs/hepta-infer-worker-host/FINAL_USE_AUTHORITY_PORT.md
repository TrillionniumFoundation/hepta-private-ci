# runtime.codex final-use authority port

This document describes the concrete final-use authority boundary used by the
native `runtime.codex` App Server caller. It is repository source design, not
proof of a deployed approval service, target-host trust, activation, promotion,
or release.

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

The configuration path must be absolute. Its no-follow open accepts only a
single-link regular file owned by root or the effective worker UID, without
group/world write permission, and reads at most 64 KiB. The socket leaf must
be a socket owned by the configured issuer UID with no world access; its
immediate parent must be a directory without group/world write permission.
The connected peer UID is checked before request bytes are sent. These checks
do not validate every ancestor or establish worker/issuer UID separation:
the host must protect the complete path and provision the trust topology.
The [configuration fields and invocation](../../docs/readiness/LANE_B_NATIVE_HOST.md#native-worker-authority-configuration)
and [configuration/socket implementation](src/final_use_authorizer.rs) are the
source adapter contract, not proof of deployed ACLs.

Wrong peer identity, malformed or oversized frames, unknown fields,
signer/key mismatch, invalid signature, wrong binding, expiry, revoked grant,
nonce replay, stale revocation head, or durable-store failure fail closed
before physical `turn/start`.

### Issuer interoperability

The independent issuer implements the request/response types in
[`final_use_authorizer.rs`](src/final_use_authorizer.rs) and the grant/binding
types in [`hepta-contracts/final_use.rs`](../hepta-contracts/src/final_use.rs).
The worker does not start an issuer service. Each exchange opens one Unix
connection, sends one request and reads one response. Each frame is a
four-byte unsigned big-endian JSON byte length followed by exactly that many
UTF-8 JSON bytes; it has no line delimiter. Request length is 1 through
16 KiB and response length is 1 through 64 KiB. The configured exchange
timeout is 1 through 30000 ms and also consumes the native request's remaining
absolute deadline.

Wire field names are snake_case and all these types reject unknown fields.
The request object contains exactly `schema_version: 1`,
`operation: "runtime.codex.turn_start"`, and `binding`. The binding contains
`subject_id`, `destination_id`, `request_sha256`, `scope_sha256` and
`payload_sha256`. Its digests are JSON arrays of exactly 32 integers in
0 through 255, not hex or base64 strings, and must be nonzero.

The response object has the following fields:

| Field | Exact value or representation |
| --- | --- |
| `schema_version` | Integer `1` |
| `revocations` | Object containing nonzero `authority_epoch`, nonzero `revision`, and `revoked_grant_ids`, an array of grant-ID strings representing a set |
| `grant` | A signed-grant object for approval, otherwise `null` or omitted |
| `denial_reason` | A nonempty string of at most 1024 UTF-8 bytes for denial, otherwise `null` or omitted |

Exactly one of `grant` and `denial_reason` must be non-null. The revocation
head is required for either outcome. An identical head is accepted; an update
must increase revision, cannot decrease epoch, and cannot remove revoked IDs
within the same epoch. Revocation-head authentication comes from the protected
Unix channel and pinned peer UID. The grant's Ed25519 signature does not sign
the response or its separate `revocations` field. The issuer must authenticate
and authorize its callers and obtain any policy inputs needed to approve the
exact binding; the request carries digests, not the original prompt or full
model/provider context.

A signed-grant object contains `grant` and `signature`. The nested `grant`
contains, in its Rust serialization order, `schema_version`, `signer_id`,
`authority_epoch`, `grant_id`, `nonce`, `binding`, `not_before_unix_ms`, and
`expires_at_unix_ms`. Its schema version is `1`, signer must match the pinned
configuration and epoch must match the current trusted head. `nonce` is a
nonzero 32-byte integer array; `signature` is a 64-byte Ed25519 integer array.
The returned binding must equal the requested binding. Signer, grant, subject,
destination and revoked-grant identifiers contain 1 through 128 ASCII
letters/digits or `_-.:/`.

The authoritative signing input is `FinalUseGrant::signing_bytes()`:
the bytes `hepta.kernel.authority.final-use.v1` followed by one NUL byte,
then the compact `serde_json::to_vec` serialization of the unsigned grant in
the declaration order above. The nested binding uses the declaration order
listed for the request. This is the existing Rust serialization contract,
not a generic canonical-JSON algorithm; do not sign the received JSON text,
the outer response, a hex/base64 representation, or the signature field.
Reuse `signing_bytes()` where possible. Timestamps are unsigned Unix
milliseconds, with `not_before_unix_ms <= now < expires_at_unix_ms` and a
positive grant lifetime no longer than 300000 ms. The
[issuer fixture](src/final_use_authorizer_tests.rs) demonstrates framing and
signing against these exact source types; it is not a deployed service.

## 4. Revocation freshness boundary

The endpoint response can advance the worker's durable monotonic revocation
head before the grant is claimed. `VerifiedUseToken::enter()` then rechecks
expiry and that locally trusted head at effect entry.

This does **not** make the worker an independent revocation-distribution
service. A revocation that exists upstream but has not yet reached the worker
cannot be discovered by `enter()` on its own. The current Unix adapter calls
`FinalUseAuthority::open_state_dir`: it uses one pinned key, the system clock,
and no external `AuthorityFrontierStore`. The shared authority also exposes a
constructor accepting an issuer key ring, host clock and external frontier,
but this CLI and its configuration do not compose it. That host integration
remains source work,
in addition to independently qualifying the deployed issuer/revocation
distribution, trusted time, peer/socket ACLs, key custody and anti-rollback
recovery procedure. Restoring or relocating the local authority store is not
an independent anti-rollback oracle.

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
