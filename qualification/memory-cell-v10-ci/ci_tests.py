"""Exercise the evidence boundary with real files; no model, encoder or holdout runs."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import common
import github_gate
import pack
import request
import verify


class EvidenceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        common.save(self.source / "receipt.json", {"passed": False, "original": "保留原始字节"})
        common.save(self.source / "SOURCE_FILES.json", {"one.py": {"sha256": "a" * 64}})
        (self.source / "memory-bundle:1-actual").write_bytes(b"\x00\xffcheckpoint\n")
        (self.root / "outside").write_bytes(b"must not be followed")
        (self.source / "link").symlink_to(self.root / "outside")
        self.transport = self.root / "transport"
        pack.pack(self.source, self.transport)
        self.zip_path = self.root / "artifact.zip"
        with zipfile.ZipFile(self.zip_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(self.transport.iterdir()):
                archive.write(path, path.name)
        self.proof = {"transport_sha256": common.identity(self.transport / "memory-v10-evidence.tar.xz")["sha256"],
                      "receipt_sha256": common.identity(self.transport / "receipt.json")["sha256"]}

    def read(self, proof=None):
        directory = self.root / "decoded"
        directory.mkdir()
        return github_gate.read_transport(self.zip_path, directory, proof or self.proof)

    def test_roundtrip_retains_unix_names_exact_bytes_and_records_unfollowed_links(self):
        receipt, sources, index = self.read()
        self.assertEqual(receipt, common.load(self.source / "receipt.json"))
        self.assertEqual(sources, common.load(self.source / "SOURCE_FILES.json"))
        self.assertEqual(index["files"]["memory-v10-ci-output/memory-bundle:1-actual"],
                         common.identity(self.source / "memory-bundle:1-actual"))
        self.assertFalse(index["nonregular_entries"]["memory-v10-ci-output/link"]["contents_followed"])
        self.assertNotIn("memory-v10-ci-output/link", index["files"])

    def test_wrong_archive_pin_is_rejected_before_returning_receipts(self):
        proof = {**self.proof, "transport_sha256": "0" * 64}
        with self.assertRaisesRegex(ValueError, "archive differs"):
            self.read(proof)

    def test_wrong_receipt_pin_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "receipt differs"):
            self.read({**self.proof, "receipt_sha256": "0" * 64})

    def test_extra_zip_member_is_rejected(self):
        with zipfile.ZipFile(self.zip_path, "a") as archive:
            archive.writestr("extra", b"unregistered")
        with self.assertRaisesRegex(ValueError, "three-file"):
            self.read()

    def test_duplicate_json_fields_cannot_replace_evidence(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            common.decode(b'{"passed":false,"passed":true}')


class RequestBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.value = {"schema": "hepta.memory.v10.ci-request.v1", "mode": "verify", "request_id": "dev-01",
                      "baseline_commit": common.BASELINE, "source_manifest_sha256": "a" * 64,
                      "protocol_sha256": "a" * 64, "tests_before_final_fix_and_format": True}

    def read(self, value):
        with patch.object(request, "load", return_value=copy.deepcopy(value)), \
             patch.object(request, "identity", return_value={"sha256": "a" * 64}), \
             patch.dict(request.os.environ, {"GITHUB_ACTIONS": "false"}):
            return request.read_request()

    def test_verify_is_a_separate_mode_without_unverified_finalize_authority(self):
        self.assertEqual(self.read(self.value), self.value)
        with self.assertRaisesRegex(ValueError, "unexpected request"):
            self.read({**self.value, "verification": {}})

    def test_finalization_requires_all_exact_ci_origin_fields(self):
        with self.assertRaisesRegex(ValueError, "verification proof"):
            self.read({**self.value, "mode": "finalize", "verification": {"commit": "a" * 40}})

    def test_request_cannot_change_the_test_before_format_rule(self):
        with self.assertRaisesRegex(ValueError, "source/order"):
            self.read({**self.value, "tests_before_final_fix_and_format": False})

    def test_actual_path_guard_rejects_overlong_and_unicode_byte_paths_before_training(self):
        accepted = verify.native_output_path(Path("/tmp/h10-40900187124-1"))
        self.assertEqual(accepted, Path("/tmp/h10-40900187124-1/native-actual"))
        for root in ("/home/runner/work/hepta-private-ci/hepta-private-ci/memory-v10-ci-output",
                     "/tmp/" + "存" * 20):
            with self.subTest(root=root), self.assertRaisesRegex(ValueError, "Unix socket path"):
                verify.native_output_path(Path(root))


class JunitEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        self.output = self.root / "evidence"
        self.output.mkdir()
        config = self.workspace / ".config/nextest.toml"
        config.parent.mkdir(parents=True)
        config.write_text('[profile.default.junit]\npath="junit.xml"\n'
                          '[profile.local]\ninherits="default"\n')

    def test_workspace_report_is_fresh_and_independent_of_cargo_target(self):
        expected = self.workspace / "target/nextest/local/junit.xml"
        expected.parent.mkdir(parents=True)
        expected.write_text("stale report")
        cargo = self.root / "external-cargo-cache"
        decoy = cargo / "nextest/local/junit.xml"
        decoy.parent.mkdir(parents=True)
        decoy.write_text("wrong root")
        with patch.dict(verify.os.environ, {"CARGO_TARGET_DIR": str(cargo)}):
            source = verify.prepare_junit(self.workspace, self.output, "ordinary")
        self.assertEqual(source, expected)
        self.assertFalse(source.exists())
        self.assertEqual(decoy.read_text(), "wrong root")
        with self.assertRaisesRegex(ValueError, "JUnit report is missing"):
            verify.retain_junit(source, self.output, "ordinary")
        source.write_text('<testsuites><testsuite><testcase name="case"/></testsuite></testsuites>')
        receipt = verify.retain_junit(source, self.output, "ordinary")
        self.assertEqual(receipt["cases"], 1)
        self.assertEqual((self.output / receipt["path"]).read_bytes(), source.read_bytes())
        location = common.load(self.output / "ordinary-junit-location.json")
        self.assertEqual(location["source"], str(expected))
        self.assertTrue(location["removed_previous_report"])
        self.assertEqual(verify.prepare_junit(self.workspace, self.output, "actual"), source)
        self.assertFalse(source.exists())
        source.write_text(f'<testsuites><testsuite><testcase name="{common.ACTUAL_TEST}"/></testsuite></testsuites>')
        self.assertEqual(verify.retain_junit(source, self.output, "actual")["cases"], 1)

    def test_empty_failed_and_wrong_actual_reports_remain_rejected(self):
        source = verify.prepare_junit(self.workspace, self.output, "actual")
        source.parent.mkdir(parents=True)
        for cases in ('', '<testcase name="case"><failure/></testcase>', '<testcase name="wrong-parent"/>'):
            source.write_text(f'<testsuites><testsuite>{cases}</testsuite></testsuites>')
            with self.subTest(cases=cases), self.assertRaises(ValueError):
                verify.retain_junit(source, self.output, "actual")


if __name__ == "__main__":
    unittest.main()
