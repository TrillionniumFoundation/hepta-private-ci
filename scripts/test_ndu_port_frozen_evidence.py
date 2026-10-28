"""Preserve historical result bytes while keeping the original docs gate strict."""

import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "experiments/multimodal_output_portfolio/closure_20261028"
DIRECTORY = PACKAGE / "fullpath_results"
SPEC = importlib.util.spec_from_file_location(
    "frozen_evidence_docs", ROOT / "scripts/hepta-docs.py"
)
assert SPEC is not None and SPEC.loader is not None
DOCS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DOCS)


class FrozenEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.receipt = json.loads(
            (DIRECTORY / "SOURCE_REFUSAL_ENCODING.json").read_text()
        )
        self.system = json.loads(
            (ROOT / "docs/governance/DOCUMENT_SYSTEM.json").read_text()
        )

    def test_actual_archive_restores_exact_original_publication_bytes(self):
        frozen = json.loads(
            (PACKAGE / "control_results/PUBLISH_MANIFEST.json").read_text()
        )
        original = next(
            row
            for row in frozen["files"]
            if row["path"] == self.receipt["original"]["path"]
        )
        stored = (ROOT / self.receipt["stored"]["path"]).read_bytes()
        self.assertEqual(
            {"bytes": len(stored), "sha256": hashlib.sha256(stored).hexdigest()},
            {key: self.receipt["stored"][key] for key in ("bytes", "sha256")},
        )
        recovered = gzip.decompress(stored)
        identity = {
            "path": original["path"],
            "bytes": len(recovered),
            "sha256": hashlib.sha256(recovered).hexdigest(),
        }
        self.assertEqual(identity, original)
        self.assertEqual(
            identity, {key: self.receipt["original"][key] for key in identity}
        )
        record = json.loads(recovered)
        self.assertEqual(
            {
                "qualification_admitted": record["qualification_admitted"],
                "qualification_claim_exists": record["qualification_claim_exists"],
                "new_qualification_predictions": record[
                    "new_qualification_predictions"
                ],
                "reserved": sum(map(len, record["qualification_source_ids"].values())),
            },
            {
                "qualification_admitted": False,
                "qualification_claim_exists": False,
                "new_qualification_predictions": 0,
                "reserved": 384,
            },
        )

    def test_original_live_status_filename_still_fails_the_real_gate(self):
        original = self.receipt["original"]["path"]
        for path in (original, original.replace(".json", "_v2.json")):
            with (
                self.subTest(path=path),
                self.assertRaisesRegex(SystemExit, "legacy paths"),
            ):
                DOCS.verify_legacy(self.system, [path])

    def test_encoded_history_and_readable_refusal_use_existing_gate_boundaries(self):
        paths = [
            self.receipt["stored"]["path"],
            str((DIRECTORY / "SOURCE_REFUSAL_ENCODING.json").relative_to(ROOT)),
            str((DIRECTORY / "SOURCE_REFUSAL.md").relative_to(ROOT)),
        ]
        DOCS.verify_legacy(self.system, paths)
        self.assertFalse((ROOT / self.receipt["original"]["path"]).exists())

    def test_damaged_archive_is_not_accepted_as_historical_evidence(self):
        stored = bytearray((ROOT / self.receipt["stored"]["path"]).read_bytes())
        stored[-1] ^= 1
        self.assertNotEqual(
            hashlib.sha256(stored).hexdigest(), self.receipt["stored"]["sha256"]
        )
        with self.assertRaises((gzip.BadGzipFile, EOFError, OSError)):
            gzip.decompress(stored)


if __name__ == "__main__":
    unittest.main()
