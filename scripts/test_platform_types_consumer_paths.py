#!/usr/bin/env python3
"""Exercise consumer-map path admission; these are not product execution tests."""

import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import verify_platform_types_consumers as consumers


class ConsumerSourcePathTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "repository"
        self.root.mkdir()
        self.matrix = json.loads(consumers.MATRIX.read_text(encoding="utf-8"))
        for row in self.matrix["consumers"]:
            target = self.root / row["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((consumers.ROOT / row["path"]).read_bytes())
        self.qualification = (
            self.root / "scripts/run_platform_types_consumer_qualification.sh"
        )
        self.qualification.parent.mkdir(parents=True, exist_ok=True)
        self.qualification.write_bytes(consumers.QUALIFICATION.read_bytes())
        self.matrix_path = self.root / "consumer-matrix.json"
        self.original_path = self.matrix["consumers"][0]["path"]
        self.source = self.root / self.original_path
        self.outside = self.base / "outside.py"
        self.outside.write_bytes(self.source.read_bytes())

    def verify(self, path):
        self.matrix["consumers"][0]["path"] = path
        self.matrix_path.write_text(json.dumps(self.matrix), encoding="utf-8")
        with patch.multiple(
            consumers,
            ROOT=self.root,
            MATRIX=self.matrix_path,
            QUALIFICATION=self.qualification,
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                return consumers.main()

    def test_declared_repository_regular_files_pass(self):
        self.assertEqual(self.verify(self.original_path), 0)

    def test_absolute_paths_reject_inside_and_outside_repository(self):
        for path in (str(self.source), str(self.outside)):
            with self.subTest(path=path), self.assertRaises(SystemExit):
                self.verify(path)

    def test_parent_traversal_rejects_even_when_it_returns_inside(self):
        for path in ("../outside.py", "scripts/../" + self.original_path):
            with self.subTest(path=path), self.assertRaises(SystemExit):
                self.verify(path)

    def test_noncanonical_and_other_platform_paths_reject(self):
        for path in (
            "./" + self.original_path,
            self.original_path.replace("/", "//", 1),
            self.original_path + "/",
            "C:/source.py",
            "C:source.py",
            r"C:\source.py",
            self.original_path.replace("/", "\\"),
            "source\0.py",
        ):
            with self.subTest(path=path), self.assertRaises(SystemExit):
                self.verify(path)

    def test_missing_or_nonregular_final_source_rejects(self):
        for path in ("missing.py", "scripts"):
            with self.subTest(path=path), self.assertRaises(SystemExit):
                self.verify(path)

    @unittest.skipIf(os.name == "nt", "symlinks need Windows runner privileges")
    def test_file_symlinks_reject_inside_outside_and_broken_targets(self):
        link = self.root / "linked.py"
        for target in (self.source, self.outside, self.base / "missing.py"):
            with self.subTest(target=target):
                link.symlink_to(target)
                try:
                    with self.assertRaises(SystemExit):
                        self.verify("linked.py")
                finally:
                    link.unlink()

    @unittest.skipIf(os.name == "nt", "symlinks need Windows runner privileges")
    def test_directory_symlinks_reject_inside_and_outside_targets(self):
        link = self.root / "linked"
        for target, filename in (
            (self.source.parent, self.source.name),
            (self.base, self.outside.name),
        ):
            with self.subTest(target=target):
                link.symlink_to(target, target_is_directory=True)
                try:
                    with self.assertRaises(SystemExit):
                        self.verify("linked/" + filename)
                finally:
                    link.unlink()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO creation is unavailable")
    def test_fifo_rejects_without_opening_it(self):
        os.mkfifo(self.root / "source.fifo")
        with self.assertRaises(SystemExit):
            self.verify("source.fifo")


if __name__ == "__main__":
    unittest.main()
