# Native gateway authenticated-read subprotocol v2

## Ownership and compatibility

The shared executable contract is `codex-rs/hepta-contracts/src/native_gateway.rs`.
The server remains `codex-hepta-native-gateway`, and the client remains
`apps/hepta-native/src/backend.rs` plus `native_http.rs`. This is a versioned
transport-authentication subprotocol of the existing runtime presentation port;
it neither changes `ModulePort::runtime.agentd::ui.native` domain semantics in
place nor creates a writer, signer, effect grant or second runtime owner.

The product native application now requires a signed endpoint manifest with
`protocol_version: 2`. It does not fall back to sending its secret as a bearer.
Legacy non-native bearer consumers still receive the separately identified v1
health response. Deploy the compatible gateway first, then independently sign a
v2 endpoint manifest for the same provisioned keyring account. Do not edit a
signed manifest without reissuing its signature. Rolling back to an old v1
client also requires an explicitly selected compatible configuration; a failed
v2 bootstrap is not a reason to silently re-enable unauthenticated access.

## Request proof

The existing random keyring capability is the HMAC-SHA256 key. The capability
never appears in a native network request, general log or receipt. A native
request sends exactly one header:

```text
Authorization: Hepta-MAC-V2 <issued-ms>:<nonce-hex>:<server-incarnation-hex>:<tag-hex>
```

The nonce is 32 CSPRNG bytes, encoded as 64 lowercase hex characters. The
initial `GET /healthz` may use a zero server incarnation. Its authenticated
response supplies the server's random per-process incarnation; every subsequent
`GET /api/hepta/runtime` proof binds that incarnation. A restarted gateway thus
rejects an old runtime-read proof even though its in-memory replay cache is new.

Request MAC input is the concatenation of:

1. `hepta.native-gateway.request.v2\0GET\0`;
2. the exact allowlisted path and one zero byte;
3. issue time as an unsigned 64-bit big-endian integer;
4. 32-byte request nonce; and
5. 32-byte server incarnation.

Only these two exact GET routes are admitted by v2; request bodies, alternate
HTTP versions and mutated paths are rejected. The proof expires 30 seconds after
issue and admits at most five seconds of future clock skew. A mutex-protected
4096-entry live-nonce cache rejects duplicates and overflow without dropping
still-valid entries. The existing 64-connection and request-byte ceilings remain.
These are bounded read proofs, not effect permissions.

## Response proof and framing

Each native response supplies exactly one `X-Hepta-Response-MAC` header. Its MAC
input is the concatenation of the response-domain tag
`hepta.native-gateway.response.v2\0`, request MAC bytes, HTTP status as u16
big-endian, body length as u64 big-endian, and the exact body bytes. Verification
uses the HMAC library's constant-time verifier before decoding JSON. The status,
body and originating request cannot be substituted independently.

The client enforces one total three-second deadline across connection, writes
and reads; incremental progress does not extend it. HTTP headers are bounded to
16 KiB and the entire response to 1 MiB. Native v2 requires a single decimal
Content-Length, a JSON Content-Type and a single response MAC; Transfer-Encoding,
duplicate critical headers, overlong bodies and trailing bytes are rejected.
No fake localhost listener can become authenticated merely by returning
`product=hepta` or by echoing an authentication-mode string.

## Evidence and limitations

Tests are `native_gateway_tests.rs` in the shared owner, `native_mac_tests.rs` in
the gateway, and `tests/backend.rs`, `tests/backend_security.rs` plus
`src/native_http_tests.rs` in the native client. The Linux product qualification
script additionally starts the real gateway against an isolated owner-format
SQLite fixture and uses the actual OS keyring and normal packaged GUI entry.
A fixture is not a production data initializer or independent acceptance.

The subprotocol authenticates, but does not encrypt, these loopback reads. It
does not defend against an attacker that can already read the user's keyring or
control the trusted gateway process. Revocation of platform effects continues
through the current kernel final-use authority, independently of this transport.
