# runtime.agentd: implementation design

Parent: `docs/modules/runtime.agentd/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: native Agentd host, live typed run-lifecycle control surface, crash-recoverable lifecycle metadata ledger and explicit production-writer attachment implemented; named non-test Codex caller composition and independent acceptance remain separate and are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-agentd`.
Packages: `P0.8B-READINESS`, `P0.8D-VERTICAL-SLICE`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`compose_runtime(supervisor_snapshot, ports, configuration) -> AgentHost`; `start_run(now, frozen_snapshot) -> RunReceipt`; `attach_context(now, expected_revision, complete_frozen_tuple, compilation_receipt) -> RunReceipt`; `mark_dispatched(now, run_id, expected_revision) -> RunReceipt`; `cancel_run(run_id, expected_revision, reason) -> (CancellationDisposition, RunReceipt)`; `observe_terminal(run_id, expected_revision, observed_phase, terminal_observed) -> RunReceipt`. The local Agentd wire protocol additionally exposes status and closed-run removal. Each operation uses the existing Codex session spine and typed owner ports. Agentd cannot create a second model/tool execution spine or memory/learning store.

## 3. State records and transaction design

Own only the canonical runtime-health observation surface plus bounded operational lifecycle metadata. The recoverable Agent-local run ledger stores run identity, immutable input digests, authority/deadline metadata, revision, phase and cancellation reason; it never stores authoritative objective, memory, prompt, context or artifact bytes. The ledger is restart/reconciliation metadata rather than a product-domain source of truth. Configuration includes owner-store endpoints, dependency readiness, queue/deadline limits and the exact adapter versions. Host restart revalidates ownership from the supervisor/owners, cancels safe pre-dispatch work and converts uncertain post-dispatch work to `Indeterminate`; it never redispatches from cache contents.

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

The explicit `AgentdConfig::with_cognitive_ranker` host connects existing artifact-owner loading and the tabular operator to the real SQLite control-read projection before truncation. Current views and memory deletion are rechecked; source tests are `cognitive_ranker_tests.rs`. This is not the App Server automatic memory path or complete C1; the ordinary CLI has no implicit learned-ranker selection.

- **Implemented entrypoints:** `compose_runtime`, `start_run`, `attach_context`, `mark_dispatched`, `cancel_run` and `observe_terminal` in [codex-rs/hepta-agentd/src/lane_b_runtime.rs](../../../codex-rs/hepta-agentd/src/lane_b_runtime.rs); `response` in [codex-rs/hepta-agentd/src/state_control.rs](../../../codex-rs/hepta-agentd/src/state_control.rs); `AgentdProductionWriterHost` in [codex-rs/hepta-agentd/src/production_writer_host.rs](../../../codex-rs/hepta-agentd/src/production_writer_host.rs); `read` in [codex-rs/hepta-agentd/src/cognitive_context.rs](../../../codex-rs/hepta-agentd/src/cognitive_context.rs). The coordinator is now owned by live `AgentdState`; the shared [Agentd control protocol](../../../codex-rs/hepta-agent-protocol/src/lib.rs) and `AgentdClient` expose typed start, attach, dispatch-boundary, cancel, terminal-observation, status and removal calls. This closes the former library-only/wire-API source gap.
- **Frozen tuple and deadlines:** request/objective/body/artifact digests, authority epoch and deadline are bound across start/attachment. Attachment and dispatch re-check wall-clock deadline, and the runtime monitor advances expired records conservatively without fabricating terminal completion.
- **State and recovery:** [codex-rs/hepta-agentd/src/run_ledger.rs](../../../codex-rs/hepta-agentd/src/run_ledger.rs) atomically persists only bounded lifecycle metadata in the registered Agent run root. Restart closes pre-dispatch work and makes post-dispatch uncertainty explicit. The ledger never redispatches a turn and never stores prompt/context bytes. Durable cognitive facts remain in hepta-memory SQLite.
- **Drain:** SIGINT, SIGTERM and SIGHUP close Agentd admission and allow the embedded App Server to run its native graceful drain while the Agentd control/reconciliation surface remains alive. The wait is bounded; unresolved post-dispatch lifecycle records become `Indeterminate` before task teardown.
- **Backpressure:** the primary UDS connection pool remains bounded. When it is saturated, a separately bounded responder pool returns typed `overloaded` errors; if even that pool is exhausted, the socket is closed rather than allocating unbounded work.
- **Production writer boundary:** `AgentdProductionWriterHost` still requires an externally verified lease and explicit target attachment and is not enabled automatically by startup.
- **Source tests:** [codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs](../../../codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs), [codex-rs/hepta-agent-protocol/src/lib.rs](../../../codex-rs/hepta-agent-protocol/src/lib.rs), [codex-rs/hepta-agentd/src/cognitive_context_tests.rs](../../../codex-rs/hepta-agentd/src/cognitive_context_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [docs/readiness/LANE_B_NATIVE_HOST.md](../../../docs/readiness/LANE_B_NATIVE_HOST.md), [codex-rs/hepta-agentd/AUTHBUS_TEXT.md](../../../codex-rs/hepta-agentd/AUTHBUS_TEXT.md).
- **Remaining work / claim boundary:** bind a named non-test Codex caller that possesses authentic frozen-tuple and context-compilation receipts; prove the deployed socket/generation identity; measure drain/backpressure/restart behavior on the target host. Do not substitute fabricated receipt hashes to turn source-complete lifecycle APIs into a product-composition claim.
