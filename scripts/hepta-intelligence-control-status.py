#!/usr/bin/env python3
"""Stable entrypoint for intelligence.control generated source/test truth.

The retained generator owns the document schema and source assertions. This
entrypoint normalizes only additive implementation-file splits so a reviewed
logical test keeps its historical source path in the broad inventory. New
closure-specific supervisor tests are intentionally governed by the explicit,
human-reviewed REQUIREMENT_TEST_MAP instead of being inferred into the broad
name-based inventory.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMPLEMENTATION = HERE / "hepta-intelligence-control-status-base.py"

spec = importlib.util.spec_from_file_location(
    "_hepta_intelligence_control_status_base", IMPLEMENTATION
)
if spec is None or spec.loader is None:
    raise SystemExit("cannot load retained intelligence.control status generator")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

original_discover_tests = module.discover_tests

ALIASES = {
    "codex-rs/hepta-agentd/src/intelligence_ingress_base.rs":
        "codex-rs/hepta-agentd/src/intelligence_ingress.rs",
    "codex-rs/hepta-infer-worker-host/src/canonical_intelligence_product_loop_base.rs":
        "codex-rs/hepta-infer-worker-host/src/canonical_intelligence_product_loop.rs",
}
CLOSURE_ONLY_FILES = {
    "codex-rs/hepta-agentd/src/intelligence_invocation_supervisor.rs",
    "codex-rs/hepta-infer-worker-host/src/canonical_intelligence_owner_supervisor.rs",
}


def discover_tests():
    tests = []
    for test in original_discover_tests():
        source = test["sourcePath"]
        if source in CLOSURE_ONLY_FILES:
            continue
        normalized = dict(test)
        normalized["sourcePath"] = ALIASES.get(source, source)
        tests.append(normalized)
    tests.sort(key=lambda value: (value["sourcePath"], value["name"]))
    return tests


module.discover_tests = discover_tests
module.main()
