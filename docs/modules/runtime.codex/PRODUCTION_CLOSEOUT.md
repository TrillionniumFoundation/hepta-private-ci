# runtime.codex production execution closeout

This document records the source-composed execution boundary introduced by PR #673. It complements `TECHNICAL.md` and the module execution dossier; it does **not** self-issue deployment, independent acceptance, promotion, merge, or release authority.

Baseline before this closeout: `d7af096f28fa9989388939efa0e6600b52a43952`.

## 1. Product execution path

The production CLI path is now:

`hepta-infer-worker` -> `AppServerModelDriver::run_bound` -> Agentd exact-generation session ingress -> bounded `RemoteAppServerClient` -> App Server v2 `thread/start` -> durable `dispatch_native` -> App Server v2 `turn/start` -> streamed notifications -> durable settlement/reconciliation -> sealed `RuntimeCodexRun` -> `runtime.codex` receipt adapter.

The caller cannot construct a successful `RuntimeCodexRun` directly. `bind_runtime_codex_run` is crate-private and consumes the exact durable `NativeRunRecord` that fenced provider dispatch plus the observed `NativeRunOutput`.

## 2. Success rule

Product success requires all of the following simultaneously:

1. the real App Server emitted the matching `turn/completed` event;
2. the terminal `TurnStatus` is `Completed`, not `Failed` or `Interrupted`;
3. thread id and turn id match the durable dispatch/started record;
4. protocol generation is the v2 App Server boundary;
5. the frozen request payload digest matches the adapter payload binding;
6. the exact Agent owner is still observed ready and unfenced after terminal observation;
7. the `runtime.codex` receipt status is `Succeeded`.

Provider completion alone never grants model/provider authority. The receipt continues to carry deny-all authority.

## 3. Terminal and failure mapping

| Physical observation | Boundary status | Terminal turn receipt | Replay policy |
| --- | --- | --- | --- |
| matching `TurnStatus::Completed` + owner ready | `Succeeded` | yes | no replay |
| matching `TurnStatus::Failed` | `Failed` | yes | no replay |
| matching `TurnStatus::Interrupted` | `Interrupted` | yes | no replay |
| completed but owner authority lost/unverified | `Quarantined` | yes | no replay |
| explicit `turn/start` JSON-RPC rejection | `Rejected` | no turn was admitted, so no terminal turn receipt | same request id remains deduplicated; new policy-controlled request may be attempted |
| explicit App Server overload (`-32001`) | `Overloaded` | no turn was admitted, so no terminal turn receipt | same request id remains deduplicated; caller may apply bounded backoff with a new request identity |
| `turn/start` timeout, transport loss, invalid/missing response | `Indeterminate` | no forged receipt | never automatically replay |
| event-stream loss/lag/deadline after turn admission without terminal event | `Indeterminate` | no terminal success receipt | interrupt best-effort, hold/reconcile; never automatically replay |
| local cancellation before provider dispatch | local pre-dispatch stop | none | slot released; no provider effect claimed |
| cancellation after dispatch | remains non-success until a matching terminal event is observed | only if terminal later arrives | interrupt acknowledgment is not terminality |

The distinction between explicit server rejection and transport uncertainty is intentional. An explicit JSON-RPC error proves that `turn/start` did not return an admitted turn identity and can release local execution capacity. A timeout or disconnect cannot establish that fact and therefore remains indeterminate.

## 4. Correlation and digest binding

`CodexOperationIntent` now binds:

- operation id;
- thread id;
- turn id;
- method id (`app-server.v2.turn-start` in the composed path);
- App Server protocol version;
- frozen payload digest;
- lease payload digest;
- exclusive deadline.

The request digest domain is `hepta.codex.adapter.request.v2`. Changing the turn id, protocol version, payload, operation identity, method, thread, or deadline changes or invalidates the receipt. An observation with a different thread, turn, or protocol version is rejected rather than normalized.

## 5. Durable lost-ack and idempotency semantics

The existing native control journal is reused as the reconciliation source; no second operation ledger is introduced.

- Reservation is durable before external execution.
- `dispatch_native` is committed before awaiting `turn/start`.
- A returned turn id is committed with `native_started`.
- Matching terminal observations are settled durably.
- Reopening a record that may already have been dispatched never invokes the provider again.
- A lost `turn/start` acknowledgement is represented as indeterminate, retains its durable identity, and receives no terminal receipt.
- An explicit server rejection is recorded by the dedicated post-dispatch rejection event, releases the local slot, and remains idempotently replayable as the same stored rejection rather than performing another provider call.

## 6. Capacity and backpressure

The App Server client connection is bounded. The composed path preserves the App Server overload code `-32001` as `AdapterStatus::Overloaded` only when the server explicitly returns that error. Transport saturation or missing acknowledgement is not converted into overload because doing so would incorrectly make an uncertain effect look safely retryable.

The durable journal also enforces a bounded local in-flight reservation policy and byte limits. Unknown executions hold capacity until reconciled; explicit no-turn server rejection may release it.

## 7. Fault matrix required for source qualification

The candidate test matrix includes or must retain coverage for:

- `Completed`, `Failed`, and `Interrupted` terminal status separation;
- in-progress events never treated as terminal;
- cross-thread and cross-turn notifications ignored/rejected;
- protocol correlation mismatch;
- payload/lease digest drift;
- exact retry digest stability;
- exclusive deadline behavior;
- explicit overload/rejection versus transport uncertainty;
- cancellation before dispatch versus after dispatch;
- owner fence/loss before, during, and immediately after terminal provider completion;
- event-stream lag/disconnect;
- output byte bound and monotonic observed token usage;
- process reopen after durable dispatch but before known `turn/start` acknowledgement;
- late terminal reconciliation after an indeterminate attempt;
- historical observation without owner-authority evidence never upgraded to success;
- local journal capacity and corruption fail-closed behavior.

## 8. Verification commands

Source qualification should include at least:

```text
cd codex-rs
just test -p codex-hepta-codex-adapter
cargo test -p codex-hepta-infer-core native_control
cargo test -p codex-hepta-infer-worker-host
cargo clippy -p codex-hepta-codex-adapter -p codex-hepta-infer-core -p codex-hepta-infer-worker-host --all-targets --no-deps -- -D warnings
```

Repository qualification additionally runs the existing consolidated source, repository-integrity, blocking CI, and v8 canary workflows for the exact PR head. A command listed here is not a pass receipt; only the recorded exact-head run can establish that result.

## 9. Remaining external gates

After source checks pass, these claims still require evidence outside this PR and must not be self-certified:

- deployed target identity/configuration matches the qualified source candidate;
- real provider credentials and selected model profile are accepted on the target host;
- real production-like provider stream passes the fault matrix under bounded load;
- delegated external tool effects have their own terminal observer and acknowledgement-loss qualification;
- operator acceptance / canary / independent review requirements are satisfied;
- selection, promotion, merge, and release are authorized by their existing governance gates.

Therefore the closeout target is **source-composed and qualification-ready**, not an automatic assertion that production deployment or release has already occurred.
