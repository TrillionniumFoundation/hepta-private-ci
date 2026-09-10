#!/usr/bin/env python3
# Install a fail-closed, full-coverage Lane G native-binding repair.

from __future__ import annotations

import re
from pathlib import Path

FINALIZER = Path("scripts/hepta-global-finalizer-r7.py")

CORRECT_FUNCTION = r"""def repair_lane_g_shared_artifacts(
    lane_g_branch: str | None,
) -> dict[str, Any]:
    # Rebuild the 40-module source map and bind Lane G's merged implementation.

    if not lane_g_branch:
        raise RuntimeError("Lane G source branch is required for shared-artifact repair")

    import ast

    relative_path = "qualification/module-execution-dossiers/NATIVE_BINDINGS.json"
    profiles_path = (
        ROOT / "qualification/module-execution-dossiers/IMPLEMENTATION_PROFILES.json"
    )
    native_path = ROOT / relative_path
    profiles = read_json(profiles_path)
    profile_rows = profiles.get("modules")
    if not isinstance(profile_rows, list):
        raise RuntimeError("implementation profiles must contain a module list")
    module_order = [
        row.get("module") for row in profile_rows if isinstance(row, dict)
    ]
    if (
        len(module_order) != 40
        or len(set(module_order)) != 40
        or any(not isinstance(module, str) or not module for module in module_order)
        or module_order[-1] != "control.engineering"
    ):
        raise RuntimeError("canonical 40-module profile order is invalid")

    current = read_json(native_path)
    current_rows = current.get("observations")
    if not isinstance(current_rows, list):
        raise RuntimeError("current native observations must be a list")
    current_map: dict[str, dict[str, Any]] = {}
    for row in current_rows:
        if not isinstance(row, dict):
            raise RuntimeError("current native observation must be an object")
        module = row.get("module")
        if not isinstance(module, str) or not module:
            raise RuntimeError("current native observation module is invalid")
        if module in current_map:
            raise RuntimeError(f"duplicate current native observation: {module}")
        current_map[module] = row
    unknown_current = sorted(set(current_map) - set(module_order))
    if unknown_current:
        raise RuntimeError(
            "current native observations contain unknown modules: "
            + ", ".join(unknown_current)
        )

    baseline_branches = (
        "codex/lane-g-real-full-closure-20260910",
        "codex/lane-g-full-closure-20260910",
    )
    baseline_document: dict[str, Any] | None = None
    baseline_branch: str | None = None
    baseline_commit: str | None = None
    baseline_errors: list[str] = []
    for branch in baseline_branches:
        probe = git("show", f"origin/{branch}:{relative_path}", check=False)
        if not probe.passed:
            baseline_errors.append(f"{branch}: source document missing")
            continue
        try:
            candidate = json.loads(probe.output)
        except json.JSONDecodeError:
            baseline_errors.append(f"{branch}: source document is invalid JSON")
            continue
        observations = candidate.get("observations")
        if not isinstance(observations, list):
            baseline_errors.append(f"{branch}: observations are not a list")
            continue
        modules = [
            row.get("module") if isinstance(row, dict) else None
            for row in observations
        ]
        if (
            candidate.get("moduleCoverage") != 40
            or modules != module_order
            or len(set(modules)) != 40
        ):
            baseline_errors.append(f"{branch}: not an exact 40-module profile projection")
            continue
        baseline_document = candidate
        baseline_branch = branch
        baseline_commit = git_text("rev-parse", f"origin/{branch}^{{commit}}")
        break
    if baseline_document is None or baseline_branch is None or baseline_commit is None:
        raise RuntimeError(
            "no admissible full native-binding baseline: " + "; ".join(baseline_errors)
        )

    baseline_rows = baseline_document["observations"]
    baseline_map = {row["module"]: row for row in baseline_rows}
    if len(baseline_map) != 40:
        raise RuntimeError("full native-binding baseline contains duplicate modules")

    merged_rows = [
        dict(current_map.get(module, baseline_map[module])) for module in module_order
    ]

    selected_native = git(
        "show", f"origin/{lane_g_branch}:{relative_path}", check=False
    )
    selected_row: dict[str, Any] | None = None
    if selected_native.passed:
        try:
            selected_document = json.loads(selected_native.output)
        except json.JSONDecodeError as error:
            raise RuntimeError("selected Lane G native bindings are invalid JSON") from error
        selected_rows = selected_document.get("observations")
        if not isinstance(selected_rows, list):
            raise RuntimeError("selected Lane G native observations must be a list")
        matches = [
            row
            for row in selected_rows
            if isinstance(row, dict) and row.get("module") == "control.engineering"
        ]
        if len(matches) > 1:
            raise RuntimeError("selected Lane G has duplicate control.engineering rows")
        if matches:
            selected_row = dict(matches[0])

    candidate_paths: list[str] = []
    if selected_row is not None:
        source_path = selected_row.get("path")
        if isinstance(source_path, str) and source_path:
            candidate_paths.append(source_path)
    candidate_paths.extend(
        [
            "tools/hepta-engineering-control/control_engineering_v2/__init__.py",
            "tools/hepta-engineering-control/hepta_engineering_control.py",
        ]
    )
    desired_path = next(
        (path for path in candidate_paths if (ROOT / path).is_file()),
        None,
    )
    if desired_path is None:
        raise RuntimeError("no merged Lane G engineering-control source is present")

    source = (ROOT / desired_path).read_text(encoding="utf-8", errors="strict")
    if desired_path.endswith("/__init__.py"):
        try:
            tree = ast.parse(source, filename=desired_path)
        except SyntaxError as error:
            raise RuntimeError("Lane G export module is not valid Python") from error
        desired_exports: list[str] = []
        seen: set[str] = set()
        for node in tree.body:
            if not isinstance(node, ast.ImportFrom):
                continue
            for alias in node.names:
                name = alias.asname or alias.name
                if (
                    isinstance(name, str)
                    and name
                    and not name.startswith("_")
                    and name not in seen
                ):
                    seen.add(name)
                    desired_exports.append(name)
    else:
        exports = selected_row.get("exports") if selected_row is not None else None
        if not isinstance(exports, list) or not exports or not all(
            isinstance(value, str) and value for value in exports
        ):
            exports = baseline_map["control.engineering"].get("exports")
        if not isinstance(exports, list) or not exports or not all(
            isinstance(value, str) and value for value in exports
        ):
            raise RuntimeError("Lane G engineering exports are unavailable")
        desired_exports = list(exports)

    if not desired_exports:
        raise RuntimeError("Lane G engineering export set is empty")
    missing_exports = [
        value
        for value in desired_exports
        if re.search(r"\b" + re.escape(value) + r"\b", source) is None
    ]
    if missing_exports:
        raise RuntimeError(
            "Lane G engineering exports are missing from merged source: "
            + ", ".join(missing_exports)
        )

    prior_engineering = baseline_map["control.engineering"]
    desired_row = {
        "module": "control.engineering",
        "path": desired_path,
        "blobSha": git_text("hash-object", "--", desired_path),
        "exports": desired_exports,
    }
    interpretation = prior_engineering.get("interpretation")
    if isinstance(interpretation, str) and interpretation:
        desired_row["interpretation"] = interpretation

    merged_rows[module_order.index("control.engineering")] = desired_row
    if [row.get("module") for row in merged_rows] != module_order:
        raise RuntimeError("rebuilt native bindings do not match canonical module order")

    document = dict(baseline_document)
    document["sourceSnapshot"] = git_text("rev-parse", "HEAD")
    document["moduleCoverage"] = 40
    document["coverageScope"] = baseline_document.get(
        "coverageScope",
        "one reviewed primary source blob anchor for each canonical module",
    )
    document["evidenceClass"] = "source_observation_only"
    document["consumerCallsitesProved"] = False
    document["productExecutionProved"] = False
    document["observations"] = merged_rows
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
    if "implementation_contract_tests_native" in harness:
        raise RuntimeError("shadow native tests must not replace cumulative A-F coverage")
    if "class NativeBindingCoverageTests" not in core:
        raise RuntimeError("cumulative native-binding coverage tests are missing")

    return {
        "laneGBranch": lane_g_branch,
        "laneGCommit": git_text("rev-parse", f"origin/{lane_g_branch}^{{commit}}"),
        "baselineBranch": baseline_branch,
        "baselineCommit": baseline_commit,
        "currentRowsRetained": len(current_map),
        "moduleCoverage": len(merged_rows),
        "sourcePath": desired_path,
        "exportCount": len(desired_exports),
        "changed": [relative_path],
        "count": 1,
    }
"""


