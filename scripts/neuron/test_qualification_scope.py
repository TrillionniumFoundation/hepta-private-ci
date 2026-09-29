from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_FILES = (
    ROOT / ".github/workflows/neuron-runtime-closure.yml",
    ROOT / ".github/workflows/neuron-runtime-closure-arm.yml",
    ROOT / ".github/workflows/neuron-runtime-closure-macos.yml",
)
QUALIFICATION_FILES = WORKFLOW_FILES + (ROOT / "scripts/neuron/qualify.sh",)


def normalized_shell(text: str) -> str:
    return re.sub(r"\\\s*\n\s*", " ", text)


class NeuronQualificationScopeTests(unittest.TestCase):
    def test_shared_agentd_tests_are_neuron_owned(self) -> None:
        for path in QUALIFICATION_FILES:
            with self.subTest(path=path.relative_to(ROOT)):
                text = normalized_shell(path.read_text())
                commands = [
                    line.strip()
                    for line in text.splitlines()
                    if "just test" in line and "-p codex-hepta-agentd" in line
                ]
                self.assertTrue(commands, "missing Agentd Neuron test command")
                for command in commands:
                    self.assertIn(
                        "-E 'test(/neuron_runtime_v2/)'",
                        command,
                        "shared Agentd package tests must be filtered to Neuron ownership",
                    )

    def test_workflows_still_compile_and_lint_all_agentd_targets(self) -> None:
        for path in WORKFLOW_FILES:
            with self.subTest(path=path.relative_to(ROOT)):
                text = normalized_shell(path.read_text())
                self.assertRegex(
                    text,
                    r"cargo check[^\n]*-p codex-hepta-agentd[^\n]*--all-targets",
                )
                self.assertRegex(
                    text,
                    r"cargo clippy[^\n]*-p codex-hepta-agentd[^\n]*--all-targets",
                )

    def test_cross_platform_workflows_cover_worker_host_owner(self) -> None:
        for path in WORKFLOW_FILES:
            with self.subTest(path=path.relative_to(ROOT)):
                text = path.read_text()
                self.assertIn('"codex-rs/hepta-infer-worker-host/**"', text)
                normalized = normalized_shell(text)
                self.assertRegex(
                    normalized,
                    r"cargo check[^\n]*-p codex-hepta-infer-worker-host",
                )
                self.assertRegex(
                    normalized,
                    r"cargo clippy[^\n]*-p codex-hepta-infer-worker-host",
                )

    def test_workflows_do_not_hide_untracked_source_mutation(self) -> None:
        for path in WORKFLOW_FILES:
            with self.subTest(path=path.relative_to(ROOT)):
                text = path.read_text()
                self.assertNotIn("--untracked-files=no", text)
                self.assertIn("--untracked-files=all", text)

    def test_arm_diagnostics_bind_the_actual_tested_commit(self) -> None:
        text = (ROOT / ".github/workflows/neuron-runtime-closure-arm.yml").read_text()
        self.assertIn('TESTED_COMMIT="$(git rev-parse HEAD)"', text)
        self.assertIn(
            'HEPTA_NEURON_DIAGNOSTIC_SOURCE_SHA="$TESTED_COMMIT"',
            text,
        )
        self.assertIn('--source-sha "$TESTED_COMMIT"', text)
        self.assertNotIn('HEPTA_NEURON_DIAGNOSTIC_SOURCE_SHA="$SOURCE_SHA"', text)

    def test_every_architecture_lane_has_an_aggregate_result_job(self) -> None:
        for path in WORKFLOW_FILES:
            with self.subTest(path=path.relative_to(ROOT)):
                text = path.read_text()
                self.assertIn("qualification-result:", text)
                self.assertIn("check_ci_results.py", text)

    def test_standalone_lane_keeps_agentd_in_compile_and_lint_packages(self) -> None:
        text = (ROOT / "scripts/neuron/qualify.sh").read_text()
        package_line = next(
            line for line in text.splitlines() if line.startswith("pkgs=(")
        )
        self.assertIn("-p codex-hepta-agentd", package_line)


if __name__ == "__main__":
    unittest.main()
