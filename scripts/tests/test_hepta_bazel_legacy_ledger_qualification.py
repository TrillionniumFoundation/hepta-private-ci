"""Fail-closed checks for narrowly scoped Bazel legacy-ledger test fixtures.

These are static wiring regressions, not a substitute for native Bazel
compilation or full production/runtime qualification.
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
            "integration_test_deps = rust_test_dependencies(" in generated_tests,
            "integration_test_dependency_replacements.get(test_file_stem, {})"
            in generated_tests,
            generated_tests.count("deps = integration_test_deps,") == 3,
            '"plasticity_process_e2e": {' in agentd,
            '"terminal_cell_owner": {' not in agentd,
            '"intuition_policy_product": {' not in agentd,
            LEDGER_TEST_LABEL in agentd,
            "unit_test_dependency_replacements = _UNIT_TEST_DEPENDENCIES" in agentd,
            "deps = all_crate_deps() + maybe_deps + deps_extra," in macro,
            "testonly = True" in ledger,
            'crate_features = ["qualification-legacy-write"]' in ledger,
        ]
    )


class BazelLegacyLedgerQualificationTests(unittest.TestCase):
    def setUp(self):
        self.defs = (ROOT / "defs.bzl").read_text(encoding="utf-8")
        self.agentd = (ROOT / "codex-rs/hepta-agentd/BUILD.bazel").read_text(
            encoding="utf-8"
        )
        self.ledger = (ROOT / "codex-rs/hepta-learning-ledger/BUILD.bazel").read_text(
            encoding="utf-8"
        )

    def test_only_serialized_fixture_receives_legacy_feature(self):
        self.assertTrue(qualifying_wiring(self.defs, self.agentd, self.ledger))

    def test_global_dependency_replacement_is_rejected(self):
        altered = self.defs.replace(
            "integration_test_dependency_replacements.get(test_file_stem, {})",
            'integration_test_dependency_replacements.get("plasticity_process_e2e", {})',
        )
        self.assertFalse(qualifying_wiring(altered, self.agentd, self.ledger))

    def test_retarget_to_type_sharing_test_is_rejected(self):
        altered = self.agentd.replace(
            '"plasticity_process_e2e": {', '"terminal_cell_owner": {'
        )
        self.assertFalse(qualifying_wiring(self.defs, altered, self.ledger))

    def test_unmapped_default_test_dependency_is_required(self):
        altered = self.defs.replace(
            "deps = integration_test_deps,",
            "deps = all_crate_deps(normal = True, normal_dev = True) + maybe_deps + deps_extra,",
        )
        self.assertFalse(qualifying_wiring(altered, self.agentd, self.ledger))

    def test_non_testonly_qualification_target_is_rejected(self):
        altered = self.agentd.replace(
            LEDGER_TEST_LABEL, "//codex-rs/hepta-learning-ledger"
        )
        self.assertFalse(qualifying_wiring(self.defs, altered, self.ledger))


if __name__ == "__main__":
    unittest.main()
