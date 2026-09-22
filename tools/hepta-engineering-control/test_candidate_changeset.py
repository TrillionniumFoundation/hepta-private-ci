from pathlib import Path
import hashlib
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

    def test_atomic_changeset_can_create_only_required_parent_directories(self):
        temp, root, base = self.fixture()
        self.addCleanup(temp.cleanup)
        envelope = CandidateEnvelope(
            "env", base, ("src",), require_network_isolation=False
        )
        change = MutationSet(
            (
                Mutation(
                    "add_file",
                    "src/newpkg/first.py",
                    replacement_text="FIRST = 1\n",
                ),
                Mutation(
                    "add_file",
                    "src/newpkg/nested/second.py",
                    replacement_text="SECOND = 2\n",
                ),
            )
        )
        candidate = generate_candidates(envelope, (change,))[1]
        tested, receipt = sandbox_candidate(
            root,
            envelope,
            candidate,
            (
                (
                    sys.executable,
                    "-c",
                    "from pathlib import Path; "
                    "assert Path('src/newpkg/first.py').is_file(); "
                    "assert Path('src/newpkg/nested/second.py').is_file()",
                ),
            ),
        )
        self.assertTrue(receipt.passed)
        self.assertEqual(tested.state, "fixture_tested")
        self.assertEqual(
            tested.changed_paths,
            ("src/newpkg/first.py", "src/newpkg/nested/second.py"),
        )

    def test_rename_can_create_required_destination_parent_directory(self):
        temp, root, base = self.fixture()
        self.addCleanup(temp.cleanup)
        envelope = CandidateEnvelope(
            "env", base, ("src",), require_network_isolation=False
        )
        rename = Mutation(
            "rename_file",
            "src/b.txt",
            target_path="src/newpkg/b.txt",
        )
        candidate = generate_candidates(envelope, (rename,))[1]
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
                    "assert Path('src/newpkg/b.txt').read_text() == 'B\\n'",
                ),
            ),
        )
        self.assertTrue(receipt.passed)
        self.assertEqual(
            tested.changed_paths,
            ("src/b.txt", "src/newpkg/b.txt"),
        )

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

    def test_binary_rename_uses_streaming_digest_precondition(self):
        temp, root, base = self.fixture()
        self.addCleanup(temp.cleanup)
        payload = b"\x00\xffbinary\x80payload\n"
        binary = root / "src/blob.bin"
        binary.write_bytes(payload)
        git(root, "add", "src/blob.bin")
        git(root, "commit", "-m", "binary fixture")
        base = git(root, "rev-parse", "HEAD")
        envelope = CandidateEnvelope(
            "env", base, ("src",), require_network_isolation=False
        )
        mutation = Mutation(
            "rename_file",
            "src/blob.bin",
            expected_text=hashlib.sha256(payload).hexdigest(),
            target_path="src/archive/blob.bin",
        )
        candidate = generate_candidates(envelope, (mutation,))[1]
        tested, receipt = sandbox_candidate(
            root,
            envelope,
            candidate,
            (
                (
                    sys.executable,
                    "-c",
                    "from pathlib import Path; "
                    "assert not Path('src/blob.bin').exists(); "
                    "assert Path('src/archive/blob.bin').read_bytes() == "
                    + repr(payload),
                ),
            ),
        )
        self.assertTrue(receipt.passed)
        self.assertEqual(
            tested.changed_paths,
            ("src/archive/blob.bin", "src/blob.bin"),
        )
        self.assertTrue(binary.exists())
        self.assertFalse((root / "src/archive/blob.bin").exists())

    def test_rename_digest_precondition_must_be_sha256(self):
        temp, _root, base = self.fixture()
        self.addCleanup(temp.cleanup)
        envelope = CandidateEnvelope(
            "env", base, ("src",), require_network_isolation=False
        )
        with self.assertRaisesRegex(ValueError, "invalid_rename_precondition"):
            generate_candidates(
                envelope,
                (
                    Mutation(
                        "rename_file",
                        "src/b.txt",
                        expected_text="not-a-digest",
                        target_path="src/renamed.txt",
                    ),
                ),
            )

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
