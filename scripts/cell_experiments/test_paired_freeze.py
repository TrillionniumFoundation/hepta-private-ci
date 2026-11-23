"""Use tiny on-disk inventory fixtures. No model or verifier execution is needed."""

import copy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from . import adoption, coding_sft, data, paired_cold, paired_freeze
from .test_data import record


class PairedFreezeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.spec_path = self.root / "input.json"
        self.snapshot = self.root / "freeze.json"
        self.future_path = self.root / "future.json"
        self.request_path = self.root / "request.json"
        parent = self.manifest("parent")
        self.spec = {
            "parent": parent,
            "candidate": self.manifest("candidate", data.digest(parent)),
            "retention": [record(1, "selection")],
            "timeout_seconds": 17,
        }
        self.future = [record(2, "confirmation")]
        self.future[0]["authorization"]["training_allowed"] = False
        self.save(self.spec_path, self.spec)

    def manifest(self, name, parent=None):
        directory = self.root / name
        directory.mkdir()
        for filename in ("config.json", "tokenizer.json", "tokenizer_config.json"):
            (directory / filename).write_bytes(b"{}")
        (directory / "model.safetensors").write_text("fixture " + name)
        return {
            "schema": coding_sft.MODEL_SCHEMA,
            "family": coding_sft.FAMILY,
            "parent": parent,
            "files": coding_sft.inventory(self.root, directory.iterdir(), "base"),
            "runtime": {"base_directory": name, "adapter_directory": None},
        }

    def save(self, path, value):
        path.write_bytes(data.canonical(value))

    def freeze(self):
        return paired_freeze.freeze(self.spec_path, self.root, self.snapshot)

    def assemble(self, expected):
        return paired_freeze.assemble(
            self.snapshot, expected, self.future_path, self.request_path
        )

    def test_freeze_then_bind_later_future_to_exact_runner_request(self):
        self.assertFalse(self.future_path.exists())
        expected = self.freeze()
        snapshot = adoption.read_json(self.snapshot)
        self.assertEqual(expected, data.digest(snapshot))
        self.assertEqual(snapshot, {"schema": paired_freeze.FREEZE_SCHEMA, **self.spec})
        self.save(self.future_path, self.future)
        request_hash = self.assemble(expected)
        self.assertEqual(
            paired_cold.checked_request(self.request_path, request_hash),
            {
                "schema": paired_freeze.REQUEST_SCHEMA,
                **self.spec,
                "future": self.future,
            },
        )

    def test_freeze_rejects_future_field_even_if_empty(self):
        for extra in (self.future, []):
            with self.subTest(extra=bool(extra)):
                self.save(self.spec_path, {**self.spec, "future": extra})
                with self.assertRaisesRegex(ValueError, "freeze accepts only"):
                    self.freeze()
                self.assertFalse(self.snapshot.exists())

    def test_verify_each_inventory_before_publishing(self):
        for arm in ("parent", "candidate"):
            path = self.root / arm / "model.safetensors"
            original = path.read_bytes()
            with self.subTest(arm=arm):
                path.write_bytes(original[::-1])
                with self.assertRaisesRegex(ValueError, "model artifact identity"):
                    self.freeze()
                self.assertFalse(self.snapshot.exists())
                path.write_bytes(original)

    def test_changed_manifest_retention_or_timeout_fails_before_reading_future(self):
        expected = self.freeze()
        original = adoption.read_json(self.snapshot)
        for field in ("parent", "candidate", "retention", "timeout_seconds"):
            with self.subTest(field=field):
                self.save(self.snapshot, {**original, field: None})
                with self.assertRaisesRegex(ValueError, "retained freeze digest"):
                    self.assemble(expected)
                self.assertFalse(self.request_path.exists())
        self.save(self.snapshot, original)
        with self.assertRaisesRegex(ValueError, "retained freeze digest"):
            self.assemble("0" * 64)

    def test_rejects_mutable_request_fields_or_ineligible_future(self):
        expected = self.freeze()
        trainable = copy.deepcopy(self.future[0])
        trainable["authorization"]["training_allowed"] = True
        duplicate = copy.deepcopy(self.future[0])
        duplicate["task_id"] = self.spec["retention"][0]["task_id"]
        cases = [
            ({"future": self.future, "timeout_seconds": 18}, "future list"),
            ([], "future list"),
            ([trainable], "evaluation-only"),
            ([{**self.future[0], "split": "selection"}], "evaluation-only"),
            ([duplicate], "repeated task identity"),
        ]
        for future, reason in cases:
            with self.subTest(reason=reason):
                self.save(self.future_path, future)
                with self.assertRaisesRegex(ValueError, reason):
                    self.assemble(expected)
                self.assertFalse(self.request_path.exists())

    def test_neither_phase_overwrites_an_existing_file(self):
        self.snapshot.write_text("existing snapshot")
        with self.assertRaises(FileExistsError):
            self.freeze()
        self.assertEqual(self.snapshot.read_text(), "existing snapshot")
        self.snapshot.unlink()
        expected = self.freeze()
        self.save(self.future_path, self.future)
        self.request_path.write_text("existing request")
        with self.assertRaises(FileExistsError):
            self.assemble(expected)
        self.assertEqual(self.request_path.read_text(), "existing request")


if __name__ == "__main__":
    unittest.main()
