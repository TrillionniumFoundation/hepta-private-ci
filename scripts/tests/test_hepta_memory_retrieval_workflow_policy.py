from pathlib import Path
import tempfile
import unittest

from scripts import hepta_memory_retrieval_workflow_policy as policy


class WorkflowPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / ".github/workflows"
        self.directory.mkdir(parents=True)

    def write(self, name, text):
        (self.directory / name).write_text(text)

    def test_read_only_workflow_passes(self):
        self.write(
            "hepta-memory-retrieval-safe.yml",
            "permissions:\n  contents: read\nsteps:\n  - uses: actions/checkout@deadbeef\n"
            "    with:\n      persist-credentials: false\n",
        )
        self.assertEqual(policy.audit(self.root), [])

    def test_contents_write_fails(self):
        self.write("hepta-memory-retrieval-bad.yml", "permissions:\n  contents: write\n")
        self.assertIn("repository write permission", policy.audit(self.root)[0])

    def test_pull_request_target_fails(self):
        self.write("hepta-memory-retrieval-bad.yml", "on:\n  pull_request_target: {}\n")
        self.assertIn("pull_request_target event", policy.audit(self.root)[0])

    def test_git_push_fails(self):
        self.write("hepta-memory-retrieval-bad.yml", "run: git push origin HEAD\n")
        self.assertIn("git push", policy.audit(self.root)[0])

    def test_no_workflow_fails_closed(self):
        with self.assertRaises(policy.WorkflowPolicyError):
            policy.audit(self.root)


if __name__ == "__main__":
    unittest.main()
