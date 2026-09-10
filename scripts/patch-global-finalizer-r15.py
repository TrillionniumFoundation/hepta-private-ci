#!/usr/bin/env python3
"""Replace the Lane G shared-artifact repair with an exact-source merge."""
from __future__ import annotations

import re
from pathlib import Path

FINALIZER = Path("scripts/hepta-global-finalizer-r7.py")

CORRECT_FUNCTION = '''def repair_lane_g_shared_artifacts(
    lane_g_branch: str | None,
) -> dict[str, Any]:
    """Merge Lane G's exact native row while retaining cumulative A-F tests."""

    if not lane_g_branch:
        raise RuntimeError("Lane G source branch is required for shared-artifact repair")

    relative_path = "qualification/module-execution-dossiers/NATIVE_BINDINGS.json"
    native_path = ROOT / relative_path
    try:
        lane_g_document = json.loads(
            git_text("show", f"origin/{lane_g_branch}:{relative_path}")
        )
    except json.JSONDecodeError as error:
        raise RuntimeError("Lane G native bindings are not valid JSON") from error
    document = read_json(native_path)

    def exact_row(source: dict[str, Any], label: str) -> dict[str, Any]:
        observations = source.get("observations")
        if not isinstance(observations, list):
            raise RuntimeError(f"{label} native observations must be a list")
        rows = [
            row
            for row in observations
            if isinstance(row, dict) and row.get("module") == "control.engineering"
        ]
        if len(rows) != 1:
            raise RuntimeError(
                f"expected one control.engineering row in {label}, observed {len(rows)}"
            )
        row = rows[0]
        source_path = row.get("path")
        exports = row.get("exports")
        blob_sha = row.get("blobSha")
        if not isinstance(source_path, str) or not source_path:
            raise RuntimeError(f"{label} control.engineering path is invalid")
        if not isinstance(exports, list) or not exports or not all(
            isinstance(value, str) and value for value in exports
        ):
            raise RuntimeError(f"{label} control.engineering exports are invalid")
        if not isinstance(blob_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", blob_sha):
            raise RuntimeError(f"{label} control.engineering blob is invalid")
        return {
            "module": "control.engineering",
            "path": source_path,
            "blobSha": blob_sha,
            "exports": list(exports),
        }

    desired = exact_row(lane_g_document, lane_g_branch)
    current = exact_row(document, "cumulative candidate")
    merged_source = ROOT / desired["path"]
    if not merged_source.is_file():
        raise RuntimeError(
            f"Lane G control.engineering source is missing after merge: {desired['path']}"
        )
    source_text = merged_source.read_text(encoding="utf-8", errors="replace")
    missing_exports = [
        value
        for value in desired["exports"]
        if re.search(r"\\b" + re.escape(value) + r"\\b", source_text) is None
    ]
    if missing_exports:
        raise RuntimeError(
            "Lane G control.engineering exports are missing after merge: "
            + ", ".join(missing_exports)
        )

    changed: list[str] = []
    if current != desired:
        observations = document["observations"]
        index = next(
            index
            for index, row in enumerate(observations)
            if isinstance(row, dict) and row.get("module") == "control.engineering"
        )
        observations[index] = desired
        write_json(native_path, document)
        changed.append(relative_path)

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
        raise RuntimeError("a weaker shadow native-test module must not replace A-F coverage")
    if "class NativeBindingCoverageTests" not in core:
        raise RuntimeError("cumulative native-binding coverage tests are missing")

    return {
        "laneGBranch": lane_g_branch,
        "laneGCommit": git_text("rev-parse", f"origin/{lane_g_branch}^{{commit}}"),
        "sourcePath": desired["path"],
        "exports": desired["exports"],
        "changed": changed,
        "count": len(changed),
    }
'''


def main() -> int:
    text = FINALIZER.read_text(encoding="utf-8")
    function_pattern = re.compile(
        r"def repair_lane_g_shared_artifacts\(\) -> dict\[str, Any\]:\n"
        r".*?\n\ndef repair_argument_comment_blockers\(\) -> dict\[str, Any\]:\n",
        re.DOTALL,
    )
    matches = list(function_pattern.finditer(text))
    if len(matches) != 1:
        raise SystemExit(
            "r15 function precondition drifted: "
            f"expected one hard-coded Lane G repair, observed {len(matches)}"
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
    if text.count(old_call) != 1 or new_call in text:
        raise SystemExit("r15 call-site precondition drifted")
    text = text.replace(old_call, new_call, 1)

    required = (
        "def repair_lane_g_shared_artifacts(",
        'git_text("show", f"origin/{lane_g_branch}:{relative_path}")',
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
        "control_engineering_v2",
        "implementation_contract_tests_native.py",
        "EngineeringStore",
        "issue_work_envelope",
    )
    for phrase in forbidden:
        if phrase in text:
            raise SystemExit(f"patched finalizer retains forbidden hard-coded drift: {phrase}")

    FINALIZER.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
