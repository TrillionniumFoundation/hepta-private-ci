# Authorized HeptaBao HTTPS consumer

`codex-hepta-bao-adapter` implements a narrowly enrolled read-only secret-use
boundary. Only read operations exist here. Generic provider issue, renew,
revoke and mutation remain fail-closed at the fixed provider pin.

The canonical semantic manifest is
`docs/modules/secrets.heptabao/MODULE_MANIFEST_V1.json`. The current registered
durable contract is
`docs/modules/secrets.heptabao/CONSUMPTION_SAGA_V4.md`. Historical validation
observations are retained separately in
`docs/modules/secrets.heptabao/evidence/HISTORY.md`.

## Supported provider contract

`BaoClient` reads exactly one string field from one exact KV-v2 version using
`GET /v1/{mount}/data/{path}?version=N`. It supplies `X-Vault-Token` and, for a
non-root namespace, `X-Vault-Namespace`. Construction accepts only an HTTPS root
origin with no userinfo, query or fragment. The client pins the supplied CA,
validates the hostname, disables ambient roots, proxies, redirects, protocol
retries, request diagnostics and ambient trace propagation, and caps the full
response at one mebibyte.

The fixed provider is
`HeptaBao@eac9c608bfda77a8972e1e8a1343dfc21985d62b`. Isolated probing proves the
KV-v2 read contract and separately records that generic dynamic lease endpoints
are unavailable. Healthy KV reads are not evidence for dynamic issue/renew or
revoke.

## Authority and final use

Before provider dispatch, `FinalUseAuthority` verifies an independently signed,
single-use Ed25519 grant bound to subject, consumer, origin, CA, namespace,
mount, path, field, version and expected secret digest. The adapter owns no
issuer key. After response validation, live time/epoch/revocation state is
checked again immediately before consumer entry.

`BaoFinalUseHost` is the registered composition boundary. The signed consumer ID
must resolve in a closed registry. Operation-aware registrations bind a nonzero
immutable configuration digest, callback and observer. The exact grant also
requires an independent operator approval, and revocation freshness comes only
from an independently pinned signed feed.

## Durable registered ingress

`BaoFinalUseHost::consume_kv_v2_with_authbus` is the operation-aware ingress. It
persists `Claimed`, then `Reserved`, and only after AuthBus
`mark_dispatch_attempted` succeeds persists `DispatchFenced`. It commits the
validated metadata receipt before final authority recheck and records consumer
success, evidence-bound negative outcome or uncertainty without storing secret
bytes.

A retry of an incomplete identity never redispatches. Use
`reconcile_consumption`; it looks up the original hot or archived AuthBus
reservation by operation ID, validates operation/effect/amount identity, queries
the original registered observer and settles only immutable terminal evidence.
A completed result is historical evidence, not fresh authority.

## Reference and production owners

`DurableLeaseRegistryV1` is a bounded Unix JSON reference owner. It uses an
owner-only directory/files, a lifetime writer lock, `NOFOLLOW`, single-link
checks, write-and-fsync replacement, rename and parent-directory fsync. A
post-rename durability failure fences the handle. It retains no provider token
or secret value.

The JSON owner is deliberately not a high-throughput production ledger. The
SQLite owner and migration/anti-rollback contract are described in
`docs/modules/secrets.heptabao/SQLITE_OWNER_V1.md`; production activation remains
false until target-host qualification and an external monotonic checkpoint
service are complete.

## Secret handling

Response buffers and decoded strings are zeroized on drop where controlled by
this crate. TLS, HTTP and operating-system internals may retain transient copies;
this is not a locked-memory guarantee. Secret/value SHA-256 fields are sensitive
metadata and may support offline guessing for low-entropy values. Exclude them
from general telemetry and apply bounded retention.

Registered consumers must be synchronous and bounded, must not re-enter the
authority while inside the final-use callback, and must never copy secret bytes
into prompts, logs, learning records or ordinary receipts.

## Verification

Run the independent native qualifier on an exact checkout:

```text
python3 codex-rs/hepta-bao-adapter/qa/qualify.py \
  --expected-sha <HEAD> \
  --candidate-role source-head \
  --output <evidence-dir>
```

A deterministic merge job supplies the synthetic merge identity separately.
Receipts bind source/tree, merge/tree, Rust toolchain, OS/architecture,
`Cargo.lock`, provider binary evidence and the canonical manifest. Committed
documents do not attempt to contain the hash of the commit that contains them.

The isolated real-service read fixture remains available through
`qa/real_service_smoke.py`; the dynamic-contract probe is
`qa/probe_dynamic_lease_contract.py`. Neither may contact an existing production
service. Unsupported dynamic endpoints are a blocker and must exit nonzero.

## Nonclaims

Source composition is not a selected Agentd/App Server bootstrap. Test keys are
synthetic. External trusted time, settlement signing, key rotation, revocation
distribution, backup anti-rollback, operator acceptance, canary, promotion and
release remain independently owned gates.
