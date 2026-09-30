from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TRANSIENT_MUTATION_PATHS = (
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
        for relative in TRANSIENT_MUTATION_PATHS:
            with self.subTest(path=relative):
                self.assertFalse(
                    (ROOT / relative).exists(),
                    f"transient Matrix source mutation path returned: {relative}",
                )

    def test_authoritative_matrix_workflows_are_read_only(self) -> None:
        workflow_root = ROOT / ".github/workflows"
        workflows = sorted(workflow_root.glob("channel-matrix-*.yml"))
        self.assertTrue(workflows, "no authoritative Matrix workflow was found")
        for workflow in workflows:
            with self.subTest(path=workflow.relative_to(ROOT).as_posix()):
                text = workflow.read_text(encoding="utf-8")
                self.assertIn("permissions:\n  contents: read", text)
                self.assertNotIn("contents: write", text)
                self.assertNotIn("git commit", text)
                self.assertNotIn("push origin", text)
                self.assertNotIn("--allow-dirty", text)

    def test_exact_candidate_binds_api_compile_fail_receipts_in_both_lanes(self) -> None:
        workflow = ROOT / ".github/workflows/channel-matrix-preserve-unknown.yml"
        text = workflow.read_text(encoding="utf-8")
        labels = "compile api-compile-fail focused-tests clippy format"

        # API negative proofs are now a first-class canonical command receipt,
        # not an unstructured side log created by an ad-hoc workflow step.
        self.assertEqual(text.count(f"for label in {labels}; do"), 2)
        self.assertIn("scripts/channel_matrix_evidence_v2.py", text)
        self.assertIn("scripts/channel_matrix_pair_acceptance_v2.py", text)
        self.assertNotIn(
            "$RUNNER_TEMP/matrix-source-head/api-compile-fail.log",
            text,
        )
        self.assertNotIn(
            "$RUNNER_TEMP/matrix-base-merge/api-compile-fail.log",
            text,
        )
        self.assertNotIn(
            "cargo test --locked -p codex-hepta-matrix-sdk --doc 2>&1 | tee",
            text,
        )


if __name__ == "__main__":
    unittest.main()
