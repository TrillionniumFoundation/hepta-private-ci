import io
from contextlib import redirect_stdout
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import capture_original_job_logs as capture


class CaptureTests(unittest.TestCase):
    def test_signed_redirect_uses_fresh_credential_free_request_and_exact_bytes(self):
        requests = []
        raw = b"original\x00bytes\xff\n"

        def open_request(request, deadline):
            requests.append(request)
            if len(requests) == 1:
                raise HTTPError(
                    request.full_url,
                    302,
                    "redirect",
                    {"Location": "https://logs.example/original?sig=private"},
                    io.BytesIO(),
                )
            return io.BytesIO(raw)

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(capture, "open_request", open_request),
        ):
            path = Path(temporary) / "log"
            capture.download_log("ephemeral-secret", path, time.monotonic() + 10)
            self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(
            requests[0].get_header("Authorization"), "Bearer ephemeral-secret"
        )
        self.assertEqual(requests[1].header_items(), [])

    def test_bound_preserves_exact_prefix_and_expired_deadline_refuses(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "partial"
            with self.assertRaises(ValueError):
                capture.retain(io.BytesIO(b"12345"), path, 4, time.monotonic() + 10)
            self.assertEqual(path.read_bytes(), b"1234")
            with self.assertRaises(TimeoutError):
                capture.retain(io.BytesIO(b"x"), Path(temporary) / "expired", 4, 0)

    def test_failure_artifact_never_retains_error_url_or_token(self):
        error = HTTPError(
            "https://logs.example/?sig=private", 403, "secret", {}, io.BytesIO()
        )
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict(capture.os.environ, {"GITHUB_TOKEN": "ephemeral-secret"}),
            patch.object(capture, "open_request", side_effect=error),
            redirect_stdout(io.StringIO()) as console,
        ):
            path = Path(temporary)
            self.assertEqual(capture.main(path), 1)
            result = (path / "RESULT.json").read_text()
            self.assertEqual(json.loads(result)["status"], "failed")
            for value in (result, console.getvalue()):
                self.assertNotIn("ephemeral-secret", value)
                self.assertNotIn("sig=private", value)


if __name__ == "__main__":
    unittest.main()
