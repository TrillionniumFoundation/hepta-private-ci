"""Network-boundary fixtures; no external requests or research acquisition."""

import io
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from .acquire_vizwiz import CAP, DownloadBudget
from .extend_vizwiz import extend


class Response(io.BytesIO):
    def __init__(self, body, *, status, headers):
        super().__init__(body)
        self.status, self.headers, self.url = (
            status,
            headers,
            "https://fixture.invalid/archive.zip",
        )
        self.read_calls = 0

    def read(self, size=-1):
        self.read_calls += 1
        return super().read(size)


class DownloadContainmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.download = DownloadBudget(Path(self.temp.name))

    def test_ignored_range_refuses_full_archive_before_body_read(self):
        response = Response(
            b"must not consume", status=200, headers={"Content-Length": "12000000000"}
        )
        with (
            patch("urllib.request.urlopen", return_value=response),
            self.assertRaisesRegex(ValueError, "exact byte range"),
        ):
            self.download.fetch(response.url, span=(10, 19))
        self.assertEqual(response.read_calls, 0)
        self.assertEqual(self.download.bytes_read, 0)
        self.assertEqual(self.download.receipts[0]["status"], "failed")

    def test_archive_change_and_truncated_ranges_retain_failed_attempts(self):
        response = Response(
            b"different bytes",
            status=206,
            headers={"Content-Range": "bytes 10-19/100", "ETag": '"changed"'},
        )
        with (
            patch("urllib.request.urlopen", return_value=response),
            self.assertRaisesRegex(ValueError, "ETag changed"),
        ):
            self.download.fetch(response.url, span=(10, 19), etag='"original"')
        self.assertEqual(response.read_calls, 0)
        short = Response(
            b"short",
            status=206,
            headers={"Content-Range": "bytes 10-19/100", "ETag": '"original"'},
        )
        with (
            patch("urllib.request.urlopen", return_value=short),
            self.assertRaisesRegex(ValueError, "Truncated"),
        ):
            self.download.fetch(short.url, span=(10, 19), etag='"original"')
        self.assertEqual(self.download.bytes_read, 5)
        self.assertEqual(
            [row["status"] for row in self.download.receipts], ["failed", "failed"]
        )

    def test_missing_length_cannot_consume_more_than_shared_cap(self):
        response = Response(b"x" * 40, status=200, headers={})
        with (
            patch("urllib.request.urlopen", return_value=response),
            patch("ndu_semantic_state.acquire_vizwiz.CAP", 10),
            self.assertRaisesRegex(ValueError, "budget exhausted"),
        ):
            self.download.fetch(response.url)
        self.assertEqual(self.download.bytes_read, 10)
        self.assertEqual(self.download.receipts[0]["bytes_read"], 10)
        self.assertEqual(self.download.receipts[0]["status"], "failed")

    def test_extension_cannot_reset_an_exhausted_prior_budget(self):
        root = Path(self.temp.name)
        (root / "CANDIDATES.json").write_text(
            json.dumps({"cases": [{"project_split": "development"}] * 3})
        )
        (root / "HISTORY.json").write_text("{}")
        (root / "ACQUISITION_RECEIPT.json").write_text(
            json.dumps({"status": "completed", "body_bytes_read": CAP})
        )
        with (
            patch.object(DownloadBudget, "fetch") as fetch,
            self.assertRaisesRegex(ValueError, "remaining shared budget"),
        ):
            extend(root, root / "must-not-exist")
        fetch.assert_not_called()
        self.assertFalse((root / "must-not-exist").exists())

    def test_extension_cannot_reassign_original_development_roles(self):
        root = Path(self.temp.name)
        (root / "CANDIDATES.json").write_text(
            json.dumps({"cases": [{"project_split": "train"}] * 3})
        )
        (root / "HISTORY.json").write_text("{}")
        (root / "ACQUISITION_RECEIPT.json").write_text(
            json.dumps({"status": "completed", "body_bytes_read": 1})
        )
        with (
            patch.object(DownloadBudget, "fetch") as fetch,
            self.assertRaisesRegex(ValueError, "original three development roles"),
        ):
            extend(root, root / "must-not-exist")
        fetch.assert_not_called()
        self.assertFalse((root / "must-not-exist").exists())


if __name__ == "__main__":
    unittest.main()
