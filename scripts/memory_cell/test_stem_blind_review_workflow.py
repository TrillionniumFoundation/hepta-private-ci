"""Prevent GitHub Actions blind-review exports from leaking owner mapping.

Synthetic/static workflow policy regression only: it cannot authenticate an
independent reviewer or isolate users who can themselves access original gold.
"""

from pathlib import Path
import re
import unittest

from stem_blind_review_export import SOURCE, TREE, ZIP_SHA

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github/workflows/hepta-memory-stem-blind-review.yml"
ALLOWED = frozenset({
    "/tmp/stem-blind-review/reviewer-visible",
    "/tmp/stem-blind-review/audit-safe",
})


def uploaded_paths(text):
    """Inspect every upload action, not only conveniently named artifacts."""
    segments = text.split("      - uses: actions/upload-artifact@")
    if len(segments) != 3:
        raise ValueError("exact two bounded upload actions required")
    result = []
    for segment in segments[1:]:
        match = re.search(r"(?m)^\s+path: ([^\n]+)$", segment)
        if match is None:
            raise ValueError("missing artifact upload path")
        result.append(match.group(1).strip())
    if len(set(result)) != 2 or set(result) != ALLOWED:
        raise ValueError("owner mapping, raw archive or unreviewed gold could be uploaded")
    return result


class SafeReviewerExportWorkflowTests(unittest.TestCase):
    def test_export_is_pinned_to_completed_strict_asof_source(self):
        text = WORKFLOW.read_text()
        self.assertEqual(SOURCE, "d0f69d7b94f65730fa1e093dee6989916f01898e")
        self.assertEqual(TREE, "87e3b17a0601c17712b9512fc01eadc123060391")
        self.assertEqual(
            ZIP_SHA,
            "07b0f15ec150cc9817db6bfc9b4bae1e2c06a5296ca2ba3c4c7895da18b99e2f",
        )
        self.assertIn("actions/artifacts/11726530850/zip", text)
        self.assertIn(ZIP_SHA, text)
        self.assertIn("test_stem_blind_review_packet test_stem_blind_review_workflow", text)

    def test_only_review_worklist_and_nonidentity_source_logs_are_uploaded(self):
        text = WORKFLOW.read_text()
        self.assertEqual(set(uploaded_paths(text)), ALLOWED)
        self.assertIn("private-owner-case-mapping.json /tmp/stem-blind-review/runner-only", text)
        self.assertIn("rm /tmp/stem-blind-review/runner-only/private-owner-case-mapping.json", text)
        self.assertNotIn("path: /tmp/stem-blind-review/owner-private", text)
        self.assertIn("retention-days: 7", text)

    def test_attempts_to_upload_identity_map_or_entire_temp_root_reject(self):
        text = WORKFLOW.read_text()
        for unsafe in (
            "/tmp/stem-blind-review/runner-only",
            "/tmp/stem-blind-review/owner-private",
            "/tmp/stem-blind-review",
            "/tmp",
        ):
            changed = text.replace(
                "path: /tmp/stem-blind-review/audit-safe",
                "path: " + unsafe,
                1,
            )
            with self.subTest(path=unsafe), self.assertRaises(ValueError):
                uploaded_paths(changed)

    def test_workflow_does_not_open_scored_labels_or_original_oracle(self):
        text = WORKFLOW.read_text()
        for prohibited in (
            "comparison/scored-policy-attempts.json",
            "comparison/oracle-diagnostic.jsonl",
            "target-answers.json",
            "gold-labels.json",
        ):
            self.assertNotIn(prohibited, text)
        self.assertIn(
            "test ! -e /tmp/stem-blind-review/audit-safe/private-owner-case-mapping.json",
            text,
        )
        self.assertIn("test \"$(wc -l < /tmp/stem-blind-review/owner-review/blind-question-answer-worklist.jsonl)\" -eq 32", text)
        self.assertIn("test \"$(wc -l < /tmp/stem-blind-review/owner-review/unsigned-reviewer-return-template.jsonl)\" -eq 64", text)

    def test_only_successful_review_packet_is_exported(self):
        text = WORKFLOW.read_text()
        packet = text.split("name: stem-unreviewed-strict-reader-worklist")[0]
        self.assertIn("if: success()", packet[-160:])
        self.assertIn("name: stem-blind-review-source-and-tests-only", text)
        self.assertFalse(
            "name: private-stem-owner-only-unblinding-mapping" in text
        )


if __name__ == "__main__":
    unittest.main()
