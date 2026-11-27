"""Reject unregistered package initialization before and after real execution."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).parent
RELATIVE = Path("experiments/multimodal_output_portfolio/v6")
PACKAGES = ("experiments", "experiments/multimodal_output_portfolio",
            "experiments/multimodal_output_portfolio/v6")
NAMES = ("conditioned.py", "data.py", "neural.py", "observer.py",
         "owner_worker.py", "plan_training.py", "owner_worker_tests.py")


def copy_sources(directory):
    root = Path(directory) / "repository"
    target = root / RELATIVE
    target.mkdir(parents=True)
    for name in NAMES:
        shutil.copyfile(SOURCE / name, target / name)
    return root


def source_hashes(root):
    return {name: hashlib.sha256((root / RELATIVE / name).read_bytes()).hexdigest()
            for name in NAMES}


class SourcePackageTests(unittest.TestCase):
    def check_before_import(self, relative, symlink):
        with tempfile.TemporaryDirectory() as directory:
            root = copy_sources(directory)
            before = source_hashes(root)
            marker = Path(directory) / "executed.txt"
            initializer = root / relative / "__init__.py"
            body = f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"
            if symlink:
                target = Path(directory) / "initializer.py"
                target.write_text(body)
                initializer.symlink_to(target)
            else:
                initializer.write_text(body)
            result = subprocess.run(
                [sys.executable, "-I", "-B", "-X", "pycache_prefix=/dev/null",
                 str(root / RELATIVE / "owner_worker.py")],
                input=b"{}", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=root, timeout=30, check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"Unexpected source package initializer", result.stderr)
            self.assertFalse(marker.exists())
            self.assertEqual(before, source_hashes(root))

    def test_parent_initializer_files_reject_before_local_import(self):
        for relative in PACKAGES:
            with self.subTest(relative=relative):
                self.check_before_import(relative, symlink=False)

    def test_parent_initializer_links_reject_before_local_import(self):
        for relative in PACKAGES:
            with self.subTest(relative=relative):
                self.check_before_import(relative, symlink=True)
        with tempfile.TemporaryDirectory() as directory:
            root = copy_sources(directory)
            initializer = root / PACKAGES[0] / "__init__.py"
            initializer.symlink_to(Path(directory) / "missing.py")
            result = subprocess.run(
                [sys.executable, "-I", "-B", str(root / RELATIVE / "owner_worker.py")],
                input=b"{}", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=root, timeout=30, check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"Unexpected source package initializer", result.stderr)

    def test_initializer_added_after_pins_rejects_real_execution(self):
        body = """
import json
from pathlib import Path
import sys
from unittest.mock import patch
root, artifacts, relative, marker = map(Path, sys.argv[1:])
sys.path.insert(0, str(root))
from experiments.multimodal_output_portfolio.v6 import neural, owner_worker
from experiments.multimodal_output_portfolio.v6.owner_worker_tests import prepare_fixture
fixture, _ = prepare_fixture(artifacts)
initializer = root / relative / "__init__.py"
original = neural.NeuralSnapshot.decode
def decode_and_add(self, *args, **kwargs):
    result = original(self, *args, **kwargs)
    initializer.write_text("from pathlib import Path\\nPath(" + repr(str(marker)) +
                           ").write_text('executed')\\n")
    return result
envelope = {"checkpoint": str(artifacts / "base.pt"),
            "request_json": json.dumps(fixture["request"], separators=(",", ":"))}
with patch.object(neural.NeuralSnapshot, "decode", decode_and_add):
    try:
        owner_worker.execute(envelope)
    except ValueError as error:
        if "Unexpected source package initializer" not in str(error):
            raise
    else:
        raise AssertionError("Unregistered initializer survived the final source check")
if not initializer.is_file() or marker.exists():
    raise AssertionError("Mutation did not occur at the intended post-pin boundary")
print(json.dumps({"real_decode_reached": True, "initializer_rejected": True,
                  "initializer_executed": False}))
"""
        for relative in PACKAGES:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                root = copy_sources(directory)
                before = source_hashes(root)
                result = subprocess.run(
                    [sys.executable, "-I", "-B", "-c", body, str(root),
                     str(Path(directory) / "artifacts"), relative,
                     str(Path(directory) / "executed.txt")],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    cwd=root, timeout=60, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                self.assertEqual(json.loads(result.stdout),
                                 {"real_decode_reached": True, "initializer_rejected": True,
                                  "initializer_executed": False})
                self.assertEqual(before, source_hashes(root))


if __name__ == "__main__":
    unittest.main()
