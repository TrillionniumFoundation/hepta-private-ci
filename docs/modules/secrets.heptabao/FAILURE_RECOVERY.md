# secrets.heptabao failure and recovery

## Outcome classes

Before `Dispatched`, failure proves that no provider request was intentionally
sent by the operation. The durable record may remain `Prepared`; retry requires
a fresh final-use grant because any already claimed nonce is never refunded.

After `Dispatched`, only an explicit provider response with validated semantics
can establish `Succeeded` or `Rejected`. The following are indeterminate:

- request timeout or cancellation;
- connection loss after dispatch;
- provider 5xx/unexpected status where an effect may already have occurred;
- oversized response after a successful/effectful request;
- malformed success body;
- success body whose lease identity or TTL violates the typed contract;
- process death while the durable state is `Dispatched`.

Indeterminate means "the effect may have happened." It never means failure.

## Recovery matrix

| Durable state | Safe action |
| --- | --- |
| `Prepared` | Obtain a fresh grant and dispatch once. |
| `Dispatched` after restart/next prepare | Convert/treat as `Indeterminate`; do not dispatch. |
| `Indeterminate` | Reconcile externally; do not blind retry. |
| `Succeeded` | Do not redeliver a dynamic secret from storage; only metadata remains. |
| `Rejected` | Treat the operation identity as terminal. |

For a known lease ID, `lookup_secret_lease` can refresh provider observations.
For an issuance whose response and lease ID were lost, use external provider
audit/administrative evidence and submit a signed reconciliation observation.

A signed `NotApplied` observation is the only transition that reopens an
indeterminate operation for dispatch under the same operation ID. The next
dispatch still requires a new final-use grant/nonce.

## Crash ordering

Issuance ordering is deliberately:

1. persist `Prepared`;
2. claim/burn final-use nonce;
3. persist `Dispatched`;
4. perform one provider request;
5. validate response;
6. persist provider lease metadata and `Succeeded`;
7. revalidate live final-use authority;
8. synchronously deliver secret material through the registered consumer.

Crashes before step 3 cannot have been caused by an intentional provider
dispatch in this path. Crashes from step 3 through step 6 are indeterminate.
Crashes after step 6 do not lose the lease identity, even if secret delivery was
never completed.

Renew/revoke use the same durable dispatch ordering without secret delivery.

## Authority-store recovery

Replay claims are append-only checksummed records. A partial/corrupt claim
record, unsafe permissions, invalid trust key/head, missing initialized state or
I/O failure fails closed.

Deleting/restoring authority state is not a replay-safe repair. After loss or
rollback, the owner must independently advance/rotate authority trust before
accepting grants that could overlap the lost history.

## Lease-registry recovery

The lease registry stores metadata only and uses a private local state directory,
short cross-process mutation lock, atomic same-directory replacement and fsync.
Missing initialized state or corruption fails closed.

Restoring an old lease registry can lose knowledge of provider leases. Recovery
must reconcile provider lease state before resuming effect operations; an old
snapshot is not proof that a lease no longer exists.
