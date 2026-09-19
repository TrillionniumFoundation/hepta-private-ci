# OpenBao/HeptaBao bounded dynamic SecretLease adapter contract

This document freezes the dynamic lease API slice implemented by
`codex-hepta-bao-adapter`. It is a source contract for the client adapter, not
a claim that the vendored HeptaBao server or any named production deployment has
passed full OpenBao dynamic-engine compatibility.

## V1 issue profile

V1 issues exactly one provider request:

```text
GET /v1/{mount}/{issue_path} HTTP/1.1
X-Vault-Token: <host-injected token>
X-Vault-Namespace: <namespace>       # omitted for root namespace
Accept: application/json
```

`mount`, `issue_path`, subject, consumer and operation identity are bounded
and included in an independently signed final-use binding. V1 intentionally has
no arbitrary issue JSON body and no caller-selected HTTP method.

A successful response must contain:

- a bounded non-empty `lease_id`;
- `lease_duration` in the supported non-zero TTL range;
- `renewable`;
- a non-empty map of string-valued secret fields.

The adapter persists lease metadata before final secret delivery. Secret fields
are serialized only into an application-owned zeroizing buffer and delivered
through the host-owned `TrustedConsumerRegistry`. Raw secret bytes and stable
secret fingerprints are not stored in the lease registry or returned in the
receipt.

## Renew, revoke and lookup

The implemented control endpoints are:

```text
POST /v1/sys/leases/renew
POST /v1/sys/leases/revoke
POST /v1/sys/leases/lookup
```

Renew and revoke require a lease already known to the local registry. Lookup is
read-only and may refresh the observed Active/Missing metadata for a known or
explicitly queried lease ID.

## Durable effect semantics

Every issue/renew/revoke operation has a bounded `operation_id` and canonical
request digest. The local registry persists:

```text
Prepared -> Dispatched -> Succeeded | Rejected | Indeterminate
```

`Dispatched` is durable before network I/O. Once that state exists, timeout,
transport loss, unexpected/5xx status, oversized response, malformed success or
a process crash is not converted to "failed"; the operation is indeterminate
and the same operation ID cannot be blindly dispatched again.

An independently signed reconciliation observation is required to resolve the
operation as:

- `NotApplied`: reopen as `Prepared`, still requiring a fresh final-use grant;
- `Applied`: persist reconciled lease metadata and close as succeeded;
- `Rejected`: close without retry.

A lost issuance response can also lose the newly created provider lease ID.
The generic V1 adapter therefore does not claim automatic issuance
reconciliation. Provider audit/administrative evidence must establish the
outcome before a signed reconciliation observation is accepted.

## Error/side-effect classification

| Observation | Local effect state | Automatic retry |
| --- | --- | --- |
| Authority denied before dispatch | `Prepared` / no provider effect | No; new grant required if retried |
| Explicit provider denial/bad request classified as rejection | `Rejected` | No |
| Valid issue/renew/revoke response | `Succeeded` | No |
| Timeout/transport/5xx/unexpected status | `Indeterminate` | Never |
| Malformed/oversized semantic success | `Indeterminate` | Never |
| Crash after durable `Dispatched` | treated as `Indeterminate` on next prepare | Never |
| Signed external reconciliation = `NotApplied` | `Prepared` | Only with a new final-use grant |

## Qualification boundary

Source tests in
[`lease_lifecycle_tests.rs`](../../codex-rs/hepta-bao-adapter/src/lease_lifecycle_tests.rs)
cover TLS issue/renew/revoke flow and no-blind-retry timeout reconciliation.
The exact-head workflow
[`heptabao-qualification.yml`](../../.github/workflows/heptabao-qualification.yml)
binds those tests, package formatting and strict Clippy to a candidate SHA.

The `leases_dynamic_secrets` OpenBao compatibility row remains `partial`
until a selected real dynamic engine/profile, named product caller and
independent operational acceptance are recorded. Source implementation alone is
not sufficient to close that compatibility blocker.
