# secrets.heptabao security invariants

## Raw secret boundary

Dynamic secret values may exist in the provider response buffer, zeroizing decoded string owners and the trusted synchronous consumer callback. They are not fields of `SecretLeaseRecord`, not returned in lifecycle receipts and not written to the evidence database.

The dynamic path deliberately does not persist a per-value `value_sha256`. Ordinary SHA-256 of a low-entropy credential can become a long-lived offline fingerprint. If a future audit need requires value correlation, it needs an explicit sensitivity/retention design and should prefer a scoped keyed construction rather than silently adding raw digests to general evidence.

## Trusted final consumer

The callback is a privileged host-selected capability, not a sandbox. A signed `consumer_id` binds the authorized identity but cannot prove that an arbitrary closure supplied by untrusted in-process code is that consumer.

The host must choose callbacks from a protected registry/composition boundary. Callback implementations must be bounded, non-reentrant with FinalUse authority and forbidden from copying secret bytes into model context, telemetry, logs, long-lived caches or unrelated receipts.

## Dynamic final-use binding

For static KV v2 reads, the grant binds the expected secret digest because that value is known before dispatch.

For provider-native dynamic issuance the future credential value is unknowable before the provider creates it. The grant therefore binds the exact issuance request, CA/origin, namespace, provider path, selected fields, logical lease key, subject and final consumer. Secret delivery still requires the live post-response final-use recheck. Do not describe dynamic issuance as pre-binding the unknown credential bytes.

Renew/revoke/reconcile grants bind the durable lease identity, provider lease ID, revision and exact operation request.

## Zeroization boundary

Application-owned response buffers, selected dynamic strings and dynamic request-body values use `Zeroizing`. This reduces retention after use. It does **not** prove plaintext never existed elsewhere in RAM: TLS records, HTTP buffers, JSON parser temporaries, allocator behavior, kernel buffers, crash dumps and a trusted consumer can create copies.

Documentation and security claims must use this narrower statement.

## Privileged metadata

Provider lease IDs can authorize lookup, renew or revoke operations and are treated as privileged metadata. Debug output for `SecretLeaseRecord` redacts the provider lease ID. General model/log receipts should use logical lease key/state/revision rather than exporting provider handles.

The provider token remains a host-enrolled secret, uses a sensitive HTTP header and has redacted Debug output.

## Transport

The same pinned direct HTTPS client used by KV v2 is used for lifecycle APIs. Ambient proxies, ambient trust roots, redirects, request diagnostics, automatic retries and ambient trace propagation remain disabled by the enrolled transport.
