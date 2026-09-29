#!/usr/bin/env python3
"""Transport integrity fixtures are not host execution or AWS evidence."""
import copy
import json
from pathlib import Path
import tarfile
import tempfile
import subprocess
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
                receipt["host"] = "fixture-host"
                if suite == "host":
                    native = {
                        "schema": "hepta.ndu.named-host-qualification.v3", "sourceSha": receipt["sourceSha"], "sourceTree": receipt["sourceTree"], "lane": lane, "hostId": receipt["host"],
                        "journal": {"recordCapacity": 4096, "liveProjectionCapacity": 2048, "ordinaryOverflowRejected": True, "fullEnvelopeRevocation": True, "restartRecovery": True},
                        "hotPath": {"runs": 100, "candidates": 32, "organs": 8, "p50Micros": 100, "p95Micros": 200, "p99Micros": 300, "targetPass": True},
                        "durability": dict.fromkeys(["restartReopen", "revocationNonResurrection", "backupRestore", "fullCapacityDiskRecovery", "oversizedImageBoundedReject"], True),
                    }
                    native["durability"]["oversizedSparseBytes"] = 1 << 40
                    host_path = root / "named-host.json"; host_path.write_text(json.dumps(native))
                    mounted = {"schema": "hepta.ndu.mounted-filesystem-qualification.v1", "sourceSha": receipt["sourceSha"], "sourceTree": receipt["sourceTree"], "lane": lane, "host": receipt["host"], "binaryUnchanged": True, "passed": True, "productionActivation": False, "binarySha256": "e" * 64,
                        "cases": [{"fault": fault, "filesystem": "tmpfs", "observedErrno": errno, "passed": True, "cleanupPassed": True, "exitCode": 0, "phases": ["READY", "FAULT_OBSERVED", "RECOVERED"], "filledBytes": 4096} for fault, errno in [("enospc", 28), ("erofs", 30)]]}
                    (root / "mounted-filesystem").mkdir()
                    mounted_path = root / "mounted-filesystem/mounted-filesystem.json"; mounted_path.write_text(json.dumps(mounted))
                    runner = evidence.trusted_runner()
                    receipt["hostReceipt"] = runner.validate_host_receipt(host_path, receipt["sourceSha"], receipt["sourceTree"], lane, expected_host=receipt["host"])
                    receipt["mountedFilesystemReceipt"] = runner.validate_mounted_receipt(mounted_path, receipt["sourceSha"], receipt["sourceTree"], lane, expected_host=receipt["host"])
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

    def test_resealed_native_evidence_cannot_override_actual_observations(self):
        self.twelve()
        root = self.root / "source-head-host"
        native_path = root / "named-host.json"
        original = json.loads(native_path.read_text())
        receipt_path = root / "suite-receipt.json"
        receipt = json.loads(receipt_path.read_text())
        for modification in ["slow", "foreign-host", "missing-recovery"]:
            native = copy.deepcopy(original)
            if modification == "slow": native["hotPath"]["p99Micros"] = 6000
            elif modification == "foreign-host": native["hostId"] = "foreign"
            else: native["durability"]["restartReopen"] = False
            native_path.write_text(json.dumps(native))
            receipt["hostReceipt"]["sha256"] = evidence.digest(native_path.read_bytes())
            receipt_path.write_text(json.dumps(receipt))
            (root / evidence.MANIFEST).unlink(); evidence.seal(root)
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

    def test_lost_put_ack_and_exact_retries_reconcile_without_overwrite(self):
        archive = self.root / "archive"; archive.write_bytes(b"sealed fixture")
        kwargs = dict(bucket="ndu-test-bucket", key="ndu-evidence/fixture", kms="arn:aws:kms:us-east-1:123456789012:key/test", account="123456789012")
        for failure in (subprocess.TimeoutExpired("aws", 120), subprocess.CalledProcessError(1, "aws", stderr="412 PreconditionFailed"), None):
            calls = []
            def aws(*args):
                calls.append(args)
                if args[1] == "get-caller-identity": return {"Account": kwargs["account"]}
                if args[1] == "get-bucket-versioning": return {"Status": "Enabled"}
                if args[1] == "put-object":
                    if failure is not None: raise failure
                    return {}  # Acknowledgement missing the version is unresolved too.
                if args[1] == "head-object": return {"VersionId": "retained-v1"}
                self.assertEqual(args[args.index("--version-id") + 1], "retained-v1")
                Path(args[-1]).write_bytes(b"sealed fixture")
                return {"VersionId": "retained-v1", "ServerSideEncryption": "aws:kms", "SSEKMSKeyId": kwargs["kms"]}
            with patch.object(evidence, "aws", side_effect=aws):
                first = evidence.publish(archive, **kwargs)
                second = evidence.publish(archive, **kwargs)
            self.assertEqual(first, second)
            self.assertTrue(first["reconciledExistingVersion"])
            self.assertEqual(len([call for call in calls if call[1] == "put-object"]), 2)
            self.assertTrue(all("--if-none-match" in call for call in calls if call[1] == "put-object"))
            self.assertFalse(list(self.root.glob("ndu-readback-*")))
            self.assertFalse(archive.with_name("archive.readback").exists())

    def test_unknown_publication_never_becomes_absence_or_success(self):
        archive = self.root / "archive"; archive.write_bytes(b"sealed fixture")
        kwargs = dict(bucket="ndu-test-bucket", key="ndu-evidence/fixture", kms="arn:aws:kms:us-east-1:123456789012:key/test", account="123456789012")
        for head in (None, {}):
            calls = []
            def aws(*args):
                calls.append(args[1])
                if args[1] == "get-caller-identity": return {"Account": kwargs["account"]}
                if args[1] == "get-bucket-versioning": return {"Status": "Enabled"}
                if args[1] == "head-object" and head is not None: return head
                raise subprocess.TimeoutExpired("aws", 120)
            with patch.object(evidence, "aws", side_effect=aws), self.assertRaisesRegex(RuntimeError, "NDU-PUB-003"):
                evidence.publish(archive, **kwargs)
            self.assertEqual(calls.count("put-object"), 1)
            self.assertNotIn("delete-object", calls)

    def test_reconciliation_rejects_conflicting_bytes_version_or_kms(self):
        archive = self.root / "archive"; archive.write_bytes(b"sealed fixture")
        kwargs = dict(bucket="ndu-test-bucket", key="ndu-evidence/fixture", kms="arn:aws:kms:us-east-1:123456789012:key/test", account="123456789012")
        for corruption in ("bytes", "version", "kms", "encryption"):
            def aws(*args):
                if args[1] == "get-caller-identity": return {"Account": kwargs["account"]}
                if args[1] == "get-bucket-versioning": return {"Status": "Enabled"}
                if args[1] == "put-object": raise subprocess.CalledProcessError(1, "aws")
                if args[1] == "head-object": return {"VersionId": "v1"}
                Path(args[-1]).write_bytes(b"other" if corruption == "bytes" else b"sealed fixture")
                return {"VersionId": "other" if corruption == "version" else "v1", "ServerSideEncryption": "other" if corruption == "encryption" else "aws:kms", "SSEKMSKeyId": "other" if corruption == "kms" else kwargs["kms"]}
            with patch.object(evidence, "aws", side_effect=aws), self.assertRaisesRegex(ValueError, "NDU-PUB-004"):
                evidence.publish(archive, **kwargs)
            self.assertFalse(list(self.root.glob("ndu-readback-*")))

if __name__ == "__main__": unittest.main()
