"""Materialization must bind the full successor without rewriting its parent."""

import ast
import json
from pathlib import Path
import tempfile
import unittest

from .atomic_io import identity
from .materialize import ARCHIVE, materialize


class MaterializeTests(unittest.TestCase):
    def test_original_remains_exact_and_successor_manifest_covers_execution(self):
        repository = Path(__file__).resolve().parents[2]
        before = identity(repository / ARCHIVE)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "new-source"
            receipt = materialize(repository, output)
            self.assertEqual(identity(repository / ARCHIVE), before)
            manifest = json.loads((output / "PROGRAM-MANIFEST.json").read_bytes())
            self.assertEqual(
                receipt["program_manifest"], identity(output / "PROGRAM-MANIFEST.json")
            )
            self.assertIs(manifest["real_execution_authorized"], False)
            self.assertEqual(manifest["production_steps_executed"], 0)
            for name, expected in manifest["files"].items():
                self.assertEqual(identity(output / name), expected, name)
            for name in ("atomic_io.py", "journal.py", "__init__.py"):
                self.assertIn("hcsn_persistence_v1/" + name, manifest["files"])
            prior = json.loads((output / "ORIGINAL-PROGRAM-MANIFEST.json").read_bytes())
            for name in ("CONTRACT.json", "c2_boundary.py", "c2_recording.py"):
                self.assertEqual(manifest["files"][name], prior["files"][name])
            for name in ("c2_io.py", "c2_runner.py", "c2_controller.py"):
                self.assertNotEqual(manifest["files"][name], prior["files"][name])
                ast.parse((output / name).read_text())
            with self.assertRaises(FileExistsError):
                materialize(repository, output)


if __name__ == "__main__":
    unittest.main()
