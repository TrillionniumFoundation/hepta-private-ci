"""Source wiring regressions; not substitutes for executing CI or real models."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
MAINTENANCE = ROOT / ".github/workflows/hepta-inference-maintenance.yml"
MULTISCALE = ROOT / ".github/workflows/hepta-multiscale-regressions.yml"


def step(text: str, name: str) -> str:
    match = re.search(r"^      - name: " + re.escape(name) + r"\n(?:(?!^      - ).*\n)*",
                      text, re.MULTILINE)
    if not match:
        raise AssertionError(f"missing step: {name}")
    return match.group()


class MultiscaleCiTests(unittest.TestCase):
    def setUp(self):
        self.maintenance = MAINTENANCE.read_text()
        self.multiscale = MULTISCALE.read_text()

    def test_maintenance_executes_both_exact_candidates_without_same_tree_skip(self):
        self.assertIn('["source-head","base-merge"]', self.maintenance)
        self.assertNotIn("steps.execution.outputs.run_native", self.maintenance)
        for name in ("Run actual owner tests without unrelated product prerequisites",
                     "Measure retained-history growth and durable replay",
                     "Check strict owner lint",
                     "Check owner formatting without modifying tested source"):
            self.assertNotIn("        if:", step(self.maintenance, name))

    def test_owner_tests_use_repository_entrypoint_and_nonzero_test_floor(self):
        command = step(self.maintenance, "Run actual owner tests without unrelated product prerequisites")
        self.assertIn("--minimum-tests 112 -- just test --locked", command)
        self.assertIn("-p codex-hepta-infer-core -p codex-hepta-types", command)
        self.assertIn("--retries 0", command)
        self.assertNotIn("-- cargo test", self.maintenance)
        self.assertNotIn("continue-on-error", self.maintenance)

    def test_growth_selects_an_existing_ignored_test_not_an_empty_filter(self):
        command = step(self.maintenance, "Measure retained-history growth and durable replay")
        self.assertIn("--minimum-tests 1 -- just test", command)
        self.assertIn("--run-ignored only", command)
        self.assertIn("test(semantic_journal_retained_history_curve)", command)
        source = (ROOT / "codex-rs/hepta-infer-core/src/semantic_control_tests.rs").read_text()
        self.assertIn("fn semantic_journal_retained_history_curve()", source)
        self.assertNotIn("post_compaction_multi_generation_curve", command)

    def test_strict_lint_and_nonmutating_format_remain_gates(self):
        lint = step(self.maintenance, "Check strict owner lint")
        self.assertIn("cargo clippy --locked", lint)
        self.assertIn("--all-targets -- -D warnings", lint)
        formatting = step(self.maintenance, "Check owner formatting without modifying tested source")
        self.assertIn("cargo fmt", formatting)
        self.assertIn("-- --check", formatting)
        self.assertNotIn("--fix", lint)

    def test_real_process_suite_is_run_and_records_are_retained(self):
        tests = step(self.multiscale, "Bind identity and test without model weights")
        self.assertIn("--minimum-tests 27 -- python3 -m unittest -v scripts.tests.test_hepta_laya_process", tests)
        self.assertIn("--minimum-tests 9 -- python3 -m unittest -v scripts.tests.test_hepta_multiscale_ci", tests)
        records = step(self.multiscale, "Retain protocol execution records")
        self.assertIn("${{ runner.temp }}/laya-process.*", records)
        self.assertIn("${{ runner.temp }}/multiscale-ci.*", records)
        self.assertIn("if-no-files-found: error", records)

    def test_maintenance_process_changes_are_in_both_trigger_path_sets(self):
        for path in ("scripts/hepta_laya*", "scripts/tests/test_hepta_laya*",
                     "scripts/tests/test_hepta_multiscale_ci.py"):
            self.assertEqual(self.maintenance.count(f"      - '{path}'"), 2)
        tests = step(self.maintenance, "Run real subprocess and binary-protocol regressions")
        self.assertIn("--minimum-tests 64", tests)
        self.assertIn("scripts.tests.test_hepta_laya_process", tests)

    def test_generation_recovery_executes_real_worker_unit_tests(self):
        command = step(self.multiscale, "Semantic worker generation recovery")
        self.assertIn("--minimum-tests 4 -- just test --locked", command)
        self.assertIn("-p codex-hepta-infer-worker-host --lib model_worker::semantic_worker::tests", command)
        self.assertIn("worker-generation-recovery.json", command)
        self.assertIn("if: always() && steps.scope.outputs.inference == 'true'", command)
        source = ROOT / "codex-rs/hepta-infer-worker-host/src/semantic_worker.rs"
        tests = source.with_name("semantic_worker_tests.rs").read_text()
        self.assertIn('#[path = "semantic_worker_tests.rs"]', source.read_text())
        self.assertEqual(len(re.findall(r"#\[test\]", tests)), 4)
        records = step(self.multiscale, "Retain worker execution records")
        self.assertIn("${{ runner.temp }}/worker-*", records)

    def test_repository_toolchain_and_test_tools_are_explicit(self):
        toolchain = step(self.maintenance, "Install repository-pinned Rust toolchain")
        config = (ROOT / "codex-rs/rust-toolchain.toml").read_text()
        channel = re.search(r'^channel = "([^"]+)"', config, re.MULTILINE).group(1)
        self.assertIn(f'toolchain: "{channel}"', toolchain)
        self.assertIn("components: clippy,rustfmt", toolchain)
        tools = step(self.maintenance, "Install existing repository test entry point")
        self.assertIn("just@1.51.0,nextest@0.9.103", tools)

    def test_no_candidate_mutation_or_credentials_and_both_parents_checked(self):
        for text in (self.maintenance, self.multiscale):
            self.assertIn("permissions:\n  contents: read", text)
            self.assertNotIn("contents: write", text)
            self.assertIn("persist-credentials: false", text)
            self.assertNotIn("git push", text)
        identity = step(self.maintenance, "Verify GitHub prospective merge identity")
        self.assertIn('test "${parents[0]}" = "$BASE_SHA"', identity)
        self.assertIn('test "${parents[1]}" = "$SOURCE_SHA"', identity)
        clean = step(self.maintenance, "Verify the tested source is unchanged")
        self.assertIn("if: always()", clean)
        self.assertIn("git diff --exit-code", clean)
        self.assertIn("git diff --cached --exit-code", clean)


if __name__ == "__main__":
    unittest.main()
