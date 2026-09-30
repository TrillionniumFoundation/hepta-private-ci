#!/usr/bin/env python3
"""Fail closed when a production crate can activate knowledge.graph V1.

The V1 implementation remains available only as the `codex-hepta-kg` fixture
feature. No other workspace manifest may activate `legacy-v1` or `fixture`, and
the public re-exports must remain behind the exact `legacy-v1` cfg gate.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
KG_MANIFEST = ROOT / "codex-rs/hepta-kg/Cargo.toml"
KG_LIB = ROOT / "codex-rs/hepta-kg/src/lib.rs"
FORBIDDEN_FEATURES = {"legacy-v1", "fixture"}
LEGACY_EXPORTS = ("Error", "KnowledgeEdge", "KnowledgeProjection", "rebuild")


class LegacyGuardError(ValueError):
    """The production/V1 feature boundary is not closed."""


def load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        value = tomllib.load(handle)
    if not isinstance(value, dict):
        raise LegacyGuardError(f"invalid TOML document: {path}")
    return value


def dependency_tables(value: Any, prefix: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
    if not isinstance(value, dict):
        return
    for key, child in value.items():
        name = f"{prefix}.{key}" if prefix else key
        if key in {"dependencies", "dev-dependencies", "build-dependencies"}:
            if isinstance(child, dict):
                yield name, child
            continue
        if key == "target" and isinstance(child, dict):
            for target_name, target_value in child.items():
                yield from dependency_tables(target_value, f"{name}.{target_name}")


def dependency_features(specification: Any) -> set[str]:
    if not isinstance(specification, dict):
        return set()
    raw = specification.get("features", [])
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise LegacyGuardError("dependency features must be a list of strings")
    return set(raw)


def dependency_is_kg(name: str, specification: Any) -> bool:
    if name == "codex-hepta-kg":
        return True
    return isinstance(specification, dict) and specification.get("package") == "codex-hepta-kg"


def tracked_manifests(root: Path) -> list[Path]:
    output = subprocess.check_output(
        ["git", "-C", str(root), "ls-files", "-z", "**/Cargo.toml", "Cargo.toml"],
        text=True,
    )
    return [root / item for item in output.split("\0") if item]


def verify_manifest_boundary(root: Path) -> list[str]:
    kg = load_toml(root / "codex-rs/hepta-kg/Cargo.toml")
    features = kg.get("features")
    if not isinstance(features, dict):
        raise LegacyGuardError("codex-hepta-kg [features] is missing")
    if features.get("default") != []:
        raise LegacyGuardError("codex-hepta-kg default features must remain empty")
    if features.get("legacy-v1") != []:
        raise LegacyGuardError("legacy-v1 must remain an explicit empty leaf feature")
    if features.get("fixture") != ["legacy-v1"]:
        raise LegacyGuardError("fixture must be the only alias for legacy-v1")

    checked: list[str] = []
    for manifest in tracked_manifests(root):
        if manifest == root / "codex-rs/hepta-kg/Cargo.toml":
            continue
        relative = manifest.relative_to(root).as_posix()
        document = load_toml(manifest)
        for table_name, table in dependency_tables(document):
            for dependency_name, specification in table.items():
                if not dependency_is_kg(dependency_name, specification):
                    continue
                enabled = dependency_features(specification) & FORBIDDEN_FEATURES
                if enabled:
                    joined = ", ".join(sorted(enabled))
                    raise LegacyGuardError(
                        f"{relative} {table_name}.{dependency_name} enables forbidden KG features: {joined}"
                    )
                checked.append(f"{relative}:{table_name}.{dependency_name}")
    return sorted(checked)


def verify_source_gate(root: Path) -> None:
    source = (root / "codex-rs/hepta-kg/src/lib.rs").read_text(encoding="utf-8")
    if not re.search(r'#\[cfg\(feature = "legacy-v1"\)\]\s*mod legacy_v1;', source):
        raise LegacyGuardError("legacy_v1 module is not gated by the exact legacy-v1 feature")
    for symbol in LEGACY_EXPORTS:
        pattern = (
            r'#\[cfg\(feature = "legacy-v1"\)\]'
            r'(?:\s*#\[[^\n]+\])*'
            r'\s*pub use legacy_v1::'
            + re.escape(symbol)
            + r'(?:\s+as\s+[A-Za-z0-9_]+)?;'
        )
        if not re.search(pattern, source):
            raise LegacyGuardError(f"legacy export {symbol} escaped or lost its feature gate")

    output = subprocess.check_output(
        ["git", "-C", str(root), "grep", "-n", "legacy-v1", "--", "*.rs"],
        text=True,
        stderr=subprocess.DEVNULL,
    )
    cfg_pattern = re.compile(r"\bcfg(?:_attr)?\s*\([^)]*legacy-v1")
    for line in output.splitlines():
        path, _, source_line = line.partition(":")
        if not cfg_pattern.search(source_line):
            continue
        if not path.startswith("codex-rs/hepta-kg/"):
            raise LegacyGuardError(f"legacy-v1 Rust cfg escaped codex-hepta-kg: {line}")


def verify(root: Path) -> dict[str, Any]:
    checked = verify_manifest_boundary(root)
    verify_source_gate(root)
    return {
        "status": "PASS_HEPTA_KG_LEGACY_GUARD",
        "defaultFeatures": [],
        "fixtureFeature": ["legacy-v1"],
        "workspaceKgDependenciesChecked": checked,
        "productionLegacyFeatureEnabled": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        result = verify(args.root.resolve())
    except (LegacyGuardError, OSError, subprocess.CalledProcessError, tomllib.TOMLDecodeError) as exc:
        print(f"FAIL_HEPTA_KG_LEGACY_GUARD: {exc}", file=sys.stderr)
        return 1
    print(result["status"])
    for dependency in result["workspaceKgDependenciesChecked"]:
        print(f"checked {dependency}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
