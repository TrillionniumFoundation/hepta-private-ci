# OpenBao KV v2 adapter contract

This document freezes the exact interoperability slice currently implemented by
the HeptaBao consumer. It is an API contract record, not a claim that the
consumer is an OpenBao server or that the complete OpenBao KV engine is
implemented.

## Supported request

The adapter emits one request of the following form:

```text
GET /v1/{mount}/data/{path}?version=N HTTP/1.1
X-Vault-Token: <host-injected token>
X-Vault-Namespace: <namespace>       # omitted for the root namespace
Accept: application/json
```

`N` is a non-zero exact version. The mount and path are bounded slash-separated
components. The request also binds the HTTPS origin, supplied CA digest,
namespace, mount, path, field, version, expected secret digest and consumer ID
to an independently signed final-use grant. The adapter does not mint that
grant and has no provider signing key.

The implementation is bound to
[`BaoClient::consume_kv_v2`](../../codex-rs/hepta-bao-adapter/src/https_consumer.rs)
and the request shape is [`BaoReadRequest`](../../codex-rs/hepta-bao-adapter/src/https_consumer.rs).
Only one string-valued field is delivered to the trusted callback. The receipt
contains request, response and secret digests, version and byte count; it never
contains secret bytes.

## Response and failure contract

| Provider observation | Adapter result | Callback invoked |
| --- | --- | --- |
| `200` with matching metadata version and expected digest | `BaoSecretReceipt` | Yes, under the live revocation fence |
| `401` or `403` | `ProviderDenied` | No |
| `404` | `NotFound` | No |
| Other status, invalid TLS, transport failure or timeout | fixed unavailable/timeout error | No |
| malformed JSON or missing field | `InvalidResponse` | No |
| metadata version differs from `N` | `VersionMismatch` | No |
| expected field digest differs | `SecretDigestMismatch` | No |
| callback reports failure after entry | `ConsumerIndeterminate` | It was entered; the grant remains claimed |

There is no automatic retry, write operation, metadata mutation, lease
operation or type coercion. Response and decoded secret buffers are zeroized on
drop; the transport remains bounded to a one MiB response.

## Executable contract evidence

The exact test source is
[`https_consumer_tests.rs`](../../codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs).
The current receipt records 153/153 passing adapter and contract tests in
[`adapter-tests-20260912.json`](evidence/adapter-tests-20260912.json), including
the following versioned API cases:

- exact mount/path/version and token/namespace headers;
- root namespace omission;
- metadata version and secret digest mismatches before delivery;
- `404` and malformed-success response classification;
- signature, revocation, TLS trust, size, timeout and indeterminate-delivery
  fences.

These are source-linked synthetic fixtures. They do not establish a named
production caller, independent acceptance, or complete OpenBao compatibility.
Those gates remain open in [`COMPATIBILITY_MATRIX.json`](COMPATIBILITY_MATRIX.json).
