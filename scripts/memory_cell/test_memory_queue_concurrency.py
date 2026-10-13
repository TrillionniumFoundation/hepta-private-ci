"""No experimental PR run may acquire a new concurrency group for every SHA."""

from pathlib import Path
import re
import unittest

FILES = (
    "hepta-memory-grounded-development.yml",
    "hepta-memory-reader-reference.yml",
    "hepta-memory-token-task.yml",
    "hepta-memory-evidence-preference.yml",
    "hepta-memory-selector-development.yml",
    "hepta-memory-masked-span.yml",
    "hepta-memory-relevance-development.yml",
    "hepta-memory-bundle-diagnostic.yml",
    "hepta-memory-composition-evidence.yml",
    "hepta-memory-stem-mechanics.yml",
    "hepta-memory-necessity.yml",
    "hepta-memory-owner-observation.yml",
    "hepta-memory-adjudication-handoff.yml",
    "hepta-memory-balanced-quality.yml",
    "hepta-memory-event-organization.yml",
    "hepta-memory-event-reader-view.yml",
    "hepta-memory-reviewed-source-diagnostic.yml",
    "hepta-memory-startup-validation.yml",
    "hepta-memory-span-e2e.yml",
)
ROOT = Path(__file__).resolve().parents[2] / ".github" / "workflows"
SUFFIX = chr(36) + "{{ github.event.pull_request.number || github.ref }}"


class QueueContracts(unittest.TestCase):
    def test_non_cancelling_pr_concurrency(self):
        seen = set()
        for file in FILES:
            with self.subTest(file=file):
                source = (ROOT / file).read_text(encoding="utf-8")
                groups = re.findall(r"^  group: ([^\r\n]+)$", source, re.M)
                self.assertEqual(len(groups), 1)
                self.assertTrue(groups[0].endswith(SUFFIX))
                prefix = groups[0][: -len(SUFFIX)]
                self.assertTrue(prefix.startswith("memory-"))
                self.assertNotIn(prefix, seen)
                seen.add(prefix)
                self.assertIn("  pull_request:", source)
                self.assertEqual(source.count("  cancel-in-progress: false"), 1)
                self.assertNotIn("pull_request.head.sha", groups[0])
        self.assertEqual(len(seen), len(FILES))


if __name__ == "__main__":
    unittest.main()
