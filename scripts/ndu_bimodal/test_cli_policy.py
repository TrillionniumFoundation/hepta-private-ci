"""Test fail-closed exact-policy preflight without any native actor execution."""

import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from .cli import resolve_native_policy, main


class NativePolicyAdmissionTests(unittest.TestCase):
    def test_static_options_keep_exact_identity(self):
        for policy in ("encoder-only", "static-quota", "fixed-steps"):
            with self.subTest(policy=policy):
                self.assertEqual(resolve_native_policy(policy), (policy, None))
                self.assertEqual(
                    resolve_native_policy(policy, require_exact=True), (policy, None)
                )

    def test_dynamic_is_explicit_fallback_but_not_an_exact_policy(self):
        actual, reason = resolve_native_policy("dynamic")
        self.assertEqual(actual, "static-quota")
        self.assertIn("future net-gain absent", reason)
        with self.assertRaisesRegex(ValueError, "Native dynamic policy not admitted"):
            resolve_native_policy("dynamic", require_exact=True)
        for policy in ("DYNAMIC", "unknown", None):
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                resolve_native_policy(policy)
        with self.assertRaises(ValueError):
            resolve_native_policy("dynamic", require_exact=1)

    def test_strict_cli_refuses_before_loading_inputs_or_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "must-not-exist"
            arguments = [
                "ndu_bimodal",
                "infer",
                "--weights",
                "unreadable-weights",
                "--weights-sha256",
                "0" * 64,
                "--binary",
                "unreadable-binary",
                "--binary-sha256",
                "0" * 64,
                "--text",
                "public prompt",
                "--image",
                "unreadable-image",
                "--output",
                str(output),
                "--policy",
                "dynamic",
                "--require-exact-policy",
            ]
            with (
                patch.object(sys, "argv", arguments),
                patch("scripts.ndu_bimodal.cli.bounded_bytes", side_effect=AssertionError("read forbidden")),
                patch("scripts.ndu_bimodal.cli.NativeSession", side_effect=AssertionError("native dispatch forbidden")),
                patch("scripts.ndu_bimodal.cli.torch.set_num_threads", side_effect=AssertionError("Torch setup forbidden")),
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaisesRegex(ValueError, "Native dynamic policy not admitted"),
            ):
                main()
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
