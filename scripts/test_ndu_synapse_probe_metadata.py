"""Synthetic small-file tests; no subprocess, network, Docker or native probe."""

from contextlib import redirect_stderr
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SPEC = importlib.util.spec_from_file_location(
    "ndu_synapse_probe_metadata",
    Path(__file__).with_name("ndu_synapse_probe_metadata.py"),
)
METADATA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(METADATA)


class ProbeMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="synapse-metadata-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.input_root = self.root / "tool-probe"
        self.input_root.mkdir()
        self.output = self.root / "summary.json"
        self.paths = []
        counts = {}
        for group, label, tool in METADATA.STAGES:
            number = counts.get(group, 0)
            counts[group] = number + 1
            directory = self.input_root / group
            directory.mkdir(exist_ok=True)
            path = directory / f"{number:03d}-END.json"
            value = {
                "tool": tool,
                "exit_code": 0,
                "executable_unchanged": True,
                "arguments": ["SECRET-ARGUMENT"],
                "environment": {"TOKEN": "SECRET-ENVIRONMENT"},
                "executable": {"path": "/SECRET-BINARY-PATH"},
                "cwd": "/SECRET-WORKING-PATH",
                "started_at": "SECRET-TIMESTAMP",
                "stdout": {
                    "path": f"{number:03d}-{label}.stdout",
                    "bytes": 8,
                    "sha256": "a" * 64,
                },
                "stderr": {
                    "path": f"{number:03d}-{label}.stderr",
                    "bytes": 0,
                    "sha256": "b" * 64,
                },
            }
            path.write_text(json.dumps(value))
            self.paths.append(path)

    def change(self, field, value):
        receipt = json.loads(self.paths[0].read_text())
        receipt[field] = value
        self.paths[0].write_text(json.dumps(receipt))

    def summary(self):
        return METADATA.collect(self.input_root)

    def first(self):
        return self.summary()["stages"][0]

    def run_main(self):
        return METADATA.main(
            ["--input-root", str(self.input_root), "--output", str(self.output)]
        )

    def test_complete_receipts_emit_only_whitelisted_bounded_metadata(self):
        self.assertEqual(self.run_main(), 0)
        raw = self.output.read_bytes()
        self.assertLessEqual(len(raw), METADATA.OUTPUT_LIMIT)
        self.assertNotIn(b"SECRET", raw)
        result = json.loads(raw)
        self.assertEqual(result["qualification_status"], "not_assessed")
        expected = []
        for _group, label, _tool in METADATA.STAGES:
            expected.append(
                {
                    "stage": label,
                    "receipt_status": "observed",
                    "exit_code": 0,
                    "timed_out": False,
                    "executable_unchanged": True,
                    "launch_error_present": False,
                    "stdout": {"bytes": 8, "sha256": "a" * 64},
                    "stderr": {"bytes": 0, "sha256": "b" * 64},
                }
            )
        self.assertEqual(
            result,
            {
                "schema": "hepta.synapse.probe-metadata.v1",
                "scope": "diagnostic_only_not_qualified",
                "qualification_status": "not_assessed",
                "stages": expected,
            },
        )

    def test_extra_receipts_and_raw_streams_are_not_opened(self):
        extra = self.paths[0].parent / "999-END.json"
        raw = self.paths[0].parent / "000-actual-cargo.stdout"
        extra.write_text("SECRET-EXTRA")
        raw.write_text("SECRET-RAW")
        with mock.patch.object(METADATA.os, "open", wraps=os.open) as observed:
            result = self.summary()
        opened = [str(call.args[0]) for call in observed.call_args_list]
        self.assertNotIn(extra.name, opened)
        self.assertNotIn(raw.name, opened)
        self.assertNotIn("SECRET", json.dumps(result))

    def test_missing_receipt_is_fixed_enum_and_nonzero_diagnostic(self):
        self.paths[0].unlink()
        self.assertEqual(self.run_main(), 1)
        self.assertEqual(
            self.first(), {"stage": "actual-cargo", "receipt_status": "missing"}
        )

    def test_absent_root_still_emits_not_assessed_summary(self):
        result = METADATA.collect(self.root / "absent")
        self.assertEqual(result["qualification_status"], "not_assessed")
        self.assertTrue(
            all(item["receipt_status"] == "missing" for item in result["stages"])
        )

    def test_malformed_duplicate_deep_and_nonfinite_json_rejected(self):
        cases = [
            b"not JSON",
            b"\xff",
            b'{"tool":"rustup","tool":"rustup"}',
            b"[" * 2000 + b"]" * 2000,
        ]
        original = self.paths[0].read_bytes()
        cases.append(original[:-1] + b',"ignored":NaN}')
        for raw in cases:
            with self.subTest(raw_size=len(raw)):
                self.paths[0].write_bytes(raw)
                self.assertEqual(self.first()["receipt_status"], "malformed")

    def test_exact_input_limit_allowed_and_one_more_byte_rejected(self):
        raw = self.paths[0].read_bytes()
        self.paths[0].write_bytes(raw + b" " * (METADATA.INPUT_LIMIT - len(raw)))
        self.assertEqual(self.first()["receipt_status"], "observed")
        with self.paths[0].open("ab") as stream:
            stream.write(b" ")
        self.assertEqual(self.first()["receipt_status"], "oversize")

    def test_reads_never_request_more_than_limit_plus_one(self):
        with mock.patch.object(METADATA.os, "read", wraps=os.read) as observed:
            self.summary()
        self.assertTrue(
            all(
                call.args[1] == METADATA.INPUT_LIMIT + 1
                for call in observed.call_args_list
            )
        )

    def test_receipt_growth_and_change_are_rejected(self):
        real_stat = os.fstat
        calls = []

        def changed(descriptor):
            actual = real_stat(descriptor)
            calls.append(descriptor)
            if len(calls) == 2:
                return mock.Mock(
                    st_size=actual.st_size,
                    st_mtime_ns=actual.st_mtime_ns + 1,
                    st_ctime_ns=actual.st_ctime_ns,
                )
            return actual

        with mock.patch.object(METADATA.os, "fstat", side_effect=changed):
            self.assertEqual(self.first()["receipt_status"], "changed")
        with mock.patch.object(
            METADATA.os, "read", return_value=b" " * (METADATA.INPUT_LIMIT + 1)
        ):
            self.assertEqual(self.first()["receipt_status"], "oversize")

    def test_strict_integer_boolean_and_digest_validation(self):
        original = json.loads(self.paths[0].read_text())
        mutations = [
            ("exit_code", True),
            ("exit_code", 0.0),
            ("exit_code", "0"),
            ("exit_code", 2**31),
            ("exit_code", -(2**31) - 1),
            ("timeout_expired", 0),
            ("timeout_expired", "false"),
            ("executable_unchanged", 1),
            ("executable_unchanged", None),
            ("launch_error", {}),
            ("tool", "unexpected"),
        ]
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                candidate = copy.deepcopy(original)
                candidate[field] = value
                self.paths[0].write_text(json.dumps(candidate))
                self.assertEqual(self.first()["receipt_status"], "malformed")
        for field, values in {
            "bytes": [True, -1, 1.0, 2**63],
            "sha256": [None, "a" * 63, "a" * 65, "A" * 64, "a" * 64 + "\n"],
            "path": ["../SECRET", "000-wrong-stage.stdout"],
        }.items():
            for value in values:
                with self.subTest(stream_field=field, value=value):
                    candidate = copy.deepcopy(original)
                    candidate["stdout"][field] = value
                    self.paths[0].write_text(json.dumps(candidate))
                    self.assertEqual(self.first()["receipt_status"], "malformed")

    def test_missing_required_fields_and_extra_stream_fields_rejected(self):
        original = json.loads(self.paths[0].read_text())
        for field in ("exit_code", "executable_unchanged", "stdout", "stderr"):
            with self.subTest(field=field):
                candidate = copy.deepcopy(original)
                del candidate[field]
                self.paths[0].write_text(json.dumps(candidate))
                self.assertEqual(self.first()["receipt_status"], "malformed")
        candidate = copy.deepcopy(original)
        candidate["stdout"]["raw"] = "SECRET"
        self.paths[0].write_text(json.dumps(candidate))
        self.assertEqual(self.first()["receipt_status"], "malformed")

    def test_launch_error_records_presence_without_free_text(self):
        value = json.loads(self.paths[0].read_text())
        value.update(exit_code=None, launch_error="SECRET-LAUNCH-ERROR")
        del value["stdout"]
        del value["stderr"]
        self.paths[0].write_text(json.dumps(value))
        record = self.first()
        self.assertEqual(record["receipt_status"], "observed")
        self.assertTrue(record["launch_error_present"])
        self.assertIsNone(record["stdout"])
        self.assertNotIn("SECRET", json.dumps(record))
        self.assertEqual(self.run_main(), 1)

    def test_exit_failure_timeout_and_changed_tool_are_not_green(self):
        original = self.paths[0].read_text()
        for field, value in [
            ("exit_code", 1),
            ("exit_code", -9),
            ("exit_code", None),
            ("timeout_expired", True),
            ("executable_unchanged", False),
        ]:
            with self.subTest(field=field):
                self.paths[0].write_text(original)
                self.change(field, value)
                if self.output.exists():
                    self.output.unlink()
                self.assertEqual(self.run_main(), 1)
                self.assertEqual(
                    json.loads(self.output.read_text())["qualification_status"],
                    "not_assessed",
                )

    def test_symlink_receipt_root_group_and_ancestor_rejected(self):
        target = self.root / "private.json"
        target.write_text("SECRET")
        self.paths[0].unlink()
        self.paths[0].symlink_to(target)
        self.assertEqual(self.first()["receipt_status"], "unsafe_path")
        link = self.root / "linked-root"
        link.symlink_to(self.input_root, target_is_directory=True)
        self.assertTrue(
            all(
                item["receipt_status"] == "unsafe_path"
                for item in METADATA.collect(link)["stages"]
            )
        )
        ancestor = self.root / "linked-ancestor"
        ancestor.symlink_to(self.root, target_is_directory=True)
        self.assertTrue(
            all(
                item["receipt_status"] == "unsafe_path"
                for item in METADATA.collect(ancestor / "tool-probe")["stages"]
            )
        )
        group = self.input_root / "bootstrap-tool-commands"
        moved = self.root / "moved-group"
        group.rename(moved)
        group.symlink_to(moved, target_is_directory=True)
        self.assertEqual(self.first()["receipt_status"], "unsafe_path")

    def test_directory_receipt_and_permission_error_rejected(self):
        self.paths[0].unlink()
        self.paths[0].mkdir()
        self.assertEqual(self.first()["receipt_status"], "not_regular")
        with mock.patch.object(
            METADATA, "directory_fd", side_effect=PermissionError("SECRET")
        ):
            result = self.summary()
        self.assertTrue(
            all(item["receipt_status"] == "unreadable" for item in result["stages"])
        )
        self.assertNotIn("SECRET", json.dumps(result))

    def test_output_limit_rejects_before_file_creation(self):
        with self.assertRaises(ValueError):
            METADATA.publish({"oversize": "x" * METADATA.OUTPUT_LIMIT}, self.output)
        self.assertFalse(self.output.exists())

    def test_existing_output_is_never_overwritten_and_errors_are_fixed(self):
        self.output.write_text("SECRET-EXISTING")
        errors = io.StringIO()
        with redirect_stderr(errors):
            self.assertEqual(self.run_main(), 2)
        self.assertEqual(self.output.read_text(), "SECRET-EXISTING")
        self.assertEqual(
            errors.getvalue(),
            "Probe metadata publication failed; no qualification assessed.\n",
        )

    def test_output_symlink_and_parent_symlink_are_rejected(self):
        target = self.root / "target"
        target.write_text("SECRET-EXISTING")
        self.output.symlink_to(target)
        with self.assertRaises(OSError):
            METADATA.publish(self.summary(), self.output)
        self.assertEqual(target.read_text(), "SECRET-EXISTING")
        link = self.root / "parent-link"
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            METADATA.publish(self.summary(), link / "new.json")
        self.assertFalse((self.root / "new.json").exists())


if __name__ == "__main__":
    unittest.main()
