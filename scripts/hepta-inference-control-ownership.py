#!/usr/bin/env python3
"""Keep the worker exclusively owned by inference.worker across known registries.

Inference.control may cite the worker as evidence, but never acquire its root.
Unknown shapes and conflicting Cargo ownership fail closed.
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
FILES = (
    ROOT / "docs/modules/MODULES.json",
    ROOT / "docs/modules/CARGO_BINDINGS.json",
    ROOT / "docs/modules/SOURCE_BINDINGS.json",
    ROOT / "docs/delivery/PATH_OWNERSHIP.json",
)


def transform(value: Any, filename: str) -> tuple[Any, int]:
    """Project only known registry rows; caller evidence never transfers roots."""
    schemas = {
        "MODULES.json": "hepta.module-registry.v7",
        "SOURCE_BINDINGS.json": "hepta.module-source-binding.v2",
        "CARGO_BINDINGS.json": "hepta.cargo-module-binding.v1",
        "PATH_OWNERSHIP.json": "hepta.path-ownership.v3",
    }
    if (
        filename not in schemas
        or not isinstance(value, dict)
        or value.get("schema") != schemas[filename]
    ):
        raise ValueError("unknown ownership registry schema")
    result = copy.deepcopy(value)
    layouts = {
        "MODULES.json": ("modules", "id"),
        "SOURCE_BINDINGS.json": ("bindings", "module"),
        "PATH_OWNERSHIP.json": ("moduleNamespaces", "module"),
    }
    if filename == "CARGO_BINDINGS.json":
        rows = result.get("bindings")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("invalid Cargo bindings")
        for path, owner in [
            (CORE, "inference.control"),
            (INFERD, "inference.control"),
            (WORKER, "inference.worker"),
        ]:
            matches = [row for row in rows if row.get("packagePath") == path]
            if len(matches) != 1 or matches[0].get("module") != owner:
                raise ValueError("Cargo root must retain its registered owner: " + path)
        return result, 0
    if filename not in layouts:
        raise ValueError("unknown ownership registry")
    key, identity = layouts[filename]
    rows = result.get(key)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("invalid ownership registry rows")
    selected = {}
    for owner in ("inference.control", "inference.worker"):
        matches = [row for row in rows if row.get(identity) == owner]
        if len(matches) != 1:
            raise ValueError("missing or duplicated owner: " + owner)
        selected[owner] = matches[0]
    control = selected["inference.control"]
    worker = selected["inference.worker"]
    if filename == "SOURCE_BINDINGS.json":
        for field in ("declaredRoots", "existingDeclaredRoots"):
            roots = control.get(field)
            if (
                not isinstance(roots, list)
                or any(not isinstance(root, str) for root in roots)
                or len(roots) != len(set(roots))
                or set(roots)
                not in (
                    {CORE, INFERD},
                    {CORE, INFERD, WORKER},
                )
            ):
                raise ValueError("unknown inference control roots")
            control[field] = [root for root in roots if root != WORKER]
            if worker.get(field) != [WORKER]:
                raise ValueError("worker exclusive roots changed")
            for row in rows:
                declared = row.get(field)
                if not isinstance(declared, list) or any(
                    not isinstance(root, str) for root in declared
                ):
                    raise ValueError("invalid declared source root shape")
                if row.get(identity) != "inference.worker" and WORKER in declared:
                    raise ValueError("another module claims exclusive worker root")
    else:
        roots = control.get("rootBindings")
        if (
            not isinstance(roots, list)
            or any(
                not isinstance(row, dict)
                or set(row) != {"path", "mode"}
                or not isinstance(row.get("path"), str)
                or row.get("mode") != "exclusive"
                for row in roots
            )
            or len(roots) != len({row["path"] for row in roots})
            or {row.get("path") for row in roots}
            not in (
                {CORE, INFERD},
                {CORE, INFERD, WORKER},
            )
        ):
            raise ValueError("unknown inference control root bindings")
        control["rootBindings"] = [row for row in roots if row.get("path") != WORKER]
        if worker.get("rootBindings") != [{"path": WORKER, "mode": "exclusive"}]:
            raise ValueError("worker exclusive binding changed")
        for row in rows:
            bindings = row.get("rootBindings")
            if not isinstance(bindings, list) or any(
                not isinstance(binding, dict) for binding in bindings
            ):
                raise ValueError("invalid ownership root binding rows")
            if row.get(identity) != "inference.worker" and any(
                binding.get("path") == WORKER for binding in bindings
            ):
                raise ValueError("another module claims exclusive worker root")
    if filename in {"MODULES.json", "SOURCE_BINDINGS.json"}:
        evidence = control.get("sourceEvidenceRoots")
        if not isinstance(evidence, list) or CORE not in evidence:
            raise ValueError("missing inference evidence roots")
        if WORKER not in evidence:
            evidence.insert(evidence.index(CORE) + 1, WORKER)
    return result, int(result != value)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=OrderedDict)


def render(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def projected(path: Path) -> tuple[str, int]:
    original = load(path)
    transformed, changes = transform(original, path.name)
    rendered = render(transformed)
    if WORKER not in rendered:
        raise ValueError(
            f"{path.relative_to(ROOT)} has no registered worker source binding"
        )
    if "inference.control" not in rendered:
        raise ValueError(
            f"{path.relative_to(ROOT)} does not identify inference.control"
        )
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
        raise SystemExit(
            "stale inference.control ownership projections: " + ", ".join(stale)
        )
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