def main() -> int:
    text = FINALIZER.read_text(encoding="utf-8")
    function_pattern = re.compile(
        r"def repair_lane_g_shared_artifacts(?:\(\)|\(\n"
        r"    lane_g_branch: str \| None,\n\)) -> dict\[str, Any\]:\n"
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
        if text.count(old_call) != 1 or new_call in text:
            raise SystemExit("r15 call-site precondition drifted")
        text = text.replace(old_call, new_call, 1)
    elif text.count(new_call) != 1:
        raise SystemExit("r15 call site is missing or duplicated")

    required = (
        "def repair_lane_g_shared_artifacts(",
        '"codex/lane-g-real-full-closure-20260910"',
        'module_order[-1] != "control.engineering"',
        new_call,
        '"laneGArtifactRepair": lane_g_artifact_repair',
        "LANE_G_PRIOR_OWNER_CONFLICTS = frozenset(",
        'path == ".github/workflows/lane-f-bootstrap.yml"',
        "def dependency_cycle_path(",
    )
    for phrase in required:
        if phrase not in text:
            raise SystemExit(f"patched finalizer is missing required phrase: {phrase}")

    forbidden = (
        "implementation_contract_tests_native.py",
        "from implementation_contract_tests_native import *",
        "expected one control.engineering native binding, observed",
    )
    for phrase in forbidden:
        if phrase in text:
            raise SystemExit(f"patched finalizer retains forbidden drift: {phrase}")

    FINALIZER.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
