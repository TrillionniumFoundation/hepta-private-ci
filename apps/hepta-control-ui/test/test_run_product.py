import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "run_product", ROOT / "tools/run-product.py"
)
product = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(product)


@unittest.skipUnless(
    os.name == "posix", "Product bundle launcher currently requires Unix anchoring"
)
class ProductLaunchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root / "dist").mkdir()
        self.manifest = self.root / "dist/build-manifest.json"
        self.value = {
            "schema": "hepta.robrix-ui.build.v1",
            "browserRuntime": "rust-makepad-wasm",
            "fixtures": False,
            "sourceIdentity": {"sha256": "a" * 64},
        }
        self.manifest.write_text(json.dumps(self.value))

    def test_digest_is_derived_from_exact_current_build_bytes(self):
        with patch.object(
            product.subprocess, "check_output", return_value="a" * 64 + "\n"
        ):
            args = product.bundle_arguments(self.root)
        self.assertEqual(
            args,
            [
                "--ui-bundle",
                str((self.root / "dist").resolve()),
                "--ui-manifest-sha256",
                hashlib.sha256(self.manifest.read_bytes()).hexdigest(),
            ],
        )

    def test_stale_source_or_fixture_artifact_cannot_be_selected(self):
        with patch.object(product.subprocess, "check_output", return_value="b" * 64):
            with self.assertRaisesRegex(ValueError, "stale"):
                product.bundle_arguments(self.root)
        self.value["fixtures"] = True
        self.manifest.write_text(json.dumps(self.value))
        with patch.object(
            product.subprocess,
            "check_output",
            side_effect=AssertionError("must not execute stale fixture"),
        ):
            with self.assertRaisesRegex(ValueError, "production"):
                product.bundle_arguments(self.root)

    def test_oversize_manifest_fails_before_source_tool_execution(self):
        self.manifest.write_bytes(b" " * (product.MAX_MANIFEST_BYTES + 1))
        with patch.object(
            product.subprocess,
            "check_output",
            side_effect=AssertionError("must not execute"),
        ):
            with self.assertRaisesRegex(ValueError, "bound"):
                product.bundle_arguments(self.root)

    def test_fifo_manifest_fails_within_deadline_instead_of_blocking_launch(self):
        self.manifest.unlink()
        os.mkfifo(self.manifest)
        script = "import importlib.util, pathlib, sys; s=importlib.util.spec_from_file_location('p',sys.argv[1]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); m.bundle_arguments(pathlib.Path(sys.argv[2]))"
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                script,
                str(ROOT / "tools/run-product.py"),
                str(self.root),
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not a regular file", result.stderr)

    def test_symlink_manifest_and_ancestor_are_rejected(self):
        self.manifest.rename(self.root / "original.json")
        self.manifest.symlink_to(self.root / "original.json")
        with patch.object(product.subprocess, "check_output", return_value="a" * 64):
            with self.assertRaises(OSError):
                product.bundle_arguments(self.root)
        self.manifest.unlink()
        (self.root / "dist").rename(self.root / "real-dist")
        (self.root / "real-dist/build-manifest.json").write_bytes(
            (self.root / "original.json").read_bytes()
        )
        (self.root / "dist").symlink_to(
            self.root / "real-dist", target_is_directory=True
        )
        with patch.object(product.subprocess, "check_output", return_value="a" * 64):
            with self.assertRaises(OSError):
                product.bundle_arguments(self.root)
