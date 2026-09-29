# intelligence.control operations runbook

Parent: [TECHNICAL.md](TECHNICAL.md). This runbook is an operator decision tree;
it is not an activation receipt.

## 1. Identify the exact candidate

Record the immutable source SHA, workflow SHA, dependency lock digest, target
triple, source-head command-record manifest and synthetic-merge SHA. Ignore a
cached status in tracked documentation: tracked maps deliberately contain
`CI_EXACT_HEAD` and `pending`. A passing execution projection must be generated
from the unchanged checkout and retained as a workflow artifact.

Any source or qualification-workflow change invalidates the prior acceptance
receipt. Re-run source-head, current-main and deterministic synthetic-merge
lanes; do not transplant logs from an older head.

## 2. Triage by typed recovery disposition

| Signal | Operator action |
|---|---|
| `Reject` | Return the stable typed error; do not retry or rewrite identity. |
| `RetrySameIdentity` | Retry only under the same operation identity and current lease. |
| `RetryAfterCapacity` | Apply bounded backoff; expose queue age and capacity metrics. |
| `ReconcileOnly` | Query the authoritative destination and durable operation; never call the provider first. |
| `ReplaceOwner` | Fence the stale generation and let Supervisor start/admit the successor. |
| `RepairClockOrStore` | Close admission, preserve files and evidence, repair clock/storage, then reopen and reconcile. |

`Unavailable` means the durable result may be unknown. It is never evidence that
a commit or physical effect failed.

## 3. Restart and crash handling

1. Keep the original operation identity, semantic digest, generation and fence.
2. Enumerate unsettled operations in stable `(scope_id, operation_id)` pages.
3. Observe destination dedupe evidence before requesting new write authority.
4. Requeue only a live `Prepared` claim that is proven unused.
5. Treat `Dispatching`, `Dispatched` and `Indeterminate` as reconcile-only.
6. Preserve terminal observations even when Outcome publication or acknowledgement
   fails.
7. Quarantine corruption, attempt exhaustion and identity drift; never normalize
   them into an ordinary transient retry.

## 4. Clock rollback

Durable timestamps are trusted Unix time; elapsed budgets use monotonic time.
On `ClockRollback`, stop new admission and compare host time with the greatest
durable `updated_at_ms`. Do not edit timestamps or clamp the clock. Correct the
trusted clock or restore a verified store, reopen it, and execute reconciliation
before resuming effects.

## 5. Required telemetry

At minimum retain active/terminal operation counts, queued/leased/indeterminate
outbox counts, oldest active outbox age, owner generation/fence, provider entry
classification, cancellation-to-stop latency, reconciliation results and the
exact workflow/source identities. Structured logs and traces must carry the same
operation ID from ObjectiveStart through provider observation and learning
acknowledgement.

## 6. Release decision

Do not set activation or release from source presence. Release requires all
required checks on the exact head, deterministic synthetic merge, immutable raw
logs and digests, real product/provider evidence, target-host qualification and
an independent acceptance identity. The implementation map intentionally keeps
those fields false until their dedicated evidence exists.
