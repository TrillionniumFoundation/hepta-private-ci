#!/usr/bin/env python3
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CognitiveReadQualificationReadOnlyTests(unittest.TestCase):
    def test_qualification_workflow_is_read_only(self) -> None:
        body = (ROOT / ".github/workflows/cognitive-read-qualification.yml").read_text()
        self.assertIn("permissions:\n  contents: read", body)
        self.assertNotIn("source-proposal:", body)
        self.assertNotIn("contents: write", body)
        self.assertNotIn("pull-requests: write", body)
        self.assertNotIn("git commit", body)
        self.assertNotIn("git push", body)
        self.assertNotIn("gh pr", body)

    def test_qualification_entry_point_has_no_repair_sidecar(self) -> None:
        body = (ROOT / "scripts/run-cognitive-read-qualification.sh").read_text()
        self.assertIn("cognitive_read_full_evidence.py", body)
        self.assertNotIn("qualification_with_proposal", body)
        self.assertNotIn("source_proposal", body)
        self.assertFalse(
            (ROOT / "scripts/cognitive_read_qualification_with_proposal.py").exists()
        )

    def test_local_proposal_is_manual_and_credential_free(self) -> None:
        body = (ROOT / ".github/workflows/cognitive-read-lock-refresh.yml").read_text()
        self.assertIn("workflow_dispatch:", body)
        self.assertNotIn("pull_request:", body)
        self.assertNotIn("  push:", body)
        self.assertIn("contents: read", body)
        self.assertIn("persist-credentials: false", body)
        self.assertNotIn("contents: write", body)
        self.assertNotIn("git push", body)

    def test_receipt_binds_lockfile_and_toolchain(self) -> None:
        body = (ROOT / "scripts/cognitive_read_full_evidence.py").read_text()
        self.assertIn('"cargo_lock"', body)
        self.assertIn('base.digest(root / "codex-rs/Cargo.lock")', body)
        self.assertIn('"toolchain"', body)
        self.assertIn('"nextest"', body)

    def test_self_modifying_authoring_surface_is_absent(self) -> None:
        self.assertFalse(
            (ROOT / ".github/workflows/cognitive-read-apply-once.yml").exists()
        )
        self.assertFalse(
            (ROOT / "scripts/apply-cognitive-read-qualification-governance.py").exists()
        )


if __name__ == "__main__":
    unittest.main()
