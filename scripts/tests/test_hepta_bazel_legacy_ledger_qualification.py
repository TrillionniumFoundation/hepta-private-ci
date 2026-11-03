"""Fail-closed checks for Bazel product-ledger and historical test-only wiring.

These assertions cover source wiring only. Real Bazel compile, signed admission,
witness durability and Agentd process replay remain mandatory separate checks.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER_TEST_LABEL = (
    "//codex-rs/hepta-learning-ledger:hepta-learning-ledger-qualification-lib"
)


def qualifying_wiring(defs: str, agentd: str, ledger: str, fixture: str) -> bool:
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
            # No test-only raw-append dependency replacement is permitted for
            # the Agentd fixture now that it shares product types and receipts.
            "integration_test_dependency_replacements" not in agentd,
            '"terminal_cell_owner": {' not in agentd,
            '"intuition_policy_product": {' not in agentd,
            "unit_test_dependency_replacements = _UNIT_TEST_DEPENDENCIES" in agentd,
            LEDGER_TEST_LABEL in agentd,
            "deps = all_crate_deps() + maybe_deps + deps_extra," in macro,
            # Historical ledger qualification remains private to tests.
            "testonly = True" in ledger,
            'crate_features = ["qualification-legacy-write"]' in ledger,
            # The cross-process fixture must use the real signed product writer
            # and independently witnessed durable source, not raw append.
            "LedgerWriter::from_durable(" in fixture,
            "LedgerWitnessStore::create(" in fixture,
            "activate_learning_trust(" in fixture,
            "decision_signing_payload_v2(" in fixture,
            "writer.append_decision(" in fixture,
            "drop(writer);" in fixture,
            "append_qualification" not in fixture,
            "LedgerEvent::Decision(" not in fixture,
            # A record's event digest is distinct from its chain-head digest.
            "source_record_digests: vec![source_event_digest]" in fixture,
            ".event_digest;" in fixture,
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
        self.fixture = (
            ROOT / "codex-rs/hepta-agentd/tests/plasticity_process_e2e.rs"
        ).read_text(encoding="utf-8")

    def check(self, *, defs=None, agentd=None, ledger=None, fixture=None):
        return qualifying_wiring(
            self.defs if defs is None else defs,
            self.agentd if agentd is None else agentd,
            self.ledger if ledger is None else ledger,
            self.fixture if fixture is None else fixture,
        )

    def test_product_fixture_uses_signed_witnessed_ledger(self):
        self.assertTrue(self.check())

    def test_global_dependency_replacement_is_rejected(self):
        altered = self.defs.replace(
            "integration_test_dependency_replacements.get(test_file_stem, {})",
            'integration_test_dependency_replacements.get("plasticity_process_e2e", {})',
        )
        self.assertFalse(self.check(defs=altered))

    def test_test_only_qualification_retarget_is_rejected(self):
        altered = self.agentd.replace(
            "unit_test_dependency_replacements = _UNIT_TEST_DEPENDENCIES,",
            (
                "integration_test_dependency_replacements = {"
                '"terminal_cell_owner": {"//codex-rs/hepta-learning-ledger": '
                '"//codex-rs/hepta-learning-ledger:hepta-learning-ledger-qualification-lib"}},\n'
                "    unit_test_dependency_replacements = _UNIT_TEST_DEPENDENCIES,"
            ),
        )
        self.assertNotEqual(altered, self.agentd)
        self.assertFalse(self.check(agentd=altered))

    def test_unmapped_default_test_dependency_is_required(self):
        altered = self.defs.replace(
            "deps = integration_test_deps,",
            "deps = all_crate_deps(normal = True, normal_dev = True) + maybe_deps + deps_extra,",
        )
        self.assertFalse(self.check(defs=altered))

    def test_non_testonly_qualification_target_is_rejected(self):
        altered = self.ledger.replace("testonly = True", "testonly = False")
        self.assertNotEqual(altered, self.ledger)
        self.assertFalse(self.check(ledger=altered))

    def test_legacy_test_dependency_reintroduced_is_rejected(self):
        altered = self.agentd.replace(
            "unit_test_dependency_replacements = _UNIT_TEST_DEPENDENCIES,",
            (
                "integration_test_dependency_replacements = {"
                '"plasticity_process_e2e": {"//codex-rs/hepta-learning-ledger": '
                '"//codex-rs/hepta-learning-ledger:hepta-learning-ledger-qualification-lib"}},\n'
                "    unit_test_dependency_replacements = _UNIT_TEST_DEPENDENCIES,"
            ),
        )
        self.assertFalse(self.check(agentd=altered))

    def test_unsigned_raw_fixture_write_is_rejected(self):
        altered = self.fixture.replace(
            "writer.append_decision(", "ledger.append_qualification("
        )
        self.assertNotEqual(altered, self.fixture)
        self.assertFalse(self.check(fixture=altered))

    def test_missing_independent_witness_is_rejected(self):
        altered = self.fixture.replace(
            "LedgerWitnessStore::create(", "FixtureLedger::create("
        )
        self.assertFalse(self.check(fixture=altered))

    def test_missing_root_authenticated_trust_is_rejected(self):
        altered = self.fixture.replace(
            "activate_learning_trust(", "local_unverified_trust("
        )
        self.assertFalse(self.check(fixture=altered))

    def test_chain_head_misused_as_source_event_is_rejected(self):
        altered = self.fixture.replace(
            "source_record_digests: vec![source_event_digest]",
            "source_record_digests: vec![ledger_head]",
        )
        self.assertFalse(self.check(fixture=altered))

    def test_missing_writer_release_before_child_is_rejected(self):
        altered = self.fixture.replace("drop(writer);", "drop(ledger);")
        self.assertFalse(self.check(fixture=altered))


if __name__ == "__main__":
    unittest.main()
