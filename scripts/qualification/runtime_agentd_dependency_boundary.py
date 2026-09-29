#!/usr/bin/env python3
"""Verify runtime.agentd's staged core/product dependency boundary.

This ratchet freezes the current dependency inventory and prevents broad product
adapters from being relabelled as core. It deliberately does not claim that a
core-only Cargo profile exists until the manifest says so and CI compiles it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tomllib
from typing import Any

SCHEMA = "hepta.runtime-agentd-dependency-boundary.v1"
NORMAL_CATEGORIES = ("core_runtime", "platform_support", "product_adapters")
REQUIRED_PRODUCT_ADAPTERS = {
    "codex-app-server",
    "codex-hepta-intelligence",
    "codex-hepta-neuron",
    "codex-hepta-prompt-registry",
    "codex-hepta-memory",
    "codex-hepta-plasticity",
}
FORBIDDEN_CORE_PREFIXES = (
    "codex-app-server",
    "codex-model-provider",
)
FORBIDDEN_CORE_EXACT = {
    "codex-hepta-intelligence",
    "codex-hepta-neuron",
    "codex-hepta-prompt-registry",
    "codex-hepta-memory",
    "codex-hepta-plasticity",
}


def fail(message: str) -> None:
    raise ValueError(message)


def read_json(path: Path) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                fail(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)


def require_string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        fail(f"{label} must be a string list")
    if value != sorted(set(value)):
        fail(f"{label} must be sorted and unique")
    return value


def verify(repository: Path) -> dict[str, Any]:
    crate = repository / "codex-rs/hepta-agentd"
    cargo = tomllib.loads((crate / "Cargo.toml").read_text(encoding="utf-8"))
    boundary = read_json(crate / "DEPENDENCY_BOUNDARY.json")
    if boundary.get("schema") != SCHEMA or boundary.get("module") != "runtime.agentd":
        fail("dependency boundary identity or schema mismatch")

    categories = boundary.get("categories")
    if not isinstance(categories, dict):
        fail("missing dependency categories")
    classified: dict[str, str] = {}
    for category in NORMAL_CATEGORIES:
        for dependency in require_string_list(categories.get(category), category):
            previous = classified.setdefault(dependency, category)
            if previous != category:
                fail(f"dependency {dependency} appears in {previous} and {category}")
    actual = set(cargo.get("dependencies", {}))
    expected = set(classified)
    if actual != expected:
        fail(
            "normal dependency inventory drift: missing="
            f"{sorted(actual - expected)} extra={sorted(expected - actual)}"
        )

    development = set(require_string_list(categories.get("development_only"), "development_only"))
    actual_development = set(cargo.get("dev-dependencies", {}))
    if development != actual_development:
        fail(
            "development dependency inventory drift: missing="
            f"{sorted(actual_development - development)} "
            f"extra={sorted(development - actual_development)}"
        )

    core = set(categories["core_runtime"])
    for dependency in core:
        if dependency in FORBIDDEN_CORE_EXACT or dependency.startswith(FORBIDDEN_CORE_PREFIXES):
            fail(f"product adapter was relabelled as core: {dependency}")
    product = set(categories["product_adapters"])
    missing_required = REQUIRED_PRODUCT_ADAPTERS - product
    if missing_required:
        fail(f"required product adapters are not isolated: {sorted(missing_required)}")

    features = cargo.get("features", {})
    if features.get("default") != []:
        fail("runtime.agentd default feature set must remain empty")
    if "production-cognitive-write" in set(features.get("default", [])):
        fail("production cognitive write cannot be a default capability")
    if features.get("qualification-cognitive-write") != ["production-cognitive-write"]:
        fail("qualification writer must retain explicit production-writer dependency")

    status = boundary.get("status")
    if not isinstance(status, dict):
        fail("missing boundary status")
    if status.get("defaultFeatureReadOnly") is not True:
        fail("default read-only status disagrees with Cargo features")
    target_feature = boundary.get("migration", {}).get("targetFeature")
    target_exists = isinstance(target_feature, str) and target_feature in features
    if status.get("productAdaptersOptionalized") is not target_exists:
        fail("product adapter optionalization status disagrees with Cargo features")
    core_only_established = status.get("coreOnlyBuildEstablished")
    if core_only_established not in (True, False):
        fail("coreOnlyBuildEstablished must be boolean")
    if core_only_established and not target_exists:
        fail("core-only build cannot be claimed before the product-adapter feature exists")

    return {
        "schema": SCHEMA,
        "normalDependencies": len(actual),
        "productAdapters": len(product),
        "developmentDependencies": len(development),
        "coreOnlyBuildEstablished": core_only_established,
        "productAdaptersOptionalized": target_exists,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        result = verify(args.repository.resolve())
    except (OSError, ValueError, tomllib.TOMLDecodeError, json.JSONDecodeError) as error:
        print(f"FAIL_RUNTIME_AGENTD_DEPENDENCY_BOUNDARY: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
