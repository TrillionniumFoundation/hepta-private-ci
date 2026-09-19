# runtime.agentd: implementation design

Parent: `docs/modules/runtime.agentd/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: native Agentd host and daemon-owned durable run-lifecycle control API implemented; the normal non-test Codex turn adapter and physical interrupt/terminal-ack binding remain repository work, with independent deployment acceptance listed separately in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-agentd`.
Packages: `P0.8B-READINESS`, `P0.8D-VERTICAL-SLICE`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`compose_runtime(supervisor_snapshot, ports, configuration) -> AgentHost`; `start_run(authenticated_request, objective_snapshot, body_snapshot, artifact_set) -> RunHandle`; `cancel_run(run_id, reason) -> CancellationDisposition`; `attach_context(run_id, compilation_receipt) -> AttachmentObservation`. These operations are now exposed through the strict local Agentd control protocol as `RunStart`, `RunAttachContext`, `RunMarkDispatched`, `RunCancel`, `RunObserveTerminal`, `RunGet` and `RunRemoveClosed`, all routed through the daemon-owned coordinator. The normal Codex session spine remains the only thread/turn execution owner; a separate adapter still has to drive these lifecycle calls from actual non-test turn events.

## 3. State records and transaction design

Own only the canonical runtime-health observation surface, bounded lifecycle control state and a crash-recovery projection of run identity/revision/phase. The recovery file stores immutable snapshot references, cancellation metadata and the bounded cancellation-ack deadline, not authoritative objective, memory, prompt, artifact, Codex turn or provider bytes. It is bounded to 4 MiB. Each mutation is applied to a candidate coordinator and synced before publication. Failure before rename leaves memory unchanged. If rename is already visible but parent-directory durability is ambiguous, the same candidate is retained in memory and the Agentd generation is fenced, preventing a conflicting semantic reuse while crash durability is unresolved. A newer generation cancels retained pre-dispatch work; dispatched/cancelling work without terminal owner observation restores as `indeterminate` and is never redispatched.

## 4. Deterministic algorithm and scheduling

Bootstrap auth and revocation readers, stores/read ports, execution adapters and intelligence composition in explicit order. Freeze request/objective/body/artifact/authority/deadline identity before admission; every context attachment must repeat that complete tuple. The generation monitor enforces elapsed run deadlines and cancellation-ack deadlines. Local drain rejects new admission, cancels only work that provably has not crossed dispatch, waits for execution-owner terminal observations, and persists remaining externally uncertain work as `indeterminate` before shutdown. A recorded post-dispatch `Cancelling` phase is intent only; the composed host gives acknowledgement a bounded 5-second window and advances an unacknowledged cancellation to `indeterminate` instead of fabricating terminality.

## 5. Capacity and performance profile

Pilot <= 256 active runs and <= 1024 retained lifecycle records; the lifecycle recovery projection is <= 4 MiB. At the retention ceiling, one deterministic closed row is compacted before new admission, while active/uncertain rows are never evicted for capacity. The control server has 32 normal concurrent connection slots plus four bounded overload-response slots. Each attachment remains bounded by the control-frame/context profile. Per-run deadlines and the 5-second cancellation-ack deadline are enforced by the daemon monitor. The ack deadline bounds how long `Cancelling` may remain unresolved; it does not itself prove that a physical interrupt occurred. Track queue age, overload responses, drain duration and dependency/readiness latency.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- AGENT-01: mixed objective/body/artifact generations reject before context attachment.
- AGENT-02: missing critical owner store blocks readiness while optional advice can fall back.
- AGENT-03: cancel before/after dispatch preserves terminal/indeterminate distinction.
- AGENT-04: new-process C1 uses actual owner ports and creates no undeclared durable files.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

The integration package names actual host entrypoints and callsites for C1. A mocked port is labelled qualification-only. Rollback restarts from a compatible selected tuple; current runs are drained rather than receiving an in-place artifact swap.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

