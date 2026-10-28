"""Validate immutable-object transfer without credentials or network."""

import base64
import gzip
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ndu_reviewed_object_transfer as transfer


class ReviewedObjectTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repository = self.root / "repository"
        self.artifact = self.root / "artifact"
        self.repository.mkdir()
        self.artifact.mkdir()
        result = b'{"verified": true}\n'
        (self.artifact / "RESULT.json").write_bytes(result)
        self.result_sha = hashlib.sha256(result).hexdigest()
        active = patch.object(transfer, "ORIGIN_RESULT", self.result_sha)
        active.start()
        self.addCleanup(active.stop)
        self.manifest = {
            "schema": "hepta.reviewed-object-transfer.v1",
            "repository": transfer.REPOSITORY,
            "origin": {
                "run_id": 40656660435,
                "artifact_id": 12801988362,
                "result_sha256": self.result_sha,
            },
            "files": [],
        }
        raw = b"actual generated lock\n"
        target = self.artifact / "files/MODULE.bazel.lock"
        target.parent.mkdir(parents=True)
        target.write_bytes(raw)
        self.manifest["files"].append(
            {
                "path": "MODULE.bazel.lock",
                **transfer.identity(raw),
                "source": {"kind": "artifact", "path": "files/MODULE.bazel.lock"},
            }
        )
        self.write_manifest()

    def write_manifest(self):
        path = self.repository / transfer.MANIFEST
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.manifest))

    def test_exact_artifact_and_encoded_payloads(self):
        raw = b"recorded scientific evidence\n"
        encoded = base64.b64encode(gzip.compress(raw, mtime=0)) + b"\n"
        (self.repository / "part.b64").write_bytes(encoded)
        self.manifest["files"].append(
            {
                "path": "evidence.json",
                **transfer.identity(raw),
                "source": {
                    "kind": "gzip-base64-parts",
                    "parts": [
                        {
                            "path": "part.b64",
                            "bytes": len(encoded),
                            "sha256": hashlib.sha256(encoded).hexdigest(),
                        }
                    ],
                },
            }
        )
        self.write_manifest()
        rows = transfer.checked_payloads(self.repository, self.artifact)
        self.assertEqual(
            [value for _, value in rows], [b"actual generated lock\n", raw]
        )

    def test_modified_result_or_payload_refused(self):
        (self.artifact / "files/MODULE.bazel.lock").write_bytes(b"different")
        with self.assertRaisesRegex(ValueError, "Object identity"):
            transfer.checked_payloads(self.repository, self.artifact)
        (self.artifact / "RESULT.json").write_bytes(b"wrong producer")
        with self.assertRaisesRegex(ValueError, "Producer result"):
            transfer.checked_payloads(self.repository, self.artifact)

    def test_path_escape_and_symlink_refused(self):
        with self.assertRaisesRegex(ValueError, "Unsafe input"):
            transfer.regular_bytes(self.repository, "../artifact/RESULT.json")
        (self.repository / "linked").symlink_to(self.artifact / "RESULT.json")
        with self.assertRaisesRegex(ValueError, "Symlink"):
            transfer.regular_bytes(self.repository, "linked")

    def test_oversize_and_duplicate_refused(self):
        self.manifest["files"][0]["bytes"] = transfer.MAX_RAW_BYTES + 1
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "reviewed bound"):
            transfer.checked_payloads(self.repository, self.artifact)
        self.manifest["files"][0]["bytes"] = len(b"actual generated lock\n")
        self.manifest["files"].append(self.manifest["files"][0])
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            transfer.checked_payloads(self.repository, self.artifact)

    def test_api_is_only_immutable_blob_post(self):
        raw = b"reviewed"
        expected = transfer.identity(raw)["git_blob_sha"]
        requests = []

        class Client:
            def open(self, request, timeout):
                requests.append((request, timeout))
                return io.BytesIO(json.dumps({"sha": expected}).encode())

        with patch.object(
            transfer.urllib.request, "build_opener", return_value=Client()
        ):
            self.assertEqual(
                transfer.publish_blob(raw, expected, "fixture-token"), expected
            )
        request, timeout = requests[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(
            request.full_url,
            "https://api.github.com/repos/" + transfer.REPOSITORY + "/git/blobs",
        )
        self.assertEqual(base64.b64decode(json.loads(request.data)["content"]), raw)
        self.assertEqual(timeout, 60)
        with self.assertRaisesRegex(ValueError, "redirect refused"):
            transfer.NoRedirect().redirect_request(
                None, None, 302, "redirect", {}, "https://example.invalid/"
            )


if __name__ == "__main__":
    unittest.main()
