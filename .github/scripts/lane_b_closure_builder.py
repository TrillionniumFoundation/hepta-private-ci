#!/usr/bin/env python3
"""Build the Lane B closure candidate, then remove this temporary builder."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BASE_COMMIT = "04f60466394a024c218ce66b1b32d1c42c462985"
BASE_TREE = "a9797f471d27194e29c13f49723d4508ac52cb84"
DEFAULT_BRANCH = "integration/vnext-main-20260811"

FALSE_CLAIMS = [
    "productRuntimeQualified",
    "providerExecutionProved",
    "externalEffectProved",
    "deploymentQualified",
    "independentAcceptance",
    "promotionAuthorized",
    "releaseAuthorized",
]

MODULE_ROWS: list[dict[str, Any]] = [
    {
        "module": "runtime.supervisor",
        "guide": "docs/modules/runtime.supervisor/TECHNICAL.md",
        "design": "qualification/module-execution-dossiers/detail/runtime.supervisor.md",
        "roots": ["codex-rs/hepta-supervisor"],
        "lifecycleState": "source_mapped",
        "currentCapability": "The Rust crate exposes the supervisor daemon, process driver, control client, lifecycle snapshots and signed mutation boundary while explicitly excluding model-turn execution.",
        "targetCapability": "A generation-fenced supervisor that starts, observes, drains and reloads selected runtime instances under bounded readiness, resource and rollback policy.",
        "operationMappings": [
            {"operation": "start_instance_and_supervise_generation", "path": "codex-rs/hepta-supervisor/src/lib.rs", "symbols": ["Supervisor", "ProcessDriver", "run_supervisord"], "status": "partial_source_boundary"},
            {"operation": "observe_health_and_control_epoch", "path": "codex-rs/hepta-supervisor/src/lib.rs", "symbols": ["SupervisordHealth", "SupervisordClient", "SupervisorEpoch"], "status": "exact_source_boundary"},
            {"operation": "drain_or_change_release", "path": "codex-rs/hepta-supervisor/src/lib.rs", "symbols": ["AgentCommand", "AgentRelease", "TickReport"], "status": "partial_source_boundary"},
        ],
        "remainingBridges": [
            "Bind each design operation to exact methods and named product callers.",
            "Publish the physical persistence schema, migration identifiers and writer-fencing recovery proof.",
            "Qualify service deployment, restart storms, drain deadlines and rollback on target hosts.",
        ],
    },
    {
        "module": "runtime.fleet",
        "guide": "docs/modules/runtime.fleet/TECHNICAL.md",
        "design": "qualification/module-execution-dossiers/detail/runtime.fleet.md",
        "roots": ["codex-rs/hepta-fleet"],
        "lifecycleState": "source_mapped",
        "currentCapability": "The fleet crate exposes the durable-style registry model, release metadata and a deterministic local allocation calculator over bounded host and resource vectors.",
        "targetCapability": "A fleet allocator that enrolls hosts, issues fenced resource leases, reconciles uncertain holders and preserves essential floors across failures and partitions.",
        "operationMappings": [
            {"operation": "register_and_read_fleet_state", "path": "codex-rs/hepta-fleet/src/lib.rs", "symbols": ["FleetRegistry", "AgentRecord", "FleetSnapshot"], "status": "exact_source_boundary"},
            {"operation": "calculate_local_allocation", "path": "codex-rs/hepta-fleet/src/lib.rs", "symbols": ["calculate_local_allocation_v1", "LocalAllocationCalculationV1", "LocalResourceVectorV1"], "status": "exact_source_boundary"},
            {"operation": "bind_release_metadata", "path": "codex-rs/hepta-fleet/src/lib.rs", "symbols": ["RegisteredRelease", "AgentReleaseState", "ReleaseMetadata"], "status": "exact_source_boundary"},
        ],
        "remainingBridges": [
            "Implement and document durable allocation-lease storage, renewal and fencing linearization.",
            "Name the product caller that consumes allocation decisions and starts real resource holders.",
            "Execute fairness, partition, clock-skew and capacity benchmarks on qualified hosts.",
        ],
    },
    {
        "module": "runtime.agentd",
        "guide": "docs/modules/runtime.agentd/TECHNICAL.md",
        "design": "qualification/module-execution-dossiers/detail/runtime.agentd.md",
        "roots": ["codex-rs/hepta-agentd"],
        "lifecycleState": "source_mapped",
        "currentCapability": "The agent host embeds the existing Codex App Server path, exposes a bounded local control protocol and has explicit configuration, client and production-writer host types.",
        "targetCapability": "A one-workspace runtime composition host with authenticated local IPC, frozen run snapshots, deterministic cancellation and owner-preserving restart recovery.",
        "operationMappings": [
            {"operation": "run_agent_host", "path": "codex-rs/hepta-agentd/src/lib.rs", "symbols": ["run", "AgentdConfig", "AgentdIdentity"], "status": "exact_source_boundary"},
            {"operation": "control_and_observe_agent", "path": "codex-rs/hepta-agentd/src/lib.rs", "symbols": ["AgentdClient", "AgentdRequest", "AgentdResponse"], "status": "exact_source_boundary"},
            {"operation": "compose_authorized_writer_host", "path": "codex-rs/hepta-agentd/src/lib.rs", "symbols": ["AgentdProductionWriterHost", "SessionIngress", "LifecycleSnapshot"], "status": "partial_source_boundary"},
        ],
        "remainingBridges": [
            "Publish peer-credential, socket-permission, nonce and replay requirements for every supported platform.",
            "Map start-run, context-attachment and cancellation semantics to exact protocol methods and callsites.",
            "Qualify service installation, crash recovery, upgrade and undeclared-file audits.",
        ],
    },
    {
        "module": "runtime.codex",
        "guide": "docs/modules/runtime.codex/TECHNICAL.md",
        "design": "qualification/module-execution-dossiers/detail/runtime.codex.md",
        "roots": ["codex-rs/codex-app-server", "codex-rs/hepta-codex-adapter"],
        "lifecycleState": "source_mapped",
        "currentCapability": "The Hepta adapter validates an already-authorized payload-bound intent and converts a terminal App Server observation into a deny-all receipt; it does not invoke a model or provider.",
        "targetCapability": "A traced Codex thread and turn boundary that binds actual templates, tokenizer, model profile, delivery observation and final tool authority to the existing App Server spine.",
        "operationMappings": [
            {"operation": "adapt_authorized_app_server_intent", "path": "codex-rs/hepta-codex-adapter/src/lib.rs", "symbols": ["adapt", "CodexOperationIntent", "CodexAdapterReceipt"], "status": "exact_source_boundary"},
            {"operation": "classify_terminal_or_indeterminate_observation", "path": "codex-rs/hepta-codex-adapter/src/lib.rs", "symbols": ["AppServerObservation", "AdapterStatus", "MissingTerminalResponse"], "status": "exact_source_boundary"},
        ],
        "remainingBridges": [
            "Bind open-thread, submit-turn, tool-dispatch and delivery operations to exact App Server RPC symbols and named callers.",
            "Add disconnect, replay, cancellation and acknowledgement-loss integration tests through a real App Server process.",
            "Retain the current authority-free adapter boundary until an independently authorized provider path is composed.",
        ],
    },
    {
        "module": "inference.control",
        "guide": "docs/modules/inference.control/TECHNICAL.md",
        "design": "qualification/module-execution-dossiers/detail/inference.control.md",
        "roots": ["codex-rs/hepta-infer-core", "codex-rs/hepta-inferd"],
        "lifecycleState": "source_mapped",
        "currentCapability": "The control sources provide an in-memory request and reservation state machine plus an exact-bound dispatch plan over request, reservation, lease and model digests.",
        "targetCapability": "A durable inference control plane with quota reservation, deterministic worker selection, outbox dispatch, cancellation settlement and reconciliation of unknown usage.",
        "operationMappings": [
            {"operation": "submit_reserve_complete_or_cancel_request", "path": "codex-rs/hepta-infer-core/src/lib.rs", "symbols": ["InferenceLedger", "InferenceRequest", "LedgerReceipt"], "status": "exact_source_boundary"},
            {"operation": "plan_digest_bound_worker_dispatch", "path": "codex-rs/hepta-inferd/src/lib.rs", "symbols": ["plan", "DispatchRequest", "DispatchPlan"], "status": "exact_source_boundary"},
        ],
        "remainingBridges": [
            "Replace process-memory state with a declared durable schema, transaction/outbox and recovery protocol.",
            "Compose a named scheduler caller and independently authorized provider-dispatch adapter.",
            "Implement quota settlement, cancellation races and unknown-consumption reconciliation with executable fault tests.",
        ],
    },
    {
        "module": "inference.worker",
        "guide": "docs/modules/inference.worker/TECHNICAL.md",
        "design": "qualification/module-execution-dossiers/detail/inference.worker.md",
        "roots": ["codex-rs/hepta-infer-worker-host"],
        "lifecycleState": "source_mapped",
        "currentCapability": "The worker host validates a pre-existing request, lease and reservation and turns an observed terminal result into a receipt; it deliberately does not load or execute a model provider.",
        "targetCapability": "A sandboxed worker that verifies model artifacts and runtime identity, loads under explicit resource grants, performs bounded inference, observes cancellation and reports measured usage.",
        "operationMappings": [
            {"operation": "validate_worker_request_and_observation", "path": "codex-rs/hepta-infer-worker-host/src/lib.rs", "symbols": ["execute", "InferenceRequest", "InferenceReceipt"], "status": "exact_source_boundary"},
            {"operation": "bind_authority_lease_and_reservation", "path": "codex-rs/hepta-infer-worker-host/src/lib.rs", "symbols": ["AuthorityLease", "Reservation", "ExecutionObservation"], "status": "exact_source_boundary"},
        ],
        "remainingBridges": [
            "Implement a provider adapter ABI and real load-model, run and unload lifecycle without weakening authority checks.",
            "Bind weights, tokenizer, runtime, driver and device digests to a measured resource grant.",
            "Qualify streaming, cancellation, out-of-memory, driver-reset and worker-crash behavior with real model execution.",
        ],
    },
    {
        "module": "automation.taskflow",
        "guide": "docs/modules/automation.taskflow/TECHNICAL.md",
        "design": "qualification/module-execution-dossiers/detail/automation.taskflow.md",
        "roots": ["codex-rs/hepta-automation"],
        "lifecycleState": "source_mapped",
        "currentCapability": "The automation crate contains a per-agent schedule and lease store, scheduler interfaces, TaskFlow graph and run state types, and an authority-free local execution-boundary assessment.",
        "targetCapability": "A fenced scheduler that materializes deterministic occurrences, claims one execution owner, routes typed steps through operation owners and reconciles indeterminate effects.",
        "operationMappings": [
            {"operation": "schedule_and_store_automation", "path": "codex-rs/hepta-automation/src/lib.rs", "symbols": ["AutomationScheduler", "AutomationStore", "AutomationSchedule"], "status": "exact_source_boundary"},
            {"operation": "manage_taskflow_definition_and_run", "path": "codex-rs/hepta-automation/src/lib.rs", "symbols": ["TaskFlowDefinition", "TaskFlowRun", "TaskFlowTransition"], "status": "exact_source_boundary"},
            {"operation": "assess_local_execution_boundary", "path": "codex-rs/hepta-automation/src/lib.rs", "symbols": ["assess_local_taskflow_boundary", "TaskFlowBoundaryAuthority", "TaskFlowExecutionUnavailableV1"], "status": "exact_source_boundary"},
        ],
        "remainingBridges": [
            "Freeze recurrence grammar and tzdb versions with executable DST gap, fold and revision fixtures.",
            "Qualify scheduler leadership, lease fencing, missed-run policy and crash-after-dispatch recovery.",
            "Bind the production feature profile and named step runner without granting generated skills execution authority.",
        ],
    },
    {
        "module": "channel.matrix",
        "guide": "docs/modules/channel.matrix/TECHNICAL.md",
        "design": "qualification/module-execution-dossiers/detail/channel.matrix.md",
        "roots": ["codex-rs/hepta-matrix-sdk", "codex-rs/hepta-matrixd"],
        "lifecycleState": "source_mapped",
        "currentCapability": "The Matrix SDK source implements bounded ingress and durable-outbox transport, while the daemon source bridges one enrolled room to the existing Agentd and App Server session path.",
        "targetCapability": "A scoped Matrix channel with durable sync and send identities, redaction propagation, encrypted-session recovery, rate-limit handling and exact terminal delivery observations.",
        "operationMappings": [
            {"operation": "ingest_and_dispatch_matrix_events", "path": "codex-rs/hepta-matrix-sdk/src/lib.rs", "symbols": ["MatrixIngress", "dispatch_outbox_once", "MatrixSdkClient"], "status": "exact_source_boundary"},
            {"operation": "run_matrix_daemon_and_bridge_session", "path": "codex-rs/hepta-matrixd/src/lib.rs", "symbols": ["run", "MatrixRuntime", "MatrixAppServerTransport"], "status": "exact_source_boundary"},
        ],
        "remainingBridges": [
            "Freeze Matrix specification, SDK and homeserver compatibility and document E2EE key lifecycle and recovery.",
            "Qualify sync-token, redaction, retry-after, poisoned-event and acknowledgement-loss behavior against a real homeserver.",
            "Publish daemon service, credential permissions, migration and rollback procedures.",
        ],
    },
    {
        "module": "browser.servo",
        "guide": "docs/modules/browser.servo/TECHNICAL.md",
        "design": "qualification/module-execution-dossiers/detail/browser.servo.md",
        "roots": ["apps/hepta-browser", "third_party/servo-patches"],
        "lifecycleState": "source_mapped",
        "currentCapability": "The JavaScript source validates and projects authority-free navigation proposals and page observations; the Servo manifest pins upstream source but no production navigation caller is asserted.",
        "targetCapability": "An isolated Servo-backed browser session with generation-bound observations, typed navigation and input actions, scoped credentials and reconciliation of unknown remote effects.",
        "operationMappings": [
            {"operation": "build_navigation_intent", "path": "apps/hepta-browser/src/browser.js", "symbols": ["buildNavigationIntent", "buildLocalNavigationProposalFromCanonicalJson"], "status": "exact_source_boundary"},
            {"operation": "project_page_state", "path": "apps/hepta-browser/src/browser.js", "symbols": ["projectPageState", "projectPageStateFromLocalCanonicalJson"], "status": "exact_source_boundary"},
        ],
        "remainingBridges": [
            "Implement and identify the real Servo process or library integration and its DOM and action protocol.",
            "Qualify network, filesystem, DNS, proxy, download, origin and credential sandbox boundaries.",
            "Run real Servo build, stale-element, navigation-race, crash and remote-effect reconciliation tests.",
        ],
    },
    {
        "module": "ui.control",
        "guide": "docs/modules/ui.control/TECHNICAL.md",
        "design": "qualification/module-execution-dossiers/detail/ui.control.md",
        "roots": ["apps/hepta-control-ui"],
        "lifecycleState": "source_mapped",
        "currentCapability": "The control UI source provides authority-free runtime projections and operator request construction with bounded canonical JSON shadow entrypoints and Node tests.",
        "targetCapability": "A production control client using generated versioned protocols, authenticated sessions, coherent state revisions, accessible emergency controls and deployable browser assets.",
        "operationMappings": [
            {"operation": "project_runtime_view", "path": "apps/hepta-control-ui/src/control.js", "symbols": ["projectRuntime", "projectRuntimeFromLocalCanonicalJson"], "status": "exact_source_boundary"},
            {"operation": "build_operator_request", "path": "apps/hepta-control-ui/src/control.js", "symbols": ["buildOperationIntent", "buildLocalOperationProposalFromCanonicalJson"], "status": "exact_source_boundary"},
        ],
        "remainingBridges": [
            "Select and pin the production framework, build pipeline, generated client and deployment artifact.",
            "Implement authenticated session, routing, state management, CSP, error boundaries and sensitive-data presentation rules.",
            "Qualify component, end-to-end, accessibility, localization and browser-compatibility behavior.",
        ],
    },
    {
        "module": "ui.native",
        "guide": "docs/modules/ui.native/TECHNICAL.md",
        "design": "qualification/module-execution-dossiers/detail/ui.native.md",
        "roots": ["apps/hepta-native"],
        "lifecycleState": "source_mapped",
        "currentCapability": "The native UI source constructs payload-bound native-operation intents and refuses terminal success without a trusted backend receipt; it does not invoke host platform APIs.",
        "targetCapability": "A signed native shell with scoped IPC, secure session storage, explicit platform permission decisions, accessible lifecycle handling and independently selected updates.",
        "operationMappings": [
            {"operation": "build_native_operation_intent", "path": "apps/hepta-native/src/native.js", "symbols": ["buildNativeIntent"], "status": "exact_source_boundary"},
            {"operation": "observe_native_outcome", "path": "apps/hepta-native/src/native.js", "symbols": ["observeNativeOutcome"], "status": "exact_source_boundary"},
        ],
        "remainingBridges": [
            "Select and pin the native shell framework and define the OS and architecture support matrix.",
            "Implement IPC allowlists, secure storage, platform permissions, signing, notarization and update rollback.",
            "Qualify crash recovery, request reconciliation, accessibility and release provenance on each target OS.",
        ],
    },
]

NATIVE_OBSERVATIONS = [
    {"module": "runtime.supervisor", "path": "codex-rs/hepta-supervisor/src/lib.rs", "blobSha": "419b613801889ba314ca96b195f7d653774c1ba4", "exports": ["Supervisor", "ProcessDriver", "run_supervisord", "SupervisordClient"], "interpretation": "Concrete supervisor daemon and process-control exports; target deployment and independent acceptance are not inferred."},
    {"module": "runtime.fleet", "path": "codex-rs/hepta-fleet/src/lib.rs", "blobSha": "6e81d287a79e86335dc9456877b5cba872345fee", "exports": ["FleetRegistry", "calculate_local_allocation_v1", "AgentReleaseState"], "interpretation": "Registry and deterministic local allocation exports; durable distributed lease qualification is not inferred."},
    {"module": "runtime.agentd", "path": "codex-rs/hepta-agentd/src/lib.rs", "blobSha": "e6284ae50e73d2801eb208f0df2b568fee8fb64c", "exports": ["AgentdClient", "AgentdProductionWriterHost", "run"], "interpretation": "Agent host and local protocol exports; production composition and deployment evidence remain separate."},
    {"module": "runtime.codex", "path": "codex-rs/hepta-codex-adapter/src/lib.rs", "blobSha": "c81c3ec10dd11a85ed28cf71207ff0f973329c17", "exports": ["adapt", "CodexOperationIntent", "CodexAdapterReceipt"], "interpretation": "Authority-free adapter exports; no model or provider invocation is inferred."},
    {"module": "inference.control", "path": "codex-rs/hepta-infer-core/src/lib.rs", "blobSha": "60757e17b2342a38e62bf43419d07651260a6afe", "exports": ["InferenceLedger", "request_digest", "InferenceRequest"], "interpretation": "In-memory request state machine; durable control-plane execution is not inferred."},
    {"module": "inference.control", "path": "codex-rs/hepta-inferd/src/lib.rs", "blobSha": "a149b745e7eb2d40c93fe312ea95070c119ddb7b", "exports": ["plan", "DispatchPlan", "DispatchRequest"], "interpretation": "Digest-bound dispatch planning; provider dispatch authority is explicitly absent."},
    {"module": "inference.worker", "path": "codex-rs/hepta-infer-worker-host/src/lib.rs", "blobSha": "f4fca6216821c994a401e401442cf06f69a3d082", "exports": ["execute", "InferenceReceipt", "AuthorityLease"], "interpretation": "Request and observation validation boundary; no model loading or provider execution is inferred."},
    {"module": "automation.taskflow", "path": "codex-rs/hepta-automation/src/lib.rs", "blobSha": "f6534c6b20d9fcf9ae6c6b58fac6e6595fcf69a2", "exports": ["AutomationScheduler", "AutomationStore", "TaskFlowDefinition", "assess_local_taskflow_boundary"], "interpretation": "Schedule, graph and local boundary exports; product scheduler authority remains separately gated."},
    {"module": "channel.matrix", "path": "codex-rs/hepta-matrix-sdk/src/lib.rs", "blobSha": "35b644e33e8756c5d780bba1004e73d0b84d0e97", "exports": ["MatrixIngress", "dispatch_outbox_once", "MatrixSdkClient"], "interpretation": "Matrix SDK ingress and outbound exports; remote user reading and administrative authority are not inferred."},
    {"module": "channel.matrix", "path": "codex-rs/hepta-matrixd/src/lib.rs", "blobSha": "4eae4b8b7cb8bb5c57f21be3e076459994e2b1a0", "exports": ["run", "MatrixRuntime", "MatrixAppServerTransport"], "interpretation": "Daemon and App Server bridge exports; target homeserver qualification remains separate."},
    {"module": "browser.servo", "path": "apps/hepta-browser/src/browser.js", "blobSha": "4d8e8cbb1886083ec23d21ef5810c7cca50be81d", "exports": ["buildNavigationIntent", "projectPageState", "buildLocalNavigationProposalFromCanonicalJson"], "interpretation": "Authority-free browser proposal and projection exports; Servo runtime execution is not inferred."},
    {"module": "ui.control", "path": "apps/hepta-control-ui/src/control.js", "blobSha": "9ceeea6df55c108831acd00fca00dd58b8fb8513", "exports": ["projectRuntime", "buildOperationIntent", "buildLocalOperationProposalFromCanonicalJson"], "interpretation": "Authority-free presentation and request-construction exports; deployable UI composition is not inferred."},
    {"module": "ui.native", "path": "apps/hepta-native/src/native.js", "blobSha": "0b43af170d02a2d672c68b18e100a1507957f483", "exports": ["buildNativeIntent", "observeNativeOutcome"], "interpretation": "Native intent and guarded observation exports; host platform execution and signed release are not inferred."},
]


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(relative: str, content: str) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if not content.endswith("\n") and path.suffix in {".md", ".json", ".py", ".yml"}:
        content += "\n"
    path.write_text(content, encoding="utf-8")


def write_json(relative: str, value: Any) -> None:
    path = ROOT / relative
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    compact = bool(original) and len(original.splitlines()) <= 2
    rendered = (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if compact
        else json.dumps(value, ensure_ascii=False, indent=2)
    )
    write_text(relative, rendered)


def claims() -> dict[str, bool]:
    return {key: False for key in FALSE_CLAIMS}


def build_registry() -> dict[str, Any]:
    rows = []
    for source in MODULE_ROWS:
        row = dict(source)
        row["claims"] = claims()
        rows.append(row)
    blockers = [
        {"id": "LB-P0-001-STATE-SOURCE", "state": "closed_by_candidate", "evidence": ["docs/lane-b/LANE_B_CLOSURE.json", "docs/lane-b/STATUS.md"]},
        {"id": "LB-P0-002-RECEIPT-WORKFLOW", "state": "closed_by_candidate", "evidence": [".github/workflows/hepta-lane-b-closure.yml", "docs/lane-b/LANE_B_CLOSURE.json"]},
        {"id": "LB-P0-003-NATIVE-MAPPING", "state": "closed_by_candidate", "evidence": ["qualification/module-execution-dossiers/NATIVE_BINDINGS.json", "scripts/hepta-lane-b-closure.py"]},
        {"id": "LB-P0-004-DEFAULT-BRANCH-CI", "state": "closed_by_candidate", "evidence": [".github/workflows/blocking-ci.yml", ".github/workflows/postmerge-ci.yml"]},
        {"id": "LB-P0-005-EXACT-CANDIDATE-EVIDENCE", "state": "closed_by_candidate", "evidence": [".github/workflows/hepta-lane-b-closure.yml"]},
        {"id": "LB-P1-001-CURRENT-TARGET-BRIDGE", "state": "closed_by_candidate", "evidence": ["docs/lane-b/README.md", "docs/lane-b/LANE_B_CLOSURE.json"]},
        {"id": "LB-P2-001-MACHINE-VERIFICATION", "state": "closed_by_candidate", "evidence": ["scripts/hepta-lane-b-closure.py", ".github/workflows/hepta-implementation-readiness.yml"]},
    ]
    external = [
        {"id": f"RDY-EXT-{index:03d}", "state": "external_evidence_required", "repositoryMaySelfCertify": False}
        for index in range(1, 10)
    ]
    return {
        "schema": "hepta.lane-b-closure.v1",
        "schemaVersion": 1,
        "documentClass": "canonical_subordinate_registry",
        "authorityScope": "repository_internal_documentation_native_mapping_and_ci_evidence_only",
        "planId": "HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN",
        "planVersion": "8.0.0",
        "laneId": "LANE-B-RUNTIME",
        "moduleCount": len(rows),
        "baseline": {
            "repository": "TrillionniumFoundation/hepta-private-ci",
            "baseCommit": BASE_COMMIT,
            "baseTree": BASE_TREE,
            "defaultBranch": DEFAULT_BRANCH,
            "selectionPolicy": "exact_commit_tree_and_ci_receipt_required",
        },
        "lifecycleStates": [
            "specified",
            "source_mapped",
            "compiled",
            "unit_tested",
            "integration_tested",
            "production_called",
            "deployment_qualified",
            "independently_accepted",
        ],
        "claimBoundary": {
            "repositoryInternalGapsClosed": True,
            **claims(),
            "allGapsClosed": False,
        },
        "nativeSourceFiles": len(NATIVE_OBSERVATIONS),
        "modules": rows,
        "repositoryBlockers": blockers,
        "externalGates": external,
        "closureRule": "Repository-internal documentation, mapping and CI blockers may close only with exact candidate evidence. Product, provider, external-effect, deployment, operator, promotion and release claims require separate external receipts.",
    }


def technical_section(row: dict[str, Any]) -> str:
    lines = [
        "## 18. Lane B current capability, native mapping and remaining gates",
        "",
        "<!-- generated: hepta-lane-b-closure -->",
        "",
        "This section is generated from `docs/lane-b/LANE_B_CLOSURE.json` and is the current Lane B status projection. It separates source observation from product execution and supersedes any broader interpretation of a source-location receipt.",
        "",
        "### Current source capability",
        "",
        row["currentCapability"],
        "",
        "### Target capability",
        "",
        row["targetCapability"],
        "",
        "### Native source mapping",
        "",
        "| Design operation | Source path and symbols | Mapping disposition |",
        "|---|---|---|",
    ]
    for mapping in row["operationMappings"]:
        symbols = ", ".join(f"`{symbol}`" for symbol in mapping["symbols"])
        lines.append(
            f"| `{mapping['operation']}` | `{mapping['path']}` — {symbols} | `{mapping['status']}` |"
        )
    lines.extend(["", "### Remaining bridges", ""])
    lines.extend(f"- {item}" for item in row["remainingBridges"])
    lines.extend(
        [
            "",
            "### Evidence boundary",
            "",
            "The mapping above proves named source locations and symbols at the bound baseline. Exact-head and deterministic-merge CI must still pass for each candidate. It grants no model, provider, tool, network, filesystem, Matrix, platform, deployment, acceptance, promotion or release authority.",
            "",
        ]
    )
    return "\n".join(lines)


def source_observation_section(row: dict[str, Any]) -> str:
    roots = "\n".join(f"- `{root}`" for root in row["roots"])
    return (
        "## 17. Lane B source inventory observation\n\n"
        f"The declared source roots for `{row['module']}` are present at the bound baseline:\n\n"
        f"{roots}\n\n"
        "Exact paths and inspected symbols are recorded in `docs/lane-b/LANE_B_CLOSURE.json` and `qualification/module-execution-dossiers/NATIVE_BINDINGS.json`. The read-only gate `.github/workflows/hepta-lane-b-closure.yml` validates the exact source candidate, registered symbols, focused package tests and deterministic merge candidate. A source observation is not product execution, deployment qualification, independent acceptance, promotion or release evidence.\n"
    )


def patch_module_docs(registry: dict[str, Any]) -> None:
    for row in registry["modules"]:
        path = ROOT / row["guide"]
        text = path.read_text(encoding="utf-8")
        text = re.sub(
            r"\n## 18\. Lane B current capability, native mapping and remaining gates\n.*\Z",
            "",
            text,
            flags=re.S,
        )
        replacement = "\n" + source_observation_section(row).rstrip() + "\n"
        pattern = r"\n## 17\. Source implementation receipt\n.*?(?=\n## \d+\.|\Z)"
        text, count = re.subn(pattern, replacement.rstrip(), text, count=1, flags=re.S)
        if count == 0:
            pattern = r"\n## 17\. Lane B source inventory observation\n.*?(?=\n## \d+\.|\Z)"
            text, count = re.subn(pattern, replacement.rstrip(), text, count=1, flags=re.S)
        if count == 0:
            text = text.rstrip() + replacement
        text = text.rstrip() + "\n\n" + technical_section(row)
        path.write_text(text, encoding="utf-8")


def update_native_bindings() -> None:
    relative = "qualification/module-execution-dossiers/NATIVE_BINDINGS.json"
    value = load(ROOT / relative)
    lane_modules = {row["module"] for row in MODULE_ROWS}
    retained = [row for row in value["observations"] if row.get("module") not in lane_modules]
    value["sourceSnapshot"] = BASE_COMMIT
    value["observations"] = retained + NATIVE_OBSERVATIONS
    value["laneBModuleCount"] = len(lane_modules)
    value["laneBSourceFileCount"] = len(NATIVE_OBSERVATIONS)
    value["laneBMappingComplete"] = True
    write_json(relative, value)


def patch_reference_text() -> None:
    replacements = {
        "docs/readiness/README.md": [
            (
                "Five exact source observations in `NATIVE_BINDINGS.json` are neither forty complete native mappings nor production-call evidence.",
                "The exact source observations in `NATIVE_BINDINGS.json` now include all eleven Lane B modules across thirteen source files, while the remaining module mappings and all production-call evidence remain separate gates.",
            )
        ],
        "qualification/module-execution-dossiers/README.md": [
            (
                "five exact inspected source exports",
                "eighteen exact inspected source-file observations, including all eleven Lane B modules",
            )
        ],
        "qualification/module-execution-dossiers/IMPLEMENTATION_CONTRACTS.md": [
            (
                "The source observations in `NATIVE_BINDINGS.json` are deliberately bounded: five inspected source files, not forty proven deployments. The remaining native mappings must be produced by implementation packages.",
                "The source observations in `NATIVE_BINDINGS.json` are deliberately bounded: eighteen inspected source files, including complete source-file coverage for the eleven Lane B modules, not forty proven deployments. The remaining module mappings and every product caller must still be produced by implementation packages.",
            )
        ],
    }
    for relative, rows in replacements.items():
        path = ROOT / relative
        text = path.read_text(encoding="utf-8")
        for old, new in rows:
            if old in text:
                text = text.replace(old, new)
        path.write_text(text, encoding="utf-8")

    relative = "qualification/module-execution-dossiers/IMPLEMENTATION_COMPLETION.json"
    value = load(ROOT / relative)
    item = next(row for row in value["designRequirements"] if row["id"] == "IMP-02")
    item["remainingEvidence"] = (
        "Lane B source-file and symbol mappings are complete at the bound baseline. Re-read changed blobs, map the remaining twenty-nine registered modules, and supply named product callers, executed tests and deployment evidence; source observation alone is not a qualified runtime."
    )
    write_json(relative, value)


def patch_package_manifests() -> None:
    for relative in (
        "apps/hepta-browser/package.json",
        "apps/hepta-control-ui/package.json",
        "apps/hepta-native/package.json",
    ):
        value = load(ROOT / relative)
        value["scripts"] = {
            "check": "node --check src/*.js",
            "test": "node --test",
            "ci": "npm run check && npm test",
        }
        write_json(relative, value)


def patch_work_packages() -> None:
    relative = "docs/delivery/WORK_PACKAGES.json"
    value = load(ROOT / relative)
    matrix = next(row for row in value["packages"] if row["id"] == "MATRIX-1-CHANNEL-BOUNDARY")
    if "codex-rs/hepta-matrixd/**" not in matrix["allowedWritePaths"]:
        matrix["allowedWritePaths"].append("codex-rs/hepta-matrixd/**")
    matrix["allowedWritePaths"] = sorted(matrix["allowedWritePaths"])
    write_json(relative, value)


def branch_block() -> str:
    return "  push:\n    branches:\n      - main\n      - integration/vnext-main-20260811\n"


def patch_branch_trigger(relative: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    text = text.replace("  push:\n    branches: [main]\n", branch_block())
    if DEFAULT_BRANCH not in text and "  push:\n" in text:
        text = text.replace("      - main\n", f"      - main\n      - {DEFAULT_BRANCH}\n", 1)
    path.write_text(text, encoding="utf-8")


def add_verifier_commands(relative: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if "scripts/hepta-lane-b-closure.py" in text:
        return
    anchors = [
        "          python3 scripts/hepta-readiness.py verify\n",
        "          python3 scripts/hepta-gap-closure.py verify\n",
    ]
    commands = (
        "          python3 scripts/hepta-lane-b-closure.py self-test\n"
        "          python3 scripts/hepta-lane-b-closure.py generate-status --check\n"
        "          python3 scripts/hepta-lane-b-closure.py verify\n"
    )
    for anchor in anchors:
        if anchor in text:
            text = text.replace(anchor, anchor + commands)
            path.write_text(text, encoding="utf-8")
            return
    raise RuntimeError(f"no verifier insertion point: {relative}")


def patch_blocking_ci() -> None:
    relative = ".github/workflows/blocking-ci.yml"
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    text = text.replace("  push:\n    branches: [main]\n", branch_block())
    if "  hepta-lane-b:\n" not in text:
        marker = "  repo-checks:\n"
        job = (
            "  hepta-lane-b:\n"
            "    name: Hepta Lane B closure\n"
            "    uses: ./.github/workflows/hepta-lane-b-closure.yml\n"
            "    secrets: inherit\n\n"
        )
        if marker not in text:
            raise RuntimeError("blocking-ci insertion point missing")
        text = text.replace(marker, job + marker, 1)
    needs_marker = "      - repo-checks\n"
    if "      - hepta-lane-b\n" not in text:
        if needs_marker not in text:
            raise RuntimeError("blocking-ci needs insertion point missing")
        text = text.replace(needs_marker, "      - hepta-lane-b\n" + needs_marker, 1)
    path.write_text(text, encoding="utf-8")


def patch_workflows() -> None:
    patch_blocking_ci()
    for relative in (
        ".github/workflows/postmerge-ci.yml",
        ".github/workflows/hepta-consolidated-source.yml",
    ):
        patch_branch_trigger(relative)
    for relative in (
        ".github/workflows/hepta-implementation-readiness.yml",
        ".github/workflows/hepta-development-docs.yml",
        ".github/workflows/hepta-consolidated-source.yml",
    ):
        add_verifier_commands(relative)


def write_lane_docs(registry: dict[str, Any]) -> None:
    write_json("docs/lane-b/LANE_B_CLOSURE.json", registry)
    readme = """# Lane B runtime closure

