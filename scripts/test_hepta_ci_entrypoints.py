from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.hepta_ci_entrypoints import events
from scripts.hepta_ci_entrypoints import verify


class CiEntrypointPolicyTests(unittest.TestCase):
    def test_event_parser_supports_mapping_and_inline_forms(self) -> None:
        self.assertEqual(events("name: x\non: [push, pull_request]\njobs: {}\n"), {"push", "pull_request"})
        self.assertEqual(
            events("name: x\non:\n  workflow_call:\n  workflow_dispatch:\npermissions: {}\n"),
            {"workflow_call", "workflow_dispatch"},
        )

    def test_parallel_specialty_trigger_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            workflows = root / ".github/workflows"
            workflows.mkdir(parents=True)
            (workflows / "blocking-ci.yml").write_text(
                "name: blocking\non:\n  pull_request:\n  push:\njobs: {}\n"
            )
            (workflows / "hepta-architecture-convergence.yml").write_text(
                "name: architecture\non:\n  pull_request:\n  push:\njobs: {}\n"
            )
            (workflows / "hepta-module.yml").write_text(
                "name: module\non:\n  pull_request:\n  workflow_dispatch:\njobs: {}\n"
            )
            with self.assertRaisesRegex(ValueError, "parallel automatic events"):
                verify(root)

    def test_manual_specialty_workflow_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            workflows = root / ".github/workflows"
            workflows.mkdir(parents=True)
            (workflows / "blocking-ci.yml").write_text(
                "name: blocking\non:\n  pull_request:\n  push:\njobs: {}\n"
            )
            (workflows / "hepta-architecture-convergence.yml").write_text(
                "name: architecture\non:\n  pull_request:\n  push:\njobs: {}\n"
            )
            (workflows / "hepta-module.yml").write_text(
                "name: module\non:\n  workflow_call:\n  workflow_dispatch:\njobs: {}\n"
            )
            self.assertEqual(verify(root)["status"], "aligned")


if __name__ == "__main__":
    unittest.main()
