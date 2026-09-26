#!/usr/bin/env python3
"""Generate and verify the closed-world platform.types public implementation map."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DETAILED_PATH = ROOT / "docs/modules/platform.types/IMPLEMENTATION_MAP.json"
INVENTORY_RELATIVE = "docs/modules/platform.types/PUBLIC_API_INVENTORY_V1.json"

try:
    from platform_types_public_api import expected_inventory
except ImportError as error:  # pragma: no cover - executable location invariant
    raise SystemExit(f"cannot import platform_types_public_api: {error}") from error


class ImplementationMapError(RuntimeError):
    """The generated map or its detailed implementation anchors diverged."""


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ImplementationMapError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise ImplementationMapError(f"JSON object required: {path}")
    return value


def expected_map() -> dict[str, Any]:
    inventory = expected_inventory()
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"sourcePaths": set(), "exports": []}
    )
    for module in inventory["sourceModules"]:
        source_module = module["sourceModule"]
        source_path = module["sourcePath"]
        for symbol, operation in module["exports"].items():
            row = grouped[operation]
            row["sourcePaths"].add(source_path)
            row["exports"].append(
                {
                    "symbol": symbol,
                    "sourceModule": source_module,
                    "sourcePath": source_path,
                }
            )

    operations = []
    for operation in sorted(grouped):
        row = grouped[operation]
        exports = sorted(row["exports"], key=lambda item: item["symbol"])
        operations.append(
            {
                "operation": operation,
                "sourcePaths": sorted(row["sourcePaths"]),
                "exportCount": len(exports),
                "exports": exports,
            }
        )

    return {
        "schema": "hepta.platform-types.generated-implementation-map.v1",
        "schemaVersion": 1,
        "module": "platform.types",
        "generatedFrom": [
            "codex-rs/hepta-types/src/lib.rs",
            INVENTORY_RELATIVE,
        ],
        "generationCommand": (
            "python3 scripts/platform_types_implementation_map.py --output <candidate-artifact-path>"
        ),
        "coveragePolicy": (
            "every exact pub-use export is assigned to exactly one "
            "implementation operation and source path"
        ),
        "exportCount": inventory["exportCount"],
        "operationCount": inventory["operationCount"],
        "operations": operations,
    }


def _validate_detailed_map(generated: dict[str, Any]) -> None:
    detailed = _read_object(DETAILED_PATH)
    operations = detailed.get("operations")
    if not isinstance(operations, list):
        raise ImplementationMapError("detailed implementation map needs operations")

    by_name: dict[str, dict[str, Any]] = {}
    for row in operations:
        if not isinstance(row, dict) or not isinstance(row.get("operation"), str):
            raise ImplementationMapError("invalid detailed operation row")
        name = row["operation"]
        if name in by_name:
            raise ImplementationMapError(f"duplicate detailed operation: {name}")
        by_name[name] = row

    for operation in generated["operations"]:
        name = operation["operation"]
        detailed_row = by_name.get(name)
        if detailed_row is None:
            raise ImplementationMapError(
                f"detailed implementation map is missing public operation {name}"
            )
        if detailed_row.get("sourcePath") not in operation["sourcePaths"]:
            raise ImplementationMapError(
                f"detailed source path for {name} is outside generated public ownership"
            )
        if detailed_row.get("sourcePathExists") is not True:
            raise ImplementationMapError(f"{name} is not marked source-present")
        for source_path in operation["sourcePaths"]:
            if not (ROOT / source_path).is_file():
                raise ImplementationMapError(
                    f"generated source path does not exist for {name}: {source_path}"
                )

    reference = detailed.get("publicApiInventory")
    expected_reference = {
        "path": INVENTORY_RELATIVE,
        "coveragePolicy": "closed_world_exact_pub_use_exports",
        "exportCount": generated["exportCount"],
        "operationCount": generated["operationCount"],
    }
    if reference != expected_reference:
        raise ImplementationMapError("detailed public API reference is stale")

    claim = detailed.get("claimBoundary")
    if not isinstance(claim, dict) or claim.get("publicApiInventoryComplete") is not True:
        raise ImplementationMapError(
            "detailed map must claim publicApiInventoryComplete only after verification"
        )


def verify_repository() -> dict[str, Any]:
    expected = expected_map()
    _validate_detailed_map(expected)
    return expected


def write_map(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        help="write the exact generated projection to this candidate-artifact path",
    )
    args = parser.parse_args()
    try:
        verified = verify_repository()
        if args.output is not None:
            write_map(args.output, verified)
    except ImplementationMapError as error:
        print(f"platform.types implementation map failed: {error}", file=sys.stderr)
        return 1
    print(
        "platform.types implementation map: ok "
        f"({verified['exportCount']} exports, "
        f"{verified['operationCount']} operations)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
