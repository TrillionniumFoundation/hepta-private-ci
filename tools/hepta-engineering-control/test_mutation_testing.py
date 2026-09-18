from pathlib import Path
import subprocess
import tempfile
import unittest

from control_engineering_v2 import CandidateEnvelope, Mutation
from control_engineering_v2.mutation_testing import run_mutation_testing


class MutationTestingTests(unittest.TestCase):
    def test_evaluator_checks_must_kill_every_source_mutant(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            (root / "src").mkdir()
            (root / "src" / "value.py").write_text("VALUE = 1\n", encoding="utf-8")
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
                "mutation-env",
                head,
                ("src",),
                maximum_candidates=4,
                require_network_isolation=False,
            )
            receipt = run_mutation_testing(
                root,
                envelope,
                (Mutation("replace_text", "src/value.py", "VALUE = 1", "VALUE = 2"),),
                (
                    (
                        "python3",
                        "-c",
                        "from pathlib import Path; "
                        "assert Path('src/value.py').read_text() == 'VALUE = 1\\n'",
                    ),
                ),
            )
            self.assertTrue(receipt.passed)
            self.assertEqual(len(receipt.killed_candidates), 1)
            self.assertEqual(receipt.surviving_candidates, ())
            self.assertFalse(receipt.merge_authority)


if __name__ == "__main__":
    unittest.main()
