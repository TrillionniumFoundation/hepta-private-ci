from __future__ import annotations
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRANSIENT = (
    ".github/channel-matrix-repair.py",
    ".github/workflows/channel-matrix-bootstrap.yml",
    ".github/workflows/channel-matrix-closure-apply.yml",
    ".github/workflows/channel-matrix-hardening-apply.yml",
    ".github/workflows/channel-matrix-ops-evidence-finalize.yml",
    ".github/workflows/channel-matrix-source-export.yml",
    ".matrix-staging",
    "scripts/channel_matrix_full_patch.py.gz.b64",
    "scripts/channel_matrix_preserve_unknown_patch.py",
)

class ChannelMatrixSourcePurityTests(unittest.TestCase):
    def test_transient_mutation_paths_are_absent(self) -> None:
        for relative in TRANSIENT:
            with self.subTest(path=relative):
                self.assertFalse((ROOT / relative).exists())

    def test_authoritative_matrix_workflows_are_read_only(self) -> None:
        workflows = sorted((ROOT / ".github/workflows").glob("channel-matrix-*.yml"))
        self.assertTrue(workflows)
        for workflow in workflows:
            with self.subTest(path=workflow.relative_to(ROOT).as_posix()):
                text = workflow.read_text(encoding="utf-8")
                self.assertIn("permissions:\n  contents: read", text)
                self.assertNotIn("contents: write", text)
                self.assertNotIn("push origin", text)
                self.assertNotIn("--allow-dirty", text)
                for line in text.splitlines():
                    self.assertFalse(line.strip().startswith("git commit "))
                    self.assertFalse(line.strip().startswith("git push "))

    def test_readiness_runs_three_exact_lanes_and_one_manifest(self) -> None:
        text = (ROOT / ".github/workflows/channel-matrix-readiness.yml").read_text(encoding="utf-8")
        self.assertIn("lane: [source-head, deterministic-merge, github-merge]", text)
        self.assertIn("git ls-files", (ROOT / "scripts/channel_matrix_source_provenance.py").read_text())
        self.assertIn("--error-unmatch", (ROOT / "scripts/channel_matrix_source_provenance.py").read_text())
        self.assertIn("channel_matrix_readiness.py", text)
        self.assertIn("--mode \"$QUALIFICATION_MODE\"", text)
        self.assertIn("readiness-manifest.json", text)
        self.assertEqual(text.count("cargo test --locked -p codex-hepta-matrix-sdk --doc"), 1)

    def test_readiness_schema_has_all_required_identity_fields(self) -> None:
        text = (ROOT / "scripts/channel_matrix_readiness.py").read_text(encoding="utf-8")
        for field in (
            "source_head_sha", "frozen_source_sha", "base_sha", "deterministic_merge_sha",
            "github_merge_sha", "workflow_sha", "final_merge_sha", "workflow_run_id",
            "attempt_id", "runner_image", "target_triple", "Cargo.lock_hash",
            "migration_hash", "test_set_hash", "qualification_profile_hash",
            "implementation_map_hash", "documentation_hash", "source_tree_hash",
            "artifact_hashes", "productionQualified", "mergeReady",
        ):
            self.assertIn(f'"{field}"', text)

if __name__ == "__main__": unittest.main()
