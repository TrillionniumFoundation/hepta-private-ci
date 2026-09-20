# runtime.agentd: implementation design

Parent: `docs/modules/runtime.agentd/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: native Agentd host, daemon-owned run lifecycle control, explicit indeterminate recovery seam and explicit production-writer attachment implemented; canonical non-test run-tuple production, target-host restart/backpressure evidence and independent acceptance remain open as listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-agentd`.
Packages: `P0.8B-READINESS`, `P0.8D-VERTICAL-SLICE`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`compose_runtime(supervisor_snapshot, ports, configuration) -> AgentHost`; `start_run(authenticated_request, objective_snapshot, body_snapshot, artifact_set, authority_epoch, deadline) -> RunHandle`; `attach_context(run_id, expected_revision, complete_frozen_tuple, compilation_receipt) -> AttachmentObservation`; `mark_dispatched(run_id, expected_revision) -> RunReceipt`; `cancel_run(run_id, expected_revision, reason) -> CancellationDisposition`; `observe_terminal(run_id, expected_revision, owner_observation) -> RunReceipt`; `recover_indeterminate(external_recovery) -> RunReceipt`. The local control socket advertises `run.lifecycle/1.0` before clients use these additive methods. Each operation uses the existing Codex session spine and typed owner ports. Agentd cannot create a second memory/learning store.

## 3. State records and transaction design

Own only the canonical runtime-health observation surface and ephemeral composition state. The daemon now owns one bounded `AgentRunCoordinator` inside `AgentdState`; its run map stores handles, revisions, immutable snapshot references, cancellation reason and terminality, not authoritative objective, memory, prompt or artifact bytes. Context attachment binds request/objective/body/artifact digests together with the original authority epoch and deadline. Host restart does not treat the in-memory map as durable truth: an authenticated external execution owner may rehydrate an exact prior run only as `Indeterminate`, preserving its revision and attachment identities, after which only terminal reconciliation is permitted. Recovery never authorizes redispatch.

## 4. Deterministic algorithm and scheduling

Bootstrap auth and revocation readers, stores/read ports, execution adapters and intelligence composition in explicit order. Freeze run snapshots; validate every attached receipt against the complete tuple; re-check the run deadline before attachment and dispatch; route effects to the sole execution spine; observe cancellation at defined boundaries. Shutdown first closes admission, converts pre-dispatch work to local cancellation, moves dispatched work to cancelling, keeps the control path alive for bounded terminal reconciliation, and marks unresolved post-dispatch work `Indeterminate` before process teardown. A dependency failure takes a declared deterministic/read-only fallback or rejects the run. Shutdown never turns an unknown external effect into success/failure or silently redispatches it.

## 5. Capacity and performance profile

Pilot <= 256 active runs, bounded ingress <= 1024 requests, each attachment <= the context/wire profile. Per-run deadlines and cancellation acknowledgement deadlines are mandatory host configuration. Track queue age and dependency/readiness latency.

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

The explicit `AgentdConfig::with_cognitive_ranker` host connects existing artifact-owner loading and the tabular operator to the real SQLite control-read projection before truncation. Current views and memory deletion are rechecked; source tests are `cognitive_ranker_tests.rs`. This is not the App Server automatic memory path or complete C1; the ordinary CLI has no implicit selection.

- **Implemented entrypoints:** `AgentRunCoordinator` in [codex-rs/hepta-agentd/src/lane_b_runtime.rs](../../../codex-rs/hepta-agentd/src/lane_b_runtime.rs) is owned by `AgentdState` and reached through the real control dispatch in [codex-rs/hepta-agentd/src/state_control.rs](../../../codex-rs/hepta-agentd/src/state_control.rs); typed clients are in [codex-rs/hepta-agentd/src/client.rs](../../../codex-rs/hepta-agentd/src/client.rs). `AgentdProductionWriterHost` remains an explicit host seam in [codex-rs/hepta-agentd/src/production_writer_host.rs](../../../codex-rs/hepta-agentd/src/production_writer_host.rs); cognitive `read` remains in [codex-rs/hepta-agentd/src/cognitive_context.rs](../../../codex-rs/hepta-agentd/src/cognitive_context.rs).
- **State and recovery:** Agentd owns one bounded in-memory run/revision coordinator per process. Admission, complete-tuple attachment, dispatch boundary, reasoned cancellation, deadline transitions, terminal observation and explicit recovery are generation-fenced through the daemon control path. On shutdown, admission closes before task teardown and the control socket remains available during the bounded drain/reconciliation window. An external durable owner may reconstruct an exact prior operation only as `Indeterminate`; Agentd does not persist or fabricate the external effect result and recovery cannot redispatch. Durable cognitive facts stay in hepta-memory SQLite; `AgentdProductionWriterHost` still requires an externally verified lease and explicit target attachment and is not enabled automatically by startup.
- **Control saturation:** the bounded UDS server returns a small typed overload frame with retry guidance instead of silently dropping a saturated connection. This is backpressure signaling, not target-host capacity qualification.
- **Source tests:** [codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs](../../../codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs), [codex-rs/hepta-agentd/src/state_isolation_tests.rs](../../../codex-rs/hepta-agentd/src/state_isolation_tests.rs), [codex-rs/hepta-agentd/src/runtime_tests.rs](../../../codex-rs/hepta-agentd/src/runtime_tests.rs), [codex-rs/hepta-agentd/src/cognitive_context_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [docs/readiness/LANE_B_NATIVE_HOST.md](../../../docs/readiness/LANE_B_NATIVE_HOST.md), [codex-rs/hepta-agentd/AUTHBUS_TEXT.md](../../../codex-rs/hepta-agentd/AUTHBUS_TEXT.md).
- **Remaining repository work:** Compose a canonical non-test caller that supplies authenticated request/objective/body/artifact/authority identities rather than synthetic hashes, and bind restart recovery to that caller's durable exact-operation record.
- **Remaining external evidence:** Prove deployed socket/generation identity and measure target-host drain, restart and saturation behavior. Independent acceptance/promotion/release remain separate.