The live `AgentdState` now owns one `AgentRunCoordinator` and exposes it through the local generation-fenced control socket. `AgentdMethod::RunStart`, `RunAttachContext`, `RunMarkDispatched`, `RunCancel`, `RunObserveTerminal`, `RunGet` and `RunRemoveClosed` all mutate or observe that same coordinator. The deterministic transition core remains in `lane_b_runtime.rs`; it is no longer only a re-exported library fixture.

- **Daemon composition:** [codex-rs/hepta-agentd/src/state.rs](../../../codex-rs/hepta-agentd/src/state.rs) owns the coordinator and bounded recovery projection; [codex-rs/hepta-agentd/src/state_control.rs](../../../codex-rs/hepta-agentd/src/state_control.rs) routes the typed wire methods. The daemon advertises `run.lifecycle` v1.1 and `control.typed_backpressure` v1; lifecycle minor 1 includes the durable cancellation-ack deadline.
- **Frozen identity:** run start freezes request/objective/body/artifact digests, authority epoch and deadline. Context attachment must repeat the complete tuple plus context and compilation-receipt digests; authority/deadline drift rejects before attachment.
- **Deadline and cancellation:** the generation monitor sweeps elapsed run deadlines and durable cancellation-ack deadlines. Pre-dispatch expiry is terminal local cancellation. Post-dispatch expiry records cancellation intent plus a bounded 5-second acknowledgement deadline; missing acknowledgement advances to `indeterminate` without claiming a physical interrupt.
- **Drain and restart:** SIGTERM/SIGINT first enter local draining and stop admission. Pre-dispatch work can be cancelled locally; dispatched work is allowed to reach an execution-owner terminal observation. After the bounded drain interval, still-unobserved external work is persisted as `indeterminate`. Restart never redispatches such work; a newer generation also cancels retained pre-dispatch work rather than reusing stale authority.
- **Bounded backpressure:** the UDS control server retains 32 normal connection permits and four separately bounded overload responders. When possible, saturation returns typed error code `overloaded`; exhaustion of both pools still fails closed by dropping the connection rather than allocating an unbounded queue.
- **Other implemented host surfaces:** `AgentdProductionWriterHost` remains an explicit externally verified writer seam and is not enabled automatically; cognitive context/ranker, automation and AuthBus continue through their existing owner-specific paths.
- **Source tests:** [codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs](../../../codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs), [codex-rs/hepta-agentd/src/state_isolation_tests.rs](../../../codex-rs/hepta-agentd/src/state_isolation_tests.rs), [codex-rs/hepta-agentd/src/cognitive_context_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_tests.rs). These are test identities; current exact-candidate CI receipts remain separate.
- **Named product caller:** `hepta-infer-worker --profile native-app-server` now drives lifecycle start/context/dispatch around its real App Server `turn/start`. On cancellation, deadline, event loss or owner loss it records Agentd cancellation intent, sends the real `TurnInterrupt`, observes the bounded grace window and records matching terminal or `indeterminate` state. Turn/start acknowledgement loss is recorded as `indeterminate` and is never replayed as a new lifecycle/turn execution. After the inference journal has durably settled a terminal fresh-run result, the caller eagerly retires the closed Agentd lifecycle row; historical completed duplicate replay remains journal-only and does not contact the retired Agentd/provider. The owner also compacts closed rows at the retention ceiling, so transient cleanup failure cannot permanently exhaust admission.
- **Remaining repository work:** compose the remaining direct `SessionIngress` product consumer(s), notably `hepta-matrixd` queue/turn execution, into the Agentd lifecycle API or an equivalent host-side hook before claiming universal per-Agent lifecycle coverage. Also define bare-`RunCancel` ownership outside native inference: by itself it is durable intent, not proof that a physical interrupt occurred.
- **Remaining external evidence:** prove deployed Agentd socket/generation identity, target-host saturation/restart behavior and independent drain/restart acceptance.
