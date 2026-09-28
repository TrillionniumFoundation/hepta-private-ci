#!/usr/bin/env python3
"""Stable entrypoint for intelligence.control generated source/test truth.

The retained generator owns the document schema and source assertions. This
entrypoint points those assertions at the active split implementation files and
normalizes their test paths back to the stable public module paths. New
closure-specific supervisor tests remain governed by the explicit,
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

# The public module files intentionally use include! wrappers. Source truth must
# inspect the active implementation bodies rather than accepting wrapper text or
# stale, uncompiled alternatives.
ACTIVE_SOURCE_FILES = {
    "runner": "codex-rs/hepta-agentd/src/intelligence_product_runner_base.rs",
    "product": "codex-rs/hepta-agentd/src/intelligence_product_base.rs",
    "learning": "codex-rs/hepta-agentd/src/intelligence_learning_base.rs",
    "state": "codex-rs/hepta-agentd/src/state_base.rs",
}
module.SOURCE_FILES.update(ACTIVE_SOURCE_FILES)
module.SOURCE_FILES["provider"] = (
    "codex-rs/hepta-agentd/src/intelligence_invocation_supervisor.rs"
)
module.EXPECTED_SOURCE_FACTS["concreteProviderPresent"] = (
    "provider",
    "impl<F> AgentdIntelligenceInvocationProviderV1",
)

original_discover_tests = module.discover_tests

ALIASES = {
    "codex-rs/hepta-agentd/src/intelligence_product_runner_base.rs":
        "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    "codex-rs/hepta-agentd/src/intelligence_product_base.rs":
        "codex-rs/hepta-agentd/src/intelligence_product.rs",
    "codex-rs/hepta-agentd/src/intelligence_learning_base.rs":
        "codex-rs/hepta-agentd/src/intelligence_learning.rs",
    "codex-rs/hepta-agentd/src/state_base.rs":
        "codex-rs/hepta-agentd/src/state.rs",
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