This directory is the canonical Lane B projection for the eleven registered runtime modules. It closes repository-internal documentation, native-source mapping, branch-trigger and CI-evidence blockers without converting those facts into product-runtime or release authority.

## Read order

1. `LANE_B_CLOSURE.json` — lifecycle states, current capability, target capability, exact source mappings, remaining bridges and evidence boundaries.
2. `STATUS.md` — generated closure projection.
3. `../modules/<module>/TECHNICAL.md` — stable module guide with the generated Lane B current/target/bridge section.
4. `../../qualification/module-execution-dossiers/NATIVE_BINDINGS.json` — exact blob and symbol observations.
5. `../../.github/workflows/hepta-lane-b-closure.yml` — read-only exact-source, focused package and deterministic-merge gate.

## Interpretation

`source_mapped` means that current source paths and exported symbols have been inspected and bound to the design surface. It does not mean that the full target operation, product caller, provider, remote effect, deployment, operator acceptance, promotion or release has been proved.

Repository-internal blockers may be closed by exact candidate documents and CI. The nine `RDY-EXT-*` gates remain external and non-self-certifiable.

## Validation

```bash
python3 scripts/hepta-lane-b-closure.py self-test
python3 scripts/hepta-lane-b-closure.py generate-status --check
python3 scripts/hepta-lane-b-closure.py verify
python3 scripts/hepta_module_doc_metadata.py
python3 scripts/hepta-module-docs.py verify
python3 qualification/module-execution-dossiers/implementation_contracts.py verify-repository
```
"""
    write_text("docs/lane-b/README.md", readme)


def run(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def remove_builder() -> None:
    for relative in (
        ".github/scripts/lane_b_closure_builder.py",
        ".github/workflows/lane-b-closure-builder.yml",
    ):
        path = ROOT / relative
        if path.exists():
            path.unlink()


def main() -> int:
    registry = build_registry()
    write_lane_docs(registry)
    patch_module_docs(registry)
    update_native_bindings()
    patch_reference_text()
    patch_package_manifests()
    patch_work_packages()
    patch_workflows()
    run(sys.executable, "scripts/hepta_module_doc_metadata.py", "--write")
    run(sys.executable, "scripts/hepta-lane-b-closure.py", "generate-status")
    remove_builder()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
