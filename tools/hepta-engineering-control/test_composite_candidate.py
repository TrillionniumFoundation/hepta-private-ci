from pathlib import Path
import subprocess
import tempfile
import unittest

from control_engineering_v2 import CandidateEnvelope, Mutation, generate_candidates
from control_engineering_v2.composite_candidate import (
    generate_composite_candidates,
    sandbox_composite_candidate,
)


class CompositeCandidateTests(unittest.TestCase):
    def fixture(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
        (root / "src").mkdir()
        (root / "src" / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        envelope = CandidateEnvelope(
            "env",
            head,
            ("src",),
            maximum_candidates=8,
            maximum_changed_files=8,
            maximum_diff_bytes=1024 * 1024,
            require_network_isolation=False,
        )
        return temp, root, envelope

    def test_atomic_multi_file_candidate_is_one_identity_and_one_sandbox(self):
        temp, root, envelope = self.fixture()
        self.addCleanup(temp.cleanup)
        candidates = generate_composite_candidates(
            envelope,
            (
                (
                    Mutation("replace_text", "src/a.py", "VALUE = 1", "VALUE = 2"),
                    Mutation("add_file", "src/b.py", "", "OTHER = 3\n"),
                ),
            ),
        )
        candidate = candidates[1]
        self.assertEqual(candidate.changed_paths, ("src/a.py", "src/b.py"))
        tested, receipt = sandbox_composite_candidate(
            root,
            envelope,
            candidate,
            (
                (
                    "python3",
                    "-c",
                    "from pathlib import Path; "
                    "assert Path('src/a.py').read_text() == 'VALUE = 2\\n'; "
                    "assert Path('src/b.py').read_text() == 'OTHER = 3\\n'",
                ),
            ),
        )
        self.assertEqual(tested.state, "fixture_tested")
        self.assertTrue(receipt.passed)
        self.assertEqual(tested.changed_paths, ("src/a.py", "src/b.py"))

    def test_candidate_cannot_modify_test_oracle_even_if_envelope_allows_it(self):
        envelope = CandidateEnvelope(
            "env",
            "a" * 40,
            ("pkg",),
            require_network_isolation=False,
        )
        with self.assertRaisesRegex(ValueError, "protected_oracle_path"):
            generate_candidates(
                envelope,
                (Mutation("add_file", "pkg/tests/test_candidate.py", "", "pass\n"),),
            )


if __name__ == "__main__":
    unittest.main()
