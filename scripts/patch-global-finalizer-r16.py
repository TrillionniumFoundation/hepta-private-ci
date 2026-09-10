#!/usr/bin/env python3
"""Patch r7 to aggregate the 40-module native index by primary lane."""
from __future__ import annotations

import re
from pathlib import Path

FINALIZER = Path("scripts/hepta-global-finalizer-r7.py")

CORRECT_FUNCTION = '''def repair_lane_g_shared_artifacts(
    selected: dict[str, str | None],
) -> dict[str, Any]:
    """Aggregate exact native rows by primary lane and regenerate Lane G."""

    relative_path = "qualification/module-execution-dossiers/NATIVE_BINDINGS.json"
    native_path = ROOT / relative_path
    profiles = read_json(
        ROOT
        / "qualification/module-execution-dossiers/IMPLEMENTATION_PROFILES.json"
    )
    profile_rows = profiles.get("modules")
    if not isinstance(profile_rows, list):
        raise RuntimeError("implementation profiles modules must be a list")
    canonical_modules = [row.get("module") for row in profile_rows]
    if len(canonical_modules) != 40 or len(set(canonical_modules)) != 40:
        raise RuntimeError("implementation profiles must contain 40 unique modules")
    module_lanes = {row.get("module"): row.get("lane") for row in profile_rows}
    invalid_lanes = sorted(
        f"{module}:{lane}"
        for module, lane in module_lanes.items()
        if lane not in LANE_ORDER
    )
    if invalid_lanes:
        raise RuntimeError(
            "implementation profiles contain invalid lane bindings: "
            + ", ".join(invalid_lanes)
        )

    seed_ref = "origin/codex/hepta-native-source-closed-world-20260909"
    seed_commit = git_text("rev-parse", f"{seed_ref}^{{commit}}")
    seed_result = git("show", f"{seed_ref}:{relative_path}", check=False)
    if not seed_result.passed:
        raise RuntimeError(
            "cannot read immutable 40-module native seed: "
            + "\n".join(seed_result.output.splitlines()[-20:])
        )
    try:
        seed_document = json.loads(seed_result.output)
    except json.JSONDecodeError as error:
        raise RuntimeError("40-module native seed is invalid JSON") from error
    seed_rows = seed_document.get("observations")
    if not isinstance(seed_rows, list):
        raise RuntimeError("40-module native seed observations must be a list")
    seed_modules = [
        row.get("module") if isinstance(row, dict) else None for row in seed_rows
    ]
    if (
        len(seed_rows) != 40
        or len(set(seed_modules)) != 40
        or set(seed_modules) != set(canonical_modules)
    ):
        raise RuntimeError("40-module native seed does not match canonical modules")

    aggregated: dict[str, dict[str, Any]] = {
        row["module"]: dict(row) for row in seed_rows
    }
    row_sources: dict[str, dict[str, str]] = {
        module: {"source": "seed", "ref": seed_ref, "commit": seed_commit}
        for module in canonical_modules
    }
    lane_receipts: list[dict[str, Any]] = []
    for lane in LANE_ORDER:
        branch = selected.get(lane)
        if not branch:
            raise RuntimeError(f"selected lane {lane} branch is missing")
        lane_ref = f"origin/{branch}"
        lane_commit = git_text("rev-parse", f"{lane_ref}^{{commit}}")
        lane_result = git("show", f"{lane_ref}:{relative_path}", check=False)
        if not lane_result.passed:
            lane_receipts.append(
                {
                    "lane": lane,
                    "branch": branch,
                    "commit": lane_commit,
                    "indexPresent": False,
                    "ownedRows": [],
                }
            )
            continue
        try:
            lane_document = json.loads(lane_result.output)
        except json.JSONDecodeError as error:
            raise RuntimeError(
                f"selected lane {lane} native index is invalid JSON"
            ) from error
        lane_rows = lane_document.get("observations")
        if not isinstance(lane_rows, list):
            raise RuntimeError(
                f"selected lane {lane} native observations must be a list"
            )
        lane_modules = [
            row.get("module") if isinstance(row, dict) else None for row in lane_rows
        ]
        duplicates = sorted(
            str(module)
            for module in set(lane_modules)
            if lane_modules.count(module) > 1
        )
        unknown = sorted(
            str(module) for module in lane_modules if module not in module_lanes
        )
        if duplicates or unknown:
            raise RuntimeError(
                f"selected lane {lane} native index invalid: "
                f"duplicates={duplicates} unknown={unknown}"
            )
        owned_rows: list[str] = []
        for row in lane_rows:
            module = row["module"]
            if module_lanes[module] != lane:
                continue
            aggregated[module] = dict(row)
            row_sources[module] = {
                "source": "primary_lane",
                "ref": lane_ref,
                "commit": lane_commit,
            }
            owned_rows.append(module)
        lane_receipts.append(
            {
                "lane": lane,
                "branch": branch,
                "commit": lane_commit,
                "indexPresent": True,
                "indexObservationCount": len(lane_rows),
                "ownedRows": sorted(owned_rows),
            }
        )

    lane_g_branch = selected.get("G")
    if not lane_g_branch:
        raise RuntimeError("Lane G source branch is required")
    source_path = (
        "tools/hepta-engineering-control/control_engineering_v2/__init__.py"
    )
    source_text = git_text(
        "show", f"origin/{lane_g_branch}:{source_path}"
    )
    merged_source = ROOT / source_path
    if not merged_source.is_file():
        raise RuntimeError(
            f"Lane G control.engineering source is missing after merge: {source_path}"
        )
    merged_text = merged_source.read_text(encoding="utf-8")
    expected_text = source_text + ("" if source_text.endswith("\n") else "\n")
    if merged_text != expected_text:
        raise RuntimeError("merged Lane G public surface differs from exact lane source")
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
    lane_g_commit = git_text(
        "rev-parse", f"origin/{lane_g_branch}^{{commit}}"
    )
    aggregated["control.engineering"] = {
        "module": "control.engineering",
        "path": source_path,
        "blobSha": git_text(
            "rev-parse", f"origin/{lane_g_branch}:{source_path}"
        ),
        "exports": exports,
    }
    row_sources["control.engineering"] = {
        "source": "exact_lane_g_public_surface",
        "ref": f"origin/{lane_g_branch}",
        "commit": lane_g_commit,
    }

    observations = [aggregated[module] for module in canonical_modules]
    for row in observations:
        module = row.get("module")
        source = row.get("path")
        row_exports = row.get("exports")
        if (
            module not in module_lanes
            or not isinstance(source, str)
            or not source
            or not isinstance(row_exports, list)
            or not row_exports
            or any(not isinstance(value, str) or not value for value in row_exports)
        ):
            raise RuntimeError(f"invalid aggregated native row for {module}")

    output_document = dict(seed_document)
    output_document["sourceSnapshot"] = git_text("rev-parse", "HEAD")
    output_document["moduleCoverage"] = 40
    output_document["consumerCallsitesProved"] = False
    output_document["productExecutionProved"] = False
    output_document["observations"] = observations
    write_json(native_path, output_document)

    harness_path = (
        ROOT / "qualification/module-execution-dossiers/test_implementation_contracts.py"
    )
    harness = harness_path.read_text(encoding="utf-8")
    test_surfaces = [harness]
    for name in (
        "implementation_contract_tests_core.py",
        "implementation_contract_tests_native.py",
        "implementation_contract_tests_system.py",
    ):
        candidate = harness_path.with_name(name)
        if candidate.is_file():
            test_surfaces.append(candidate.read_text(encoding="utf-8"))
    if "class NativeBindingCoverageTests" not in "\n".join(test_surfaces):
        raise RuntimeError("cumulative native-binding coverage tests are missing")
    if "from implementation_contract_tests_core import *" in harness:
        core_path = harness_path.with_name("implementation_contract_tests_core.py")
        if not core_path.is_file():
            raise RuntimeError("split implementation-contract core tests are missing")

    fallback_modules = sorted(
        module
        for module, source in row_sources.items()
        if source["source"] == "seed"
    )
    return {
        "seedRef": seed_ref,
        "seedCommit": seed_commit,
        "laneReceipts": lane_receipts,
        "fallbackModules": fallback_modules,
        "rowSources": row_sources,
        "laneGBranch": lane_g_branch,
        "laneGCommit": lane_g_commit,
        "laneGSourcePath": source_path,
        "laneGExports": exports,
        "moduleCoverage": len(observations),
        "changed": [relative_path],
        "count": 1,
    }
'''


