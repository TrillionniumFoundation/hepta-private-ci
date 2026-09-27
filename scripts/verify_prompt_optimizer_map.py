#!/usr/bin/env python3
"""Closed-world source check for prompt.optimizer's implementation map."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRATE = ROOT / "codex-rs" / "hepta-prompt-optimizer" / "src"
MAP = ROOT / "docs" / "modules" / "prompt.optimizer" / "IMPLEMENTATION_MAP.json"

CANONICAL_OPERATIONS = (
    "enumerate_factors_v1",
    "price_factors_v1",
    "select_portfolio_v1",
    "exercise_v1",
)
DEAD_POLICY_FILES = (
    "policy.rs",
    "policy_contracts.rs",
    "policy_digest.rs",
    "policy_enumeration_pricing.rs",
    "policy_exercise_helpers.rs",
    "policy_portfolio.rs",
    "policy_portfolio_helpers.rs",
)


def fail(message: str) -> None:
    raise SystemExit(f"prompt.optimizer implementation-map check failed: {message}")


def source_has_function(source: str, name: str) -> bool:
    return re.search(rf"\bpub\s+fn\s+{re.escape(name)}\s*\(", source) is not None


def source_has_test(name: str) -> bool:
    needle = re.compile(rf"\bfn\s+{re.escape(name)}\s*\(")
    return any(
        needle.search(path.read_text(encoding="utf-8"))
        for path in CRATE.glob("*tests.rs")
    )


def main() -> int:
    data = json.loads(MAP.read_text(encoding="utf-8"))
    crate_root = (CRATE / "lib.rs").read_text(encoding="utf-8")
    canonical_root = (CRATE / "canonical.rs").read_text(encoding="utf-8")

    if "pub mod canonical;" not in crate_root or "pub mod compat;" not in crate_root:
        fail("crate root must expose canonical and compat modules")
    if data.get("productionImplementation") is not False:
        fail("productionImplementation must remain false before exact product evidence")
    surface = data.get("canonicalSurface", {})
    if not surface.get("uniqueActivePipeline"):
        fail("canonicalSurface.uniqueActivePipeline must be true")
    if not surface.get("verifiedTypeStateRequired"):
        fail("canonicalSurface.verifiedTypeStateRequired must be true")
    for required_module in (
        "canonical_raw.rs",
        "canonical_verified.rs",
        "canonical_solver.rs",
        "canonical_runtime.rs",
    ):
        if required_module not in canonical_root:
            fail(f"canonical module tree does not include {required_module}")

    for filename in DEAD_POLICY_FILES:
        if (CRATE / filename).exists():
            fail(f"dead policy implementation remains in tree: {filename}")

    mapped = {entry["operation"]: entry for entry in data.get("operations", [])}
    if set(mapped) != set(CANONICAL_OPERATIONS):
        fail(f"canonical operation inventory mismatch: {sorted(mapped)}")

    for operation in CANONICAL_OPERATIONS:
        entry = mapped[operation]
        source_path = ROOT / entry["sourcePath"]
        if not source_path.is_file():
            fail(f"mapped source is missing for {operation}: {source_path}")
        source = source_path.read_text(encoding="utf-8")
        if not source_has_function(source, operation):
            fail(f"mapped source does not define {operation}")
        tests = entry.get("tests")
        if not tests:
            fail(f"{operation} has no mapped test identity")
        for test in tests:
            if not source_has_test(test):
                fail(f"mapped test is not present: {test}")

    forbidden_raw_exports = (
        "pub use raw::enumerate_factors_v1",
        "pub use raw::price_factors_v1",
        "pub use raw::select_portfolio_v1",
        "pub use raw::exercise_v1",
    )
    for forbidden in forbidden_raw_exports:
        if forbidden in canonical_root:
            fail(f"raw product operation is publicly re-exported: {forbidden}")

    compat = (CRATE / "compat.rs").read_text(encoding="utf-8")
    for symbol in ("optimize", "optimize_with_factor_graph", "local_shadow"):
        if symbol not in compat:
            fail(f"compatibility surface is missing {symbol}")

    print("prompt.optimizer implementation map matches the sealed source tree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
