# secrets.heptabao failure and recovery

## Crash/timeout matrix

| Window | Durable state after restart | Recovery rule |
| --- | --- | --- |
| final-use nonce claimed, lease intent not created | no lease operation | grant is burned; obtain new authority if the host still wants the operation |
| `Requesting` committed, process dies before send | `Requesting` | indistinguishable from death after send; never reissue generically |
| issuance sent, response lost before lease ID observed | `Requesting` or `Unknown` without lease ID | provider-specific/operator reconciliation required |
| issuance lease ID observed but success cannot be durably completed | fail-closed pending/unknown if persistence is available | retain/lookup the provider lease ID when possible; never return secret values before `Active` is durable |
| `Renewing` committed, response lost | `Renewing` or `Unknown` with lease ID | lookup; positive TTL becomes a reconciled active observation, not-found becomes expired |
| `RevokePending` committed, response lost | `RevokePending` or `Unknown` with lease ID | lookup; not-found is revoked; still-present is not proof of safe retry |
| provider success persisted `Active`, final consumer fails | `Active` | result is `ConsumerIndeterminate`; do not infer that the consumer had no side effect |
| FinalUse claim appended, process dies | nonce remains in `authority.claims` | replay is rejected after restart |
| authority epoch update persists new head, process dies before journal reset | new epoch + old claims | safe over-denial; restart may compact only under the already stronger epoch |

## Unknown is a quarantine state

`Unknown` is not a retry queue. It means the system lacks enough evidence to assert the terminal provider outcome. Only a provider status lookup, engine-specific idempotency evidence or an explicit operator reconciliation can leave it.

The generic adapter does not manufacture an operation key that OpenBao does not support.

## Store failure

A CAS/store error after an external effect may hide a stronger provider state than the local row. Treat the operation as unresolved and repair the authoritative store without resetting/reusing the logical lease key. Do not delete a conflicting record to make a retry possible.

The FinalUse filesystem owner similarly fences itself after persistence errors. Missing/corrupt authority state never becomes a new empty replay registry.

## Clock behavior

Lease expiration is projected from the provider TTL and the host wall clock. Clock failure/overflow rejects the transition. A distributed deployment must provide an operationally trustworthy clock; this module does not pretend local wall time is an anti-rollback oracle.

## Operator recovery

Recovery tooling should surface lease key, state, provider namespace/path, provider lease ID when available, operation ID, revision and last error code. It must not print provider token, dynamic secret values, request-body values or model-facing secret fingerprints.
