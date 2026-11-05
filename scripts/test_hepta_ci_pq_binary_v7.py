"""Controlled compiler records and ELF bytes; never execute a native fixture."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from hepta_ci_pq_binary_v7 import BinaryObservation, BUILD_COMMAND


class CurrentPqBinaryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name).resolve()
        self.chain = Path(os.environ.get("HEPTA_PQ_CHAIN", "../chain")).resolve(
            strict=True
        )
        self.binary = self.output / "controlled-never-executed"
        self.binary.write_bytes(
            b"\x7fELF\x02\x01"
            + bytes(12)
            + (62).to_bytes(2, "little")
            + b"controlled fixture"
        )
        self.binary.chmod(0o700)
        crate = self.chain / "trillionnium/crates/trnm-pon-node"
        self.artifact = dict(
            reason="compiler-artifact",
            manifest_path=str(crate / "Cargo.toml"),
            target=dict(
                name="trnm_pon_node",
                kind=["lib"],
                crate_types=["lib"],
                test=True,
                src_path=str(crate / "src/lib.rs"),
            ),
            profile=dict(test=True, opt_level="3", debug_assertions=False),
            features=["default", "pq-native-openssl"],
            executable=str(self.binary),
            filenames=[str(self.binary)],
        )
        self.reader = BinaryObservation(self.chain, self.output, "X64")
        self.build()

    def build(self, rows=None, **receipt_changes):
        raw = "\n".join(
            json.dumps(row)
            for row in (
                rows
                if rows is not None
                else [self.artifact, dict(reason="build-finished", success=True)]
            )
        ).encode()
        (self.output / "build.log").write_bytes(raw)
        receipt = dict(
            status="command_succeeded",
            exit_code=0,
            argv=BUILD_COMMAND,
            log_sha256=hashlib.sha256(raw).hexdigest(),
        )
        receipt.update(receipt_changes)
        (self.output / "build.json").write_text(json.dumps(receipt))

    def test_one_current_release_artifact_records_both_unchanged_observations(self):
        before, after = self.reader.before(), self.reader.after()
        self.assertEqual(before["binary"], after["before"])
        self.assertEqual(after["before"], after["after"])
        self.assertTrue(after["unchanged"])
        self.assertFalse(after["every_exec_observed"])
        self.assertFalse(after["whole_chain_quantum_security_qualified"])
        self.assertEqual(
            before["compiler_artifact"]["profile"], self.artifact["profile"]
        )

    def test_absent_or_duplicate_artifact_refuses_before_controls(self):
        for records in ([], [self.artifact, self.artifact]):
            with self.subTest(count=len(records)):
                self.build(records + [dict(reason="build-finished", success=True)])
                with self.assertRaisesRegex(ValueError, "UNIQUE_FINISHED_ARTIFACT"):
                    self.reader.before()
                self.assertFalse(
                    (self.output / "binary-inventory-before.json").exists()
                )

    def test_changed_binary_retains_failed_after_observation(self):
        self.reader.before()
        with self.binary.open("ab") as stream:
            stream.write(b"changed after controls")
        with self.assertRaisesRegex(ValueError, "CHANGED_BETWEEN_OBSERVATIONS"):
            self.reader.after()
        result = json.loads((self.output / "binary-inventory-after.json").read_bytes())
        self.assertFalse(result["unchanged"])
        self.assertNotEqual(result["before"]["sha256"], result["after"]["sha256"])

    def test_wrong_source_profile_features_or_finish_refuses(self):
        for field, replacement in (
            ("manifest_path", "/another/Cargo.toml"),
            ("profile", dict(test=True, opt_level="0")),
            ("features", ["default"]),
            ("target", dict(self.artifact["target"], kind=["test"])),
        ):
            with self.subTest(field=field):
                row = dict(self.artifact, **{field: replacement})
                self.build([row, dict(reason="build-finished", success=True)])
                with self.assertRaises(ValueError):
                    self.reader.before()
        self.build([self.artifact, dict(reason="build-finished", success=False)])
        with self.assertRaisesRegex(ValueError, "BUILD_FINISH_REQUIRED"):
            self.reader.before()

    def test_linked_binary_refuses_original_chain_file_reader(self):
        original = self.binary.with_suffix(".original")
        self.binary.rename(original)
        self.binary.symlink_to(original)
        with self.assertRaisesRegex(ValueError, "CANONICAL_FILE_REQUIRED"):
            self.reader.before()

    def test_failed_build_wrong_command_or_log_change_refuses(self):
        for changed in (
            dict(status="command_failed", exit_code=1),
            dict(argv=BUILD_COMMAND[:-1]),
            dict(log_sha256="0" * 64),
        ):
            with self.subTest(changed=changed):
                self.build(**changed)
                with self.assertRaisesRegex(ValueError, "CURRENT_BUILD_REQUIRED"):
                    self.reader.before()

    def test_wrong_runner_machine_refuses_before_controls(self):
        self.reader = BinaryObservation(self.chain, self.output, "ARM64")
        with self.assertRaisesRegex(ValueError, "RUNNER_ARCH_MISMATCH"):
            self.reader.before()


if __name__ == "__main__":
    unittest.main()
