#!/usr/bin/env python3
"""Generate and verify Lane A module-owned GitHub Actions path filters.

The module inventory is the sole source for module-owned source/evidence roots and
technical-document directories. Governance scripts and the workflow itself remain
explicit fixed filters next to the generated block.
"""

from __future__ import annotations

import argparse
import json
import posixpath
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
MODULES_PATH = ROOT / "docs/modules/MODULES.json"
WORKFLOW_PATH = ROOT / ".github/workflows/lane-a-foundation.yml"
BEGIN_MARKER = "      # BEGIN GENERATED LANE A MODULE PATHS"
END_MARKER = "      # END GENERATED LANE A MODULE PATHS"
ITEM_INDENT = "      "

# Closed-world membership is intentionally shared with the truth verifier. A
# membership change must therefore update one reviewed source of truth rather
# than a second handwritten workflow list.
sys.path.insert(0, str(ROOT / "scripts"))
from lane_a_foundation_core import EXPECTED_MODULES  # noqa: E402


class GenerationError(RuntimeError):
    """The module inventory cannot produce a safe deterministic path block."""


def _read_inventory(path: Path = MODULES_PATH) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GenerationError(f"cannot read module inventory {path}: {error}") from error
    if not isinstance(value, dict) or not isinstance(value.get("modules"), list):
        raise GenerationError("module inventory must contain a modules array")
    return value


def _safe_repo_path(raw: object, *, field: str, module_id: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise GenerationError(f"{module_id}.{field} must be a non-empty string")
    value = raw.replace("\\", "/").strip().rstrip("/")
    candidate = PurePosixPath(value)
    if not candidate.parts or candidate.is_absolute() or ".." in candidate.parts:
        raise GenerationError(f"{module_id}.{field} escapes the repository: {raw!r}")
    if any(part in {"", "."} for part in candidate.parts):
        raise GenerationError(f"{module_id}.{field} is not canonical: {raw!r}")
    if any(char in value for char in "*?[]{}!\n\r\t") or any(ord(char) < 32 for char in value):
        raise GenerationError(f"{module_id}.{field} contains workflow glob syntax: {raw!r}")
    normalized = posixpath.normpath(value)
    if normalized != value:
        raise GenerationError(f"{module_id}.{field} is not normalized: {raw!r}")
    return value


def _directory_glob(path: str) -> str:
    return f"{path}/**"


def module_owned_paths(
    inventory: dict[str, Any], expected_modules: Iterable[str] = EXPECTED_MODULES
) -> list[str]:
    rows = inventory.get("modules")
    if not isinstance(rows, list):
        raise GenerationError("module inventory must contain a modules array")

    by_id: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise GenerationError(f"modules[{index}] must be an object")
        module_id = row.get("id")
        if not isinstance(module_id, str) or not module_id:
            raise GenerationError(f"modules[{index}].id must be a non-empty string")
        if module_id in by_id:
            raise GenerationError(f"duplicate module id: {module_id}")
        by_id[module_id] = row

    paths: list[str] = []
    seen: set[str] = set()

    def add(path: str) -> None:
        glob = _directory_glob(path)
        if glob not in seen:
            seen.add(glob)
            paths.append(glob)

    for module_id in expected_modules:
        row = by_id.get(module_id)
        if row is None:
            raise GenerationError(f"Lane A module missing from inventory: {module_id}")

        bindings = row.get("rootBindings")
        if not isinstance(bindings, list) or not bindings:
            raise GenerationError(f"{module_id}.rootBindings must be a non-empty array")
        for index, binding in enumerate(bindings):
            if not isinstance(binding, dict):
                raise GenerationError(f"{module_id}.rootBindings[{index}] must be an object")
            add(
                _safe_repo_path(
                    binding.get("path"), field=f"rootBindings[{index}].path", module_id=module_id
                )
            )

        evidence_roots = row.get("sourceEvidenceRoots", [])
        if not isinstance(evidence_roots, list):
            raise GenerationError(f"{module_id}.sourceEvidenceRoots must be an array")
        for index, evidence_root in enumerate(evidence_roots):
            add(
                _safe_repo_path(
                    evidence_root,
                    field=f"sourceEvidenceRoots[{index}]",
                    module_id=module_id,
                )
            )

        technical_document = _safe_repo_path(
            row.get("technicalDocument"), field="technicalDocument", module_id=module_id
        )
        technical_parent = str(PurePosixPath(technical_document).parent)
        if technical_parent == ".":
            raise GenerationError(f"{module_id}.technicalDocument must have a parent directory")
        add(technical_parent)

    return paths


def render_generated_block(paths: Iterable[str]) -> str:
    lines = [BEGIN_MARKER]
    lines.extend(f"{ITEM_INDENT}- {json.dumps(path)}" for path in paths)
    lines.append(END_MARKER)
    return "\n".join(lines)


def replace_generated_block(workflow: str, block: str) -> str:
    begin_count = workflow.count(BEGIN_MARKER)
    end_count = workflow.count(END_MARKER)
    if begin_count != 1 or end_count != 1:
        raise GenerationError(
            "workflow must contain exactly one generated Lane A path marker pair"
        )
    begin = workflow.index(BEGIN_MARKER)
    end = workflow.index(END_MARKER) + len(END_MARKER)
    if end <= begin:
        raise GenerationError("generated Lane A path markers are reversed")
    return workflow[:begin] + block + workflow[end:]


def expected_workflow_text(
    inventory_path: Path = MODULES_PATH,
    workflow_path: Path = WORKFLOW_PATH,
    expected_modules: Iterable[str] = EXPECTED_MODULES,
) -> str:
    inventory = _read_inventory(inventory_path)
    try:
        workflow = workflow_path.read_text(encoding="utf-8")
    except OSError as error:
        raise GenerationError(f"cannot read workflow {workflow_path}: {error}") from error
    block = render_generated_block(module_owned_paths(inventory, expected_modules))
    return replace_generated_block(workflow, block)


def check(
    inventory_path: Path = MODULES_PATH,
    workflow_path: Path = WORKFLOW_PATH,
    expected_modules: Iterable[str] = EXPECTED_MODULES,
) -> None:
    expected = expected_workflow_text(inventory_path, workflow_path, expected_modules)
    observed = workflow_path.read_text(encoding="utf-8")
    if observed != expected:
        raise GenerationError(
            "Lane A workflow module path block is stale; run "
            "python3 scripts/generate_lane_a_workflow_paths.py write"
        )


def write(
    inventory_path: Path = MODULES_PATH,
    workflow_path: Path = WORKFLOW_PATH,
    expected_modules: Iterable[str] = EXPECTED_MODULES,
) -> None:
    expected = expected_workflow_text(inventory_path, workflow_path, expected_modules)
    workflow_path.write_text(expected, encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("check", "write", "print"))
    parser.add_argument("--inventory", type=Path, default=MODULES_PATH)
    parser.add_argument("--workflow", type=Path, default=WORKFLOW_PATH)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.command == "check":
            check(args.inventory, args.workflow)
        elif args.command == "write":
            write(args.inventory, args.workflow)
        else:
            inventory = _read_inventory(args.inventory)
            print(render_generated_block(module_owned_paths(inventory)))
    except GenerationError as error:
        print(f"lane-a workflow path generation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
