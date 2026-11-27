"""Finite stdlib controls for exact historical CPU environment admission."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import torch_runtime_gate as gate


class TorchRuntimeGateTests(unittest.TestCase):
    def test_safe_freeze_keeps_every_original_package_and_byte(self):
        raw = (
            b"# retained original freeze\nnumpy==1.26.4\ntorch==2.10.0+cpu\n"
            b"torchvision==0.25.0+cpu\ntorchaudio==2.10.0+cpu\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "environment.txt"
            path.write_bytes(raw)
            actual = gate.read_regular(path)
            packages = gate.parse_freeze(actual)
            gate.validate_environment(packages)
            self.assertEqual(len(packages), 4)
            self.assertEqual(packages["numpy"], "1.26.4")
            self.assertEqual(actual, raw)
            self.assertEqual(path.read_bytes(), raw)

    def test_every_replaced_unsafe_torch_version_is_rejected(self):
        for version in ("2.5.1", "2.6.0", "2.7.1", "2.8.0", "2.9.1"):
            for suffix in ("", "+cpu"):
                with self.subTest(version=version + suffix):
                    with self.assertRaisesRegex(ValueError, "incompatible"):
                        gate.validate_environment({"torch": version + suffix})

    def test_missing_torch_and_incompatible_companions_are_rejected(self):
        for packages in (
            {"numpy": "1.26.4"},
            {"torch": "2.10.0", "torchvision": "0.20.1"},
            {"torch": "2.10.0", "torchaudio": "2.5.1"},
            {"torch": "2.10.0+cu128"},
        ):
            with self.subTest(packages=packages):
                with self.assertRaises(ValueError):
                    gate.validate_environment(packages)

    def test_hidden_requirement_sources_and_duplicate_names_are_rejected(self):
        for payload in (
            b"torch==2.10.0\n-r unsafe.txt\n",
            b"torch==2.10.0\n--constraint unsafe.txt\n",
            b"torch @ https://example.invalid/torch.whl\n",
            b"torch==2.10.0; python_version >= '3.11'\n",
            b"torch==2.10.0\nTORCH==2.5.1\n",
            b"torch==2.10.0\nname.one==1\nname_one==2\n",
            b"-e ./unsafe\n",
            b"torch==2.*\n",
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    gate.parse_freeze(payload)

    def test_file_bound_and_file_type_are_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                gate.read_regular(root)
            oversized = root / "oversized.txt"
            oversized.write_bytes(b"x" * (gate.MAX_FREEZE_BYTES + 1))
            with self.assertRaises(ValueError):
                gate.read_regular(oversized)
            empty = root / "empty.txt"
            empty.write_bytes(b"")
            with self.assertRaises(ValueError):
                gate.read_regular(empty)

    def test_committed_constraints_are_the_exact_official_compatible_set(self):
        self.assertEqual(
            gate.parse_freeze(gate.read_regular(gate.CONSTRAINTS)),
            {"torch": "2.10.0", "torchvision": "0.25.0", "torchaudio": "2.10.0"},
        )

    def test_cli_refuses_old_environment_and_records_unchanged_original_digest(self):
        raw = b"numpy==1.26.4\ntorch==2.5.1+cpu\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "environment.txt"
            path.write_bytes(raw)
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    "-B",
                    str(Path(gate.__file__)),
                    "--requirements",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stderr, "")
            record = json.loads(result.stdout)
            self.assertEqual(record["status"], "REFUSED_BEFORE_INSTALL")
            self.assertEqual(
                record["original_requirements_sha256"], hashlib.sha256(raw).hexdigest()
            )
            self.assertFalse(record["projection_applied"])
            self.assertFalse(record["historical_qualification_inherited"])
            self.assertTrue(record["complete_post_install_freeze_comparison_required"])
            self.assertEqual(path.read_bytes(), raw)

    def test_cli_acceptance_still_requires_complete_freeze_comparison(self):
        raw = b"numpy==1.26.4\ntorch==2.10.0+cpu\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "environment.txt"
            path.write_bytes(raw)
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    "-B",
                    str(Path(gate.__file__)),
                    "--requirements",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            record = json.loads(result.stdout)
            self.assertEqual(record["package_count"], 2)
            self.assertEqual(record["protected_pins"], {"torch": "2.10.0+cpu"})
            self.assertTrue(record["complete_post_install_freeze_comparison_required"])
            self.assertEqual(path.read_bytes(), raw)


if __name__ == "__main__":
    unittest.main()
