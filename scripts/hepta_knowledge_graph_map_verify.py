#!/usr/bin/env python3
"""Verify only the knowledge.graph implementation map against the exact checkout.

This is a source-navigation and closed-world binding check. It deliberately does
not grant execution qualification, independent acceptance, activation or release.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP_SCRIPT = ROOT / "scripts/hepta-implementation-maps.py"
MODULE_ID = "knowledge.graph"


def load_map_tools():
    sys.path.insert(0, str((ROOT / "scripts").resolve()))
    spec = importlib.util.spec_from_file_location("hepta_implementation_maps", MAP_SCRIPT)
    if spec is None or spec.loader is None:
        raise ValueError("cannot load implementation-map verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def exact_sha(value: str | None, label: str) -> str | None:
    if value is not None and re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError(f"--{label} must be an exact 40-character Git object id")
    return value


def verify(expected_sha: str | None, expected_tree: str | None) -> dict:
    maps = load_map_tools()
    candidate = maps.current_source_base()
    expected_sha = exact_sha(expected_sha, "expected-sha")
    expected_tree = exact_sha(expected_tree, "expected-tree")
    if expected_sha is not None and candidate["commit"] != expected_sha:
        raise ValueError(
            f"expected candidate SHA {expected_sha}, observed {candidate['commit']}"
        )
    if expected_tree is not None and candidate["tree"] != expected_tree:
        raise ValueError(
            f"expected candidate tree {expected_tree}, observed {candidate['tree']}"
        )

    maps.require_clean_candidate(candidate)
    modules = maps.load("docs/modules/MODULES.json")["modules"]
    if not isinstance(modules, list) or not modules:
        raise ValueError("module registry must be nonempty")
    selected = [module for module in modules if module.get("id") == MODULE_ID]
    if len(selected) != 1:
        raise ValueError("knowledge.graph must appear exactly once in the module registry")
    module = selected[0]
    lanes = maps.lane_by_module()
    row = maps.load(f"docs/modules/{MODULE_ID}/IMPLEMENTATION_MAP.json")

    maps.validate_claim_types(row)
    maps.validate_closed_world_bindings(row)
    if (
        row.get("schema") != "hepta.module-implementation-map.v3"
        or row.get("schemaVersion") != 3
    ):
        raise ValueError("schema must be v3")
    if row.get("module") != MODULE_ID or row.get("laneId") != lanes.get(MODULE_ID):
        raise ValueError("module/lane identity")

    roots = [binding["path"] for binding in module["rootBindings"]]
    declared = row.get("declaredRoots", row.get("sourceRoot", []))
    if isinstance(declared, str):
        declared = [declared]
    if declared != roots:
        raise ValueError("declared roots")
    resolved = maps.resolve_source_roots(ROOT, module)
    if row.get("resolvedRoots") != resolved:
        raise ValueError("resolved source roots")

    operations = row.get("operations")
    if (
        not isinstance(operations, list)
        or not operations
        or any(not isinstance(operation, dict) for operation in operations)
    ):
        raise ValueError("operations")
    if "sourceRootPresent" not in row or "productionImplementation" not in row:
        raise ValueError("status model")
    maps.validate_operation_inventory(MODULE_ID, operations)

    if row.get("closedWorldPublicFunctions") is True:
        exported: set[str] = set()
        for root in resolved:
            if (maps.checked_source_path(ROOT, root) / "Cargo.toml").is_file():
                exported.update(maps.public_rust_functions(root))
        mapped = {
            operation.get("nativeSymbol")
            for operation in operations
            if isinstance(operation.get("nativeSymbol"), str)
        }
        if exported != mapped:
            raise ValueError(
                "public function inventory differs: "
                f"missing={sorted(exported - mapped)}, extra={sorted(mapped - exported)}"
            )

    mapping_mode = row.get("mappingSourceIdentityMode", "path_only")
    if mapping_mode not in {"path_only", "exact_blob"}:
        raise ValueError("mapping source identity mode")
    for operation in operations:
        if not operation.get("operation"):
            raise ValueError("operation id")
        if "nativeSymbol" not in operation or "sourcePath" not in operation:
            raise ValueError("canonical operation fields")
        source = operation.get("sourcePath")
        if source is not None and not maps.checked_source_path(ROOT, source).is_file():
            raise ValueError(f"missing source: {source}")
        if mapping_mode == "exact_blob":
            source_blob = operation.get("sourceBlob")
            if (
                not source
                or not isinstance(source_blob, str)
                or re.fullmatch(r"[0-9a-f]{40}", source_blob) is None
            ):
                raise ValueError(
                    f"invalid exact source blob: {operation['operation']}"
                )
            if maps.git("rev-parse", f"{candidate['commit']}:{source}") != source_blob:
                raise ValueError(f"source blob drift: {operation['operation']}")

    checked_paths = maps.verify_source_identity(
        row, resolved, candidate, check_checkout=False
    )

    boundary = row.get("claimBoundary") or row.get("completion")
    if not isinstance(boundary, dict):
        raise ValueError("claim boundary")
    implemented_mapping_complete = all(
        bool(operation.get("sourcePathExists") and operation.get("nativeSymbol"))
        for operation in operations
    )
    if (
        "implementedOperationMappingComplete" in boundary
        and boundary["implementedOperationMappingComplete"]
        is not implemented_mapping_complete
    ):
        raise ValueError("implemented operation mapping claim drift")
    owned_protocols = row.get("ownedTargetProtocols")
    if owned_protocols is not None:
        if not isinstance(owned_protocols, list):
            raise ValueError("owned target protocols")
        owned_source_complete = all(
            isinstance(item, dict) and item.get("state") == "source_implemented"
            for item in owned_protocols
        )
        if boundary.get("ownedTargetProtocolSourceComplete") is not owned_source_complete:
            raise ValueError("owned target protocol source claim drift")
        if boundary.get("nativeSourceMappingComplete") is not (
            implemented_mapping_complete and owned_source_complete
        ):
            raise ValueError("native source mapping claim drift")

    status = row.get("status")
    if status is not None:
        if not isinstance(status, dict) or any(
            not isinstance(status.get(field), bool)
            for field in ("implemented", "composed", "qualified")
        ):
            raise ValueError("invalid implemented/composed/qualified status")
        if status["composed"] != (
            row.get("productCallerState") != "not_composed"
        ):
            raise ValueError("composition status disagreement")

    if row.get("exactSourceEvidence", {}).get("kind") == "path_blob_manifest_v1":
        manifest_failures: list[str] = []
        maps.validate_path_blob_manifest(row, MODULE_ID, manifest_failures)
        if manifest_failures:
            raise ValueError("; ".join(manifest_failures))

    source_objects = row.get("sourceObjects")
    if source_objects is not None:
        if not isinstance(source_objects, list) or not source_objects:
            raise ValueError("source objects")
        if source_objects != maps.current_source_objects(row):
            raise ValueError("stale source objects")

    if row.get("productCallerState", "not_composed") != "not_composed":
        callers = row.get("productCallers")
        if not isinstance(callers, list) or not callers:
            raise ValueError("composed map requires product callers")
        for caller in callers:
            if not isinstance(caller, dict):
                raise ValueError("invalid product caller")
            source = caller.get("sourcePath")
            symbol = caller.get("nativeSymbol")
            if not isinstance(source, str):
                raise ValueError("missing product caller source")
            local = maps.checked_source_path(ROOT, source)
            if not local.is_file():
                raise ValueError(f"missing product caller source {source}")
            if isinstance(symbol, str) and symbol:
                if symbol.rsplit("::", 1)[-1] not in local.read_text(encoding="utf-8"):
                    raise ValueError(f"missing product caller symbol {symbol}")
        if source_objects is None:
            if (
                row.get("exactSourceEvidenceMode")
                != "lane_a_runtime_head_tree_and_registered_callers"
            ):
                raise ValueError("composed map requires exact source objects")
            if row.get("laneId") != "LANE-A-FOUNDATION":
                raise ValueError(
                    "Lane A runtime source evidence mode used outside Lane A"
                )

    maps.require_clean_candidate(candidate, sorted(set(checked_paths)))
    return {
        "status": "PASS_HEPTA_KNOWLEDGE_GRAPH_MAP",
        "module": MODULE_ID,
        "candidateSource": candidate,
        "checkedPathCount": len(set(checked_paths)),
        "productionImplementationProved": False,
        "productExecutionProved": False,
        "independentAcceptance": False,
        "activation": False,
        "release": False,
        "validationScope": "knowledge.graph source navigation and closed-world bindings",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha")
    parser.add_argument("--expected-tree")
    args = parser.parse_args()
    try:
        result = verify(args.expected_sha, args.expected_tree)
    except (
        ValueError,
        TypeError,
        KeyError,
        OSError,
        subprocess.CalledProcessError,
    ) as exc:
        print(f"FAIL_HEPTA_KNOWLEDGE_GRAPH_MAP: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
