"""Behavioral checks for source and protocol freezing."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from experiments.free_boundary_neuron import provenance


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.study = self.root / "study"
        for name in ("learning", "owner"):
            directory = self.study / name
            directory.mkdir(parents=True)
            (directory / "PROTOCOL.json").write_text('{"schema": "test"}\n')
        self.source = self.study / "operator.py"
        self.source.write_text("def value(x):\n    return x * x\n")
        self.run_git("init", "--quiet")
        self.run_git("add", ".")
        self.run_git(
            "-c",
            "user.name=Research test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "Fixture",
        )
        self.patch = patch.multiple(
            provenance,
            ROOT=self.root,
            STUDY=self.study,
            NATIVE_ROOTS=(),
            NATIVE_FILES=(),
        )
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.seal = self.study / "results" / "SOURCE_SEAL.json"

    def run_git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.root, check=True, capture_output=True
        )

    def test_seal_rejects_uncommitted_source(self):
        (self.study / "new_operator.py").write_text("x = 1\n")
        with self.assertRaisesRegex(ValueError, "Uncommitted source"):
            provenance.freeze(self.seal)
        self.assertFalse(self.seal.exists())

    def test_verify_rejects_changed_source_and_added_code(self):
        provenance.freeze(self.seal)
        original = self.source.read_text()
        self.source.write_text("def value(x):\n    return x\n")
        with self.assertRaisesRegex(ValueError, "Frozen inputs changed"):
            provenance.verify(self.seal)
        self.source.write_text(original)
        (self.study / "extra.py").write_text("x = 1\n")
        with self.assertRaisesRegex(ValueError, "Frozen inputs changed"):
            provenance.verify(self.seal)

    def test_results_do_not_change_inputs_but_protocol_does(self):
        provenance.freeze(self.seal)
        before = provenance.verify(self.seal)
        (self.seal.parent / "OUTCOME.json").write_text('{"value": 1}\n')
        self.assertEqual(provenance.verify(self.seal), before)
        (self.study / "learning" / "PROTOCOL.json").write_text(
            '{"schema": "changed"}\n'
        )
        with self.assertRaisesRegex(ValueError, "Frozen inputs changed"):
            provenance.verify(self.seal)

    def test_no_overwrite_of_existing_seal(self):
        provenance.freeze(self.seal)
        original = self.seal.read_bytes()
        with self.assertRaises(FileExistsError):
            provenance.freeze(self.seal)
        self.assertEqual(self.seal.read_bytes(), original)
        self.assertEqual(len(json.loads(original)["inputs"]), 3)

    def test_source_symlink_is_rejected(self):
        (self.study / "alias.py").symlink_to(self.source)
        with self.assertRaisesRegex(ValueError, "ordinary repository file"):
            provenance.inventory()


if __name__ == "__main__":
    unittest.main()
