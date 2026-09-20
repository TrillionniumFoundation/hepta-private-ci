# runtime.agentd: implementation design

Parent: `docs/modules/runtime.agentd/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: native Agentd host, run-binding component and explicit production-writer attachment implemented; remaining target capabilities and independent acceptance are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-agentd`.
Packages: `P0.8B-READINESS`, `P0.8D-VERTICAL-SLICE`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`compose_runtime(supervisor_snapshot, ports, configuration) -> AgentHost`; `start_run(authenticated_request, objective_snapshot, body_snapshot, artifact_set) -> RunHandle`; `cancel_run(run_id, reason) -> CancellationDisposition`; `attach_context(run_id, compilation_receipt) -> AttachmentObservation`. Each operation uses the existing Codex session spine and typed owner ports. Agentd cannot create a second memory/learning store.

## 3. State records and transaction design

Own only the canonical runtime-health observation surface and ephemeral composition state. A run map stores handles and immutable snapshot references, not authoritative objective, memory, prompt or artifact bytes. Configuration includes owner-store endpoints, dependency readiness, queue/deadline limits and the exact adapter versions. Host restart reconstructs ownership from the supervisor/owners, not arbitrary local cache contents.

## 4. Deterministic algorithm and scheduling

Bootstrap auth and revocation readers, stores/read ports, execution adapters and intelligence composition in explicit order. Freeze run snapshots; validate every attached receipt against that tuple; route effects to the sole execution spine; observe cancellation at defined boundaries. A dependency failure takes a declared deterministic/read-only fallback or rejects the run. Shutdown does not erase indeterminate effects.

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

- **Implemented entrypoints:** `compose_runtime` in [codex-rs/hepta-agentd/src/lane_b_runtime.rs](../../../codex-rs/hepta-agentd/src/lane_b_runtime.rs); `AgentdProductionWriterHost` in [codex-rs/hepta-agentd/src/production_writer_host.rs](../../../codex-rs/hepta-agentd/src/production_writer_host.rs); `read` in [codex-rs/hepta-agentd/src/cognitive_context.rs](../../../codex-rs/hepta-agentd/src/cognitive_context.rs). Native Agentd host, run-binding component and explicit production-writer attachment implemented.
- **State and recovery:** lane_b_runtime keeps a bounded in-memory run/revision map. Durable cognitive facts stay in hepta-memory SQLite; AgentdProductionWriterHost requires an externally verified lease and explicit target attachment and is not enabled automatically by startup.
- **Source tests:** [codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs](../../../codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs), [codex-rs/hepta-agentd/src/cognitive_context_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [docs/readiness/LANE_B_NATIVE_HOST.md](../../../docs/readiness/LANE_B_NATIVE_HOST.md), [codex-rs/hepta-agentd/AUTHBUS_TEXT.md](../../../codex-rs/hepta-agentd/AUTHBUS_TEXT.md).
- **Remaining work:** Prove the deployed socket/generation identity and full non-test Codex caller path; measure backpressure/restart on the target host.
