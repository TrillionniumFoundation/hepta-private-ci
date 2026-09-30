#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("verify_candidate_immutability.py")
SPEC = importlib.util.spec_from_file_location("verify_candidate_immutability", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CandidateImmutabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        workflow_dir = self.root / ".github" / "workflows"
        workflow_dir.mkdir(parents=True)
        canonical = "permissions:\n  contents: read\njobs:\n  check:\n    steps:\n      - run: true\n"
        for relative in MODULE.CANONICAL_WORKFLOWS:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(canonical, encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_clean_candidate_is_accepted(self) -> None:
        self.assertEqual(MODULE.collect_violations(self.root), [])

    def test_write_enabled_secrets_workflow_is_rejected(self) -> None:
        path = self.root / ".github/workflows/secrets-heptabao-writer.yml"
        path.write_text(
            "name: secrets.heptabao writer\npermissions:\n  contents: write\n",
            encoding="utf-8",
        )
        violations = MODULE.collect_violations(self.root)
        self.assertTrue(any("contents: write" in item for item in violations))

    def test_source_export_workflow_is_rejected_even_when_read_only(self) -> None:
        path = self.root / ".github/workflows/secrets-heptabao-source-export.yml"
        path.write_text(
            "name: secrets.heptabao export\npermissions:\n  contents: read\n",
            encoding="utf-8",
        )
        violations = MODULE.collect_violations(self.root)
        self.assertTrue(any("development source workflow" in item for item in violations))

    def test_patch_payload_is_rejected(self) -> None:
        payload = self.root / ".ci/secrets-heptabao-source.patch"
        payload.parent.mkdir(parents=True)
        payload.write_text("patch", encoding="utf-8")
        violations = MODULE.collect_violations(self.root)
        self.assertTrue(any("payload remains" in item for item in violations))

    def test_materializer_script_is_rejected(self) -> None:
        script = self.root / "scripts/materialize_secrets_heptabao_development.py"
        script.parent.mkdir(parents=True)
        script.write_text("pass\n", encoding="utf-8")
        violations = MODULE.collect_violations(self.root)
        self.assertTrue(any("payload remains" in item for item in violations))


if __name__ == "__main__":
    unittest.main()
