"""Independent parser bounds and deterministic-candidate regressions."""

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("authority_verify", HERE / "verify.py")
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


class EvidenceReadTests(unittest.TestCase):
    def test_non_finite_numbers_are_rejected(self):
        for number in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(number=number), self.assertRaises(VERIFY.Invalid):
                VERIFY.parse_json(('{"value":' + number + "}").encode(), "fixture")

    def test_json_read_has_a_hard_byte_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oversized.json"
            path.write_bytes(b" " * (VERIFY.MAX_JSON_BYTES + 1))
            with self.assertRaises(VERIFY.Invalid):
                VERIFY.load_json(path)

    def test_digest_and_parser_share_the_same_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "receipt.json"
            original = b'{"measured":1}'
            path.write_bytes(original)
            checked = VERIFY.artifact_index(
                root,
                [
                    {
                        "path": path.name,
                        "sha256": hashlib.sha256(original).hexdigest(),
                    }
                ],
            )
            path.write_bytes(b'{"measured":999}')
            self.assertEqual(
                VERIFY.parse_json(checked[path.name], "fixture"), {"measured": 1}
            )


class CandidateTests(unittest.TestCase):
    def test_merge_identity_is_deterministic_and_user_work_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()

            def git(*args):
                return subprocess.run(
                    [
                        "git",
                        "-c",
                        "core.fsmonitor=false",
                        "-c",
                        "commit.gpgsign=false",
                        *args,
                    ],
                    cwd=repo,
                    check=True,
                    text=True,
                    capture_output=True,
                ).stdout.strip()

            git("init", "-q", "--initial-branch=fixture")
            git("config", "user.name", "Qualification Fixture")
            git("config", "user.email", "fixture@hepta.invalid")
            (repo / "source").write_text("base\n")
            git("add", "source")
            git("commit", "-qm", "base")
            base = git("rev-parse", "HEAD")
            (repo / "source").write_text("candidate\n")
            git("commit", "-qam", "candidate")
            source = git("rev-parse", "HEAD")
            tree = git("rev-parse", "HEAD^{tree}")
            command = [
                "python3",
                str(HERE / "prepare_candidate.py"),
                "--mode",
                "synthetic-merge",
                "--base-sha",
                base,
                "--output",
                str(root / "identity.json"),
            ]
            observed = []
            for _ in range(2):
                git("checkout", "--detach", source)
                subprocess.run(command, cwd=repo, check=True, capture_output=True)
                identity = json.loads((root / "identity.json").read_text())
                self.assertEqual(identity["sourceCommit"], source)
                self.assertEqual(identity["baseCommit"], base)
                self.assertEqual(identity["candidateTree"], tree)
                observed.append(identity["candidateCommit"])
            self.assertEqual(observed[0], observed[1])
            git("checkout", "fixture")
            self.assertNotEqual(
                subprocess.run(command, cwd=repo, capture_output=True).returncode, 0
            )
            self.assertEqual(git("rev-parse", "HEAD"), source)
            git("checkout", "--detach", source)
            (repo / "source").write_text("uncommitted user work\n")
            self.assertNotEqual(
                subprocess.run(command, cwd=repo, capture_output=True).returncode, 0
            )
            self.assertEqual((repo / "source").read_text(), "uncommitted user work\n")


if __name__ == "__main__":
    unittest.main()
