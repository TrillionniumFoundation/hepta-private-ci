# runtime.codex final-use authority port

This port composes the native Codex App Server caller with the independently
owned `kernel.authority` final-use boundary. It is a source interface, not a
deployment or approval-policy implementation. The worker never owns an issuer
private key and never invokes `hepta-final-use-signer` to authorize its own
request.

## Effect boundary

The native worker assembles the final v2 `TurnStartParams` only after the
Agent generation, App Server session/thread, selected model/provider and
context attachment are known. It serializes those exact params, computes the
payload digest, builds the runtime.codex request digest and then derives a
`FinalUseBinding` containing:

- the Agent UUID as `subject_id`;
- `provider:codex-app-server` as the destination;
- the exact runtime.codex request digest;
- a scope digest covering session, thread, model, provider, owner generation
  and App Server protocol version;
- the exact serialized `TurnStartParams` digest.

No `turn/start` request is sent without a non-constructible
`VerifiedUseToken` for that exact binding. Authority acquisition consumes the
same runtime.codex deadline as the model attempt. After the external authority
await, the worker rechecks cancellation, the exact Agent generation/readiness,
the App Server ingress path and the request deadline. `VerifiedUseToken::enter`
then rechecks binding, time, epoch and revocation state. The durable native
journal records the authority witness and exact request/payload digests after
that one-entry check but before the first App Server `turn/start` await. Thus a
failure before the write-ahead record is definitely unsent; a crash or
acknowledgement loss after it is reconcile-only.

## Protected host configuration

`hepta-infer-worker --profile native-app-server` requires
`--final-use-authority-config ABSOLUTE_JSON`. The file must be absolute, regular and non-symlink. It must be owned by root or
the worker's effective UID and must not be group/world writable; this permits a
root-owned read-only production trust file without giving the worker account
write access. Unknown fields are rejected.

Example shape:

```json
{
  "issuer_socket": "/run/hepta-authority/final-use.sock",
  "issuer_uid": 0,
  "signer_id": "security-owner",
  "verifying_key": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
  "authority_state_dir": "/var/lib/hepta/final-use/runtime-codex",
  "authority_epoch": 1,
  "revocation_revision": 1,
  "revoked_grant_ids": [],
  "issuer_timeout_ms": 5000
}
```

The example key is deliberately invalid as production trust material. Provision
the real Ed25519 public key, signer identity and trusted revocation head through
the protected host configuration channel. `authority_state_dir` remains the
durable nonce/revocation owner and is subject to the invariants in
`hepta-contracts/FINAL_USE.md`.

The authority socket path must be absolute. The socket inode must be owned by
the configured `issuer_uid`, must not be world accessible, and its parent
directory must not be group/world writable. Target-host qualification still
has to establish the intended service identity, ACL/group policy, key custody,
clock and revocation distribution.

## Wire protocol

The client uses one bounded Unix stream exchange per claim. Frames are
4-byte big-endian length followed by compact JSON.

Request, maximum 16 KiB:

```json
{
  "schema_version": 1,
  "operation": "runtime.codex.turn_start",
  "binding": {
    "subject_id": "...",
    "destination_id": "provider:codex-app-server",
    "request_sha256": [0],
    "scope_sha256": [0],
    "payload_sha256": [0]
  }
}
```

The digest arrays shown above are abbreviated documentation only; the Rust
schema requires exactly 32 bytes for every digest.

Response, maximum 64 KiB:

```json
{
  "schema_version": 1,
  "revocations": {
    "authority_epoch": 1,
    "revision": 1,
    "revoked_grant_ids": []
  },
  "grant": null,
  "denial_reason": "policy denied"
}
```

Exactly one of `grant` and `denial_reason` is present. A grant is a normal
`SignedFinalUseGrant`. Before claiming it, the client synchronizes the
endpoint's revocation head through `FinalUseAuthority::update_revocations`;
equal heads are accepted, forward-only heads are persisted and any rollback or
revocation removal is rejected. The signed grant is then verified against the
pinned key and exact requested binding, and its nonce is durably consumed.

## Failure and replay semantics

Missing configuration, unsafe files/socket metadata, endpoint timeout,
malformed/oversized replies, explicit denial, stale revocation head, invalid
signature, wrong binding, expiry, revoked grant, reused nonce or unsafe
authority storage all fail closed before `turn/start`.

Once `VerifiedUseToken::enter` succeeds, the capability cannot authorize a
second entry. The worker durably writes the dispatch binding before the actual
`turn/start` network await. A lost `turn/start` acknowledgement is therefore
never turned into a blind retry; the native control journal retains the slot
and reconciles the original stable request through
`thread/read(includeTurns=true)`.

The independent authority endpoint owns approval policy and private-key
custody. This repository client protocol does not make an automatically
granting signer production-safe, and source tests do not prove a deployed
authority service, provider run, independent acceptance, activation, canary,
promotion or release.
