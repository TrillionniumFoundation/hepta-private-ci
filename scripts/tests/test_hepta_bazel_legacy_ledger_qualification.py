"""Fail-closed regression for Bazel test-only legacy ledger qualification.

This checks the declaration surface. The actual generated Rust integration
target must still compile and run in GitHub Bazel CI; these assertions alone
are not proof of production admissibility or runtime correctness.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER_TEST_LABEL = (
    "//codex-rs/hepta-learning-ledger:"
    "hepta-learning-ledger-qualification-lib"
)


def qualifying_wiring(defs: str, agentd: str, ledger: str) -> bool:
    macro = defs.split("def codex_rust_crate(", 1)[-1]
    integration = macro.split(
        '    for test in native.glob(["tests/*.rs"], allow_empty = True):', 1
    )
    if len(integration) != 2:
        return False
    generated_tests = integration[1].split("def _test_shard_count(", 1)[0]

    return all(
        [
            "integration_test_dependency_replacements = {}" in macro,
            "integration_test_deps = rust_test_dependencies(" in integration[0],
            "integration_test_dependency_replacements," in integration[0],
            # Sharded native, unsharded native, and Windows-cross target.
            generated_tests.count("deps = integration_test_deps,") == 3,
            'integration_test_dependency_replacements = {' in agentd,
            LEDGER_TEST_LABEL in agentd,
            'unit_test_dependency_replacements = _UNIT_TEST_DEPENDENCIES' in agentd,
            # Normal product dependencies must not acquire the legacy feature.
            'deps = all_crate_deps() + maybe_deps + deps_extra,' in macro,
            'testonly = True' in ledger,
            'crate_features = ["qualification-legacy-write"]' in ledger,
        ]
    )


class BazelLegacyLedgerQualificationTests(unittest.TestCase):
    def setUp(self):
        self.defs = (ROOT / "defs.bzl").read_text(encoding="utf-8")
        self.agentd = (
            ROOT / "codex-rs/hepta-agentd/BUILD.bazel"
        ).read_text(encoding="utf-8")
        self.ledger = (
            ROOT / "codex-rs/hepta-learning-ledger/BUILD.bazel"
        ).read_text(encoding="utf-8")

    def test_qualification_is_available_only_to_generated_test_targets(self):
        self.assertTrue(qualifying_wiring(self.defs, self.agentd, self.ledger))

    def test_missing_generated_dependency_wiring_is_rejected(self):
        altered = self.defs.replace(
            "deps = integration_test_deps,",
            "deps = all_crate_deps(normal = True, normal_dev = True) + maybe_deps + deps_extra,",
        )
        self.assertFalse(qualifying_wiring(altered, self.agentd, self.ledger))

    def test_missing_testonly_qualification_label_is_rejected(self):
        altered = self.agentd.replace(LEDGER_TEST_LABEL, "//codex-rs/hepta-learning-ledger")
        self.assertFalse(qualifying_wiring(self.defs, altered, self.ledger))


if __name__ == "__main__":
    unittest.main()
