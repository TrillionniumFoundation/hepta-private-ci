"""Mock transport/byte-hash tests: no external data or real pretrained inference."""
from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import public_agnews_source as source


class FakeResponse:
    status_code = 429
    headers = {"Retry-After": "201"}


class RateLimitedError(RuntimeError):
    response = FakeResponse()


class PublicSourceTests(unittest.TestCase):
    def fixture(self, folder: Path):
        data = folder / "verified-inventory.parquet"
        data.write_bytes(b"unit-test-public-dataset-bytes")
        return data, hashlib.sha256(data.read_bytes()).hexdigest()

    def test_full_sha_is_pinned_from_actual_successful_source_run(self):
        self.assertEqual(source.DATASET_COMMIT,
                         "98c532231d96ae10e176a909192ecac548949288")
        self.assertEqual(len(source.DATASET_COMMIT), 40)

    def test_429_bounded_retry_keeps_exact_commit_and_file_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixture, digest = self.fixture(root)
            calls, slept = [], []

            def downloader(**kwargs):
                calls.append(kwargs)
                if len(calls) == 1:
                    raise RateLimitedError("429")
                return fixture

            with patch.object(source, "FILES", {"train": ("train.parquet", digest)}), \
                 patch.object(source, "check_file", return_value=digest):
                output = source.download_checked(
                    "train", root / "snapshot.parquet", downloader=downloader,
                    sleeper=slept.append)
            self.assertEqual(output["rate_limit_retries"], 1)
            self.assertEqual(slept, [201])
            self.assertEqual(output["source_sha256"], digest)
            self.assertEqual(len(calls), 2)
            self.assertTrue(all(call["revision"] == source.DATASET_COMMIT for call in calls))
            self.assertTrue(all(call["filename"] == "train.parquet" for call in calls))
            self.assertEqual(output["production_promotion"], "DENY_ALL")

    def test_exhausted_rate_limit_does_not_write_or_invent_source(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "snapshot.parquet"
            calls, waits = [], []

            def denied(**kwargs):
                calls.append(kwargs)
                raise RateLimitedError("429")

            with self.assertRaises(source.DatasetFetchError):
                source.download_checked("new_val2", path, downloader=denied,
                                        sleeper=waits.append)
            self.assertEqual(len(calls), source.MAX_ATTEMPTS)
            self.assertEqual(len(waits), source.MAX_ATTEMPTS - 1)
            self.assertFalse(path.exists())

    def test_invalid_roles_and_digest_mismatch_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixture, digest = self.fixture(root)
            with self.assertRaises(source.DatasetFetchError):
                source.download_checked("unknown", root / "unknown.parquet",
                                        downloader=lambda **kwargs: fixture)
            with patch.object(source, "FILES", {"train": ("train.parquet", "a"*64)}), \
                 patch.object(source, "check_file", side_effect=ValueError("sha mismatch")):
                with self.assertRaises(ValueError):
                    source.download_checked("train", root / "mismatch.parquet",
                                            downloader=lambda **kwargs: fixture)
            self.assertFalse((root / "mismatch.parquet").exists())
            self.assertEqual(len(digest), 64)

    def test_non_rate_limit_does_not_wait_or_create_file(self):
        class NotFound(RuntimeError):
            response = type("Response", (), {"status_code": 404, "headers": {}})()

        with tempfile.TemporaryDirectory() as folder:
            waits = []
            with self.assertRaises(source.DatasetFetchError):
                source.download_checked("train", Path(folder) / "missing",
                                        downloader=lambda **kwargs: (_ for _ in ()).throw(NotFound()),
                                        sleeper=waits.append)
            self.assertEqual(waits, [])

if __name__ == "__main__":
    unittest.main()
