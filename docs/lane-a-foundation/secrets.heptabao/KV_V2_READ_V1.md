# Legacy/raw HeptaBao exact KV-v2 read subpath V1

> **Scope:** this document specifies only the low-level trusted `BaoClient`
> subpath. It is not the module-wide implementation contract and it is not the
> registered durable product ingress. The current module contract is
> `docs/modules/secrets.heptabao/CONSUMPTION_SAGA_V4.md`.

## Request binding

The request binds subject, named consumer, endpoint origin, pinned CA digest,
namespace, mount, path, field, exact nonzero version and expected nonzero secret
digest. The final-use destination is `provider:heptabao`.

The scope digest covers origin, namespace, mount and consumer. The full request
digest additionally covers path, field, version, expected secret digest and
subject. Policy authors must not confuse the broader scope digest with the
complete operation binding.

## Network boundary

Only HTTPS root origins are accepted. Userinfo, query, fragment and non-root
paths reject at client construction. Ambient roots, proxies, redirects and
protocol retries are disabled. Provider 401/403, 404, other statuses, timeout,
oversize response, malformed JSON, version mismatch and secret digest mismatch
never invoke the consumer.

## Final-use sequence

1. Build and validate the complete binding.
2. Claim the independently signed nonce before network dispatch.
3. Read and validate exactly one string field/version.
4. Compute a metadata-only receipt.
5. Recheck live authority and enter the synchronous trusted consumer.
6. Return the receipt only after successful consumer return.

A consumer failure after entry is indeterminate. No automatic retry occurs.

## Deliberate limitations

This low-level path does not itself own durable operation identity, AuthBus quota
reservation, restart reconciliation or registered consumer configuration. A
production caller must use `BaoFinalUseHost::consume_kv_v2_with_authbus` and the
V4 saga. Only read operations exist here; generic provider issue, renew, revoke
and mutation remain fail-closed.
