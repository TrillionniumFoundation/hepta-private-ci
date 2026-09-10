#!/usr/bin/env python3
"""Replace the Lane G shared-artifact repair with exact-source insertion."""
from __future__ import annotations

import re
from pathlib import Path

FINALIZER = Path("scripts/hepta-global-finalizer-r7.py")

CORRECT_FUNCTION = '''def repair_lane_g_shared_artifacts(
    lane_g_branch: str | None,
) -> dict[str, Any]:
    """Insert or replace Lane G's exact native row while retaining A-F tests."""

    if not lane_g_branch:
        raise RuntimeError("Lane G source branch is required for shared-artifact repair")

    source_path = (
        "tools/hepta-engineering-control/control_engineering_v2/__init__.py"
    )
    source_text = git_text("show", f"origin/{lane_g_branch}:{source_path}")
    merged_source = ROOT / source_path
    if not merged_source.is_file():
        raise RuntimeError(
            f"Lane G control.engineering source is missing after merge: {source_path}"
        )
    if merged_source.read_text(encoding="utf-8") != source_text + (
        "" if source_text.endswith("\\n") else "\\n"
    ):
        raise RuntimeError("merged Lane G public surface differs from selected exact source")

    try:
        source_tree = ast.parse(source_text, filename=source_path)
    except SyntaxError as error:
        raise RuntimeError("selected Lane G public surface is invalid Python") from error
    exports = sorted(
        {
            alias.asname or alias.name
            for node in source_tree.body
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
            if not (alias.asname or alias.name).startswith("_")
        }
    )
    required_exports = {
        "EngineeringStore",
        "WorkEnvelope",
        "WorkPackage",
        "Candidate",
        "SandboxReceipt",
        "EvidenceDecision",
        "AssimilationProposal",
        "issue_work_envelope",
        "schedule_ready_packages",
        "generate_candidate",
        "execute_candidate_sandbox",
        "verify_integration_evidence",
        "request_independent_review",
        "record_integration_decision",
        "publish_audit_projection",
        "prepare_assimilation_candidate",
    }
    missing_required = sorted(required_exports - set(exports))
    if missing_required:
        raise RuntimeError(
            "selected Lane G public surface lacks required exports: "
            + ", ".join(missing_required)
        )
    desired = {
        "module": "control.engineering",
        "path": source_path,
        "blobSha": git_text(
            "rev-parse", f"origin/{lane_g_branch}:{source_path}"
        ),
        "exports": exports,
    }

    relative_path = "qualification/module-execution-dossiers/NATIVE_BINDINGS.json"
    native_path = ROOT / relative_path
    document = read_json(native_path)
    observations = document.get("observations")
    if not isinstance(observations, list):
        raise RuntimeError("cumulative native observations must be a list")
    current_indices = [
        index
        for index, row in enumerate(observations)
        if isinstance(row, dict) and row.get("module") == "control.engineering"
    ]
    if len(current_indices) > 1:
        raise RuntimeError(
            "cumulative candidate contains duplicate control.engineering observations"
        )

    changed: list[str] = []
    if current_indices:
        if observations[current_indices[0]] != desired:
            observations[current_indices[0]] = desired
            changed.append(relative_path)
    else:
        observations.append(desired)
        changed.append(relative_path)

    profiles = read_json(
        ROOT
        / "qualification/module-execution-dossiers/IMPLEMENTATION_PROFILES.json"
    )
    canonical_modules = [row.get("module") for row in profiles.get("modules", [])]
    if len(canonical_modules) != 40 or len(set(canonical_modules)) != 40:
        raise RuntimeError("implementation profiles must contain 40 unique modules")
    order = {module: index for index, module in enumerate(canonical_modules)}
    observed_modules = [
        row.get("module") if isinstance(row, dict) else None for row in observations
    ]
    duplicates = sorted(
        str(module)
        for module in set(observed_modules)
        if observed_modules.count(module) > 1
    )
    unknown = sorted(str(module) for module in observed_modules if module not in order)
    if duplicates or unknown:
        raise RuntimeError(
            f"invalid native observation set: duplicates={duplicates} unknown={unknown}"
        )
    observations.sort(key=lambda row: order[row["module"]])
    document["moduleCoverage"] = len(observations)
    if len(observations) != 40:
        raise RuntimeError(
            f"native observation closure requires 40 rows, observed {len(observations)}"
        )
    if changed:
        write_json(native_path, document)

    harness_path = (
        ROOT / "qualification/module-execution-dossiers/test_implementation_contracts.py"
    )
    core_path = (
        ROOT
        / "qualification/module-execution-dossiers/implementation_contract_tests_core.py"
    )
    harness = harness_path.read_text(encoding="utf-8")
    core = core_path.read_text(encoding="utf-8")
    if "from implementation_contract_tests_core import *" not in harness:
        raise RuntimeError("cumulative split implementation-contract harness was flattened")
    if "from implementation_contract_tests_system import *" not in harness:
        raise RuntimeError("cumulative system implementation-contract tests are missing")
    if "class NativeBindingCoverageTests" not in core:
        raise RuntimeError("cumulative native-binding coverage tests are missing")

    return {
        "laneGBranch": lane_g_branch,
        "laneGCommit": git_text("rev-parse", f"origin/{lane_g_branch}^{{commit}}"),
        "sourcePath": source_path,
        "exports": exports,
        "changed": changed,
        "count": len(changed),
    }
'''


def main() -> int:
    text = FINALIZER.read_text(encoding="utf-8")
    if "import ast\n" not in text:
        if text.count("import argparse\n") != 1:
            raise SystemExit("r15 import precondition drifted")
        text = text.replace("import argparse\n", "import argparse\nimport ast\n", 1)

    function_pattern = re.compile(
        r"def repair_lane_g_shared_artifacts\([^\n]*\n?"
        r".*?\n\ndef repair_argument_comment_blockers\(\) -> dict\[str, Any\]:\n",
        re.DOTALL,
    )
    matches = list(function_pattern.finditer(text))
    if len(matches) != 1:
        raise SystemExit(
            "r15 function precondition drifted: "
            f"expected one Lane G repair, observed {len(matches)}"
        )
    text = function_pattern.sub(
        lambda _: CORRECT_FUNCTION
        + "\n\ndef repair_argument_comment_blockers() -> dict[str, Any]:\n",
        text,
        count=1,
    )

    old_call = "lane_g_artifact_repair = repair_lane_g_shared_artifacts()"
    new_call = (
        'lane_g_artifact_repair = repair_lane_g_shared_artifacts(selected["G"])'
    )
    if old_call in text:
        if text.count(old_call) != 1:
            raise SystemExit("r15 call-site precondition drifted")
        text = text.replace(old_call, new_call, 1)
    elif text.count(new_call) != 1:
        raise SystemExit("r15 selected-Lane-G call site is missing or duplicated")

    required = (
        "import ast",
        "def repair_lane_g_shared_artifacts(",
        'git_text("show", f"origin/{lane_g_branch}:{source_path}")',
        "observations.append(desired)",
        "native observation closure requires 40 rows",
        new_call,
        '"laneGArtifactRepair": lane_g_artifact_repair',
        "LANE_G_PRIOR_OWNER_CONFLICTS = frozenset(",
        'path == ".github/workflows/lane-f-bootstrap.yml"',
        "def dependency_cycle_path(",
    )
    for phrase in required:
        if phrase not in text:
            raise SystemExit(f"patched finalizer is missing required phrase: {phrase}")

    FINALIZER.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
