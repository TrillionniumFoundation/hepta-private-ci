#!/usr/bin/env python3
"""Bound transient V8 GET retries without changing artifact integrity gates."""

import hashlib
import io
from pathlib import Path
import ssl
import sys
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from codex_package import v8

URL = "https://example.test/rusty-v8/artifact"


def http_error(status: int) -> HTTPError:
    return HTTPError(URL, status, "fixture HTTP error", {}, None)


class V8DownloadTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dest = Path(directory.name) / "artifact.a.gz"
        self.temp = self.dest.with_suffix(".gz.tmp")
        open_patch = mock.patch.object(v8, "urlopen")
        self.open = open_patch.start()
        self.addCleanup(open_patch.stop)
        sleep_patch = mock.patch.object(v8.time, "sleep")
        self.sleep = sleep_patch.start()
        self.addCleanup(sleep_patch.stop)
        self.log = io.StringIO()
        log_patch = mock.patch.object(v8.sys, "stderr", self.log)
        log_patch.start()
        self.addCleanup(log_patch.stop)

    def test_each_transient_status_can_recover_with_a_verified_artifact(self) -> None:
        payload = b"verified artifact fixture"
        checksum = hashlib.sha256(payload).hexdigest()
        for status in (502, 503, 504):
            with self.subTest(status=status):
                self.dest.unlink(missing_ok=True)
                self.open.reset_mock()
                self.sleep.reset_mock()
                self.open.side_effect = [http_error(status), io.BytesIO(payload)]
                v8.ensure_valid_artifact(self.dest, checksum, URL)
                self.assertEqual(self.dest.read_bytes(), payload)
                self.assertFalse(self.temp.exists())
                self.assertEqual(self.open.call_count, 2)
                self.sleep.assert_called_once_with(1)
        self.assertIn("attempt 1/3", self.log.getvalue())
        self.assertIn("attempt 2/3", self.log.getvalue())

    def test_three_failures_preserve_destination_and_raise_last_http_error(self) -> None:
        self.dest.write_bytes(b"existing destination")
        self.temp.write_bytes(b"stale partial download")
        errors = [http_error(502), http_error(503), http_error(504)]
        self.open.side_effect = errors
        with self.assertRaises(HTTPError) as caught:
            v8.download_file(URL, self.dest)
        self.assertIs(caught.exception, errors[-1])
        self.assertEqual(self.dest.read_bytes(), b"existing destination")
        self.assertFalse(self.temp.exists())
        self.assertEqual(
            self.open.call_args_list,
            [mock.call(URL, timeout=120)] * 3,
        )
        self.assertEqual(self.sleep.call_args_list, [mock.call(1), mock.call(2)])
        self.assertIn("attempt 3/3", self.log.getvalue())

    def test_non_transient_http_tls_and_timeout_errors_are_not_retried(self) -> None:
        errors = [
            http_error(403),
            http_error(404),
            http_error(501),
            URLError(ssl.SSLCertVerificationError("fixture invalid certificate")),
            TimeoutError("fixture timeout"),
        ]
        for error in errors:
            with self.subTest(error=error):
                self.open.reset_mock()
                self.sleep.reset_mock()
                self.dest.write_bytes(b"existing destination")
                self.open.side_effect = error
                with self.assertRaises(type(error)) as caught:
                    v8.download_file(URL, self.dest)
                self.assertIs(caught.exception, error)
                self.open.assert_called_once_with(URL, timeout=120)
                self.sleep.assert_not_called()
                self.assertEqual(self.dest.read_bytes(), b"existing destination")
                self.assertFalse(self.temp.exists())

    def test_partial_response_is_removed_before_retry(self) -> None:
        partial = io.BytesIO(b"partial")
        good = io.BytesIO(b"complete")
        self.open.side_effect = [partial, good]
        original_copy = v8.shutil.copyfileobj

        def copy_response(response, output):
            original_copy(response, output)
            if response is partial:
                raise http_error(504)

        def after_cleanup(delay):
            self.assertEqual(delay, 1)
            self.assertFalse(self.temp.exists())
            self.assertFalse(self.dest.exists())

        self.sleep.side_effect = after_cleanup
        with mock.patch.object(v8.shutil, "copyfileobj", side_effect=copy_response):
            v8.download_file(URL, self.dest)
        self.assertEqual(self.dest.read_bytes(), b"complete")
        self.assertFalse(self.temp.exists())

    def test_checksum_mismatch_after_recovery_remains_fatal_without_redownload(self) -> None:
        self.open.side_effect = [http_error(504), io.BytesIO(b"wrong artifact")]
        with self.assertRaisesRegex(RuntimeError, "failed checksum validation"):
            v8.ensure_valid_artifact(
                self.dest, hashlib.sha256(b"correct").hexdigest(), URL
            )
        self.assertEqual(self.open.call_count, 2)
        self.sleep.assert_called_once_with(1)
        self.assertFalse(self.dest.exists())
        self.assertFalse(self.temp.exists())


if __name__ == "__main__":
    unittest.main()
