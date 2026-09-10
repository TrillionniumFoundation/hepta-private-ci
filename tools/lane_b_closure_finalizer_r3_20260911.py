#!/usr/bin/env python3
"""Materialize the repository-local Lane B closure candidate, then remove itself.

This temporary developer utility performs deterministic repository edits only. The
companion workflow commits the resulting read-only validators and documentation,
executes the exact candidate checks, and pushes only when they pass.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASE = "04f60466394a024c218ce66b1b32d1c42c462985"
BRANCH = "codex/lane-b-gap-closure-20260911"
SELF_PATH = "tools/lane_b_closure_finalizer_r3_20260911.py"
WORKFLOW_PATH = ".github/workflows/lane-b-closure-finalizer-r3-20260911.yml"
MAPPING_PATH = "qualification/module-execution-dossiers/NATIVE_BINDINGS.json"
VALIDATOR_PATH = "qualification/module-execution-dossiers/lane_b_contracts.py"
TEST_PATH = "qualification/module-execution-dossiers/test_lane_b_contracts.py"
STATUS_PATH = "qualification/module-execution-dossiers/LANE_B_STATUS.md"
DEFAULT_BRANCH = "integration/vnext-main-20260811"

LANE_B: dict[str, dict[str, Any]] = {
    "runtime.supervisor": {
        "roots": ["codex-rs/hepta-supervisor"],
        "packages": ["codex-hepta-supervisor"],
        "binaries": ["hepta-supervisord", "hepta-authority-signer", "hepta-final-use-signer"],
        "sourceFiles": [
            ("codex-rs/hepta-supervisor/src/lib.rs", ["Supervisor", "run_supervisord", "ProcessDriver", "SupervisordClient", "TickReport"]),
        ],
        "operations": [
            ("start_instance", "native_boundary_partial", ["Supervisor", "ProcessDriver"], "Process construction and fencing primitives exist; the dossier-level selected-snapshot operation still needs a named product caller receipt."),
            ("observe_health", "native_boundary_partial", ["Supervisor", "TickReport"], "Health and tick surfaces exist; readiness composition and deployed watchdog measurements remain separate evidence."),
            ("drain", "native_boundary_partial", ["Supervisor"], "Lifecycle control exists; product drain, unknown-effect reconciliation and deployment timing remain unproved."),
            ("load_next", "native_boundary_partial", ["Supervisor"], "Release transition machinery exists; independent artifact selection and new-process activation remain external gates."),
        ],
        "boundary": "A real supervisor daemon and process driver are present. Model, tool and secret execution are deliberately outside this module, and deployment qualification is not inferred.",
    },
    "runtime.fleet": {
        "roots": ["codex-rs/hepta-fleet"],
        "packages": ["codex-hepta-fleet"],
        "binaries": [],
        "sourceFiles": [
            ("codex-rs/hepta-fleet/src/lib.rs", ["FleetRegistry", "calculate_local_allocation_v1", "LocalAllocationCalculationV1", "AgentReleaseState"]),
        ],
        "operations": [
            ("admit_host", "native_boundary_partial", ["FleetRegistry"], "Registry primitives exist; explicit remote enrollment, freshness and lease authority require a named composition path."),
            ("allocate", "native_symbol", ["calculate_local_allocation_v1", "LocalAllocationCalculationV1"], "The deterministic local allocation calculator is directly observed and remains authority-free."),
            ("renew_or_revoke", "native_boundary_partial", ["FleetRegistry", "AgentReleaseState"], "Lifecycle records exist; a durable allocation lease owner and current-fence renewal path remain product integration evidence."),
        ],
        "boundary": "The crate contains durable-style registry and deterministic local allocation logic. It does not prove a distributed allocator deployment or remote host ownership.",
    },
    "runtime.agentd": {
        "roots": ["codex-rs/hepta-agentd"],
        "packages": ["codex-hepta-agentd"],
        "binaries": ["codex-hepta-agentd"],
        "sourceFiles": [
            ("codex-rs/hepta-agentd/src/lib.rs", ["AgentdClient", "AgentdConfig", "AgentdProductionWriterHost", "run", "SessionIngress"]),
        ],
        "operations": [
            ("compose_runtime", "native_boundary_partial", ["run", "AgentdConfig"], "The process host and configuration boundary exist; complete owner-port composition remains callsite evidence."),
            ("start_run", "native_boundary_partial", ["run", "SessionIngress"], "The existing App Server path is embedded, but the dossier operation has no independently accepted end-to-end receipt."),
            ("cancel_run", "native_boundary_partial", ["AgentdClient"], "A typed local control client exists; cancel-before and cancel-after dispatch product races remain qualification evidence."),
            ("attach_context", "native_boundary_partial", ["SessionIngress"], "Session ingress is observed; exact objective/body/artifact attachment through a product caller remains unproved."),
        ],
        "boundary": "A one-process-per-workspace host and local control protocol exist. The source observation does not grant a second runtime kernel or prove production writer activation.",
    },
    "runtime.codex": {
        "roots": ["codex-rs/codex-app-server", "codex-rs/hepta-codex-adapter"],
        "packages": ["codex-app-server", "codex-hepta-codex-adapter"],
        "binaries": [],
        "sourceFiles": [
            ("codex-rs/hepta-codex-adapter/src/lib.rs", ["CodexOperationIntent", "AppServerObservation", "CodexAdapterReceipt", "adapt"]),
        ],
        "operations": [
            ("open_thread", "target_unimplemented", [], "The upstream App Server root is bound, but no Lane B adapter symbol implements this dossier operation."),
            ("submit_turn", "target_unimplemented", [], "The upstream execution spine exists outside this narrow adapter; an exact adapter/caller mapping remains absent."),
            ("dispatch_tool", "native_boundary_partial", ["adapt", "CodexOperationIntent"], "The adapter validates an already-authorized intent and observes an outcome; it does not execute a tool."),
            ("observe_delivery", "native_boundary_partial", ["adapt", "AppServerObservation"], "Terminal observation mapping exists; exact payload submission and product exposure evidence remain separate."),
        ],
        "boundary": "The observed adapter is intentionally authority-free. It does not mint model/provider authority and is not itself an App Server transport.",
    },
    "inference.control": {
        "roots": ["codex-rs/hepta-infer-core", "codex-rs/hepta-inferd"],
        "packages": ["codex-hepta-infer-core", "codex-hepta-inferd"],
        "binaries": [],
        "sourceFiles": [
            ("codex-rs/hepta-infer-core/src/lib.rs", ["InferenceLedger", "InferenceRequest", "RequestStatus", "request_digest"]),
            ("codex-rs/hepta-inferd/src/lib.rs", ["DispatchRequest", "DispatchPlan", "plan"]),
        ],
        "operations": [
            ("reserve_request", "native_symbol", ["InferenceLedger"], "The bounded state machine implements request reservation; durable host persistence is not inferred."),
            ("schedule", "native_symbol", ["plan", "DispatchPlan"], "Exact digest-bound planning is directly observed; provider dispatch authority remains false."),
            ("cancel", "native_symbol", ["InferenceLedger", "RequestStatus"], "The ledger implements cancellation state transitions within its current in-memory boundary."),
            ("settle", "native_symbol", ["InferenceLedger", "RequestStatus"], "The ledger implements terminal completion; quota accounting, outbox and provider reconciliation remain product work."),
        ],
        "boundary": "Request state and dispatch planning are present. No observed function dispatches a provider or executes a model.",
    },
    "inference.worker": {
        "roots": ["codex-rs/hepta-infer-worker-host"],
        "packages": ["codex-hepta-infer-worker-host"],
        "binaries": [],
        "sourceFiles": [
            ("codex-rs/hepta-infer-worker-host/src/lib.rs", ["InferenceRequest", "AuthorityLease", "Reservation", "InferenceReceipt", "execute"]),
        ],
        "operations": [
            ("load_model", "target_unimplemented", [], "No observed symbol loads verified model bytes into a real runtime or device."),
            ("run", "native_boundary_partial", ["execute", "InferenceReceipt"], "The function validates bindings and maps an supplied observation into a receipt; it does not invoke a provider."),
            ("unload", "target_unimplemented", [], "No observed symbol drains and unloads an actual model/runtime handle."),
        ],
        "boundary": "This crate is an authority-checked receipt boundary, not a model worker implementation. Real weights, tokenizer, runtime, device and measured resources remain external evidence.",
    },
    "automation.taskflow": {
        "roots": ["codex-rs/hepta-automation"],
        "packages": ["codex-hepta-automation"],
        "binaries": [],
        "sourceFiles": [
            ("codex-rs/hepta-automation/src/lib.rs", ["AutomationStore", "AutomationScheduler", "TaskFlowRun", "TaskFlowFence", "assess_local_taskflow_boundary"]),
        ],
        "operations": [
            ("register_schedule", "native_boundary_partial", ["AutomationStore"], "A durable automation store exists; the dossier API name and external caller remain to be bound."),
            ("materialize_due", "native_boundary_partial", ["AutomationScheduler"], "Scheduling machinery exists; tzdb version, DST policy and product timing receipts remain required."),
            ("claim_occurrence", "native_boundary_partial", ["TaskFlowFence", "TaskFlowRun"], "Fenced taskflow structures exist; multi-scheduler product contention evidence remains required."),
            ("execute_step", "native_boundary_partial", ["assess_local_taskflow_boundary"], "A local boundary assessment exists; it grants no scheduler or external-effect authority."),
        ],
        "boundary": "Schedules, leases and taskflow structures exist. Structural qualification features remain opt-in and do not establish production effect execution.",
    },
    "channel.matrix": {
        "roots": ["codex-rs/hepta-matrix-sdk", "codex-rs/hepta-matrixd"],
        "packages": ["codex-hepta-matrix-sdk", "codex-hepta-matrixd"],
        "binaries": ["codex-hepta-matrixd"],
        "sourceFiles": [
            ("codex-rs/hepta-matrix-sdk/src/lib.rs", ["MatrixIngress", "MatrixOutboundTransport", "dispatch_outbox_once", "MatrixSdkClient"]),
            ("codex-rs/hepta-matrixd/src/lib.rs", ["MatrixRuntime", "MatrixDispatchOutcome", "MatrixAppServerTransport", "run"]),
        ],
        "operations": [
            ("admit_event", "native_boundary_partial", ["MatrixIngress", "MatrixRuntime"], "Ingress and daemon runtime boundaries exist; enrolled-room and E2EE deployment evidence remains required."),
            ("prepare_send", "native_boundary_partial", ["MatrixOutboundTransport", "dispatch_outbox_once"], "Durable outbox dispatch primitives exist; final payload-bound authority remains external to the transport."),
            ("observe_send", "native_boundary_partial", ["MatrixDispatchOutcome", "MatrixRuntime"], "Delivery dispositions exist; server persistence and downstream reading remain distinct claims."),
        ],
        "boundary": "Both SDK and daemon roots are observed and included in one work-package verification surface. Matrix transport does not provide administrative authority.",
    },
    "browser.servo": {
        "roots": ["apps/hepta-browser", "third_party/servo-patches"],
        "packages": ["@hepta/browser"],
        "binaries": [],
        "sourceFiles": [
            ("apps/hepta-browser/src/browser.js", ["buildNavigationIntent", "projectPageState", "buildLocalNavigationProposalFromCanonicalJson"]),
        ],
        "operations": [
            ("open_profile", "target_unimplemented", [], "No observed source opens an isolated Servo profile or acquires browser process resources."),
            ("observe_page", "native_symbol", ["projectPageState"], "A bounded authority-free page projection is directly observed."),
            ("navigate_or_act", "native_boundary_partial", ["buildNavigationIntent", "buildLocalNavigationProposalFromCanonicalJson"], "Intent construction exists; no network navigation or browser effect is performed."),
        ],
        "boundary": "The JavaScript core is a shadow qualification boundary. The Servo manifest pins upstream identity but does not prove runtime integration or sandbox qualification.",
    },
    "ui.control": {
        "roots": ["apps/hepta-control-ui"],
        "packages": ["@hepta/control-ui"],
        "binaries": [],
        "sourceFiles": [
            ("apps/hepta-control-ui/src/control.js", ["projectRuntime", "buildOperationIntent", "projectRuntimeFromLocalCanonicalJson"]),
        ],
        "operations": [
            ("read_view", "native_symbol", ["projectRuntime", "projectRuntimeFromLocalCanonicalJson"], "Bounded runtime projection is directly observed and remains presentation-only."),
            ("submit_request", "native_boundary_partial", ["buildOperationIntent"], "Intent construction exists; backend authentication and owner mutation are not performed by this package."),
            ("request_stop", "target_unimplemented", [], "No observed source implements an authenticated stop request through a backend owner."),
        ],
        "boundary": "The current package is an authority-free presentation core, not a complete web application or production caller.",
    },
    "ui.native": {
        "roots": ["apps/hepta-native"],
        "packages": ["@hepta/native"],
        "binaries": [],
        "sourceFiles": [
            ("apps/hepta-native/src/native.js", ["buildNativeIntent", "observeNativeOutcome"]),
        ],
        "operations": [
            ("connect_runtime", "target_unimplemented", [], "No observed shell/runtime transport establishes an authenticated native session."),
            ("render_runtime_view", "target_unimplemented", [], "No observed native shell renders the shared runtime view."),
            ("request_platform_capability", "native_boundary_partial", ["buildNativeIntent"], "A payload-bound authority-free intent is constructed; no host API is invoked."),
            ("apply_shell_update", "target_unimplemented", [], "No observed source verifies, installs or rolls back a signed native shell package."),
        ],
        "boundary": "The current package models native intents and indeterminate outcomes. It does not call platform APIs, install updates or prove OS release qualification.",
    },
}

EXPECTED_OPERATIONS = {module: [row[0] for row in spec["operations"]] for module, spec in LANE_B.items()}


def run(*args: str, check: bool = True) -> str:
    proc = subprocess.run(
        list(args), cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if check and proc.returncode:
        raise RuntimeError("command failed: " + " ".join(args) + "\n" + proc.stderr)
    return proc.stdout.strip()


def load_json(path: str) -> Any:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def write_json(path: str, value: Any) -> None:
    (ROOT / path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def blob_sha(path: str) -> str:
    return run("git", "hash-object", path)


def root_manifest(root: str) -> str:
    candidates = [f"{root}/Cargo.toml", f"{root}/package.json", f"{root}/MANIFEST.json", f"{root}/README.md"]
    for candidate in candidates:
        if (ROOT / candidate).is_file():
            return candidate
    raise RuntimeError("no root manifest: " + root)


def test_paths(roots: list[str]) -> list[str]:
    tracked = run("git", "ls-files", "--", *roots).splitlines()
    selected = []
    for path in tracked:
        name = Path(path).name.lower()
        if (
            "/test/" in path
            or "/tests/" in path
            or name.startswith("test_")
            or "_test" in name
            or "_tests" in name
            or name.endswith(".test.js")
        ) and Path(path).suffix.lower() in {".rs", ".js", ".ts", ".tsx", ".py"}:
            selected.append(path)
    return sorted(set(selected))[:128]


def source_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for module, spec in LANE_B.items():
        source_files = []
        all_symbols: set[str] = set()
        for path, symbols in spec["sourceFiles"]:
            text = (ROOT / path).read_text(encoding="utf-8")
            missing = [symbol for symbol in symbols if re.search(r"\b" + re.escape(symbol) + r"\b", text) is None]
            if missing:
                raise RuntimeError(f"{module}: missing symbols in {path}: {missing}")
            source_files.append({"path": path, "blobSha": blob_sha(path), "symbols": symbols})
            all_symbols.update(symbols)
        operation_mappings = []
        for operation, disposition, symbols, boundary in spec["operations"]:
            if not set(symbols) <= all_symbols:
                raise RuntimeError(f"{module}.{operation}: unmapped symbols")
            operation_mappings.append(
                {
                    "operation": operation,
                    "disposition": disposition,
                    "symbols": symbols,
                    "boundary": boundary,
                }
            )
        roots = spec["roots"]
        manifests = [
            {
                "root": root,
                "manifestPath": root_manifest(root),
                "manifestBlobSha": blob_sha(root_manifest(root)),
            }
            for root in roots
        ]
        tests = test_paths(roots)
        if not tests:
            raise RuntimeError(module + ": no tracked tests observed")
        primary = source_files[0]
        rows.append(
            {
                "module": module,
                "lane": "B",
                "path": primary["path"],
                "blobSha": primary["blobSha"],
                "exports": primary["symbols"],
                "declaredRoots": roots,
                "rootEvidence": manifests,
                "sourceFiles": source_files,
                "packages": spec["packages"],
                "binaries": spec["binaries"],
                "testPaths": tests,
                "operationMappings": operation_mappings,
                "currentCapabilityBoundary": spec["boundary"],
                "productionCallerProved": False,
                "productExecutionProved": False,
                "deploymentQualified": False,
                "independentAcceptance": False,
                "interpretation": spec["boundary"],
            }
        )
    return rows


def update_native_bindings(rows: list[dict[str, Any]]) -> None:
    value = load_json(MAPPING_PATH)
    value["sourceSnapshot"] = BASE
    value["observations"] = [row for row in value["observations"] if row.get("lane") != "B"] + rows
    operation_count = sum(len(row["operationMappings"]) for row in rows)
    value["laneB"] = {
        "schema": "hepta.lane-b-source-disposition.v1",
        "moduleCount": len(rows),
        "registeredOperationCount": operation_count,
        "allDeclaredRootsObserved": True,
        "allRegisteredOperationsDisposed": True,
        "repositoryLocalMappingGapsClosed": True,
        "nativeProductExecutionProved": False,
        "productionCallersProved": False,
        "deploymentQualified": False,
        "independentAcceptance": False,
        "remainingGateClass": "product_execution_deployment_and_external_evidence",
    }
    write_json(MAPPING_PATH, value)


def technical_section(row: dict[str, Any]) -> str:
    source_lines = []
    for source in row["sourceFiles"]:
        source_lines.append(
            f"- `{source['path']}` at Git blob `{source['blobSha']}`: "
            + ", ".join(f"`{symbol}`" for symbol in source["symbols"])
            + "."
        )
    operation_lines = []
    for mapping in row["operationMappings"]:
        symbols = ", ".join(f"`{symbol}`" for symbol in mapping["symbols"]) or "no matching native symbol"
        operation_lines.append(
            f"- `{mapping['operation']}` — `{mapping['disposition']}`; {symbols}. {mapping['boundary']}"
        )
    return "\n".join(
        [
            "## 17. Lane B source observation and execution-evidence boundary",
            "",
            f"The closed-world Lane B source registry records every declared root and every dossier operation for `{row['module']}`. This is an exact source observation and disposition, not a claim that a production caller executed the operation.",
            "",
            "Observed source files:",
            "",
            *source_lines,
            "",
            "Registered operation dispositions:",
            "",
            *operation_lines,
            "",
            f"Current capability boundary: {row['currentCapabilityBoundary']}",
            "",
            "Repository verification is performed by `python3 qualification/module-execution-dossiers/lane_b_contracts.py verify-repository`. Exact source-head and synthetic-merge checks run in `.github/workflows/hepta-implementation-readiness.yml`; compiled package and JavaScript tests are configured in `.github/workflows/hepta-consolidated-source.yml` and aggregated by the blocking CI entrypoint.",
            "",
            "Source presence, symbol mapping, a passing unit test or a queued workflow cannot establish a production caller, real provider/model/browser/platform effect, deployment qualification, independent acceptance, selection, promotion or release. Those states require their separately named evidence gates.",
            "",
        ]
    )


def update_module_documents(rows: list[dict[str, Any]]) -> None:
    by_module = {row["module"]: row for row in rows}
    for module, row in by_module.items():
        path = ROOT / f"docs/modules/{module}/TECHNICAL.md"
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"\n## 17\..*\Z", "\n", text, flags=re.S).rstrip() + "\n\n" + technical_section(row)
        path.write_text(text, encoding="utf-8")
        dossier = ROOT / f"qualification/module-execution-dossiers/detail/{module}.md"
        detail = dossier.read_text(encoding="utf-8")
        detail = re.sub(
            r"^Status:.*$",
            "Status: source-observed design with closed-world operation disposition; product execution, deployment qualification and independent acceptance remain unproved.",
            detail,
            count=1,
            flags=re.M,
        )
        if "## 8. Lane B source disposition" not in detail:
            detail = detail.rstrip() + "\n\n## 8. Lane B source disposition\n\n"
            detail += f"All registered operations for `{module}` have an exact source disposition in `../NATIVE_BINDINGS.json`. A `target_unimplemented` or `native_boundary_partial` disposition remains an implementation or integration gate; it is not converted into success by documentation. The repository-local mapping surface is closed while product execution and independent evidence remain separately governed.\n"
        dossier.write_text(detail, encoding="utf-8")


def replace_once_or_leave(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old in text:
        target.write_text(text.replace(old, new), encoding="utf-8")


def update_companion_prose() -> None:
    replace_once_or_leave(
        "docs/readiness/README.md",
        "The original 160 named acceptance cases are test designs, not pass receipts. Five exact source observations in `NATIVE_BINDINGS.json` are neither forty complete native mappings nor production-call evidence.",
        "The original 160 named acceptance cases are test designs, not pass receipts. `NATIVE_BINDINGS.json` retains the five prior observations and adds closed-world root, symbol, test-path and operation dispositions for all eleven Lane B modules. These remain source observations rather than production-call, deployment or independent-acceptance evidence.",
    )
    replace_once_or_leave(
        "qualification/module-execution-dossiers/IMPLEMENTATION_CONTRACTS.md",
        "The source observations in `NATIVE_BINDINGS.json` are deliberately bounded: five inspected source files, not forty proven deployments. The remaining native mappings must be produced by implementation packages. No source path, function name, digest or generated profile establishes a production call, physical effect or accepted capability.",
        "The source observations in `NATIVE_BINDINGS.json` are deliberately bounded. In addition to the five prior inspected files, all eleven Lane B modules now have complete declared-root coverage and a disposition for every registered operation. This closes the Lane B source-mapping inventory only; no source path, function name, digest or generated profile establishes a production call, provider/browser/platform effect, deployment or accepted capability.",
    )
    readme = ROOT / "qualification/module-execution-dossiers/README.md"
    text = readme.read_text(encoding="utf-8")
    text = text.replace(
        "[NATIVE_BINDINGS.json](NATIVE_BINDINGS.json): five exact inspected source exports, explicitly distinguished from proposed implementation operations and production evidence.",
        "[NATIVE_BINDINGS.json](NATIVE_BINDINGS.json): exact source observations, including closed-world root and operation dispositions for all eleven Lane B modules, explicitly distinguished from product execution and deployment evidence.",
    )
    if "[LANE_B_STATUS.md](LANE_B_STATUS.md)" not in text:
        anchor = "[NATIVE_BINDINGS.json](NATIVE_BINDINGS.json)"
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if anchor in line:
                lines.insert(index + 1, "12. [LANE_B_STATUS.md](LANE_B_STATUS.md): generated repository-local Lane B mapping status and remaining external gate boundary.")
                break
        text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    readme.write_text(text, encoding="utf-8")


def update_gap_registries() -> None:
    completion_path = "qualification/module-execution-dossiers/IMPLEMENTATION_COMPLETION.json"
    completion = load_json(completion_path)
    imp2 = next(row for row in completion["designRequirements"] if row["id"] == "IMP-02")
    for path in [MAPPING_PATH, STATUS_PATH, VALIDATOR_PATH]:
        if path not in imp2["documents"]:
            imp2["documents"].append(path)
    imp2["remainingEvidence"] = (
        "All eleven Lane B modules now have exact declared-root, manifest, source-blob, symbol, test-path and registered-operation disposition coverage. Product callers, durable production stores where applicable, real provider/browser/platform execution, deployment qualification, other-lane mappings and independent review remain separate evidence."
    )
    write_json(completion_path, completion)

    gaps_path = "qualification/module-execution-dossiers/DETAIL_GAPS.json"
    gaps = load_json(gaps_path)
    for row in gaps["moduleDesignRequirements"]:
        if row["module"] in LANE_B:
            if MAPPING_PATH not in row["evidence"]:
                row["evidence"].append(MAPPING_PATH)
            row["nextGate"] = "product_caller_store_deployment_tests_and_independent_review"
    gaps["unresolvedIntegrationRequirements"] = [
        "real_product_caller_store_and_deployment_binding"
        if value == "real_per_module_native_symbol_and_store_binding"
        else value
        for value in gaps["unresolvedIntegrationRequirements"]
    ]
    write_json(gaps_path, gaps)


def validator_source() -> str:
    template = r'''#!/usr/bin/env python3
"""Verify Lane B source disposition, documentation truthfulness and CI coverage."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MAPPING = ROOT / "qualification/module-execution-dossiers/NATIVE_BINDINGS.json"
EXPECTED_OPERATIONS = __EXPECTED_OPERATIONS__
ALLOWED_DISPOSITIONS = {"native_symbol", "native_boundary_partial", "target_unimplemented"}
DEFAULT_BRANCH = "integration/vnext-main-20260811"

