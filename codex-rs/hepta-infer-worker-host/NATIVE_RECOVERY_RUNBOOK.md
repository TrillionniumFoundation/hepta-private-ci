# Native App Server recovery runbook

This runbook applies only to the `HostedAppServerWorker` profile. Recovery is reconcile-only: an accepted-or-unknown durable dispatch is never replayed with a second `turn/start`.

## States and operator actions

| Durable state | Meaning | Allowed action |
| --- | --- | --- |
| `Reserved` | No durable dispatch was written. | The live caller may stop before dispatch or continue through the normal final-use path. |
| `Dispatching` | Exact dispatch identity was committed; effect entry may have happened. | Query exact App Server history. Never infer “not sent” after process loss. |
| `Running` / `Cancelling` | A turn identity or cancellation intent is known. | Query the original thread/turn only. Cancellation acknowledgement does not prove terminality or zero usage. |
| `Indeterminate` | Existing evidence cannot establish a terminal outcome. | Run bounded reconciliation; retain the reservation and quarantine the operation if history is absent or ambiguous. |
| `Released` with terminal output | Provider terminality was observed. | Return the stored result. If usage is missing, continue usage reconciliation without changing it to zero. |

## Bounded history reconciliation

`NativeRecoveryManager` applies an immutable per-process policy with:

- a maximum of 64 attempts;
- nonzero initial and maximum backoff;
- a maximum backoff of 30 seconds;
- an explicit minimum App Server history-retention requirement;
- cancellation-aware sleeping;
- no path that issues a new turn.

The default policy uses six attempts, 100 ms initial backoff, 2 s maximum backoff and a 24-hour minimum retention contract. Deployment may select a stricter bounded policy. Retention is an external host contract, not a repository guarantee.

## Missing history

When exact `thread/read` history is unavailable, the operation remains held. Resolution requires a `ProviderTerminalReceipt` verified by an independently configured `ProviderReceiptAuthority`. The verifier binds:

- request, thread, turn, model and provider;
- original final-use authority witness and complete authority frontier;
- terminal stream correlation;
- exact output and trusted token usage;
- receipt digest, independent verification witness and replay protection.

A manually entered status, unsigned JSON, log line, timeout, billing estimate or operator assertion is not a provider receipt.

## Missing usage

A terminal provider result with absent trusted token usage returns `UsagePending`. It is not settled as zero and does not free the durable reservation through this recovery API. Use an independently verified receipt or provider usage reconciler to refine the record monotonically.

## Metrics and alerts

Export `NativeWorkerMetricsSnapshot` and alert on:

- `indeterminate_count` and the age derived from `oldest_indeterminate_started_ms`;
- `held_reservations`;
- reconciliation attempts, successes and failures;
- `missing_usage`;
- authority denials;
- cancellation-to-interrupt latency count, total and maximum;
- journal-capacity rejections.

Suggested operator priorities:

1. Authority denial or journal-capacity rejection: stop new admissions and repair the authority/journal boundary.
2. Growing indeterminate age or held reservations: verify App Server retention and exact Agent/session identity.
3. Reconcile failures with available history: quarantine identity drift; do not retry through a new turn.
4. Missing usage: request a trusted provider receipt; do not estimate or write zero.

## External qualification gates

Before activation, independently establish deployed issuer/key custody, trusted time, revocation distribution, socket and peer ACLs, App Server history retention, real provider terminal and usage receipts, target-host identity, canary, rollback and independent acceptance. Repository tests cannot self-approve these gates.
