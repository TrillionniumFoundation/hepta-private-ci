# SecretLease lifecycle design

## Invariants

A logical lease has one durable `lease_key`. The provider namespace/path and original issuance request digest are immutable. Provider lease identity is nullable until observed and immutable after observation. Every mutation increments `revision` exactly once and must win a store compare-and-swap.

Raw dynamic secret values are outside the durable model.

## State machine

| State | Meaning | Allowed next states |
| --- | --- | --- |
| `Requesting` | local issuance intent is durable; provider outcome may not yet be known | `Active`, `Unknown`, `Rejected` |
| `Active` | a provider lease ID and positive TTL are known | `Renewing`, `RevokePending`, `Expired` |
| `Renewing` | renew intent is durable before provider dispatch | `Active`, `Unknown`, `Expired` |
| `RevokePending` | revoke intent is durable before provider dispatch | `Active` for deterministic no-effect rejection, `Revoked`, `Unknown` |
| `Unknown` | an earlier effect cannot be safely inferred | `Active`, `Revoked`, `Expired`, or `Rejected` only with reconciliation evidence |
| `Revoked` | provider lease is confirmed absent/revoked | terminal |
| `Expired` | provider lease is confirmed absent/expired | terminal |
| `Rejected` | issuance was deterministically rejected before a lease was created | terminal |

The operation identifier and operation-request digest remain attached while an operation is pending or unknown.

## Issuance

`request_secret_lease` performs this sequence:

1. validate and hash the complete provider request, selected secret fields, namespace, path and registered consumer;
2. claim independent final-use authority;
3. atomically create `Requesting`;
4. dispatch only if this caller received `SecretLeaseCreateDisposition::Inserted`;
5. parse a provider-native `lease_id`, `lease_duration`, `renewable` and selected string values;
6. persist `Active` before delivering any selected value;
7. recheck final-use authority and invoke the synchronous trusted callback.

A second exact caller that observes `AlreadyPresent` does not dispatch. A changed caller reusing the same lease key conflicts.

A successful provider response that cannot be safely decoded is ambiguous because the provider may already have created a credential. If a valid lease ID was observed it is retained in `Unknown` so lookup can reconcile it. If no lease ID was observed, the generic implementation cannot prove provider state and does not retry.

## Renewal

`renew_secret_lease` requires `Active + renewable`, claims authority and CASes to `Renewing` before calling `POST /v1/sys/leases/renew`.

The requested increment is advisory. A successful response must return the same provider lease ID plus a positive provider TTL; the returned TTL/renewable values become the next `Active` observation and the generation increments.

A deterministic client rejection restores the previous active generation with an error code. Provider-not-found resolves to `Expired`. Transport loss, 5xx, malformed success or lease-ID mismatch resolves to `Unknown`.

## Revocation

`revoke_secret_lease` CASes `Active -> RevokePending` before calling `POST /v1/sys/leases/revoke` with `sync=true`.

Success and provider-not-found resolve to `Revoked`. A deterministic no-effect client rejection can restore `Active`. An ambiguous outcome resolves to `Unknown`; it is never blindly repeated.

## Reconciliation

Known provider lease IDs are checked with `POST /v1/sys/leases/lookup`.

- uncertain issuance/renew + positive TTL: resolve to a new `Active` observation;
- uncertain issuance/renew + not found: resolve to `Expired`;
- uncertain revoke + not found: resolve to `Revoked`;
- uncertain revoke + still present: remain unresolved because presence at one instant does not prove a previously submitted synchronous revoke cannot still complete;
- issuance with no locally observed provider lease ID: `ReconciliationRequired`.

Provider-specific engines may add a stronger operation-key lookup, but must not weaken these generic rules.

## Concurrency

The store, not an in-process mutex, owns lifecycle serialization. `create` returns the durable insert winner and `compare_and_swap(expected_revision, next)` is required to be linearizable for one lease key. A stale caller loses before crossing a new provider mutation boundary.

See [HA_AND_STORAGE.md](HA_AND_STORAGE.md) for backend requirements.
