from __future__ import annotations

import re
import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUST_TEST = ROOT / "codex-rs/hepta-infer-core/src/semantic_control_tests.rs"
MAINTENANCE_WORKFLOW = ROOT / ".github/workflows/hepta-inference-maintenance.yml"
ARCHITECTURE_WORKFLOW = ROOT / ".github/workflows/hepta-architecture-convergence.yml"
LEGACY_COMPAT_TEST = ROOT / "codex-rs/hepta-infer-core/tests/retained_history_maintenance.rs"


class InferenceMaintenanceWorkflowTests(unittest.TestCase):
    def test_retained_history_filters_select_real_ignored_tests(self) -> None:
        current_symbol = "semantic_journal_retained_history_curve"
        rust_source = RUST_TEST.read_text(encoding="utf-8")
        self.assertRegex(rust_source, rf"fn\s+{re.escape(current_symbol)}\s*\(")

        maintenance = MAINTENANCE_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(current_symbol, maintenance)
        self.assertNotIn("post_compaction_multi_generation_curve", maintenance)
        self.assertIn("--minimum-tests 1", maintenance)
        self.assertIn("-- --ignored", maintenance)

        compatibility_symbol = "post_compaction_multi_generation_curve"
        architecture = ARCHITECTURE_WORKFLOW.read_text(encoding="utf-8")
        compatibility = LEGACY_COMPAT_TEST.read_text(encoding="utf-8")
        if current_symbol not in architecture:
            self.assertIn(compatibility_symbol, architecture)
            self.assertRegex(
                compatibility,
                rf"fn\s+{re.escape(compatibility_symbol)}\s*\(",
            )
            self.assertIn("compaction_performed\": false", compatibility)
            self.assertIn("legacy_filter_compatibility\": true", compatibility)
        self.assertIn("--minimum-tests 1", architecture)
        self.assertIn("--run-ignored only", architecture)


class ArchitectureExecutionTests(unittest.TestCase):
    def block(self):
        source = ARCHITECTURE_WORKFLOW.read_text(encoding="utf-8")
        block = source.split("      - name: Inference owner regressions and streaming digest\n", 1)[1]
        return textwrap.dedent(block.split("      - name:", 1)[0].split("        run: |\n", 1)[1])

    def test_inference_selectors_have_real_tests_and_no_multiwriter_claim(self):
        block = self.block()
        self.assertNotIn("history_growth_emits_update_recovery_memory_and_disk_curve", block)
        self.assertNotIn("alternating_writers_replay_only_peer_deltas", block)
        for symbol, path in (
            ("semantic_journal_retained_history_curve", RUST_TEST),
            ("exclusive_owner_turnover_retains_unknown_and_completed_work", LEGACY_COMPAT_TEST),
            ("post_compaction_multi_generation_curve", LEGACY_COMPAT_TEST),
        ):
            self.assertIn(symbol, block)
            self.assertRegex(path.read_text(), rf"fn\s+{symbol}\s*\(")
        self.assertNotIn("cargo test", block)
        self.assertEqual(block.count("--minimum-tests 1 -- just test --locked --retries 0"), 4)
        self.assertEqual(block.count("--run-ignored only"), 3)

    def test_selector_evaluator_gate_selects_an_executable_signature_test(self):
        symbol = "selector_role_is_explicit_and_independent_from_evaluator"
        self.assertIn(symbol, ARCHITECTURE_WORKFLOW.read_text())
        source = (ROOT / "codex-rs/hepta-learning-ledger/src/signed_evidence_tests.rs").read_text()
        self.assertRegex(source, rf"fn\s+{symbol}\s*\(")
        self.assertIn("ControllerCollision", source)

    def test_each_command_runs_but_any_failed_command_fails_the_step(self):
        # Exercise the actual shell, substituting only the external test runner.
        # These are shell contracts, not observations of Rust test execution.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "python3"
            executable.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$TRACE\"\n"
                                  "case \"$*\" in *\"$FAIL_RECORD\"*) exit 9;; esac\nexit 0\n")
            executable.chmod(0o700)
            for record in ["never-fail", "inference.json", "inference-scale.json",
                           "inference-owner-turnover.json", "inference-maintenance-scale.json"]:
                with self.subTest(record=record):
                    trace = root / "calls"
                    trace.unlink(missing_ok=True)
                    env = dict(os.environ, TRACE=str(trace), FAIL_RECORD=record,
                               RUNNER_TEMP=directory, PATH=directory + os.pathsep + os.environ["PATH"])
                    observed = subprocess.run(["bash", "-c", self.block()], env=env,
                                              capture_output=True, text=True, timeout=10)
                    self.assertEqual(observed.returncode, 0 if record == "never-fail" else 1,
                                     observed.stderr)
                    self.assertEqual(len(trace.read_text().splitlines()), 4)


if __name__ == "__main__":
    unittest.main()
