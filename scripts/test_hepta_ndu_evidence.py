#!/usr/bin/env python3
"""Transport integrity fixtures are not host execution or AWS evidence."""
import copy
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import hepta_ndu_evidence as evidence


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "evidence"
        self.root.mkdir()

    def twelve(self):
        for lane in ["source-head", "synthetic-merge"]:
            for suite in sorted(evidence.SUITES):
                root = self.root / f"{lane}-{suite}"
                root.mkdir()
                (root / "test.log").write_bytes(b"actual fixture log\n")
                receipt = {"schema": "hepta.ndu.suite-receipt.v1", "lane": lane, "suite": suite, "sourceSha": "a" * 40 if lane == "source-head" else "c" * 40, "sourceTree": "d" * 40, "parents": ["b" * 40, "a" * 40], "passed": True, "sourceUnchanged": True, "commands": [{"name": "fixture", "exitCode": 0, "log": "test.log", "logSha256": evidence.digest(b"actual fixture log\n")}]}
                receipt["commands"] = [{"name": name, "command": command, "exitCode": 0, "log": "test.log", "logSha256": evidence.digest(b"actual fixture log\n")} for name, command in evidence.expected_commands(suite, receipt["sourceSha"], receipt["sourceTree"]).items()]
                receipt["hostReceipt"] = {"identityValidated": True, "performancePassed": True}
                receipt["mountedFilesystemReceipt"] = {"identityValidated": True}
                (root / "suite-receipt.json").write_text(json.dumps(receipt))
                evidence.seal(root)

    def test_seal_detects_modified_added_deleted_and_symlink(self):
        (self.root / "a").write_bytes(b"abc")
        evidence.seal(self.root)
        evidence.verify(self.root)
        (self.root / "a").write_bytes(b"abd")
        with self.assertRaises(ValueError): evidence.verify(self.root)
        (self.root / "a").unlink()
        with self.assertRaises(ValueError): evidence.verify(self.root)
        (self.root / "a").symlink_to("/etc/passwd")
        with self.assertRaises(ValueError): evidence.verify(self.root)

    def test_full_matrix_and_hashes_required(self):
        self.twelve()
        result = evidence.aggregate(self.root, "a" * 40, "b" * 40, "c" * 40)
        self.assertTrue(result["passed"])
        self.assertFalse(result["productionActivation"])
        with self.assertRaises(ValueError): evidence.aggregate(self.root, "a" * 40, "f" * 40, "c" * 40)
        (self.root / "source-head-source/test.log").write_bytes(b"changed")
        with self.assertRaises(ValueError): evidence.aggregate(self.root, "a" * 40, "b" * 40, "c" * 40)

    def test_unpassed_missing_and_boolean_exit_code_never_qualify(self):
        self.twelve()
        path = self.root / "source-head-source"
        original = json.loads((path / "suite-receipt.json").read_text())
        for modification in ["failed", "empty", "boolean", "command"]:
            row = copy.deepcopy(original)
            if modification == "failed": row["passed"] = False
            elif modification == "empty": row["commands"] = []
            elif modification == "boolean": row["commands"][0]["exitCode"] = False
            else: row["commands"][0]["command"] = ["true"]
            (path / "suite-receipt.json").write_text(json.dumps(row))
            (path / evidence.MANIFEST).unlink(); evidence.seal(path)
            with self.assertRaises(ValueError): evidence.aggregate(self.root, "a" * 40, "b" * 40, "c" * 40)
        (path / "suite-receipt.json").unlink()
        with self.assertRaises(ValueError): evidence.aggregate(self.root, "a" * 40, "b" * 40, "c" * 40)

    def test_archive_is_lossless_and_does_not_truncate_source(self):
        (self.root / "history").write_bytes(b"revocations-and-operation-identities" * 100)
        evidence.seal(self.root)
        archive = Path(self.tmp.name) / "evidence.tar.gz"
        evidence.pack(self.root, archive)
        with tarfile.open(archive, "r:gz") as source:
            self.assertEqual(source.extractfile("history").read(), (self.root / "history").read_bytes())
        evidence.verify(self.root)
        with self.assertRaises(FileExistsError): evidence.pack(self.root, archive)

    def test_publisher_requires_identity_versioning_and_readback(self):
        archive = self.root / "archive"; archive.write_bytes(b"sealed fixture")
        kwargs = dict(bucket="ndu-test-bucket", key="ndu-evidence/fixture", kms="arn:aws:kms:us-east-1:123456789012:key/test", account="123456789012")
        with patch.object(evidence, "aws", return_value={"Account": "wrong"}):
            with self.assertRaises(ValueError): evidence.publish(archive, **kwargs)
        with patch.object(evidence, "aws", side_effect=[{"Account": kwargs["account"]}, {"Status": "Suspended"}]):
            with self.assertRaises(ValueError): evidence.publish(archive, **kwargs)
        calls = []
        def aws(*args):
            calls.append(args)
            if args[1] == "get-caller-identity": return {"Account": kwargs["account"]}
            if args[1] == "get-bucket-versioning": return {"Status": "Enabled"}
            if args[1] == "put-object": return {"VersionId": "v1"}
            Path(args[-1]).write_bytes(b"sealed fixture")
            return {"VersionId": "v1", "ServerSideEncryption": "aws:kms", "SSEKMSKeyId": kwargs["kms"]}
        with patch.object(evidence, "aws", side_effect=aws):
            self.assertTrue(evidence.publish(archive, **kwargs)["readbackVerified"])
        put = next(call for call in calls if call[1] == "put-object")
        self.assertIn("--if-none-match", put)
        self.assertIn("--checksum-sha256", put)

if __name__ == "__main__": unittest.main()
