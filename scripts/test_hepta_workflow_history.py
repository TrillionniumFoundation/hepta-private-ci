"""Check historical workflow custody through the ordinary documentation verifier."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hepta_workflow_history import FROZEN_WORKFLOW_HISTORY


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("hepta_docs", ROOT / "scripts/hepta-docs.py")
DOCS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DOCS)


class HistoricalWorkflowReferencesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.addCleanup(patch.stopall)
        patch.object(DOCS, "ROOT", self.root).start()
        patch.object(DOCS, "WORKFLOW_REFERENCE_SCRIPTS", ()).start()
        self.relative = "qualification/continuation-20261021/research/original_run.json"
        self.original = (ROOT / self.relative).read_bytes()

    def write(self, relative, raw):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return path

    def test_original_observations_keep_their_bytes_without_live_workflow_files(self):
        originals = {}
        for relative in FROZEN_WORKFLOW_HISTORY:
            originals[relative] = (ROOT / relative).read_bytes()
            self.write(relative, originals[relative])
        DOCS.verify_exact_workflow_references()
        self.assertEqual(
            {relative: (self.root / relative).read_bytes() for relative in originals},
            originals,
        )

    def test_changed_historical_bytes_never_bypass_current_validation(self):
        for changed in (self.original + b"\n", self.original + b"\xff"):
            with self.subTest(changed=changed[-1:]):
                self.write(self.relative, changed)
                with self.assertRaisesRegex(SystemExit, "historical workflow observation changed"):
                    DOCS.verify_exact_workflow_references()

    def test_historical_record_cannot_be_rebound_even_to_existing_workflow(self):
        record = json.loads(self.original)
        record["path"] = ".github/workflows/current.yml"
        self.write(record["path"], b"name: current\n")
        self.write(self.relative, json.dumps(record).encode())
        with self.assertRaisesRegex(SystemExit, "historical workflow observation changed"):
            DOCS.verify_exact_workflow_references()

    def test_neighbor_and_current_document_stale_references_still_fail(self):
        self.write(self.relative, self.original)
        for relative in (
            "qualification/continuation-20261021/research/new_run.json",
            "docs/current.md",
        ):
            with self.subTest(relative=relative):
                path = self.write(relative, b".github/workflows/retired.yml\n")
                with self.assertRaisesRegex(SystemExit, "stale exact workflow references"):
                    DOCS.verify_exact_workflow_references()
                path.unlink()


if __name__ == "__main__":
    unittest.main()
