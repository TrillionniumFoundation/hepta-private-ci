# runtime.codex fault matrix

This matrix is source-level acceptance guidance for the composed Codex App Server boundary. It is not an activation, production-execution, independent-acceptance, promotion, or release receipt.

| Fault / observation | Required adapter result | Replay posture | Durable slot | Required evidence |
| --- | --- | --- | --- | --- |
| Exact `TurnStatus::Completed` for the expected thread/turn | `Succeeded` | `NotRetryable` | release after settlement | typed `TurnCompletedNotification` |
| Exact `TurnStatus::Failed` | `Failed` with mapped `FailureKind` when available | `NotRetryable` | release after settlement | typed terminal notification |
| Exact `TurnStatus::Interrupted` | `Interrupted` | `NotRetryable` | release after settlement | typed terminal notification |
| `InProgress` supplied as a completion | reject observation | none | unchanged | adapter negative test |
| Terminal notification with wrong thread | reject correlation | none | unchanged | adapter negative test |
| Terminal notification with wrong turn | reject correlation | none | unchanged | adapter negative test |
| Payload digest differs from authority-bound payload digest | reject request | none | no dispatch | adapter negative test |
| No non-constructible final-use capability from `kernel.authority`, or capability is not bound to the exact final `TurnStart` payload | production dispatch must be denied | none | no dispatch | **repository-controlled blocker: native caller wiring not yet implemented** |
| Missing/zero owner generation | reject request | none | no dispatch | adapter negative test |
| Protocol version other than App Server v2 | reject request | none | no dispatch | adapter negative test |
| App Server transport overload JSON-RPC `-32001` before handler admission | `Overloaded` | `SafeToRetry` with a new admitted request | release | typed JSON-RPC error from the bounded transport queue |
| Pre-admission JSON-RPC invalid-request / invalid-params / method-not-found (`-32600/-32602/-32601`) | `Rejected` | `SafeToRetry` with a new admitted request | release | typed JSON-RPC error whose code is emitted by validation before Core submission |
| Internal or otherwise unclassified `turn/start` JSON-RPC error | `Indeterminate` | `ReconcileOnly` | hold | typed JSON-RPC error plus durable client request identity; App Server can produce an internal error after awaiting Core submission |
| `turn/start` acknowledgement timeout | `TimedOut` | `ReconcileOnly` | hold | timeout at typed request boundary |
| Transport loss after `turn/start` dispatch | `Unavailable` | `ReconcileOnly` | hold | typed transport error |
| Response decode failure after dispatch | `Indeterminate` | `ReconcileOnly` | hold | typed decode error |
| Provider event channel lag/disconnect with no later terminal event | `Unavailable` or `Indeterminate` according to observed transport fact | `ReconcileOnly` | hold | event-client error plus durable request binding |
| Cancellation after admission | interrupt requested; success is not inferred from interrupt ACK | `ReconcileOnly` until terminal event | hold until real terminal event | matching `Interrupted`, `Failed`, or `Completed` terminal event |
| Deadline expires, then matching terminal event arrives | map the real terminal status; do not discard it | terminal result decides | release after settlement | late typed terminal event |
| Owner readiness/generation is lost, then provider completes | retain factual provider terminal status but owner authority remains lost | no success authorization | release local slot after terminal fact | durable sticky owner-loss observation |
| Duplicate/restart while original App Server still retains the thread | `thread/read(includeTurns=true)`; match exact `client_user_message_id`; do not submit a new turn | reconcile only | hold or release from recovered state | original session/thread/request digest plus retained turn |
| Reconciliation finds multiple turns for one stable request id | hard conflict | no replay | hold | duplicate-effect evidence |
| App Server process loss removes ephemeral thread history | remain unknown; never infer not-applied and never auto-replay | `ReconcileOnly` | hold | durable dispatch/request digest only |
| Reconciled request digest differs from durable dispatch digest | hard assignment conflict | no replay | hold | durable request/correlation records |

## Correlation scope

The v2 runtime.codex request digest binds the operation ID, Agent/App Server session ID, thread ID, method ID, final payload digest, owner generation, App Server protocol version, and deadline. The durable native inference journal persists the session, deadline, and request digest before `turn/start`; a later recovered turn ID is admitted only if it is correlated to the original thread and stable `client_user_message_id`.

## Witness and trust boundary

`AppServerObservation` has private fields and cannot be constructed by setting an ambient terminal boolean or response digest. Production construction accepts typed App Server protocol outcomes from the bounded App Server client. This is a source/type boundary, not a cryptographic attestation by the App Server process; target-host qualification still has to establish the authenticated local process/socket and owning Agent generation.

## Authority ceiling

Every `CodexAdapterReceipt` remains `DENY_ALL` and never grants model, provider, tool, external-effect, promotion, or release authority. Payload-binding checks do not substitute for the separately owned final-use authority contract. The current native caller has not yet composed that final-use capability, so this matrix is not a production-authorization receipt.
