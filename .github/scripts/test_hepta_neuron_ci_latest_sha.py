"""Guard PR-local diagnostic GitHub Actions concurrency semantics."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = (
    "hepta-neuron-model-trials.yml",
    "hepta-neuron-native-ledger-source.yml",
    "hepta-neuron-native-local-baseline.yml",
    "hepta-neuron-native-replay-source.yml",
    "hepta-neuron-native-supervisor-selection.yml",
    "hepta-neuron-native-worker-port.yml",
)
GROUP = "  group: hepta-neuron-${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}"
ONLY_PR = "  cancel-in-progress: ${{ github.event_name == 'pull_request' }}"


class LatestShaWorkflowTests(unittest.TestCase):
    def test_diagnostic_ci_keeps_only_latest_pr_revision(self):
        for name in FILES:
            with self.subTest(workflow=name):
                source = (ROOT / ".github" / "workflows" / name).read_text()
                self.assertEqual(source.count("\nconcurrency:\n"), 1)
                self.assertEqual(source.count(GROUP), 1)
                self.assertEqual(source.count(ONLY_PR), 1)
                self.assertLess(
                    source.index("\nconcurrency:\n"), source.index("\npermissions:\n")
                )
                self.assertIn("\n  pull_request:\n", source)
                self.assertIn("\n  workflow_dispatch:\n", source)
                self.assertIn("\npermissions:\n  contents: read\n", source)
                self.assertNotIn("cancel-in-progress: true", source)

    def test_operator_physical_measurement_workflows_not_cancelled(self):
        for name in ("hepta-neuron-physical-smoke.yml", "hepta-neuron-matched-cpu.yml"):
            with self.subTest(workflow=name):
                source = (ROOT / ".github" / "workflows" / name).read_text()
                self.assertNotIn("cancel-in-progress:", source)


if __name__ == "__main__":
    unittest.main()
