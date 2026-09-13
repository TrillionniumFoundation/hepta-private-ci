"""Resolve registered source locations, never runtime or writer authority."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath


def _path(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or "\0" in value:
        raise ValueError("invalid source path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts) or PurePosixPath(value).is_absolute():
        raise ValueError(f"non-canonical source path: {value!r}")
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise ValueError(f"symlink source path: {value}")
    return path


def _pairs(items: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"duplicate binding key: {key}")
        result[key] = value
    return result


def resolve_source_roots(root: Path, module: dict) -> list[str]:
    """Resolve exact canonical aliases and explicitly listed legacy files.

    Declared roots remain unchanged. Extra evidence must name individual files,
    not whole foreign crates; its presence never transfers writer ownership.
    Alias bindings are reviewed source data, not discovered executable code.
    """
    resolved = []
    declared = [binding["path"] for binding in module["rootBindings"]]
    for value in declared:
        path = _path(root, value)
        if not path.exists():
            continue
        if not path.is_dir():
            raise ValueError(f"declared source root is not a directory: {value}")
        binding_path = path / "BINDING.json"
        if binding_path.is_symlink():
            raise ValueError(f"invalid alias binding: {value}")
        if not binding_path.exists():
            candidates = [value]
        else:
            if binding_path.is_symlink() or not binding_path.is_file():
                raise ValueError(f"invalid alias binding: {value}")
            binding = json.loads(binding_path.read_text(encoding="utf-8"), object_pairs_hook=_pairs)
            allowed = {
                "schema_version", "module", "declared_root", "implementation_root",
                "binding_mode", "duplicate_cargo_package_created", "model_authority",
                "provider_authority", "interpretation", "source_evidence_paths",
                "source_evidence_scope",
            }
            if not isinstance(binding, dict) or set(binding) - allowed:
                raise ValueError("invalid or unknown alias binding fields")
            if (
                type(binding.get("schema_version")) is not int
                or binding["schema_version"] != 1
                or binding.get("binding_mode") != "canonical_alias"
                or binding.get("module") != module["id"]
                or binding.get("declared_root") != value
                or any(binding.get(key) is not False for key in (
                    "duplicate_cargo_package_created", "model_authority", "provider_authority"
                ))
            ):
                raise ValueError(f"alias identity or authority mismatch: {value}")
            target = binding.get("implementation_root")
            if target in declared or not _path(root, target).is_dir():
                raise ValueError(f"alias target must be an existing distinct directory: {value}")
            if (_path(root, target) / "BINDING.json").exists():
                raise ValueError(f"nested source alias is not supported: {value}")
            evidence = binding.get("source_evidence_paths", [])
            if not isinstance(evidence, list):
                raise ValueError("source evidence paths must be a list")
            for source in evidence:
                if not _path(root, source).is_file():
                    raise ValueError(f"source evidence must be an existing file: {source}")
            candidates = [target, *evidence]
        for candidate in candidates:
            if candidate in resolved:
                raise ValueError(f"duplicate resolved source: {candidate}")
            resolved.append(candidate)
    return resolved
