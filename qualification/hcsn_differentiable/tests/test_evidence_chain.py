"""Regression controls for the P0 evidence-link/HOLD gate."""
import hashlib
import tempfile
from pathlib import Path
import unittest

from qualification.hcsn_differentiable.audit_evidence_chain import check_chain


class EvidenceChainTests(unittest.TestCase):
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
