"""Subprocess failures exercise publication boundaries, not storage power loss."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from .atomic_io import atomic_publish, identity, publish_json


@unittest.skipUnless(os.name == "posix", "POSIX research persistence")
class AtomicPublicationTests(unittest.TestCase):
    def test_serialization_failure_preserves_namespace_and_previous_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint"

            def broken(stream):
                stream.write(b"partial")
                raise OSError("serialization interrupted")

            with self.assertRaises(OSError):
                atomic_publish(path, broken)
            self.assertFalse(path.exists())
            first = publish_json(path, {"epoch": 3, "optimizer_steps": 12})
            with self.assertRaises(FileExistsError):
                atomic_publish(path, broken)
            self.assertEqual(identity(path), first)
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_invalid_or_empty_serialization_never_publishes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint"
            with self.assertRaises(ValueError):
                atomic_publish(path, lambda stream: None)
            with self.assertRaises(json.JSONDecodeError):
                atomic_publish(
                    path,
                    lambda stream: stream.write(b"{"),
                    lambda candidate: json.loads(candidate.read_bytes()),
                )
            self.assertFalse(path.exists())
            with self.assertRaises(ValueError):
                publish_json(path, {"invalid": float("nan")})
            self.assertFalse(path.exists())

    def test_changed_validator_bytes_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint"
            with self.assertRaises(ValueError):
                atomic_publish(
                    path,
                    lambda stream: stream.write(b"original"),
                    lambda candidate: candidate.write_bytes(b"mutated"),
                )
            self.assertFalse(path.exists())

    def test_file_sync_failure_does_not_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint"
            with patch("os.fsync", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    publish_json(path, {"epoch": 2})
            self.assertFalse(path.exists())

    def test_kill_during_serialization_or_after_link(self):
        for boundary in ("during_write", "after_link"):
            with (
                self.subTest(boundary=boundary),
                tempfile.TemporaryDirectory() as directory,
            ):
                path = Path(directory) / "checkpoint"
                program = """
import os, sys
from pathlib import Path
from unittest.mock import patch
from proposals.hcsn_persistence_v1.atomic_io import atomic_publish
path, boundary = Path(sys.argv[1]), sys.argv[2]
def writer(stream):
    stream.write(b'{"epoch":7}')
    stream.flush()
    if boundary == 'during_write':
        os._exit(73)
real_link = os.link
def link_then_stop(source, target):
    real_link(source, target)
    os._exit(73)
if boundary == 'after_link':
    with patch('os.link', side_effect=link_then_stop):
        atomic_publish(path, writer)
else:
    atomic_publish(path, writer)
"""
                result = subprocess.run(
                    [sys.executable, "-B", "-c", program, str(path), boundary],
                    check=False,
                    timeout=20,
                )
                self.assertEqual(result.returncode, 73)
                if boundary == "during_write":
                    self.assertFalse(path.exists())
                else:
                    self.assertEqual(json.loads(path.read_bytes()), {"epoch": 7})
                    with self.assertRaises(FileExistsError):
                        publish_json(path, {"epoch": 8})
                self.assertEqual(len(list(Path(directory).glob("*.tmp"))), 1)

    def test_competing_publishers_cannot_clobber(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint"
            program = """
import sys
from proposals.hcsn_persistence_v1.atomic_io import publish_json
try:
    publish_json(sys.argv[1], {'writer': int(sys.argv[2])})
except FileExistsError:
    sys.exit(17)
"""
            children = [
                subprocess.Popen(
                    [sys.executable, "-B", "-c", program, str(path), str(index)]
                )
                for index in range(4)
            ]
            exits = [child.wait(timeout=20) for child in children]
            self.assertEqual(sorted(exits), [0, 17, 17, 17])
            self.assertEqual(json.loads(path.read_bytes())["writer"], exits.index(0))


if __name__ == "__main__":
    unittest.main()
