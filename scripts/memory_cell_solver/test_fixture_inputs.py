"""Pinned source restoration and credential confinement with no external I/O."""

import base64
import hashlib
import io
import json
from email.message import Message
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.request
import urllib.response

import fixture_inputs


class SourceRestorationTests(unittest.TestCase):
    def setUp(self):
        self.raw = b"pinned historical fixture\n"
        self.path = "scripts/original.py"
        self.commit = "a" * 40
        self.body = {
            "type": "file",
            "encoding": "base64",
            "path": self.path,
            "content": base64.encodebytes(self.raw).decode(),
            "sha": hashlib.sha1(
                f"blob {len(self.raw)}\0".encode() + self.raw
            ).hexdigest(),
            "size": len(self.raw),
        }
        self.environment = {
            "GITHUB_REPOSITORY": fixture_inputs.REPOSITORY,
            "GITHUB_TOKEN": "synthetic-restoration-canary",
        }

    def restore(self, *, body=None, redirect=None):
        seen = []
        payload = json.dumps(self.body).encode() if body is None else body

        class FixtureTransport(urllib.request.BaseHandler):
            handler_order = 400

            def https_open(self, request):
                seen.append(request)
                headers = Message()
                is_redirect = redirect is not None and len(seen) == 1
                if is_redirect:
                    headers["Location"] = redirect
                response = urllib.response.addinfourl(
                    io.BytesIO(b"" if is_redirect else payload),
                    headers,
                    request.full_url,
                    302 if is_redirect else 200,
                )
                response.msg = "Found" if is_redirect else "OK"
                return response

            http_open = https_open

        build = urllib.request.build_opener

        def opener(*handlers):
            return build(urllib.request.ProxyHandler({}), FixtureTransport(), *handlers)

        with (
            patch.dict(fixture_inputs.os.environ, self.environment),
            patch.object(
                fixture_inputs.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=128),
            ),
            patch.object(
                fixture_inputs.urllib.request, "build_opener", side_effect=opener
            ),
            patch.object(
                fixture_inputs.urllib.request, "urlopen", side_effect=opener().open
            ),
        ):
            try:
                return fixture_inputs.historical_file(
                    "/unused", self.commit, self.path
                ), seen
            finally:
                self.assertTrue(seen)
                self.assertEqual(
                    len(seen), 1, "credential-bearing request followed a redirect"
                )

    def test_local_git_object_never_needs_restoration_credentials(self):
        with (
            patch.object(
                fixture_inputs.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0, stdout=self.raw),
            ),
            patch.object(fixture_inputs.urllib.request, "build_opener") as remote,
        ):
            raw, receipt = fixture_inputs.historical_file(
                "/unused", self.commit, self.path
            )
        self.assertEqual(raw, self.raw)
        self.assertEqual(receipt["transport"], "local_git_object")
        remote.assert_not_called()

    def test_exact_api_bytes_and_wrapped_base64_bind_to_git_metadata(self):
        (raw, receipt), seen = self.restore()
        self.assertEqual(raw, self.raw)
        self.assertEqual(receipt["git_blob"], self.body["sha"])
        self.assertEqual(receipt["response_size"], len(self.raw))
        self.assertEqual(
            seen[0].get_header("Authorization"), "Bearer synthetic-restoration-canary"
        )

    def test_authenticated_redirect_is_refused_before_any_second_request(self):
        for destination in (
            "https://other.fixture.invalid/source",
            "http://api.github.com/source",
        ):
            with self.subTest(destination=destination):
                with self.assertRaisesRegex(ValueError, "redirect refused"):
                    self.restore(redirect=destination)

    def test_oversized_api_body_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "byte budget"):
            self.restore(body=b" " * (fixture_inputs.MAX_RESPONSE_BYTES + 1))

    def test_invalid_base64_or_blob_metadata_cannot_be_retained_as_provenance(self):
        for field, value in (
            ("content", "@@@"),
            ("sha", "b" * 40),
            ("size", len(self.raw) + 1),
            ("size", True),
        ):
            with self.subTest(field=field, value=value):
                body = {**self.body, field: value}
                with self.assertRaises(ValueError):
                    self.restore(body=json.dumps(body).encode())


if __name__ == "__main__":
    unittest.main()
