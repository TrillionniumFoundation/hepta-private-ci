#!/usr/bin/env python3
"""Project the exact learning.plasticity map and generated status outside the checkout.

This is an authoring projection, not qualification and not a source writer. It reads
one clean candidate, merges the reviewed exact overlay into the canonical map, uses
the repository's implementation-map routines to rebind current source objects, and
writes prospective tracked files only below --output.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
MAP_PATH = ROOT / "docs/modules/learning.plasticity/IMPLEMENTATION_MAP.json"
OVERLAY_PATH = ROOT / "docs/modules/learning.plasticity/EXACT_MAPPING.json"
CURRENT_IMPLEMENTATION = ROOT / "docs/modules/learning.plasticity/CURRENT_IMPLEMENTATION.md"


def load_module():
    sys.path.insert(0, str(SCRIPTS))
    path = SCRIPTS / "hepta-implementation-maps.py"
    spec = importlib.util.spec_from_file_location("hepta_implementation_maps", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load implementation-map generator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must contain an object")
    return value


def merge_operations(base: dict[str, Any], overlay: dict[str, Any]) -> list[dict[str, Any]]:
    order: list[str] = []
    by_id: dict[str, dict[str, Any]] = {}
    for source in (base.get("operations", []), overlay.get("operations", [])):
        if not isinstance(source, list):
            raise ValueError("operation inventory must be a list")
        for row in source:
            if not isinstance(row, dict) or not isinstance(row.get("operation"), str):
                raise ValueError("operation inventory contains an untyped record")
            operation = row["operation"]
            if operation not in by_id:
                order.append(operation)
                by_id[operation] = {}
            by_id[operation].update(row)
    return [by_id[operation] for operation in order]


def upsert_callers(row: dict[str, Any]) -> None:
    desired = [
        {
            "sourcePath": "codex-rs/hepta-agentd/src/plasticity_runtime.rs",
            "nativeSymbol": "compose_plasticity_runtime_v1",
            "state": "long_lived_agentd_owner_source_composed_not_target_host_qualified",
        },
        {
            "sourcePath": "codex-rs/hepta-agentd/src/plasticity_learning_producer.rs",
            "nativeSymbol": "AgentdLearningPlasticityProducerV1",
            "state": "state_held_named_producer_source_composed_not_target_host_qualified",
        },
        {
            "sourcePath": "codex-rs/hepta-agentd/src/plasticity_iteration_coordinator.rs",
            "nativeSymbol": "ControlEngineeringPlasticityCoordinatorV1",
            "state": "non_test_frozen_parameter_iteration_coordinator_source_composed_not_target_host_qualified",
        },
        {
            "sourcePath": "codex-rs/hepta-agentd/src/plasticity_topology_iteration_coordinator.rs",
            "nativeSymbol": "ControlEngineeringTopologyCoordinatorV1",
            "state": "non_test_frozen_topology_iteration_coordinator_source_composed_not_target_host_qualified",
        },
    ]
    existing = {
        caller.get("sourcePath", caller.get("path")): dict(caller)
        for caller in row.get("productCallers", [])
        if isinstance(caller, dict)
    }
    for caller in desired:
        existing[caller["sourcePath"]] = caller
    row["productCallers"] = [existing[path] for path in sorted(existing)]


def replace_status_block(text: str, block: str, begin: str, end: str) -> str:
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.S)
    if not pattern.search(text):
        raise ValueError("CURRENT_IMPLEMENTATION.md lacks generated status markers")
    return pattern.sub(block, text, count=1)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output == ROOT or ROOT in output.parents:
        parser.error("projection output must be outside the source checkout")

    if subprocess.check_output(
        ["git", "-C", str(ROOT), "status", "--porcelain"], text=True
    ).strip():
        raise SystemExit("projection requires a clean candidate checkout")

    impl = load_module()
    base = load_json(MAP_PATH)
    overlay = load_json(OVERLAY_PATH)
    if base.get("module") != "learning.plasticity" or overlay.get("module") != base.get("module"):
        raise SystemExit("learning.plasticity map/overlay identity mismatch")

    projected = dict(base)
    projected["operations"] = merge_operations(base, overlay)
    for key in (
        "productCallerState",
        "productionImplementation",
        "repositoryControlledGaps",
        "externalEvidenceGates",
    ):
        if key in overlay:
            projected[key] = overlay[key]
    projected["productionImplementation"] = False
    boundary = dict(projected.get("claimBoundary") or {})
    boundary.update(
        productionImplementation=False,
        productExecutionProved=False,
        independentAcceptance=False,
        activation=False,
        release=False,
    )
    projected["claimBoundary"] = boundary
    upsert_callers(projected)

    source_base = impl.current_source_base()
    modules = impl.load("docs/modules/MODULES.json")["modules"]
    module = next(item for item in modules if item["id"] == "learning.plasticity")
    lanes = impl.lane_by_module()
    projected = impl.migrate_map(projected, module, lanes, source_base)

    failures: list[str] = []
    impl.verify_plasticity_test_references(projected, failures)
    if failures:
        raise SystemExit("; ".join(failures))
    resolved = impl.resolve_source_roots(ROOT, module)
    impl.verify_source_identity(projected, resolved, source_base, check_checkout=False)
    if projected.get("sourceObjects") != impl.current_source_objects(projected):
        raise SystemExit("projected source objects are not current")

    rendered_map = json.dumps(projected, indent=2, ensure_ascii=False) + "\n"
    status_block = impl.plasticity_status_block(projected)
    rendered_current = replace_status_block(
        CURRENT_IMPLEMENTATION.read_text(encoding="utf-8"),
        status_block,
        impl.STATUS_BEGIN,
        impl.STATUS_END,
    )
    rendered_state = (
        json.dumps(
            impl.plasticity_current_state_projection(projected),
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )

    rel = Path("docs/modules/learning.plasticity")
    files = {
        rel / "IMPLEMENTATION_MAP.json": rendered_map,
        rel / "CURRENT_IMPLEMENTATION.md": rendered_current,
        rel / "CURRENT_STATE.json": rendered_state,
    }
    for path, content in files.items():
        write(output / path, content)

    manifest = {
        "schema": "hepta.learning-plasticity-map-projection.v1",
        "sourceCommit": source_base["commit"],
        "sourceTree": source_base["tree"],
        "productionImplementation": False,
        "productExecutionProved": False,
        "independentAcceptance": False,
        "activation": False,
        "release": False,
        "files": [
            {
                "path": str(path),
                "sha256": sha256(content.encode("utf-8")),
                "bytes": len(content.encode("utf-8")),
            }
            for path, content in sorted(files.items(), key=lambda item: str(item[0]))
        ],
    }
    write(output / "projection.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
