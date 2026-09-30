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
        (self.directory / name).write_text(text, encoding="utf-8")

    def test_read_only_workflow_with_event_bound_checkout_passes(self):
        self.write(
            "hepta-memory-retrieval-safe.yml",
            "permissions:\n  contents: read\nsteps:\n"
            "  - uses: actions/checkout@deadbeef\n"
            "    with:\n"
            "      ref: ${{ github.event.pull_request.head.sha || github.sha }}\n"
            "      persist-credentials: false\n",
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

    def test_job_output_cannot_control_checkout_ref(self):
        self.write(
            "hepta-memory-retrieval-bad.yml",
            "steps:\n  - uses: actions/checkout@deadbeef\n"
            "    with:\n      ref: ${{ needs.identity.outputs.source_sha }}\n",
        )
        self.assertIn("job output controls checkout ref", policy.audit(self.root)[0])

    def test_step_output_cannot_control_checkout_ref(self):
        self.write(
            "hepta-memory-retrieval-bad.yml",
            "steps:\n  - uses: actions/checkout@deadbeef\n"
            "    with:\n      ref: ${{ steps.identity.outputs.source_sha }}\n",
        )
        self.assertIn("step output controls checkout ref", policy.audit(self.root)[0])

    def test_job_output_cannot_supply_executable_sha_environment(self):
        self.write(
            "hepta-memory-retrieval-bad.yml",
            "env:\n  TESTED_SHA: ${{ needs.identity.outputs.source_sha }}\n"
            "steps:\n  - run: git checkout --detach \"$TESTED_SHA\"\n",
        )
        self.assertIn(
            "job output controls executable Git identity",
            policy.audit(self.root)[0],
        )

    def test_candidate_helper_cannot_choose_tested_checkout(self):
        self.write(
            "hepta-memory-retrieval-bad.yml",
            "steps:\n  - run: |\n"
            "      TESTED_SHA=\"$(python3 "
            "scripts/hepta_memory_retrieval_candidate.py merge "
            "--base \"$BASE_SHA\" --source \"$SOURCE_SHA\")\"\n"
            "      git checkout --detach \"$TESTED_SHA\"\n",
        )
        self.assertIn("candidate helper controls tested checkout", policy.audit(self.root)[0])

    def test_candidate_helper_cannot_publish_job_checkout_output(self):
        self.write(
            "hepta-memory-retrieval-bad.yml",
            "steps:\n  - run: |\n"
            "      python3 scripts/hepta_memory_retrieval_candidate.py refs "
            "--source \"$SOURCE_SHA\" >> \"$GITHUB_OUTPUT\"\n",
        )
        self.assertIn(
            "candidate helper publishes executable ref",
            policy.audit(self.root)[0],
        )

    def test_no_workflow_fails_closed(self):
        with self.assertRaises(policy.WorkflowPolicyError):
            policy.audit(self.root)


if __name__ == "__main__":
    unittest.main()
