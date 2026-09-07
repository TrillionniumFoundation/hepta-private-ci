# runtime.agentd: implementation design

Parent: `docs/modules/runtime.agentd/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: specified target, not implemented or independently accepted. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-agentd`.
Packages: `P0.8B-READINESS`, `P0.8D-VERTICAL-SLICE`.

Operation signatures below are design contracts, not assertions of existing native symbols. Bind each to an existing or planned symbol and consumer inside the owner envelope. Preserve existing stores and APIs; do not create another authority or execution spine.

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
