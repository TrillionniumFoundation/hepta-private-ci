"""Explicit tiny synthetic files only. No 400M/421M weights or authorization."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import review_bytes
import runtime_snapshot
import source_bytes
from test_source_bytes import harness


class RuntimeSnapshotTests(unittest.TestCase):
    def setup_case(self, model="ettin400"):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        stage = Path(temp.name) / "stage"
        lookup, downloader, _ = harness(model)
        receipt = source_bytes.acquire(model, lookup, downloader, stage)
        return receipt, stage

    def test_exact_allowlist_copy_and_cleanup(self):
        receipt, stage = self.setup_case()
        destination = None
        with runtime_snapshot.isolated_verified_runtime(receipt, stage) as runtime:
            destination = runtime
            expected = {v["filename"] for v in receipt["selected_source_inventory"]}
            actual = {p.relative_to(runtime).as_posix() for p in runtime.rglob("*") if p.is_file()}
            self.assertEqual(actual, expected)
            self.assertTrue(review_bytes.audit(receipt, runtime)["independently_rehashed_exact_physical_bytes"])
            self.assertNotEqual(runtime.resolve(), stage.resolve())
        self.assertFalse(destination.exists())

    def test_reject_modified_source_content(self):
        receipt, stage = self.setup_case()
        (stage / "config.json").write_text("tampered")
        with self.assertRaises(review_bytes.Rejected):
            with runtime_snapshot.isolated_verified_runtime(receipt, stage):
                self.fail("tampered stage was loaded")

    def test_reject_late_added_files(self):
        receipt, stage = self.setup_case()
        (stage / "generation_config.json").write_text("unreviewed")
        with self.assertRaisesRegex(review_bytes.Rejected, "unregistered"):
            with runtime_snapshot.isolated_verified_runtime(receipt, stage):
                self.fail("unregistered file was loaded")

    def test_transfer_cache_is_never_loaded(self):
        receipt, stage = self.setup_case()
        cache = stage / ".cache" / "huggingface"
        cache.mkdir(parents=True)
        (cache / "download").write_bytes(b"only private transfer bookkeeping")
        with runtime_snapshot.isolated_verified_runtime(receipt, stage) as runtime:
            self.assertFalse((runtime / ".cache").exists())

    def test_original_stage_cannot_be_mutated_by_loader(self):
        receipt, stage = self.setup_case()
        original = (stage / "tokenizer.json").read_bytes()
        with runtime_snapshot.isolated_verified_runtime(receipt, stage) as runtime:
            (runtime / "tokenizer.json").write_bytes(b"isolated runtime normalization")
            self.assertEqual((stage / "tokenizer.json").read_bytes(), original)
            with self.assertRaises(review_bytes.Rejected):
                review_bytes.audit(receipt, runtime)
        self.assertTrue(review_bytes.audit(receipt, stage)["independently_rehashed_exact_physical_bytes"])

    def test_no_unverified_symlink_copy(self):
        receipt, stage = self.setup_case()
        (stage / "bogus.json").symlink_to("tokenizer.json")
        with self.assertRaisesRegex(review_bytes.Rejected, "symlink"):
            with runtime_snapshot.isolated_verified_runtime(receipt, stage):
                self.fail("symlink was copied")

    def test_no_weight_source_returns_success_on_copy_failure(self):
        receipt, stage = self.setup_case()
        (stage / "pytorch_model.bin").unlink()
        with self.assertRaises(review_bytes.Rejected):
            with runtime_snapshot.isolated_verified_runtime(receipt, stage):
                self.fail("missing source weight was accepted")


if __name__ == "__main__":
    unittest.main()
