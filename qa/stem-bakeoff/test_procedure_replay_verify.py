"""Adversarial audit evidence boundary tests; no model calls."""

import gzip
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from procedure_replay_verify import archive_member, read_rows
import procedure_replay_verify as auditor


class ProcedureReplayVerifierBoundaryTests(unittest.TestCase):
    def test_nested_file_is_valid(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "nested").mkdir()
            (root / "nested" / "safe.json").write_text("{}")
            self.assertEqual(archive_member(root, "nested/safe.json"),
                             root / "nested" / "safe.json")

    def test_absolute_parent_and_windows_paths_denied(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "evidence").mkdir()
            outside = root / "private.json"
            outside.write_text("secret")
            for name in ("../private.json", str(outside), "..\\private.json"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    archive_member(root / "evidence", name)

    def test_symlinked_ancestor_or_member_denied(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "regular").mkdir()
            (root / "regular" / "ok.json").write_text("{}")
            try:
                (root / "alias").symlink_to("regular", target_is_directory=True)
                (root / "alias.json").symlink_to("regular/ok.json")
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            for name in ("alias/ok.json", "alias.json"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    archive_member(root, name)

    def test_compressed_expansion_and_member_bytes_are_bounded(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "data.json.gz"
            path.write_bytes(gzip.compress(b"{}\n" * 30))
            with patch.object(auditor, "MAX_MEMBER_BYTES", 4):
                with self.assertRaises(ValueError):
                    archive_member(d, path.name)
            with patch.object(auditor, "MAX_EXPANDED_BYTES", 32):
                with self.assertRaisesRegex(ValueError, "expanded"):
                    read_rows(path)
            self.assertEqual(len(read_rows(path)), 30)

    def test_python_optimized_mode_cannot_issue_pass(self):
        child = subprocess.run(
            [sys.executable, "-O", "-c",
             "from procedure_replay_verify import verify; verify('/missing', '0'*64)"],
            cwd=Path(__file__).parent, capture_output=True, text=True, check=False)
        self.assertNotEqual(child.returncode, 0)
        self.assertIn("optimized Python disables required archive audit assertions",
                      child.stderr)


if __name__ == "__main__":
    unittest.main()
