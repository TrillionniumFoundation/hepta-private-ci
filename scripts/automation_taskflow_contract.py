#!/usr/bin/env python3
"""Check source facts, not execution/acceptance; render only derived status files.

The implementation map owns capability declarations. SCHEMA_CONTRACT owns the
migration inventory. A historical Git observation is distinct from the current
candidate. Neither a source marker nor this command establishes native execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODULE = "docs/modules/automation.taskflow/"
CONTRACT_PATH = MODULE + "SCHEMA_CONTRACT.json"
MAP_PATH = MODULE + "IMPLEMENTATION_MAP.json"
STATE_PATH = MODULE + "CURRENT_STATE.json"
STATUS_PATH = MODULE + "CURRENT_IMPLEMENTATION.md"
EXTERNAL = ("deploymentQualificationComplete", "productExecutionProved",
            "independentAcceptance", "activation", "promotion", "release")
REPOSITORY = ("repositoryControlledSourceBoundaryGapsClosed",
              "repositoryControlledProductCompositionGapsClosed",
              "repositoryControlledDocumentationGapsClosed")
COMPONENTS = ("boundedAdmissionBatchComplete", "separateRecoveryBudgetComplete",
              "externalEffectProductCompositionComplete",
              "neuralCircuitRuntimeVerticalSliceComplete", "durableNeuralCircuitProductComplete",
              "crossHostRecoveryContractComplete", "crossHostRecoveryProductComplete",
              "selectedHostQualificationPathComplete", "independentAcceptanceVerificationPathComplete")
# These are source-navigation assertions only, not semantic/native qualifications.
SOURCE_MARKERS = {
    "codex-rs/hepta-automation/src/lib.rs": ("mod recovery_sweeps;", "mod runtime_policy;", "mod neural_circuit_runtime;", "mod cross_host_recovery;"),
    "codex-rs/hepta-automation/src/scheduler.rs": ("pub async fn tick_batch_cancellable", "should_stop()", "taskflow_admission_error", "AutomationBatchStopReason::RetryDeferred"),
    "codex-rs/hepta-automation/src/recovery_sweeps.rs": ("reserve_recovery_selection", "pending_occurrence_work_exact", "uncertain_dispatch_exact", "SELECT_WINDOW", "SELECT_UPPER"),
    "codex-rs/hepta-agentd/src/automation.rs": ("tick_batch_cancellable", "classify_automation_error", "recovery_transient_budget"),
    "codex-rs/hepta-agentd/src/automation_recovery.rs": ("reserve_recovery_selection", "pending_occurrence_work_exact", "uncertain_dispatch_exact"),
    "codex-rs/hepta-automation/src/neural_circuit_runtime/runtime.rs": ("event.validate()?", "runtime_profile_digest", "CircuitEffectBoundaryV1"),
    "codex-rs/hepta-automation/src/cross_host_recovery.rs": ("observed_owner_agent_id: &AgentId", "AgentId::parse(&self.owner_agent_id)"),
    "codex-rs/hepta-agentd/src/automation_effect_host.rs": ("AgentdAutomationEffectHost", "ProviderEffectTaskFlowDriver::new", "execute_authorized_taskflow_effect_async", "FinalUseAuthority::open_state_dir"),
    "scripts/automation_taskflow_commands.py": ("from hepta_ci_exec import run", "not_run"),
    "codex-rs/hepta-automation/src/runtime_policy.rs": ("AutomationFailureDisposition", "Fence", "FailStop", "Retry", "Reconcile", "Isolate"),
    "codex-rs/hepta-automation/src/neural_circuit_runtime/types.rs": ("CircuitEventIngressV1", "CircuitDecisionCellV1", "CircuitOrganPortV1", "CircuitWaitJoinPortV1", "FeedbackBudgetExhausted", "CircuitTerminalReceiptV1", "event_digest does not match the canonical event ingress"),
    "CALLERS.toml": ('id = "automation_taskflow_provider_effect_bridge"', 'product_callers = ["codex-rs/hepta-agentd/src/automation_effect_host.rs"]', 'caller_markers = ["ProviderEffectTaskFlowDriver::new"'),
    ".github/workflows/automation-taskflow-selected-host.yml": ("hepta-automation-selected-host", "expected_tzdb_sha256", "multi_scheduler_race", "runtime_crash_points", "PROVIDER_IDENTITY_SHA256", "automation-taskflow-selected-host-receipt.json"),
    ".github/workflows/automation-taskflow-independent-acceptance.yml": ("automation-taskflow-independent-acceptance", "AUTOMATION_ACCEPTANCE_PUBLIC_KEY_PEM", "gh run download", "verify_automation_taskflow_acceptance.py", "acceptance-public-key.pem"),
    "docs/modules/automation.taskflow/INDEPENDENT_ACCEPTANCE.md": ("Ed25519", "automation-taskflow-independent-acceptance", "independentAcceptance = true", "release = false"),
    "scripts/verify_automation_taskflow_acceptance.py": ("canonical_payload_bytes", "verify_ed25519_signature", "implementation and acceptance principals must be distinct", "selectedHostReceiptSha256"),
}


class ContractError(RuntimeError):
    pass


def need(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def checked_path(root: Path, relative: str) -> Path:
    need(isinstance(relative, str) and relative != "", "empty/non-string source path")
    parts = PurePosixPath(relative).parts
    need(not relative.startswith("/") and ".." not in parts and "\\" not in relative and parts[0] != ".git" and not any(ord(c) < 32 for c in relative),
         f"non-repository path: {relative}")
    need(str(PurePosixPath(relative)) == relative, f"noncanonical path: {relative}")
    path = root
    for part in parts:
        path = path / part
        need(not path.is_symlink(), f"symlink in source path: {relative}")
    return path


def text(root: Path, relative: str) -> str:
    path = checked_path(root, relative)
    need(path.is_file(), f"missing required file: {relative}")
    return path.read_text(encoding="utf-8")


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        need(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def data(root: Path, relative: str) -> dict[str, Any]:
    value = json.loads(text(root, relative), object_pairs_hook=unique_object)
    need(isinstance(value, dict), f"{relative} must contain a JSON object")
    return value


def encoded(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def facts(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    contract, implementation = data(root, CONTRACT_PATH), data(root, MAP_PATH)
    version = contract.get("storeSchemaVersion")
    need(type(version) is int and version >= 19, "store schema must be an integer >= 19")
    lib = text(root, "codex-rs/hepta-automation/src/lib.rs")
    observed = re.findall(r"^pub const AUTOMATION_SCHEMA_VERSION:\s*u32\s*=\s*(\d+);", lib, re.M)
    need(observed == [str(version)], "Rust store schema and contract disagree")
    need(implementation.get("module") == "automation.taskflow", "wrong implementation module")
    claims = implementation.get("claimBoundary")
    need(isinstance(claims, dict), "implementation map claimBoundary is missing")
    need(type(claims.get("durableStoreSchemaVersion")) is int and claims["durableStoreSchemaVersion"] == version,
         "implementation map store schema is stale")
    for key in (*REPOSITORY, *COMPONENTS, *EXTERNAL):
        need(type(claims.get(key)) is bool, f"claim {key} must be an explicit boolean")
    # External decisions are not issued by a checked-in source map. Independent
    # evidence verifiers publish their own immutable, candidate-bound receipts.
    for key in EXTERNAL:
        need(claims[key] is False, f"source map cannot self-issue external gate {key}")
    need(implementation.get("productionImplementation") is False,
         "source-map checks cannot issue production implementation qualification")
    gaps = implementation.get("remainingModuleGaps")
    product_gaps = implementation.get("repositoryControlledProductCompositionGaps")
    for label, values in (("remainingModuleGaps", gaps), ("product gaps", product_gaps)):
        need(isinstance(values, list) and all(isinstance(x, str) and x.strip() for x in values),
             f"invalid {label}")
    need(not (gaps and claims["repositoryControlledSourceBoundaryGapsClosed"]),
         "source closure contradicts remaining module gaps")
    need(not (product_gaps and claims["repositoryControlledProductCompositionGapsClosed"]),
         "product closure contradicts remaining product gaps")
    for product, adapter in (("durableNeuralCircuitProductComplete", "neuralCircuitRuntimeVerticalSliceComplete"),
                             ("crossHostRecoveryProductComplete", "crossHostRecoveryContractComplete")):
        need(not claims[product] or claims[adapter], f"{product} requires its source adapter")
    return contract, implementation, claims


def projection(root: Path) -> dict[str, Any]:
    contract, implementation, claims = facts(root)
    return {
        "schema": "hepta.automation-taskflow.current-state.v1",
        "module": "automation.taskflow",
        "storeSchemaVersion": contract["storeSchemaVersion"],
        "taskflowSchemaVersion": contract["taskflowSchemaVersion"],
        "claimBoundary": {key: claims[key] for key in (*REPOSITORY, *COMPONENTS, *EXTERNAL)},
        "remainingModuleGaps": implementation["remainingModuleGaps"],
        "repositoryControlledProductCompositionGaps": implementation["repositoryControlledProductCompositionGaps"],
        "evidenceBoundary": "Source declarations only. Native source-head, deterministic-merge, selected-runtime execution and independent acceptance require separate immutable receipts.",
        "derivedFrom": [CONTRACT_PATH, MAP_PATH],
    }


def render_status(state: dict[str, Any]) -> str:
    lines = ["# automation.taskflow current implementation", "",
             "Generated by `python3 scripts/automation_taskflow_contract.py render`; do not edit by hand.",
             "", f"**Current durable store schema: {state['storeSchemaVersion']}. V1 TaskFlow record meanings are unchanged.**", "",
             state["evidenceBoundary"], "", "| Source declaration / separate gate | State |", "|---|---|"]
    lines += [f"| `{key}` | `{str(value).lower()}` |" for key, value in state["claimBoundary"].items()]
    lines += ["", "## Remaining module work", ""]
    lines += [f"{i}. {value}" for i, value in enumerate(state["remainingModuleGaps"], 1)]
    lines += ["", "Native-test definitions, static source navigation, Python/SQLite fixtures, native source-head execution, native merged-tree execution, selected-host execution and independent acceptance are distinct evidence classes.", ""]
    return "\n".join(lines)


def render(root: Path = ROOT) -> None:
    state = projection(root)
    checked_path(root, STATE_PATH).write_text(encoded(state), encoding="utf-8")
    checked_path(root, STATUS_PATH).write_text(render_status(state), encoding="utf-8")


def git_read(root: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_NO_REPLACE_OBJECTS"] = "1"
    env["GIT_LITERAL_PATHSPECS"] = "1"
    try:
        return subprocess.check_output(["git", "-C", str(root), *args], env=env,
                                       text=True, stderr=subprocess.PIPE).strip()
    except subprocess.CalledProcessError as error:
        raise ContractError(f"Git source verification failed: {args[0]}") from error


def observe(root: Path = ROOT) -> None:
    """Developer-only: bind existing inventory to committed bytes; change no claims.

    Run after committing source. Qualification calls verify, never this writer.
    The map itself is not in its own source inventory; status projections exclude
    Git anchors, avoiding a self-referential commit/hash requirement.
    """
    need(Path(git_read(root, "rev-parse", "--show-toplevel")).resolve() == root.resolve(),
         "Git worktree differs from source root")
    need(not git_read(root, "status", "--porcelain", "--untracked-files=normal"),
         "commit source and semantic map changes before binding an observation")
    implementation = data(root, MAP_PATH)
    objects = implementation.get("sourceObjects", [])
    need(isinstance(objects, list) and objects, "source object inventory is empty")
    seen = set()
    for row in objects:
        path = row.get("path")
        checked_path(root, path)
        need(path != MAP_PATH and path not in seen, "self-reference or duplicate source object")
        seen.add(path)
        row["object"] = git_read(root, "rev-parse", f"HEAD:{path}")
    by_path = {row["path"]: row["object"] for row in objects}
    for row in implementation.get("exactSourceEvidence", {}).get("entries", []):
        need(row.get("path") in by_path, "exact evidence is outside the source inventory")
        row["blobSha"] = by_path[row["path"]]
    for operation in implementation.get("operations", []):
        need(operation.get("sourcePath") in by_path, "operation is outside the source inventory")
        operation["sourceBlob"] = by_path[operation["sourcePath"]]
    paths = implementation.get("observedSourcePaths", [])
    need(MAP_PATH not in paths, "source observation cannot include the map itself")
    implementation["observedAtHead"] = {"commit": git_read(root, "rev-parse", "HEAD"),
                                         "tree": git_read(root, "rev-parse", "HEAD^{tree}")}
    checked_path(root, MAP_PATH).write_text(encoded(implementation), encoding="utf-8")
    render(root)


def verify_source_identity(root: Path, implementation: dict[str, Any]) -> dict[str, str]:
    def git(*args: str) -> str:
        return git_read(root, *args)

    need(Path(git("rev-parse", "--show-toplevel")).resolve() == root.resolve(), "Git worktree differs from source root")
    head, tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
    need(re.fullmatch(r"[0-9a-f]{40}", head) is not None, "nonliteral Git head")
    observation = implementation.get("observedAtHead", {})
    observed = observation.get("commit", "")
    need(re.fullmatch(r"[0-9a-f]{40}", observed) is not None, "missing exact source observation")
    need(git("rev-parse", f"{observed}^{{tree}}") == observation.get("tree"), "wrong observed source tree")
    git("merge-base", "--is-ancestor", observed, head)
    paths = implementation.get("observedSourcePaths", [])
    need(isinstance(paths, list) and paths, "missing observed source paths")
    for required in ("codex-rs/hepta-automation", "codex-rs/Cargo.toml", "codex-rs/Cargo.lock"):
        need(required in paths, f"source observation omits {required}")
    for path in paths:
        checked_path(root, path)
    # Native or observed documentation changes require a new ordinary source
    # observation. Qualification never rewrites that observation itself.
    git("diff", "--exit-code", observed, head, "--", *paths)
    git("diff", "--exit-code", "HEAD", "--", *paths)
    need(not git("ls-files", "--others", "--exclude-standard", "--", *paths), "untracked mapped source")
    objects = implementation.get("sourceObjects", [])
    need(isinstance(objects, list) and objects, "source object inventory is empty")
    seen: dict[str, str] = {}
    for row in objects:
        path, expected = row.get("path"), row.get("object")
        checked_path(root, path)
        need(path not in seen, f"duplicate source object {path}")
        need(isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{40}", expected) is not None,
             f"invalid source object {path}")
        actual = git("rev-parse", f"HEAD:{path}")
        need(actual == expected, f"stale source object: {path}")
        seen[path] = actual
    for row in implementation.get("exactSourceEvidence", {}).get("entries", []):
        need(seen.get(row.get("path")) == row.get("blobSha"), "exact source inventories disagree")
    for operation in implementation.get("operations", []):
        path = operation.get("sourcePath")
        need(seen.get(path) == operation.get("sourceBlob"), f"operation source object mismatch: {path}")
    return {"commit": head, "tree": tree}


def verify(root: Path = ROOT, *, check_git: bool = True) -> dict[str, Any]:
    contract, implementation, claims = facts(root)
    version = contract["storeSchemaVersion"]
    topology = contract.get("migrationTopology")
    need(isinstance(topology, list), "migration topology must be a list")
    versions, paths = [], []
    for row in topology:
        need(isinstance(row, dict) and type(row.get("version")) is int, "invalid migration row")
        number, path = row["version"], row.get("path")
        need(isinstance(path, str) and re.fullmatch(rf"codex-rs/hepta-automation/migrations/{number:04d}_[a-z0-9_]+\.sql", path) is not None,
             "migration version/path mismatch")
        marker = row.get("requiredMarker")
        need(isinstance(marker, str) and marker, "missing migration marker")
        body = text(root, path)
        need(marker in body, f"reviewed migration marker missing: {path}")
        raw = checked_path(root, path).read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        need(row.get("blobSha") == blob, f"published migration bytes changed: {path}")
        versions.append(number)
        paths.append(path)
    need(versions == list(range(17, version + 1)), "migration topology must cover every version from 17 to current")
    actual = sorted(str(p.relative_to(root)) for p in (root / "codex-rs/hepta-automation/migrations").glob("[0-9][0-9][0-9][0-9]_*.sql") if int(p.name[:4]) >= 17)
    need(sorted(paths) == actual, "unregistered or missing current migration")
    for path, markers in SOURCE_MARKERS.items():
        body = text(root, path)
        for marker in markers:
            need(marker in body, f"source navigation missing {marker}: {path}")
    for name in ("TECHNICAL.md", "MIGRATION_V19_RUNBOOK.md", "SLO.md", "RELEASE_QUALIFICATION.md"):
        need("CURRENT_IMPLEMENTATION.md" in text(root, MODULE + name), f"{name} lacks current-state navigation")
    state = projection(root)
    need(text(root, STATE_PATH) == encoded(state), "stale CURRENT_STATE.json; run the developer render command")
    need(text(root, STATUS_PATH) == render_status(state), "stale CURRENT_IMPLEMENTATION.md; run the developer render command")
    workflow = text(root, ".github/workflows/automation-taskflow-focused.yml")
    for marker in ("pull_request:", "workflow_call:", "branches: [main]", "automation_taskflow_commands.py", "persist-credentials: false", "contents: read"):
        need(marker in workflow, f"focused workflow is missing {marker}")
    need(re.search(r"^\s*contents:\s*write\s*$", workflow, re.M) is None, "qualification must not write repository content")
    for filename in ("automation-taskflow-fact-sync.yml", "automation-taskflow-qualification-repair.yml"):
        need(not (root / ".github/workflows" / filename).exists(), "source-writing qualification workflow remains")
    blocking = text(root, ".github/workflows/blocking-ci.yml")
    need("automation-taskflow-focused:" in blocking and "- automation-taskflow-focused" in blocking,
         "CI required must depend on focused qualification")
    identity = verify_source_identity(root, implementation) if check_git else None
    return {"module": "automation.taskflow", "storeSchemaVersion": version,
            "migrationVersions": versions, "sourceStructureVerified": True,
            "sourceIdentityVerified": check_git, "candidate": identity,
            "repositoryControlledClosure": all(claims[key] for key in REPOSITORY),
            "nativeExecutionProved": False, "productExecutionProved": False,
            "independentAcceptance": False, "activation": False, "promotion": False, "release": False,
            "currentStateSha256": hashlib.sha256(encoded(state).encode()).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["verify", "self-test", "render", "observe"], nargs="?", default="verify")
    args = parser.parse_args()
    try:
        if args.command == "render":
            render()
        elif args.command == "observe":
            observe()
        else:
            print(encoded(verify()), end="")
        return 0
    except (ContractError, OSError, ValueError, KeyError, TypeError) as error:
        raise SystemExit(f"automation.taskflow contract verification failed: {error}") from error


if __name__ == "__main__":
    raise SystemExit(main())
