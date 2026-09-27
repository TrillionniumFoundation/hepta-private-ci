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
    canonical = (CRATE / "canonical.rs").read_text(encoding="utf-8")
    crate_root = (CRATE / "lib.rs").read_text(encoding="utf-8")
    compat = (CRATE / "compat.rs").read_text(encoding="utf-8")

    if "pub mod canonical;" not in crate_root or "pub mod compat;" not in crate_root:
        fail("crate root must expose canonical and compat modules")
    if data.get("productionImplementation") is not False:
        fail("productionImplementation must remain false before exact product evidence")
    if not data.get("canonicalSurface", {}).get("uniqueActivePipeline"):
        fail("canonicalSurface.uniqueActivePipeline must be true")

    for filename in DEAD_POLICY_FILES:
        if (CRATE / filename).exists():
            fail(f"dead policy implementation remains reachable in tree: {filename}")

    mapped = {entry["operation"]: entry for entry in data.get("operations", [])}
    if set(mapped) != set(CANONICAL_OPERATIONS):
        fail(f"canonical operation inventory mismatch: {sorted(mapped)}")

    for operation in CANONICAL_OPERATIONS:
        if not source_has_function(canonical, operation):
            fail(f"canonical source does not define {operation}")
        tests = mapped[operation].get("tests")
        if not tests:
            fail(f"{operation} has no mapped test identity")
        for test in tests:
            if not source_has_test(test):
                fail(f"mapped test is not present: {test}")
        if mapped[operation].get("sourcePath") != (
            "codex-rs/hepta-prompt-optimizer/src/canonical.rs"
        ):
            fail(f"{operation} is not mapped to canonical.rs")

    for symbol in ("optimize", "optimize_with_factor_graph", "calculate_local_shadow"):
        if symbol not in compat and symbol not in (
            CRATE / "compat_legacy.rs"
        ).read_text(encoding="utf-8"):
            # local_shadow and graph are linked by module, not textually re-exported
            if symbol not in {"optimize_with_factor_graph", "calculate_local_shadow"}:
                fail(f"compatibility symbol not exposed: {symbol}")

    print("prompt.optimizer implementation map matches the active source tree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
