"""Regression checks for the product prerequisite, independent of PyYAML."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/hepta-gap-agentd-process.yml"


class WiringTests(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text()
        self.process = self.text.split("  process-qualification:\n", 1)[1].split("\n  qualification-result:", 1)[0]

    def test_build_precedes_product_boundary_libraries(self):
        build = self.process.index("scripts/hepta_agentd_product_prerequisite.py")
        self.assertLess(self.process.index("scripts/hepta_ci_v8.py"), build)
        self.assertLess(build, self.process.index("just test --locked --lib"))
        self.assertIn('--expected-sha "$EXPECTED_SHA"', self.process)
        self.assertIn('--target-dir "$CARGO_TARGET_DIR"', self.process)

    def test_independent_suites_do_not_hide_peer_failures(self):
        suites = self.process.split("      - name: Exercise ")[1:]
        self.assertEqual(len(suites), 4)
        for suite in suites:
            self.assertIn("!cancelled() && steps.product_binary.outcome == 'success'", suite)
        self.assertNotIn("continue-on-error:", self.text)
        self.assertNotIn("|| true", self.text)

    def test_retains_default_and_feature_specific_tests(self):
        self.assertIn("--features qualification-cognitive-write", self.process)
        self.assertIn("-p codex-hepta-supervisor --test-threads=1", self.process)
        self.assertIn("--test supervisord_product_e2e", self.process)
        self.assertIn("cargo clippy --locked", self.process)
        self.assertIn("-- -D warnings", self.process)

    def test_trigger_includes_prerequisite_and_supervisor_inputs(self):
        paths = self.text.split("    paths:\n", 1)[1].split("\npermissions:", 1)[0]
        for path in ("codex-rs/hepta-supervisor/**", "docs/modules/runtime.supervisor/**",
                     "codex-rs/Cargo.lock", "codex-rs/Cargo.toml",
                     "codex-rs/rust-toolchain.toml", "codex-rs/hepta-matrixd/**",
                     "scripts/hepta_agentd_product_prerequisite.py",
                     "scripts/test_hepta_agentd_product_prerequisite.py",
                     "scripts/test_hepta_agentd_prerequisite_wiring.py"):
            self.assertIn("      - " + path + "\n", paths)

    def test_result_is_always_evaluated_and_evidence_retained(self):
        aggregate = self.text.split("\n  qualification-result:\n", 1)[1]
        self.assertIn("if: ${{ always() }}", aggregate)
        self.assertIn("process-qualification]", aggregate)
        self.assertIn("scripts/check_ci_results.py", aggregate)
        self.assertIn("if-no-files-found: error", self.process)
        self.assertIn("agentd-prerequisite-${{ github.run_id }}-${{ github.run_attempt }}-${{ matrix.os }}-${{ matrix.lane }}", self.process)


if __name__ == "__main__":
    unittest.main()
