# runtime.codex production-closure guide

This document records the repository-controlled work required to move `runtime.codex` from source-bound mapping to a production-composable Codex App Server execution boundary. It complements `TECHNICAL.md` and the module execution dossier; it does not grant authority, activation, acceptance, promotion or release.

## 1. Boundary being closed

`runtime.codex` is the Hepta boundary around the existing Codex App Server/Core execution spine. It does not own a second model runtime, thread store, tool router or provider implementation. The upstream App Server/Core remains authoritative for thread, turn, streaming and tool execution state.

The closure candidate has two distinct responsibilities:

1. Before a physical `turn/start`, bind the exact operation/thread/method/payload/deadline into a deterministic request digest and reject payload/deadline drift.
2. After the request crosses the App Server seam, derive an observational receipt only from real protocol outcomes, preserving failure, interruption and uncertainty instead of inferring success from handler completion or queue admission.

## 2. Real model execution path

The named model caller is `codex-rs/hepta-infer-worker-host/src/native_app_server.rs` (`AppServerModelDriver`). Its order is deliberately fixed:

1. authenticate the exact Agentd identity and generation;
2. read current Agentd health and optional bounded cognitive context;
3. connect to the owning App Server through the generation-bound Unix socket;
4. verify the App Server Codex home matches the owning Agent;
5. create the ephemeral App Server thread and verify the requested model was not substituted;
6. re-check exact Agentd generation;
7. assemble the final `TurnStartParams` and compute its SHA-256 digest;
8. run `runtime.codex::prepare` immediately before possible dispatch;
9. durably record possible dispatch in the existing inference journal;
10. issue `turn/start`;
11. correlate the exact returned turn and consume bounded streaming events;
12. derive a runtime.codex terminal receipt from the real matching `turn/completed` notification;
13. require native execution status and adapter receipt status to agree;
14. settle the existing durable inference journal.

No step creates model/provider authority. The adapter receipt remains `DENY_ALL`.

## 3. Terminal semantics

A terminal notification is not synonymous with success.

| App Server fact | Adapter status | Retry disposition |
| --- | --- | --- |
| matching `turn/completed: Completed` | `Succeeded` | `DoNotRetry` |
| matching `turn/completed: Failed` | `Failed` | `DoNotRetry` |
| matching `turn/completed: Interrupted` | `Interrupted` | `DoNotRetry` |
| `turn/completed: InProgress` | protocol error | none |
| event-stream lag/disconnect | `Indeterminate` | `ReconcileBeforeRetry` |
| turn-start timeout | `TimedOut` | `ReconcileBeforeRetry` |
| explicit local cancellation without matching terminal event | `Cancelled` | `DoNotRetry` |
| security/policy quarantine | `Quarantined` | `DoNotRetry` |

The adapter no longer exposes a public constructor that lets a product caller claim `Completed`, `Failed`, `Interrupted` or a retry-safe server rejection. Those facts are derived inside the adapter from App Server protocol objects.

## 4. Admission and overload mapping

The App Server transport uses a bounded ingress queue. `-32001` (`Server overloaded; retry later.`) is a pre-admission transport-overload signal and is represented as `Overloaded/RetrySafe` by the adapter. Closed invalid-request/invalid-params responses are represented separately from generic transport/server uncertainty.

The real inference caller is intentionally more conservative than the bare adapter: it durably marks possible dispatch before issuing `turn/start`. Once that local dispatch marker exists, the same operation identity is not blindly replayed even when a server response suggests a safe retry. Reconciliation or a new authorized attempt is required.

## 5. Lost acknowledgement and idempotency

The existing `DurableInferenceControl` journal is the source of no-replay state for the model caller. The important invariant is:

> A process restart after possible dispatch cannot turn uncertainty into permission to issue a second model turn.

`dispatch_native` persists possible dispatch before `turn/start`. Reopening a request in a possibly-dispatched state produces an indeterminate/reconciliation path rather than a new provider call. This remains separate from `CodexAdapterReceipt`, which is an observation record and not the durable operation ledger.

## 6. Cancellation

`turn/interrupt` acknowledgement means only that an interrupt request was accepted/handled. It is not a terminal model result. After cancellation the caller continues a bounded grace observation window; only a matching `turn/completed` event establishes `Interrupted`, `Failed` or `Completed` terminality. If no exact terminal event is observed, the durable result remains non-success and replay is not inferred to be safe.

