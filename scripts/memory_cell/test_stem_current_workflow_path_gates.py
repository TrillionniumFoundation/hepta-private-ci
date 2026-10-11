"""Protect the pinned strict-source audit from broken workflow path filters.

Source-only stdlib checks. A passing historical audit is useless if edits to
the auditor or its tests stop triggering that audit.
"""

from pathlib import Path
import re
import unittest

WORKFLOW = ".github/workflows/hepta-memory-stem-current-source-gate.yml"
REQUIRED = frozenset(
    (
        "scripts/memory_cell/stem_current_strict_readout_audit.py",
        "scripts/memory_cell/test_stem_current_strict_readout_audit.py",
        "scripts/memory_cell/stem_native_reader_stratification.py",
        "scripts/memory_cell/test_stem_native_reader_stratification.py",
        "scripts/memory_cell/stem_native_oracle_reader_capacity.py",
        "scripts/memory_cell/test_stem_native_oracle_reader_capacity.py",
        "scripts/memory_cell/test_stem_current_workflow_path_gates.py",
        WORKFLOW,
    )
)


class StrictSourceWorkflowPathTests(unittest.TestCase):
    def setUp(self):
        self.repo = Path(__file__).resolve().parents[2]
        self.workflow = (self.repo / WORKFLOW).read_text(encoding="utf-8")

    def declared_paths(self):
        match = re.search(
            r'(?m)^    paths:\n((?:      - "[^"\n]+"\n)+)',
            self.workflow,
        )
        self.assertIsNotNone(match, "exact on.push.paths list required")
        return re.findall(r'(?m)^      - "([^"\n]+)"$', match.group(1))

    def test_each_input_is_an_existing_individual_path(self):
        paths = self.declared_paths()
        self.assertEqual(len(paths), len(set(paths)), "duplicate workflow path")
        self.assertTrue(REQUIRED.issubset(paths), "missing direct source trigger")
        for path in paths:
            with self.subTest(path=path):
                self.assertNotIn(" ", path, "two files combined in one trigger")
                self.assertTrue(
                    path.startswith("scripts/memory_cell/") or path == WORKFLOW,
                    "unbounded strict-source audit trigger",
                )
                self.assertTrue((self.repo / path).is_file())

    def test_source_tests_are_called_in_the_same_hosted_job(self):
        command = next(
            (
                line.strip()
                for line in self.workflow.splitlines()
                if line.strip().startswith("python3 -m unittest -v ")
            ),
            None,
        )
        self.assertIsNotNone(command, "hosted regression check absent")
        for module in (
            "test_stem_current_strict_readout_audit",
            "test_stem_native_reader_stratification",
            "test_stem_native_oracle_reader_capacity",
            "test_stem_current_workflow_path_gates",
        ):
            self.assertIn(module, command)

    def test_exact_source_checkout_and_production_nonmutation(self):
        self.assertIn("ref: ${{ github.sha }}", self.workflow)
        self.assertIn("persist-credentials: false", self.workflow)
        self.assertIn("contents: read", self.workflow)
        self.assertNotIn("pull_request_target:", self.workflow)
        self.assertIn("Keep exact auditing source", self.workflow)


if __name__ == "__main__":
    unittest.main()
