# Registered HeptaBao consumption saga V4

This document is the current executable contract for the registered,
operation-aware KV-v2 read path. The machine-readable states and source anchors are maintained in
`MODULE_MANIFEST_V1.json`; exact source and merge identities are supplied by CI
receipts rather than embedded into this document.

The low-level `BaoClient` API is a trusted adapter. The durable product ingress
is `BaoFinalUseHost::consume_kv_v2_with_authbus`. It combines independent grant
approval, revocation freshness, AuthBus policy/quota authority, a registered
consumer profile and the durable consumption owner. No recovery path fetches a
secret again or invokes the consumer effect again.

## Durable states

| State | Durable fact | Only permitted recovery |
|---|---|---|
| `Claimed` | operation ID and exact semantics are committed; no reservation is implied | atomically seal non-admission in AuthBus or bind its original reservation; a SELECT absence cannot close the operation |
| `Reserved` | the original AuthBus reservation is bound; dispatch is not fenced | query the reservation; cancel or expire `Held`, then record a terminal pre-dispatch abort |
| `DispatchFenced` | `mark_dispatch_attempted` committed for the exact effect digest | never redispatch; reconcile the original provider/consumer outcome and reservation |
| `DeliveryPrepared` | a validated metadata receipt is committed before final authority recheck | query the original registered observer; receipt alone is not consumer-entry proof |
| `Indeterminate` | dispatch or consumer entry may have happened | query original observer and original reservation only |
| `ConsumerSucceeded` | observer/callback success and receipt terminal digest are durable | idempotently settle original reservation and commit `Succeeded` |
| `ConsumerNotApplied` | observer supplied nonzero immutable negative evidence | settle as `Rejected`, observed cost zero, then commit `Failed` |
| `ProviderFailed` | deterministic provider category and terminal evidence are durable | apply the recorded charging policy, settle the original reservation, then commit `Failed` |
| `Succeeded` | consumer success and AuthBus settlement are both recorded | return the historical metadata receipt only |
| `Failed` | an immutable negative outcome and its abort/settlement proof are recorded | return the historical terminal error only |
| `DispatchAttempted` | legacy schema-3 conservative state | find and bind the original reservation, then migrate to `Reserved` or `DispatchFenced`; never redispatch |

The table defines the required recovery action, not proof that every boundary
has passed native crash qualification. In particular, post-dispatch rows without
a durable response receipt cannot currently query a provider-side operation
observer; they remain pending. Unknown facts do not become success, refund or a
fresh attempt.

## Forward sequence

1. Verify registered consumer profile, independent approval and revocation-feed freshness.
2. Compute the exact request/effect/semantic digests.
3. Commit `Claimed` before contacting AuthBus.
4. Obtain trusted time, authorize and reserve quota.
5. Commit `Reserved` with the returned reservation identity.
6. Re-sample authenticated time and call AuthBus `mark_dispatch_attempted`.
7. Only after that call succeeds, commit `DispatchFenced`.
8. Perform the exact pinned-CA KV-v2 read without retry.
9. For deterministic provider failure, commit immutable `ProviderFailed` evidence before settlement.
10. For a valid response, commit `DeliveryPrepared` before the final live-authority check.
11. Enter the registered consumer only on the new-operation path. Commit success or `Indeterminate`; this does not prove exactly-once external effects.
12. Settle the original reservation from signed evidence.
13. Commit the local terminal state.

An exact duplicate transition is a no-op. Reusing an operation ID with changed
semantics, reservation identity, terminal category, evidence digest or cost is a
conflict.

## Failure classification

Transport failure, timeout, final-authority failure and consumer acknowledgement
loss are ambiguous after the dispatch fence. They remain held/indeterminate and
must be observed; they are never converted to a refund.

Provider denial, unsupported/unavailable response, missing exact value,
oversize response, malformed payload, version mismatch and secret-digest
mismatch are immutable provider terminal categories for this read-only effect.
The current charging policy records the reserved amount as observed cost. That
policy is explicit durable metadata and must not be inferred from an error string
on restart.

The legacy observer value `NotApplied` remains pending. Only
`NotAppliedWithEvidence { evidence_sha256 }` with a nonzero immutable digest is a
terminal negative outcome eligible for AuthBus `Rejected` settlement.

## Restart reconciliation

`AuthBusAuthorityHost::reservation_by_operation` searches hot and archived
reservations in one transaction. Missing local bindings are recovered through
`seal_unreserved_operation(operation, effect)`: its write transaction returns the
original reservation or commits an immutable non-admission fence. A late reserve
cannot commit after the fence. Read-only absence is never a negative proof.
Recovery validates operation ID, amount and effect digest before adopting a
reservation. The registry-shared operation guard prevents a live dispatch and
recovery from entering the same identity concurrently; it is not a substitute
for the durable seal. See `remediation/ADMISSION_FENCE_V1.md`.

A `Held` reservation proves no dispatch fence. Recovery cancels it, or expires
it under authenticated time, before committing the local terminal abort. A
`DispatchAttempted` or `Indeterminate` reservation promotes the local row to the
conservative post-fence state. A settled/released reservation is accepted only
when its terminal evidence and observed cost exactly match the local immutable
terminal record.

## Crash-injection matrix

Qualification must kill the process on both sides of each boundary and reopen
the durable owners:

- durable claim;
- trusted-time observation and authorization;
- quota reserve;
- local reservation bind;
- AuthBus dispatch fence;
- local dispatch-fence commit;
- provider response and terminal classification;
- delivery preparation;
- final authority check and consumer entry;
- consumer acknowledgement;
- signed settlement;
- local terminal commit.

The oracle is not merely “no duplicate receipt.” It must prove no blind
redispatch, no orphan reservation, no semantic drift, no invented negative
outcome and an explicit recovery action for the resulting state.

## Storage profiles

`DurableLeaseRegistryV1` remains a bounded JSON reference owner and migration
oracle. It is not the production throughput target. A production SQLite replacement is still pending in this source candidate.
Staged or partially recovered patches are not an executable owner. Migration,
independently retained anti-rollback state, bounded archival, nonblocking writer
integration and target-host power-loss qualification remain open. No missing
`SQLITE_OWNER_V1.md` or staged payload is evidence that this work is complete.

## Nonclaims

The fixed HeptaBao provider supports the qualified exact KV-v2 read contract.
Generic provider-native dynamic issue, renew and revoke remain blocked and
fail-closed. Source composition, synthetic tests and CI receipts do not activate
a normal Agentd/App Server process, grant independent acceptance, or authorize
promotion or release.
