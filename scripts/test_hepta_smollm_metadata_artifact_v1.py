"""Real local-file export controls; no model, training or install is simulated."""

import gzip
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import hepta_smollm_metadata_artifact_v1 as export


class MetadataArtifactTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "run"
        self.root.mkdir()
        self.output = self.base / "metadata"
        self.source = "a" * 40
        self.rows = {}

    def file(self, name, raw):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        self.rows[name] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        return path

    def index(self, **changes):
        value = dict(
            source=self.source,
            chain="b" * 40,
            research_chain="c" * 40,
            answer_eos_research_outcome="skipped",
            files=self.rows,
            product_qualification=False,
            three_installed_upgrades_proven=False,
            held_runtime_closure_proven=False,
        )
        value.update(changes)
        (self.root / "evidence-index.json").write_text(json.dumps(value))

    def run_export(self):
        return export.export(self.root, self.output, self.source)

    def test_declared_failed_records_retained_without_tensor_archive_or_hidden_payload(
        self,
    ):
        log = "scoped-rust.json." + "a" * 32 + ".log"
        self.file("scoped-rust.json", b'{"status":"failed","observed_failed_tests":35}')
        self.file(log, b"1840 passed; 35 failed\n")
        self.file(
            "metadata-export-controls.json",
            b'{"status":"passed","observed_passed_tests":14}',
        )
        self.file("n/p/round-1/assessment.json", b'{"installed_child":false}')
        self.file(
            "n/p/round-1/train-candidate/execution/artifact.safetensors",
            b"dummy tensor fixture",
        )
        self.file(
            "n/p/round-1/train-candidate/execution/checkpoint.tar.gz",
            gzip.compress(b"dummy tensor fixture inside an archive"),
        )
        self.file(
            "n/p/round-1/train-candidate/execution/wrapped-adapter.json",
            b'{"modules":{"q_proj":{"A":[1,2]}}}',
        )
        self.file(".hidden/scoped-rust.json", b'{"private_key":"test-only"}')
        self.file("n/p/o/b/fleet/checkpoints/assessment.json", b'{"weights":[1,2]}')
        self.index()
        result = self.run_export()
        expected = {
            "metadata-export-controls.json",
            "scoped-rust.json",
            log,
            "n/p/round-1/assessment.json",
            "evidence-index.json",
        }
        self.assertEqual(set(result["files"]), expected)
        self.assertEqual(result["omitted_file_count"], 5)
        self.assertEqual(
            {
                str(p.relative_to(self.output))
                for p in self.output.rglob("*")
                if p.is_file()
            },
            expected | {"metadata-export.json"},
        )
        for relative in expected:
            self.assertEqual(
                (self.output / relative).read_bytes(),
                (self.root / relative).read_bytes(),
            )
        self.assertFalse(result["checkpoint_payloads_exported"])
        self.assertFalse(result["independent_payload_replay_available"])

    def test_omitted_checkpoint_hash_does_not_require_payload_read_or_claim_retention(
        self,
    ):
        self.rows["model.safetensors"] = dict(bytes=1_000_000_000, sha256="d" * 64)
        self.index()
        result = self.run_export()
        self.assertEqual(set(result["files"]), {"evidence-index.json"})
        self.assertEqual(result["omitted_file_count"], 1)
        self.assertFalse(result["independent_payload_replay_available"])

    def test_wrong_index_hash_aborts_without_publishing_partial_directory(self):
        self.file("hepta-source.txt", b"original\n")
        self.file("required-outcomes.json", b'{"all_required_outcomes_passed":false}')
        self.index()
        (self.root / "required-outcomes.json").write_bytes(b'{"changed":true}')
        with self.assertRaisesRegex(ValueError, "differs from original index"):
            self.run_export()
        self.assertFalse(self.output.exists())

    def test_symbolic_link_file_refuses_external_payload(self):
        target = self.base / "external"
        target.write_bytes(b'{"status":"passed"}')
        self.rows["scoped-rust.json"] = dict(
            bytes=target.stat().st_size,
            sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        )
        (self.root / "scoped-rust.json").symlink_to(target)
        self.index()
        with self.assertRaises(OSError):
            self.run_export()
        self.assertFalse(self.output.exists())

    def test_symbolic_link_parent_refuses_even_matching_metadata_bytes(self):
        target = self.base / "external"
        target.mkdir()
        raw = b'{"installed_child":false}'
        (target / "assessment.json").write_bytes(raw)
        (self.root / "n/p").mkdir(parents=True)
        (self.root / "n/p/round-1").symlink_to(target, target_is_directory=True)
        self.rows["n/p/round-1/assessment.json"] = dict(
            bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()
        )
        self.index()
        with self.assertRaises(OSError):
            self.run_export()
        self.assertFalse(self.output.exists())

    def test_fifo_is_not_opened_as_an_unbounded_log(self):
        name = "scoped-rust.json." + "b" * 32 + ".log"
        os.mkfifo(self.root / name)
        self.rows[name] = dict(bytes=0, sha256=hashlib.sha256(b"").hexdigest())
        self.index()
        with self.assertRaisesRegex(ValueError, "regular bounded"):
            self.run_export()
        self.assertFalse(self.output.exists())

    def test_binary_data_cannot_borrow_declared_log_name(self):
        self.file("scoped-rust.json." + "c" * 32 + ".log", b"binary\x00payload")
        self.index()
        with self.assertRaisesRegex(ValueError, "binary data"):
            self.run_export()
        self.assertFalse(self.output.exists())

    def test_binary_patch_cannot_be_uploaded_as_source_text(self):
        self.file("final-source-diff.patch", b"GIT binary patch\nliteral 12\nencoded\n")
        self.index()
        with self.assertRaisesRegex(ValueError, "binary source patch"):
            self.run_export()
        self.assertFalse(self.output.exists())

    def test_tensor_serialization_in_declared_json_refuses(self):
        self.file(
            "n/p/round-1/assessment.json", b'{"candidate":{"state_dict":{"q":[1,2]}}}'
        )
        self.index()
        with self.assertRaisesRegex(ValueError, "payload-bearing"):
            self.run_export()
        self.assertFalse(self.output.exists())

    def test_duplicate_json_key_refuses_without_silent_last_value_selection(self):
        self.file("scoped-rust.json", b'{"status":"failed","status":"passed"}')
        self.index()
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            self.run_export()
        self.assertFalse(self.output.exists())

    def test_wrong_source_or_true_qualification_refuses_before_output_creation(self):
        for changes in (dict(source="d" * 40), dict(product_qualification=True)):
            with self.subTest(changes=changes):
                self.index(**changes)
                with self.assertRaises(ValueError):
                    self.run_export()
                self.assertFalse(self.output.exists())

    def test_output_is_create_only_and_cannot_be_the_original_run(self):
        self.index()
        self.output.mkdir()
        sentinel = self.output / "original"
        sentinel.write_text("keep")
        with self.assertRaises(FileExistsError):
            self.run_export()
        self.assertEqual(sentinel.read_text(), "keep")
        with self.assertRaisesRegex(ValueError, "separate absolute"):
            export.export(self.root, self.root / "output", self.source)
        self.assertFalse((self.root / "output").exists())

    def test_file_and_export_bounds_refuse_without_partial_publication(self):
        self.file("scoped-rust.json." + "e" * 32 + ".log", b"x" * 8192)
        self.index()
        for setting in ("MAX_FILE_BYTES", "MAX_EXPORT_BYTES"):
            with self.subTest(setting=setting), patch.object(export, setting, 4096):
                with self.assertRaises(ValueError):
                    self.run_export()
                self.assertFalse(self.output.exists())

    def test_cost_event_jsonl_requires_every_line_to_be_metadata(self):
        self.file(
            "n/p/round-1/train-candidate/execution/cost-events.jsonl",
            b'{"wall_ns":12}\n{"tensor_bytes":"encoded"}\n',
        )
        self.index()
        with self.assertRaisesRegex(ValueError, "payload-bearing"):
            self.run_export()
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
