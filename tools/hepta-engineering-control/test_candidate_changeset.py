from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from control_engineering_v2 import CandidateEnvelope, Mutation, MutationSet, generate_candidates, sandbox_candidate


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class CandidateChangeSetTests(unittest.TestCase):
    def fixture(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name) / "repo"
        root.mkdir()
        git(root, "init")
        git(root, "config", "user.email", "candidate@example.invalid")
        git(root, "config", "user.name", "candidate")
        (root / "src").mkdir()
        (root / "src/a.txt").write_text("A\n", encoding="utf-8")
        (root / "src/b.txt").write_text("B\n", encoding="utf-8")
        (root / "src/inline.rs").write_text(
            "fn production() -> u32 { 1 }\n"
            "#[cfg(test)]\nmod tests { #[test] fn oracle() { assert_eq!(1, 1); } }\n",
            encoding="utf-8",
        )
        git(root, "add", ".")
        git(root, "commit", "-m", "base")
        return temp, root, git(root, "rev-parse", "HEAD")

    def test_atomic_multi_file_candidate_is_one_identity(self):
        temp, root, base = self.fixture()
        self.addCleanup(temp.cleanup)
        envelope = CandidateEnvelope(
            "env", base, ("src",), require_network_isolation=False
        )
        bundle = MutationSet(
            (
                Mutation("replace_text", "src/a.txt", "A", "AA"),
                Mutation("add_file", "src/c.txt", replacement_text="C\n"),
            )
        )
        candidate = generate_candidates(envelope, (bundle,))[1]
        self.assertEqual(candidate.changed_paths, ("src/a.txt", "src/c.txt"))
        tested, receipt = sandbox_candidate(
            root,
            envelope,
            candidate,
            (
                (
                    sys.executable,
                    "-c",
                    "from pathlib import Path; "
                    "assert Path('src/a.txt').read_text() == 'AA\\n'; "
                    "assert Path('src/c.txt').read_text() == 'C\\n'",
                ),
            ),
        )
        self.assertTrue(receipt.passed)
        self.assertEqual(tested.state, "fixture_tested")
        self.assertEqual((root / "src/a.txt").read_text(encoding="utf-8"), "A\n")
        self.assertFalse((root / "src/c.txt").exists())

    def test_generation_applies_envelope_changed_file_limit(self):
        _temp, _root, base = self.fixture()
        self.addCleanup(_temp.cleanup)
        envelope = CandidateEnvelope(
            "env",
            base,
            ("src",),
            maximum_changed_files=1,
            require_network_isolation=False,
        )
        bundle = MutationSet(
            (
                Mutation("replace_text", "src/a.txt", "A", "AA"),
                Mutation("add_file", "src/c.txt", replacement_text="C\n"),
            )
        )
        with self.assertRaisesRegex(ValueError, "changed_file_limit"):
            generate_candidates(envelope, (bundle,))

    def test_rename_is_bound_as_two_path_change(self):
        temp, root, base = self.fixture()
        self.addCleanup(temp.cleanup)
        envelope = CandidateEnvelope(
            "env", base, ("src",), require_network_isolation=False
        )
        mutation = Mutation("rename_file", "src/b.txt", target_path="src/renamed.txt")
        candidate = generate_candidates(envelope, (mutation,))[1]
        self.assertEqual(candidate.changed_paths, ("src/b.txt", "src/renamed.txt"))
        tested, receipt = sandbox_candidate(
            root,
            envelope,
            candidate,
            (
                (
                    sys.executable,
                    "-c",
                    "from pathlib import Path; "
                    "assert not Path('src/b.txt').exists(); "
                    "assert Path('src/renamed.txt').read_text() == 'B\\n'",
                ),
            ),
        )
        self.assertTrue(receipt.passed)
        self.assertEqual(tested.changed_paths, ("src/b.txt", "src/renamed.txt"))

    def test_inline_oracle_source_is_immutable_even_without_test_filename(self):
        temp, root, base = self.fixture()
        self.addCleanup(temp.cleanup)
        envelope = CandidateEnvelope(
            "env", base, ("src",), require_network_isolation=False
        )
        cases = (
            Mutation(
                "replace_text",
                "src/inline.rs",
                "production()",
                "production_changed()",
            ),
            Mutation(
                "add_file",
                "src/generated.rs",
                replacement_text="#[test]\nfn generated_oracle() {}\n",
            ),
        )
        for mutation in cases:
            with self.subTest(operation=mutation.operation):
                candidate = generate_candidates(envelope, (mutation,))[1]
                with self.assertRaisesRegex(
                    ValueError, "candidate_oracle_path"
                ):
                    sandbox_candidate(
                        root,
                        envelope,
                        candidate,
                        ((sys.executable, "-c", "print('should-not-run')"),),
                    )


if __name__ == "__main__":
    unittest.main()
