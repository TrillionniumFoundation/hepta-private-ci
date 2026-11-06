"""Real filesystem substitutions; fixtures do not claim model execution."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from closure_common import ClosureError, ClosureLimits, read_capped, sha
from closure_inputs import _encoder_file
from closure_io import open_regular


@unittest.skipUnless(os.name == "posix", "POSIX descriptor qualification")
class DescriptorTests(unittest.TestCase):
    def test_fifo_directory_and_links_refuse_without_blocking(self):
        code = """
import os, pathlib, tempfile
from closure_common import ClosureError, read_capped
with tempfile.TemporaryDirectory() as d:
    p=pathlib.Path(d)
    os.mkfifo(p/'fifo')
    (p/'file').write_bytes(b'contents')
    (p/'link').symlink_to(p/'file')
    for path in (p/'fifo',p/'link',p):
        try: read_capped(path, 32)
        except ClosureError: pass
        else: raise AssertionError('nonregular input was accepted')
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            timeout=3,
        )
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_replacement_at_actual_open_refuses_fifo_and_symlink(self):
        for kind in ("fifo", "symlink"):
            for reader in ("bytes", "encoder"):
                with (
                    self.subTest(kind=kind, reader=reader),
                    tempfile.TemporaryDirectory() as d,
                ):
                    root = Path(d)
                    source = root / "model"
                    source.write_bytes(b"original")
                    other = root / "replacement"
                    other.write_bytes(b"original")
                    original_open, switched = os.open, False

                    def replace(path, flags, *args, **kwargs):
                        nonlocal switched
                        if Path(path).name == "model" and not switched:
                            switched = True
                            source.unlink()
                            if kind == "fifo":
                                os.mkfifo(source)
                            else:
                                source.symlink_to(other)
                        return original_open(path, flags, *args, **kwargs)

                    identity = {
                        "bytes": 8,
                        "sha256": sha(b"original"),
                        "source_digest": sha(b"original"),
                        "source_digest_kind": "sha256",
                    }
                    with mock.patch("closure_io.os.open", side_effect=replace):
                        with self.assertRaises(ClosureError):
                            if reader == "bytes":
                                read_capped(source, 8)
                            else:
                                _encoder_file(root, "model", identity, ClosureLimits())
                    self.assertTrue(switched)

    def test_path_replacement_never_reads_the_new_target(self):
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "model"
            source.write_bytes(b"original")
            replacement = Path(d) / "replacement"
            replacement.write_bytes(b"hostile!")
            with self.assertRaises(ClosureError):
                with open_regular(source, 8) as stream:
                    replacement.replace(source)
                    self.assertEqual(stream.read(), b"original")

    def test_parent_substitution_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "nested").mkdir()
            (root / "outside").mkdir()
            (root / "outside/model").write_bytes(b"outside")
            original_open = os.open

            def replace(path, flags, *args, **kwargs):
                if str(path) == "nested":
                    (root / "nested").rmdir()
                    (root / "nested").symlink_to(
                        root / "outside", target_is_directory=True
                    )
                return original_open(path, flags, *args, **kwargs)

            with mock.patch("closure_io.os.open", side_effect=replace):
                with self.assertRaises(ClosureError):
                    with open_regular("nested/model", 32, root=root):
                        self.fail("linked parent was opened")

    def test_inplace_mutation_and_oversize_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "model"
            path.write_bytes(b"original")
            with self.assertRaises(ClosureError):
                read_capped(path, 7)
            with self.assertRaises(ClosureError):
                with open_regular(path, 8) as stream:
                    stream.read()
                    path.write_bytes(b"changed!")


if __name__ == "__main__":
    unittest.main()
