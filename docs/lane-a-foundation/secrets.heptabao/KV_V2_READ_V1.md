# HeptaBao exact KV-v2 read boundary V1

## Request binding

The request binds subject, named consumer, endpoint origin, pinned CA digest,
namespace, mount, path, field, exact nonzero version and expected nonzero secret
digest. The final-use destination is `provider:heptabao`.

The scope digest intentionally covers origin, namespace, mount and consumer.
The full request digest additionally covers path, field, version, expected
secret digest and subject. Policy authors must not confuse the broader scope
digest with the complete operation binding.

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
4. Compute metadata-only receipt.
5. Recheck live authority and enter the synchronous registered consumer.
6. Return the receipt only after successful consumer return.

A consumer failure after entry is indeterminate. No automatic retry occurs.

## Missing production composition

This slice does not itself persist an operation intent, append evidence or
settle quota. The host must supply those steps before production activation.