class Invalid(ValueError):
    pass

def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in items:
        if key in out:
            raise Invalid("duplicate JSON key: " + key)
        out[key] = value
    return out

def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(Invalid(value)))

def git_blob(path: str) -> str:
    proc = subprocess.run(["git", "-C", str(ROOT), "hash-object", path], text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode:
        raise Invalid("cannot hash " + path)
    return proc.stdout.strip()

def need(value: bool, message: str) -> None:
    if not value:
        raise Invalid(message)

def verify_repository() -> dict[str, Any]:
    native = read_json(MAPPING)
    lane_meta = native.get("laneB")
    need(isinstance(lane_meta, dict), "missing Lane B metadata")
    need(lane_meta.get("moduleCount") == 11, "Lane B module count")
    need(lane_meta.get("registeredOperationCount") == 39, "Lane B operation count")
    need(lane_meta.get("allDeclaredRootsObserved") is True, "root observation closure")
    need(lane_meta.get("allRegisteredOperationsDisposed") is True, "operation disposition closure")
    need(lane_meta.get("repositoryLocalMappingGapsClosed") is True, "local mapping closure")
    for key in ("nativeProductExecutionProved", "productionCallersProved", "deploymentQualified", "independentAcceptance"):
        need(lane_meta.get(key) is False, "false capability claim: " + key)

    profiles = read_json(ROOT / "qualification/module-execution-dossiers/IMPLEMENTATION_PROFILES.json")
    profile_by_module = {row["module"]: row for row in profiles["modules"]}
    rows = [row for row in native["observations"] if row.get("lane") == "B"]
    need(len(rows) == 11 and {row["module"] for row in rows} == set(EXPECTED_OPERATIONS), "Lane B observation coverage")
    dispositions = {key: 0 for key in ALLOWED_DISPOSITIONS}
    for row in rows:
        module = row["module"]
        need(row["declaredRoots"] == profile_by_module[module]["declaredRoots"], module + ": declared roots")
        roots = set(row["declaredRoots"])
        evidence = row["rootEvidence"]
        need({item["root"] for item in evidence} == roots, module + ": root evidence coverage")
        for item in evidence:
            manifest = item["manifestPath"]
            need(Path(manifest).is_relative_to(Path(item["root"])), module + ": manifest root")
            need((ROOT / manifest).is_file(), module + ": manifest missing")
            need(git_blob(manifest) == item["manifestBlobSha"], module + ": manifest drift")
        observed_symbols: set[str] = set()
        for source in row["sourceFiles"]:
            path = source["path"]
            need((ROOT / path).is_file(), module + ": source file missing")
            need(any(Path(path).is_relative_to(Path(root)) for root in roots), module + ": source outside roots")
            need(git_blob(path) == source["blobSha"], module + ": source blob drift")
            text = (ROOT / path).read_text(encoding="utf-8")
            for symbol in source["symbols"]:
                need(re.search(r"\b" + re.escape(symbol) + r"\b", text) is not None, module + ": missing symbol " + symbol)
                observed_symbols.add(symbol)
        mappings = row["operationMappings"]
        need([item["operation"] for item in mappings] == EXPECTED_OPERATIONS[module], module + ": operation order/coverage")
        for item in mappings:
            disposition = item["disposition"]
            need(disposition in ALLOWED_DISPOSITIONS, module + ": disposition")
            need(set(item["symbols"]) <= observed_symbols, module + ": operation symbol mapping")
            need(bool(item["boundary"]), module + ": operation boundary")
            if disposition == "target_unimplemented":
                need(not item["symbols"], module + ": target operation cannot claim symbols")
            dispositions[disposition] += 1
        tests = row["testPaths"]
        need(bool(tests), module + ": no tests observed")
        for path in tests:
            need((ROOT / path).is_file(), module + ": missing test path")
            need(any(Path(path).is_relative_to(Path(root)) for root in roots), module + ": test outside roots")
        for key in ("productionCallerProved", "productExecutionProved", "deploymentQualified", "independentAcceptance"):
            need(row.get(key) is False, module + ": false evidence claim " + key)
        guide = (ROOT / f"docs/modules/{module}/TECHNICAL.md").read_text(encoding="utf-8")
        need("## 17. Lane B source observation and execution-evidence boundary" in guide, module + ": source boundary section")
        need("hepta-gap-closure.yml" not in guide, module + ": stale receipt workflow")
        for operation in EXPECTED_OPERATIONS[module]:
            need(f"`{operation}`" in guide, module + ": guide operation disposition")
        detail = (ROOT / f"qualification/module-execution-dossiers/detail/{module}.md").read_text(encoding="utf-8")
        need("source-observed design with closed-world operation disposition" in detail, module + ": dossier state")

    current = read_json(ROOT / "docs/CURRENT.json")
    need(current["repository"]["defaultBranch"] == DEFAULT_BRANCH, "default branch registry")
    blocking = (ROOT / ".github/workflows/blocking-ci.yml").read_text(encoding="utf-8")
    postmerge = (ROOT / ".github/workflows/postmerge-ci.yml").read_text(encoding="utf-8")
    consolidated = (ROOT / ".github/workflows/hepta-consolidated-source.yml").read_text(encoding="utf-8")
    need("branches: [main, integration/vnext-main-20260811]" in blocking, "blocking default branch trigger")
    need("branches: [main, integration/vnext-main-20260811]" in postmerge, "postmerge default branch trigger")
    need("hepta-lane-b:" in blocking and "hepta-consolidated-source.yml" in blocking, "blocking Lane B aggregation")
    need("workflow_call:" in consolidated, "reusable Lane B workflow")
    for token in [
        "codex-hepta-supervisor", "codex-hepta-fleet", "codex-hepta-agentd",
        "codex-hepta-codex-adapter", "codex-hepta-infer-core", "codex-hepta-inferd",
        "codex-hepta-infer-worker-host", "codex-hepta-automation",
        "codex-hepta-matrix-sdk", "codex-hepta-matrixd",
        "apps/hepta-browser/test/*.js", "apps/hepta-control-ui/test/*.js", "apps/hepta-native/test/*.js",
        "lane_b_contracts.py verify-repository",
    ]:
        need(token in consolidated, "consolidated source token " + token)
    for path in [
        ".github/workflows/hepta-development-docs.yml",
        ".github/workflows/hepta-implementation-readiness.yml",
    ]:
        text = (ROOT / path).read_text(encoding="utf-8")
        need(text.count("lane_b_contracts.py verify-repository") >= 2, path + ": source/merge Lane B checks")
    return {
        "status": "PASS_LANE_B_REPOSITORY_LOCAL_CLOSURE",
        "modules": len(rows),
        "registeredOperations": sum(dispositions.values()),
        "dispositions": dispositions,
        "repositoryLocalMappingGapsClosed": True,
        "nativeProductExecutionProved": False,
        "deploymentQualified": False,
        "independentAcceptance": False,
    }

def self_test() -> int:
    suite = unittest.defaultTestLoader.discover(str(MAPPING.parent), pattern="test_lane_b_contracts.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["self-test", "verify-repository"])
    args = parser.parse_args()
    try:
        if args.command == "self-test":
            return self_test()
        print(json.dumps(verify_repository(), sort_keys=True))
        return 0
    except (Invalid, OSError, KeyError, TypeError, ValueError, subprocess.SubprocessError) as exc:
        print("FAIL_LANE_B_CONTRACTS: " + str(exc), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
'''
    return template.replace("__EXPECTED_OPERATIONS__", repr(EXPECTED_OPERATIONS))


def test_source() -> str:
    return '''from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

PATH = Path(__file__).with_name("lane_b_contracts.py")
SPEC = importlib.util.spec_from_file_location("lane_b_contracts", PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)

class LaneBContractTests(unittest.TestCase):
    def test_closed_world_counts(self):
        self.assertEqual(len(MOD.EXPECTED_OPERATIONS), 11)
        self.assertEqual(sum(map(len, MOD.EXPECTED_OPERATIONS.values())), 39)

    def test_operation_identity_is_unique(self):
        for module, operations in MOD.EXPECTED_OPERATIONS.items():
            self.assertEqual(len(operations), len(set(operations)), module)
            self.assertTrue(all(operation and operation == operation.strip() for operation in operations))

    def test_duplicate_json_keys_fail(self):
        with self.assertRaises(MOD.Invalid):
            json.loads('{"a":1,"a":2}', object_pairs_hook=MOD.pairs)

    def test_disposition_set_is_closed(self):
        self.assertEqual(
            MOD.ALLOWED_DISPOSITIONS,
            {"native_symbol", "native_boundary_partial", "target_unimplemented"},
        )

if __name__ == "__main__":
    unittest.main()
'''


def write_validator_files() -> None:
    (ROOT / VALIDATOR_PATH).write_text(validator_source(), encoding="utf-8")
    (ROOT / TEST_PATH).write_text(test_source(), encoding="utf-8")
    os.chmod(ROOT / VALIDATOR_PATH, 0o755)


def insert_after_command(path: str, command: str, additions: list[str]) -> None:
    target = ROOT / path
    lines = target.read_text(encoding="utf-8").splitlines()
    output: list[str] = []
    for index, line in enumerate(lines):
        output.append(line)
        if line.strip() == command:
            indent = line[: len(line) - len(line.lstrip())]
            next_text = "\n".join(lines[index + 1 : index + 1 + len(additions)])
            if not all(addition in next_text for addition in additions):
                output.extend(indent + addition for addition in additions)
    target.write_text("\n".join(output) + "\n", encoding="utf-8")


def add_permissions(text: str, before: str) -> str:
    if re.search(r"(?m)^permissions:\s*$", text):
        return text
    return text.replace(before, "permissions:\n  contents: read\n\n" + before, 1)


def update_ci() -> None:
    blocking_path = ROOT / ".github/workflows/blocking-ci.yml"
    blocking = blocking_path.read_text(encoding="utf-8")
    blocking = blocking.replace("branches: [main]", "branches: [main, integration/vnext-main-20260811]")
    blocking = add_permissions(blocking, "concurrency:")
    if "  hepta-lane-b:\n" not in blocking:
        job = (
            "  hepta-lane-b:\n"
            "    name: Hepta Lane B\n"
            "    uses: ./.github/workflows/hepta-consolidated-source.yml\n"
            "    secrets: inherit\n\n"
        )
        blocking = blocking.replace("  repo-checks:\n", job + "  repo-checks:\n", 1)
        blocking = blocking.replace("      - repo-checks\n", "      - hepta-lane-b\n      - repo-checks\n", 1)
    blocking_path.write_text(blocking, encoding="utf-8")

    post_path = ROOT / ".github/workflows/postmerge-ci.yml"
    post = post_path.read_text(encoding="utf-8")
    post = post.replace("branches: [main]", "branches: [main, integration/vnext-main-20260811]")
    post = add_permissions(post, "jobs:")
    post_path.write_text(post, encoding="utf-8")

    consolidated_path = ROOT / ".github/workflows/hepta-consolidated-source.yml"
    consolidated = consolidated_path.read_text(encoding="utf-8")
    consolidated = re.sub(r"on:\n  push:\n    branches: \[main\]\n  pull_request:\n", "on:\n  workflow_call:\n", consolidated, count=1)
    consolidated = consolidated.replace("timeout-minutes: 45", "timeout-minutes: 90")
    package_block = '''      PACKAGES: >-
        codex-app-server
        codex-hepta-supervisor codex-hepta-fleet codex-hepta-agentd
        codex-hepta-authbus codex-hepta-authbus-p1-3-qualification
        codex-hepta-bao-adapter codex-hepta-codex-adapter
        codex-hepta-cognitive-read codex-hepta-cognitive-store
        codex-hepta-cognitive-types codex-hepta-compact-engine
        codex-hepta-context-compiler codex-hepta-control-plane
        codex-hepta-infer-core codex-hepta-inferd codex-hepta-infer-worker-host
        codex-hepta-intelligence codex-hepta-kg
        codex-hepta-memory-federation codex-hepta-memory-retrieval
        codex-hepta-automation codex-hepta-matrix-sdk codex-hepta-matrixd
'''
    consolidated = re.sub(r"      PACKAGES: >-\n(?:        .*\n)+?(?=    steps:)", package_block, consolidated, count=1)
    consolidated = consolidated.replace(
        "node --test apps/hepta-browser/test/*.js apps/hepta-native/test/*.js",
        "node --test apps/hepta-browser/test/*.js apps/hepta-control-ui/test/*.js apps/hepta-native/test/*.js",
    )
    marker = "          python3 scripts/hepta-gap-closure.py verify\n"
    additions = (
        "          python3 qualification/module-execution-dossiers/lane_b_contracts.py self-test\n"
        "          python3 qualification/module-execution-dossiers/lane_b_contracts.py verify-repository\n"
    )
    if "lane_b_contracts.py verify-repository" not in consolidated:
        consolidated = consolidated.replace(marker, marker + additions, 1)
    consolidated_path.write_text(consolidated, encoding="utf-8")

    insert_after_command(
        ".github/workflows/hepta-development-docs.yml",
        "python3 scripts/hepta-readiness.py verify",
        [
            "python3 qualification/module-execution-dossiers/lane_b_contracts.py self-test",
            "python3 qualification/module-execution-dossiers/lane_b_contracts.py verify-repository",
        ],
    )
    insert_after_command(
        ".github/workflows/hepta-implementation-readiness.yml",
        "python3 qualification/module-execution-dossiers/implementation_contracts.py verify-repository",
        [
            "python3 qualification/module-execution-dossiers/lane_b_contracts.py self-test",
            "python3 qualification/module-execution-dossiers/lane_b_contracts.py verify-repository",
        ],
    )


def write_status(rows: list[dict[str, Any]]) -> None:
    counts = {"native_symbol": 0, "native_boundary_partial": 0, "target_unimplemented": 0}
    for row in rows:
        for mapping in row["operationMappings"]:
            counts[mapping["disposition"]] += 1
    lines = [
        "# Lane B repository-local closure status",
        "",
        "This page is generated from the exact candidate source observations. It separates closed repository-local inventory from product, deployment and external evidence gates.",
        "",
        f"- Registered modules with declared-root coverage: **{len(rows)}/11**",
        f"- Registered operations with a closed-world disposition: **{sum(counts.values())}/39**",
        f"- Directly observed native operations: **{counts['native_symbol']}**",
        f"- Observed partial/authority-free boundaries: **{counts['native_boundary_partial']}**",
        f"- Explicit target operations without a matching native symbol: **{counts['target_unimplemented']}**",
        "- Repository-local mapping gaps: **closed**",
        "- Product execution, deployment qualification and independent acceptance: **not proved**",
        "",
        "## Module disposition",
        "",
        "| Module | Operations | Native | Partial boundary | Target without symbol |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        local = {key: 0 for key in counts}
        for mapping in row["operationMappings"]:
            local[mapping["disposition"]] += 1
        lines.append(
            f"| `{row['module']}` | {len(row['operationMappings'])} | {local['native_symbol']} | {local['native_boundary_partial']} | {local['target_unimplemented']} |"
        )
    lines += [
        "",
        "## Remaining evidence classes",
        "",
        "A partial or target disposition remains visible and fail-closed. Closing the inventory does not convert it into implementation success. Real callers, durable production stores, provider/model/device execution, Servo and native-platform effects, deployed timing, independent semantic review, operator acceptance, selection, promotion and release require their registered evidence owners.",
        "",
        "Validation: `python3 qualification/module-execution-dossiers/lane_b_contracts.py verify-repository`.",
        "",
    ]
    (ROOT / STATUS_PATH).write_text("\n".join(lines), encoding="utf-8")


def allowed_path(path: str) -> bool:
    exact = {
        ".github/workflows/blocking-ci.yml",
        ".github/workflows/postmerge-ci.yml",
        ".github/workflows/hepta-consolidated-source.yml",
        ".github/workflows/hepta-development-docs.yml",
        ".github/workflows/hepta-implementation-readiness.yml",
        "docs/modules/MODULE_DOCS.json",
        "docs/readiness/README.md",
        MAPPING_PATH,
        VALIDATOR_PATH,
        TEST_PATH,
        STATUS_PATH,
        "qualification/module-execution-dossiers/README.md",
        "qualification/module-execution-dossiers/IMPLEMENTATION_CONTRACTS.md",
        "qualification/module-execution-dossiers/IMPLEMENTATION_COMPLETION.json",
        "qualification/module-execution-dossiers/DETAIL_GAPS.json",
        SELF_PATH,
        WORKFLOW_PATH,
    }
    if path in exact:
        return True
    if any(path == f"docs/modules/{module}/TECHNICAL.md" for module in LANE_B):
        return True
    if any(path == f"qualification/module-execution-dossiers/detail/{module}.md" for module in LANE_B):
        return True
    return False


def clean_prior_attempt() -> None:
    changed = run("git", "diff", "--name-only", BASE + "...HEAD", "--").splitlines()
    for path in changed:
        if allowed_path(path):
            continue
        exists_at_base = subprocess.run(
            ["git", "-C", str(ROOT), "cat-file", "-e", f"{BASE}:{path}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0
        if exists_at_base:
            run("git", "checkout", BASE, "--", path)
        else:
            target = ROOT / path
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists() or target.is_symlink():
                target.unlink()


def main() -> int:
    actual_branch = run("git", "branch", "--show-current")
    if actual_branch != BRANCH:
        raise RuntimeError(f"wrong branch: {actual_branch}")
    run("git", "merge-base", "--is-ancestor", BASE, "HEAD")
    clean_prior_attempt()
    rows = source_rows()
    write_validator_files()
    update_native_bindings(rows)
    update_module_documents(rows)
    update_companion_prose()
    update_gap_registries()
    update_ci()
    write_status(rows)
    run("python3", "scripts/hepta_module_doc_metadata.py", "--write")
    # The final candidate must not retain any source-mutating helper.
    for path in [SELF_PATH, WORKFLOW_PATH]:
        target = ROOT / path
        if target.exists():
            target.unlink()
    print(json.dumps({"status": "LANE_B_CANDIDATE_MATERIALIZED", "modules": 11, "operations": 39}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
