"""Regression tests for the direct local input / native workflow trigger gate."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/check_neuron_qualification_triggers.py"
spec = importlib.util.spec_from_file_location("neuron_qualification_triggers", SCRIPT)
assert spec is not None and spec.loader is not None
coverage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coverage)


class NeuronQualificationTriggerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = (ROOT / coverage.WORKFLOW).read_text(encoding="utf-8")

    def test_exact_workflow_covers_direct_owner_dependencies_and_policies(self) -> None:
        self.assertEqual(coverage.missing_trigger_paths(ROOT, self.workflow), [])

    def test_omitted_local_worker_dependency_is_detected(self) -> None:
        missing_rule = '      - "codex-rs/app-server-client/**"\n'
        self.assertEqual(self.workflow.count(missing_rule), 1)
        changed = self.workflow.replace(missing_rule, "", 1)
        self.assertIn(
            "codex-rs/app-server-client/**",
            coverage.missing_trigger_paths(ROOT, changed),
        )

    def test_omitted_validation_policy_is_detected(self) -> None:
        missing_rule = '      - "codex-rs/rustfmt.toml"\n'
        self.assertEqual(self.workflow.count(missing_rule), 1)
        changed = self.workflow.replace(missing_rule, "", 1)
        self.assertIn(
            "codex-rs/rustfmt.toml",
            coverage.missing_trigger_paths(ROOT, changed),
        )

    def test_duplicate_or_negated_filter_fails_closed(self) -> None:
        rule = '      - "codex-rs/Cargo.toml"\n'
        self.assertEqual(self.workflow.count(rule), 1)
        with self.assertRaises(ValueError):
            coverage.workflow_path_rules(self.workflow.replace(rule, rule * 2, 1))
        with self.assertRaises(ValueError):
            coverage.workflow_path_rules(
                self.workflow.replace(rule, '      - "!codex-rs/Cargo.toml"\n', 1)
            )


if __name__ == "__main__":
    unittest.main()
