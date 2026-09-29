from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

WORKFLOWS = {
    "bounded core": ROOT / ".github/workflows/kernel-evidence-core-regression.yml",
    "native publication": ROOT / ".github/workflows/kernel-evidence-publication-native.yml",
    "publication formatting": ROOT / ".github/workflows/kernel-evidence-publication-format.yml",
}


class KernelEvidenceWorkflowScopeTests(unittest.TestCase):
    def test_candidate_diagnostics_are_not_bound_to_one_historical_branch(self) -> None:
        for label, path in WORKFLOWS.items():
            with self.subTest(workflow=label):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("fix/kernel-evidence-production-closure", text)
                self.assertIn(
                    "github.event.pull_request.head.repo.full_name == github.repository",
                    text,
                )

    def test_candidate_diagnostics_are_path_scoped_to_kernel_evidence(self) -> None:
        core = WORKFLOWS["bounded core"].read_text(encoding="utf-8")
        self.assertIn("'codex-rs/hepta-evidence/**'", core)
        self.assertIn("'qualification/kernel-evidence/probes/**'", core)

        native = WORKFLOWS["native publication"].read_text(encoding="utf-8")
        for path in (
            "'codex-rs/hepta-evidence/**'",
            "'codex-rs/hepta-agentd/**'",
            "'codex-rs/hepta-agent-protocol/**'",
            "'codex-rs/hepta-authbus/**'",
            "'codex-rs/state/**'",
        ):
            self.assertIn(path, native)

        formatting = WORKFLOWS["publication formatting"].read_text(encoding="utf-8")
        for path in (
            "'codex-rs/hepta-evidence/**'",
            "'codex-rs/hepta-agentd/**'",
            "'codex-rs/hepta-agent-protocol/**'",
        ):
            self.assertIn(path, formatting)

    def test_native_diagnostics_retain_full_qualification_commands(self) -> None:
        native = WORKFLOWS["native publication"].read_text(encoding="utf-8")
        for required in (
            "'formatting'",
            "'evidence-tests'",
            "'agentd-tests'",
            "'evidence-doctests'",
            "'clippy'",
            "'build'",
            "-D', 'warnings'",
            "lane: [source-head, base-merge]",
        ):
            self.assertIn(required, native)


if __name__ == "__main__":
    unittest.main()
