#!/usr/bin/env python3
"""Synchronize inference.control's worker-host ownership projections.

This transformer is intentionally narrow. It inserts the real native host only
where a structure already identifies inference.control/inference-platform and
already contains the inference core root. Unknown schemas fail closed instead
of receiving a guessed binding.
"""

from __future__ import annotations

import argparse
import copy
import json
from collections import OrderedDict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CORE = "codex-rs/hepta-infer-core"
WORKER = "codex-rs/hepta-infer-worker-host"
INFERD = "codex-rs/hepta-inferd"
MODULE_MARKERS = {"inference.control", "inference-platform"}
FILES = (
    ROOT / "docs/modules/MODULES.json",
    ROOT / "docs/modules/CARGO_BINDINGS.json",
    ROOT / "docs/modules/SOURCE_BINDINGS.json",
    ROOT / "docs/delivery/PATH_OWNERSHIP.json",
)
PATH_FIELDS = {
    "path",
    "root",
    "sourceRoot",
    "source_root",
    "cargoRoot",
    "cargo_root",
    "repositoryPath",
    "repository_path",
}
ROOT_LIST_FIELDS = {
    "roots",
    "sourceRoots",
    "source_roots",
    "declaredRoots",
    "declared_roots",
    "resolvedRoots",
    "resolved_roots",
    "cargoRoots",
    "cargo_roots",
    "ownedPaths",
    "owned_paths",
    "paths",
    "sourceEvidenceRoots",
}


def contains_marker(value: Any) -> bool:
    if isinstance(value, str):
        return value in MODULE_MARKERS
    if isinstance(value, list):
        return any(contains_marker(item) for item in value)
    if isinstance(value, dict):
        return any(contains_marker(item) for item in value.values())
    return False


def insert_after(values: list[str], anchor: str, addition: str) -> list[str]:
    if addition in values:
        return values
    result = list(values)
    result.insert(result.index(anchor) + 1, addition)
    return result


def clone_path_entry(entry: dict[str, Any], field: str) -> dict[str, Any]:
    clone = copy.deepcopy(entry)
    clone[field] = WORKER
    return clone


def transform(value: Any, inherited_inference: bool = False, field_name: str = "") -> tuple[Any, int]:
    local_inference = inherited_inference or contains_marker(value)
    changes = 0

    if isinstance(value, list):
        if all(isinstance(item, str) for item in value):
            strings = list(value)
            root_field = field_name in ROOT_LIST_FIELDS
            if CORE in strings and WORKER not in strings and (
                local_inference or root_field and INFERD in strings
            ):
                return insert_after(strings, CORE, WORKER), 1
            return value, 0

        transformed: list[Any] = []
        worker_entry_present = any(
            isinstance(item, dict)
            and any(item.get(field) == WORKER for field in PATH_FIELDS)
            for item in value
        )
        for item in value:
            new_item, item_changes = transform(item, local_inference, field_name)
            transformed.append(new_item)
            changes += item_changes
            if (
                not worker_entry_present
                and isinstance(item, dict)
                and (local_inference or contains_marker(item))
            ):
                for field in PATH_FIELDS:
                    if item.get(field) == CORE:
                        transformed.append(clone_path_entry(item, field))
                        worker_entry_present = True
                        changes += 1
                        break
        return transformed, changes

    if isinstance(value, dict):
        transformed = OrderedDict()
        worker_key_present = WORKER in value
        for key, item in value.items():
            new_item, item_changes = transform(item, local_inference, key)
            transformed[key] = new_item
            changes += item_changes
            if (
                key == CORE
                and not worker_key_present
                and (local_inference or contains_marker(item))
            ):
                transformed[WORKER] = copy.deepcopy(item)
                worker_key_present = True
                changes += 1
        return transformed, changes

    return value, 0


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)


def render(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def projected(path: Path) -> tuple[str, int]:
    original = load(path)
    transformed, changes = transform(original)
    rendered = render(transformed)
    if WORKER not in rendered:
        raise ValueError(f"{path.relative_to(ROOT)} has no safe inference worker-host insertion point")
    if "inference.control" not in rendered:
        raise ValueError(f"{path.relative_to(ROOT)} does not identify inference.control")
    return rendered, changes


def sync() -> None:
    changed: list[str] = []
    for path in FILES:
        if not path.is_file():
            raise ValueError(f"missing ownership projection: {path.relative_to(ROOT)}")
        rendered, _ = projected(path)
        if path.read_text(encoding="utf-8") != rendered:
            path.write_text(rendered, encoding="utf-8")
            changed.append(str(path.relative_to(ROOT)))
    print(json.dumps({"changed": changed}, ensure_ascii=False))


def check() -> None:
    stale: list[str] = []
    for path in FILES:
        if not path.is_file():
            raise ValueError(f"missing ownership projection: {path.relative_to(ROOT)}")
        rendered, _ = projected(path)
        if path.read_text(encoding="utf-8") != rendered:
            stale.append(str(path.relative_to(ROOT)))
    if stale:
        raise SystemExit("stale inference.control ownership projections: " + ", ".join(stale))
    print(json.dumps({"checked": [str(path.relative_to(ROOT)) for path in FILES]}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("sync", "check"))
    args = parser.parse_args()
    try:
        if args.command == "sync":
            sync()
        else:
            check()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
