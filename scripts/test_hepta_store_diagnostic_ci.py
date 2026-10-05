"""Bound the opt-in diagnostic lane without relaxing normal qualification."""

import json
import tempfile
import unittest

from hepta_store_diagnostic_ci import diagnostic_options
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class StoreDiagnosticWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = yaml.load(
            (ROOT / ".github/workflows/hepta-cognitive-store-native.yml").read_text(),
            Loader=yaml.BaseLoader,
        )
        cls.steps = cls.workflow["jobs"]["cognitive-owners"]["steps"]
        cls.by_name = {step.get("name"): step for step in cls.steps}

    def test_repository_options_are_explicit_and_reuse_candidate_binding(self):
        self.assertNotIn("workflow_dispatch", self.workflow["on"])
        for step in self.steps:
            if step.get("id", "") in (
                "diagnostic_strict",
                "diagnostic_counters",
                "diagnostic_example",
            ):
                self.assertIn("always()", step["if"])
                self.assertIn(
                    "steps.diagnostic_options.outputs.feature == 'true'", step["if"]
                )
                self.assertIn("steps.candidate.outcome == 'success'", step["if"])
                self.assertIn("steps.native_ready.outcome == 'success'", step["if"])
                self.assertNotIn("continue-on-error", step)
                self.assertIn("hepta_ci_exec.py", step["run"])

    def test_focused_tests_require_real_terminal_counts(self):
        counters = self.by_name["Test bounded diagnostic counters and cancellation"][
            "run"
        ]
        example = self.by_name["Test diagnostic identity and output isolation"]["run"]
        self.assertIn("--minimum-tests 3", counters)
        self.assertIn("--no-tests fail", counters)
        self.assertIn("cognitive_perf_observation::tests::", counters)
        self.assertIn("--minimum-tests 2", example)
        self.assertIn("observation_tests::", example)
        self.assertIn("--features cognitive-perf-observe", counters)
        self.assertIn("--features cognitive-perf-observe", example)

    def test_maximum_diagnostic_cannot_replace_normal_metrics(self):
        normal = self.by_name["Measure cognitive maximum-retained profile"]
        diagnostic = self.by_name[
            "Observe maximum-retained diagnostic phases (not qualification)"
        ]
        for step in (normal, diagnostic):
            self.assertEqual(step["env"]["HEPTA_COGNITIVE_PERF_RECORDS"], "16384")
            self.assertIn("--timeout-seconds 1200", step["run"])
        self.assertNotIn("--features cognitive-perf-observe", normal["run"])
        self.assertIn("HEPTA_COGNITIVE_PERF_OUTPUT", normal["env"])
        self.assertNotIn("HEPTA_COGNITIVE_PERF_OUTPUT", diagnostic["env"])
        self.assertIn("HEPTA_COGNITIVE_PERF_DIAGNOSTIC_OUTPUT", diagnostic["env"])
        for gate in ("diagnostic_strict", "diagnostic_counters", "diagnostic_example"):
            self.assertIn(f"steps.{gate}.outcome == 'success'", diagnostic["if"])
        self.assertLess(self.steps.index(diagnostic), self.steps.index(normal))
        artifact = self.by_name["Retain real command records and measured profiles"]
        self.assertEqual(artifact["if"], "always()")
        self.assertTrue(artifact["with"]["path"].endswith("/hepta-command-records/*"))


class DiagnosticOptionsTests(unittest.TestCase):
    def test_missing_configuration_is_disabled(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(
                diagnostic_options(Path(folder) / "missing"),
                {"feature": False, "maximum": False},
            )

    def test_explicit_booleans_and_invalid_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "options.json"
            for value in (
                {"feature": True, "maximum": True},
                {"feature": True, "maximum": False},
                {"feature": False, "maximum": False},
            ):
                path.write_text(json.dumps(value))
                self.assertEqual(diagnostic_options(path), value)
            for value in (
                {"feature": "true", "maximum": False},
                {"feature": 1, "maximum": False},
                {"feature": False, "maximum": True},
                {},
                [],
                {"feature": True, "maximum": False, "extra": True},
            ):
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    diagnostic_options(path)
            path.write_text('{"feature": false, "feature": true, "maximum": false}')
            with self.assertRaises(ValueError):
                diagnostic_options(path)
            path.write_text("{" * 1025)
            with self.assertRaises(ValueError):
                diagnostic_options(path)


if __name__ == "__main__":
    unittest.main()
