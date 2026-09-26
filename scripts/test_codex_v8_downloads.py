"""Concurrent V8 acquisition must not publish unchecked or delete peer bytes."""

import hashlib
import io
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from codex_package import v8


class DownloadPublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.dest = self.root / "artifact.a.gz"
        self.payload = b"verified archive bytes"
        self.digest = hashlib.sha256(self.payload).hexdigest()

    def test_valid_cache_does_not_use_network(self):
        self.dest.write_bytes(self.payload)
        with patch.object(v8, "urlopen") as request:
            v8.ensure_valid_artifact(
                self.dest, self.digest, "https://invalid.test/artifact"
            )
        request.assert_not_called()

    def test_download_failure_preserves_previous_cache_entry(self):
        self.dest.write_bytes(b"previous version")
        with patch.object(v8, "urlopen", side_effect=OSError("transport failed")):
            with self.assertRaises(OSError):
                v8.ensure_valid_artifact(
                    self.dest, self.digest, "https://invalid.test/artifact"
                )
        self.assertEqual(self.dest.read_bytes(), b"previous version")
        self.assertEqual(list(self.root.iterdir()), [self.dest])

    def test_checksum_failure_never_replaces_previous_bytes(self):
        self.dest.write_bytes(b"previous version")
        with patch.object(v8, "urlopen", return_value=io.BytesIO(b"corrupt")):
            with self.assertRaises(RuntimeError):
                v8.ensure_valid_artifact(
                    self.dest, self.digest, "https://invalid.test/artifact"
                )
        self.assertEqual(self.dest.read_bytes(), b"previous version")
        self.assertEqual(list(self.root.iterdir()), [self.dest])

    def test_verified_download_is_published_and_has_no_staging_file(self):
        with patch.object(v8, "urlopen", return_value=io.BytesIO(self.payload)):
            v8.ensure_valid_artifact(
                self.dest, self.digest, "https://invalid.test/artifact"
            )
        self.assertEqual(self.dest.read_bytes(), self.payload)
        self.assertEqual(list(self.root.iterdir()), [self.dest])

    def test_simultaneous_downloads_do_not_share_staging_files(self):
        barrier = threading.Barrier(2)

        class SynchronizedResponse(io.BytesIO):
            def read(self, size=-1):
                if self.tell() == 0:
                    barrier.wait(timeout=10)
                return super().read(size)

        with (
            patch.object(
                v8,
                "urlopen",
                side_effect=lambda *a, **k: SynchronizedResponse(self.payload),
            ),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            jobs = [
                pool.submit(
                    v8.ensure_valid_artifact,
                    self.dest,
                    self.digest,
                    "https://invalid.test/artifact",
                )
                for _ in range(2)
            ]
            for job in jobs:
                job.result(timeout=15)
        self.assertEqual(self.dest.read_bytes(), self.payload)
        self.assertEqual(list(self.root.iterdir()), [self.dest])


if __name__ == "__main__":
    unittest.main()
