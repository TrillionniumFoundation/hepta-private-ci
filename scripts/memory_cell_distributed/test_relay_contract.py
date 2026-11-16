"""Signature/run isolation and exact artifact archive admission without a model."""

import hashlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from artifact_relay import await_artifact
from relay_protocol import artifact_name, provenance, seal, verify
from rpc_costs import MeteredRPC


class RelayTests(unittest.TestCase):
    def setUp(self):
        context = patch.dict(
            os.environ,
            dict(SOURCE_SHA="a" * 40, GITHUB_RUN_ID="123", GITHUB_RUN_ATTEMPT="1"),
        )
        context.start()
        self.addCleanup(context.stop)

    def test_signed_source_cannot_be_replayed_in_another_run_or_modified(self):
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes_raw().hex()
        envelope = seal(dict(**provenance("offer"), value="retained"), key)
        self.assertEqual(verify(envelope, public, "offer")["value"], "retained")
        with patch.dict(os.environ, GITHUB_RUN_ID="124"):
            with self.assertRaises(ValueError):
                verify(envelope, public, "offer")
        envelope["payload"]["value"] = "changed"
        with self.assertRaises(ValueError):
            verify(envelope, public, "offer")

    def test_exact_artifact_digest_and_member_name_required(self):
        for member, corrupt, accepted in (
            ("offer.json", False, True),
            ("../offer.json", False, False),
            ("offer.json", True, False),
        ):
            with (
                self.subTest(member=member, corrupt=corrupt),
                tempfile.TemporaryDirectory() as directory,
            ):
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w") as archive:
                    archive.writestr(member, b'{"metadata":"only"}')
                raw = buffer.getvalue()
                run = dict(head_sha="a" * 40, run_attempt=1)
                item = dict(
                    id=12,
                    name=artifact_name("offer"),
                    expired=False,
                    digest="sha256:"
                    + ("b" * 64 if corrupt else hashlib.sha256(raw).hexdigest()),
                )
                responses = [run, dict(total_count=1, artifacts=[item]), raw]
                with patch("artifact_relay.api", side_effect=responses):
                    if accepted:
                        path = await_artifact("offer", Path(directory) / "download")
                        self.assertEqual(path.read_bytes(), b'{"metadata":"only"}')
                    else:
                        with self.assertRaises(ValueError):
                            await_artifact("offer", Path(directory) / "download")

    def test_rpc_failures_and_restart_never_refund_reserved_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "costs.jsonl"

            def failure(*_args, **_kwargs):
                raise OSError("lost connection")

            rpc = MeteredRPC(path, rpc=failure, maximum_calls=1)
            with self.assertRaises(OSError):
                rpc("https://source:443", None, dict(op="read"))
            restored = MeteredRPC(
                path, rpc=lambda *_args, **_kwargs: {}, maximum_calls=1
            )
            with self.assertRaisesRegex(ValueError, "budget exhausted"):
                restored("https://source:443", None, dict(op="read"))


if __name__ == "__main__":
    unittest.main()