## 7. Correlation and digest scope

The request digest binds:

- stable operation identity;
- exact App Server thread identity;
- method identity;
- exact final `TurnStartParams` payload digest;
- supplied lease-payload digest;
- exclusive admission deadline.

The receipt digest additionally binds:

- exact terminal turn identity when known;
- closed adapter status;
- retry disposition;
- protocol response/notification digest when present;
- the adapter's explicit lack of model/provider authority.

Cross-thread observations are hard failures. The real caller additionally requires the receipt's turn id and status to match the native `NativeRunOutput` before accepting terminal settlement.

## 8. App Server consumer inventory

Not every App Server client is the same boundary.

- `hepta-infer-worker-host/native_app_server.rs`: physical model `turn/start` and terminal stream observer. This is the model execution call site composed with `runtime.codex` in this closure candidate.
- `hepta-agentd/automation.rs`: durable queue admission with explicit `BeforeAdmission` versus `OutcomeUnknown` semantics. It retains its queue-owner idempotency/reconciliation contract.
- `hepta-agentd/authbus_dispatch.rs`: stable client identity plus `thread/queue/reconcile`; lost replies are reconciled rather than recreated.
- `hepta-matrixd`: Matrix ingress through exact-generation Agentd/App Server queue reconciliation; it is an ingress/queue contract, not the terminal model observer.
- Agentd runtime/readiness clients: lifecycle/readiness plumbing, not model-terminal authority.

This inventory prevents the anti-pattern of routing unrelated queue/readiness APIs through a receipt adapter merely to claim complete composition.

## 9. Final-use authority

`runtime.codex` consumes kernel-authority concepts but must not mint its own permission. The repository already contains `FinalUseAuthority`, signed grants, revocation heads, nonce persistence and non-cloneable `VerifiedUseToken` semantics. `P0.7B-B4-CALLSITE-PROOF` explicitly permits work in `codex-rs/hepta-infer-worker-host/**` for the real effect call site.

The closure candidate intentionally does **not** equate `payload_digest == lease_payload_digest` with independently issued authority. Exact payload stability is necessary but not sufficient. Activation requires a real independently issued final-use grant/token/witness bound to the final model/tool effect and validated at the call site. This cannot be self-certified by `runtime.codex` or by the worker it protects.

## 10. Tool execution

Model-turn observation and delegated tool-effect terminality are separate facts. App Server/Core remains the tool execution spine, but an external/delegated tool effect must be settled by the effect owner that can distinguish admission, completion, failure, cancellation and lost acknowledgement. A model `turn/completed` event is not sufficient evidence that every delegated external side effect reached its own terminal state.

Therefore delegated tool terminal-observer qualification remains an external/integration gate until a real effect owner supplies that evidence.

## 11. Fault matrix

The source candidate must prove at least:

- Completed, Failed and Interrupted map one-to-one and cannot alias;
- cross-thread/cross-turn terminal evidence cannot settle another request;
- `InProgress` in a completion event fails closed;
- payload/lease drift fails before dispatch;
- deadline is checked before dispatch but not re-applied to a legitimate late terminal event;
- event lag/disconnect is indeterminate and requires reconciliation;
- turn-start timeout is not safe replay;
- explicit overload is distinguishable from ambiguous server/transport failure;
- cancellation acknowledgement is not terminality;
- a reopened maybe-dispatched request does not issue a second turn;
- authority loss/fencing cannot be restored by a later provider completion;
- adapter receipts never grant model/provider authority.

Focused source identities are in the adapter and native App Server worker tests. Exact-head execution receipts, strict lint and merge-candidate qualification are required before source completion is claimed.

## 12. Qualification state model

Repository-controlled source closure can establish:

- real caller composition;
- deterministic request/receipt bindings;
- terminal/error/cancellation mapping;
- durable no-replay semantics;
- bounded event handling;
- compile/test/lint evidence;
- current documentation and implementation mapping.

It cannot self-establish:

- independently issued final-use authority;
- real deployment identity/host qualification;
- independent security/semantic acceptance;
- production canary success;
- selection, promotion or release.

Those remain explicit gates instead of being converted into source-code booleans.
