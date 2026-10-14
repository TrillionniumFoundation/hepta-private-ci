"""Source and weight-integrity checks; no synthetic model result is called real."""
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from four_gate_pretrained import SOURCES, build_schedule, file_hash, verify_download


class PhysicalCaptureContracts(unittest.TestCase):
    def test_exact_lfs_bytes_before_deserialization(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.bin"
            path.write_bytes(b"fixture restricted weight bytes")
            meta = SimpleNamespace(size=path.stat().st_size, blob_id="a" * 40,
                                   lfs=SimpleNamespace(sha256=file_hash(path)))
            receipt = verify_download(path, meta)
            self.assertEqual(receipt["sha256"], file_hash(path))
            path.write_bytes(b"fixture restricted WEIGHT bytes")
            with self.assertRaises(ValueError):
                verify_download(path, meta)

    def test_git_blob_header_is_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_bytes(b"{}")
            expected = hashlib.sha1(b"blob 2\0{}").hexdigest()
            meta = SimpleNamespace(size=2, lfs=None, blob_id=expected)
            self.assertEqual(verify_download(path, meta)["upstream_git_blob"], expected)
            meta.blob_id = "b" * 40
            with self.assertRaisesRegex(ValueError, "Git blob"):
                verify_download(path, meta)

    def test_real_excerpt_schedule_does_not_invent_unique_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for i, relative in enumerate(SOURCES):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("\n\n".join(f"section {i}:{j} " + "source text " * 12
                                            for j in range(40)))
            rows, payloads, sources = build_schedule(root, 64, 10000, 9000)
            self.assertEqual(len(rows), 64)
            self.assertEqual(len({r["state_sha256"] for r in rows}), 6)
            self.assertEqual(len(sources), 3)
            self.assertTrue(payloads["request-0"]["joint"].startswith("Question:"))
            self.assertLess(payloads["request-0"]["joint"].index("Options:"),
                            payloads["request-0"]["joint"].index("State:"))
            self.assertNotIn("Question:", payloads["request-0"]["state"])
            with self.assertRaisesRegex(ValueError, "insufficient distinct"):
                build_schedule(root, 4096, 10000, 0)

    def test_real_corpus_supports_all_36_workload_settings_without_fake_ids(self):
        corpus = [f"publisher fixture utterance {i}" for i in range(5000)]
        for cells in (64, 256, 1024, 4096):
            for active in (500, 2500, 10000):
                for repeat in (0, 5000, 9000):
                    rows, payloads, sources = build_schedule(Path("not-read"), cells, active, repeat,
                                                              public_corpus=corpus)
                    self.assertEqual(len(rows), len({r["cell_id"] for r in rows}))
                    self.assertEqual(len({r["state_sha256"] for r in rows}),
                                     max(1, round(len(rows) * (1 - repeat / 10000))))
                    self.assertTrue(all(v["state"] in corpus for v in payloads.values()))
                    self.assertIn("publisher_train_text_inventory", sources)

    def test_missing_real_source_is_not_replaced_with_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "missing source"):
                build_schedule(Path(directory), 64, 10000, 9000)


if __name__ == "__main__":
    unittest.main()
