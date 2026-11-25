"""Regression controls for the P0 evidence-link/HOLD gate."""
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import warnings
import zipfile

from qualification.hcsn_differentiable.audit_evidence_chain import check_chain
from qualification.hcsn_differentiable.evidence_chain import verify_evidence


class DeclaredEvidenceChainTests(unittest.TestCase):
    def test_current_candidate_files_and_explicit_hold(self):
        root = Path(__file__).resolve().parents[3]
        from json import loads
        index = loads((root / "qualification/hcsn_differentiable/EVIDENCE_CHAIN.json").read_text())
        report = check_chain(root, index)
        self.assertEqual(report["status"], "HOLD")
        self.assertFalse(report["scientific_admission"])
        self.assertGreaterEqual(len(report["bound_artifacts"]), 2)
        self.assertTrue(any(x["id"] == "localization-v2-18-interface-runs"
                            for x in report["open_holds"]))

    def test_missing_link_mismatch_and_path_escape_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            source = repo / "qualification" / "hcsn_differentiable"
            source.mkdir(parents=True)
            artifact = repo / "archive" / "receipt.txt"
            artifact.parent.mkdir()
            artifact.write_bytes(b"immutable native receipt")
            current = source / "CURRENT.md"
            current.write_text("[readable](../../archive/receipt.txt)\n", encoding="utf-8")
            ledger = {"schema": "hcsn-evidence-chain-v1",
                      "bound_files": [{"id": "proof", "path": "archive/receipt.txt",
                                       "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}],
                      "holds": [{"id": "unrun", "reason": "No independent confirmation"}]}
            self.assertEqual(check_chain(repo, ledger)["status"], "HOLD")
            current.write_text("[broken](../../archive/missing.txt)\n", encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                check_chain(repo, ledger)
            current.write_text("[readable](../../archive/receipt.txt)\n", encoding="utf-8")
            artifact.write_bytes(b"mutated")
            with self.assertRaises(ValueError):
                check_chain(repo, ledger)
            ledger["bound_files"][0]["path"] = "../archive/receipt.txt"
            with self.assertRaises(ValueError):
                check_chain(repo, ledger)

    def test_hold_cannot_be_labeled_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "qualification/hcsn_differentiable").mkdir(parents=True)
            (repo / "qualification/hcsn_differentiable/CURRENT.md").write_text("ok")
            artifact = repo / "proof.txt"
            artifact.write_text("ok")
            bound = {"id": "proof", "path": "proof.txt",
                     "sha256": hashlib.sha256(b"ok").hexdigest()}
            ledger = {"schema": "hcsn-evidence-chain-v1", "bound_files": [bound],
                      "holds": [{"id": "missing", "reason": "no log", "passed": True}]}
            with self.assertRaises(ValueError):
                check_chain(repo, ledger)


class ArtifactEvidenceIntegrityTests(unittest.TestCase):
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

    def test_svg_archive_preserves_original_manifest_digest_and_detects_tampering(self):
        svg = self.evidence / "figure.svg"
        stored = self.evidence / "figure.svg.gz"
        original = b"<svg>original figure</svg>\n"
        svg.write_bytes(original)
        self.manifest(["figure.svg"])
        svg.unlink()

        stored.write_bytes(gzip.compress(original, mtime=0))
        report = self.verify()
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(
            report["verified_files"]["evidence/figure.svg"]["sha256"],
            hashlib.sha256(original).hexdigest(),
        )
        self.assertEqual(
            report["archived_files"]["evidence/figure.svg"]["path"],
            "evidence/figure.svg.gz",
        )

        for data in (
            gzip.compress(original.replace(b"original", b"modified"), mtime=0),
            gzip.compress(original + b"x", mtime=0),
            gzip.compress(original, mtime=0)[:-5],
        ):
            with self.subTest(archive=data):
                stored.write_bytes(data)
                self.assertFalse(self.verify()["passed"])

    def test_svg_archive_never_masks_an_existing_raw_file(self):
        svg = self.evidence / "figure.svg"
        original = b"<svg>original figure</svg>\n"
        svg.write_bytes(original)
        self.manifest(["figure.svg"])
        (self.evidence / "figure.svg.gz").write_bytes(gzip.compress(original, mtime=0))
        svg.write_bytes(b"<svg>changed figure</svg>\n")
        self.assertFalse(self.verify()["passed"])

        svg.unlink()
        svg.symlink_to("missing.svg")
        self.assertFalse(self.verify()["passed"])

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
