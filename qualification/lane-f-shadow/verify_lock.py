#!/usr/bin/env python3
"""Verify that the standalone Lane F lock is an exact root-lock subset."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

EXPECTED_ROOT_DEPENDENCIES = {
    "codex-hepta-intelligence",
    "codex-hepta-intuition",
    "codex-hepta-neuron",
    "codex-hepta-plasticity",
    "codex-hepta-prompt-optimizer",
    "codex-hepta-types",
}


def load_lock(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def external_identity(package: dict[str, object]) -> tuple[object, ...]:
    return (
        package["name"],
        package["version"],
        package.get("source"),
        package.get("checksum"),
    )


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: verify_lock.py <workspace-seed.lock> <generated.lock>")

    seed_path = Path(sys.argv[1])
    generated_path = Path(sys.argv[2])
    seed = load_lock(seed_path)
    generated = load_lock(generated_path)

    seed_packages = seed.get("package", [])
    generated_packages = generated.get("package", [])
    if not isinstance(seed_packages, list) or not isinstance(generated_packages, list):
        raise SystemExit("lock file package table is not a list")

    seed_external = {
        external_identity(package)
        for package in seed_packages
        if isinstance(package, dict) and package.get("source") is not None
    }
    generated_external = {
        external_identity(package)
        for package in generated_packages
        if isinstance(package, dict) and package.get("source") is not None
    }
    drift = generated_external - seed_external
    if drift:
        raise SystemExit(
            f"standalone lock introduced dependency drift: {sorted(drift)!r}"
        )

    roots = [
        package
        for package in generated_packages
        if isinstance(package, dict)
        and package.get("name") == "lane-f-shadow-qualification"
    ]
    if len(roots) != 1:
        raise SystemExit(f"expected one harness root package, found {len(roots)}")

    dependencies = roots[0].get("dependencies", [])
    if not isinstance(dependencies, list):
        raise SystemExit("harness dependency table is not a list")
    observed = {str(dependency).split(" ", 1)[0] for dependency in dependencies}
    if observed != EXPECTED_ROOT_DEPENDENCIES:
        raise SystemExit(
            "harness dependency set mismatch: "
            f"observed={observed!r} expected={EXPECTED_ROOT_DEPENDENCIES!r}"
        )

    print(
        "validated zero-drift lock refresh: "
        f"seed_packages={len(seed_packages)} "
        f"generated_packages={len(generated_packages)} "
        f"external_packages={len(generated_external)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