def main() -> int:
    text = FINALIZER.read_text(encoding="utf-8")
    pattern = re.compile(
        r"def repair_lane_g_shared_artifacts\(.*?\n\ndef repair_argument_comment_blockers\(\) -> dict\[str, Any\]:\n",
        re.DOTALL,
    )
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise SystemExit(
            "r16 function precondition drifted: "
            f"expected one Lane G repair, observed {len(matches)}"
        )
    text = pattern.sub(
        lambda _: CORRECT_FUNCTION
        + "\n\ndef repair_argument_comment_blockers() -> dict[str, Any]:\n",
        text,
        count=1,
    )
    old_call = 'repair_lane_g_shared_artifacts(selected["G"])'
    new_call = "repair_lane_g_shared_artifacts(selected)"
    if old_call in text:
        if text.count(old_call) != 1:
            raise SystemExit("r16 call-site precondition drifted")
        text = text.replace(old_call, new_call, 1)
    elif text.count(new_call) != 1:
        raise SystemExit("r16 aggregate call site is missing or duplicated")

    required = (
        'seed_ref = "origin/codex/hepta-native-source-closed-world-20260909"',
        'module_lanes = {row.get("module"): row.get("lane")',
        "aggregated[module] = dict(row)",
        'aggregated["control.engineering"] = {',
        'output_document["moduleCoverage"] = 40',
        "class NativeBindingCoverageTests",
        new_call,
        '"laneGArtifactRepair": lane_g_artifact_repair',
    )
    for phrase in required:
        if phrase not in text:
            raise SystemExit(f"patched finalizer missing required phrase: {phrase}")

    FINALIZER.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
