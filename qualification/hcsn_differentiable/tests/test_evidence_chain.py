import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import warnings
import zipfile

from qualification.hcsn_differentiable.evidence_chain import verify_evidence


class EvidenceChainTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.evidence = self.root / "evidence"
        self.evidence.mkdir()
        self.payload = self.evidence / "result.json"
        self.payload.write_text('{"passed": false}\n')
        (self.root / "CURRENT.md").write_text("[receipt](evidence/result.json)\n")

    def manifest(self, members):
        values = {
            name: dict(
                bytes=(self.evidence / name).stat().st_size,
                sha256=hashlib.sha256((self.evidence / name).read_bytes()).hexdigest(),
            )
            for name in members
        }
        (self.evidence / "MANIFEST.json").write_text(json.dumps(dict(files=values)))

    def verify(self):
        return verify_evidence(self.root, ["evidence/MANIFEST.json"], ["CURRENT.md"])

    def test_tamper_and_missing_evidence_do_not_inherit_a_prior_pass(self):
        self.manifest(["result.json"])
        self.assertTrue(self.verify()["passed"])
        self.payload.write_text('{"passed": true }\n')
        self.assertFalse(self.verify()["passed"])
        self.payload.unlink()
        report = self.verify()
        self.assertFalse(report["passed"])
        self.assertGreaterEqual(len(report["errors"]), 2)

    def test_zip_crc_duplicate_and_traversal_are_checked_after_outer_hash(self):
        archive = self.evidence / "source.zip"
        for mode in ("good", "crc", "duplicate", "traversal"):
            with self.subTest(mode=mode), warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(
                    archive, "w", compression=zipfile.ZIP_STORED
                ) as stream:
                    stream.writestr(
                        "../escape" if mode == "traversal" else "source.py",
                        "unique-payload",
                    )
                    if mode == "duplicate":
                        stream.writestr("source.py", "other")
                if mode == "crc":
                    data = archive.read_bytes().replace(
                        b"unique-payload", b"Unique-payload", 1
                    )
                    archive.write_bytes(data)
                self.manifest(["source.zip", "result.json"])
                self.assertEqual(self.verify()["passed"], mode == "good")

    def test_broken_relative_link_and_ambiguous_manifest_are_rejected(self):
        self.manifest(["result.json"])
        (self.root / "CURRENT.md").write_text("[lost](evidence/missing.json)\n")
        self.assertFalse(self.verify()["passed"])
        (self.evidence / "MANIFEST.json").write_text('{"files":{},"files":{}}')
        report = self.verify()
        self.assertTrue(
            any("duplicate JSON key" in item["error"] for item in report["errors"])
        )
