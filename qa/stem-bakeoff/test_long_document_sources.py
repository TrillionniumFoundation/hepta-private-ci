"""Full-source reconstruction and source/version/range integrity regressions."""

import gzip
import json
from pathlib import Path
import tempfile
import unittest

from long_document_sources import FullSourceBank, canonical, sha


class FullSourceBankTests(unittest.TestCase):
    def fixture(self, root, statement="边界😀" * 5000):
        version = {"dataset_revision": "pinned", "repo": "repo/name"}
        original = {"source_id": "issue1", "source_version": "sha256:" + sha(canonical(version)),
                    "repo": "repo/name", "created_at": "2020-01-01T00:00:00Z",
                    "problem_statement": statement}
        full = f"Repository: repo/name\n\nIssue:\n{statement}"
        dataset = {"rows": [{"source_id": "issue1", "source_version": version,
                             "text": full.encode()[:16384].decode("utf-8", errors="ignore"),
                             "labels": {"never_in_input": 1}}]}
        paths = [root / name for name in ("dataset.json", "sources.gz", "receipt.json")]
        paths[0].write_bytes(canonical(dataset))
        paths[1].write_bytes(gzip.compress(canonical(original) + b"\n", mtime=0))
        paths[2].write_bytes(canonical({"schema": "hepta.exact-source-recovery.v1",
            "dataset_sha256": sha(paths[0].read_bytes()), "archive_sha256": sha(paths[1].read_bytes()),
            "source_count": 1, "byte_exact_recoveries": 1, "fresh_process": True}))
        return paths, full

    def test_tail_beyond_original_byte_cap_is_preserved_and_addressable(self):
        with tempfile.TemporaryDirectory() as directory:
            paths, full = self.fixture(Path(directory))
            bank = FullSourceBank(*paths)
            row = bank.records()[0]
            self.assertEqual(row["text"], full)
            self.assertGreater(row["source_utf8_bytes"], 16384)
            payload, receipt = bank.read_slice("issue1", row["source_version"], len(full) - 3,
                                               len(full), row["source_utf8_sha256"])
            self.assertEqual(payload, full[-3:].encode())
            self.assertEqual(receipt["utf8_span"][1], len(full.encode()))
            self.assertEqual(bank.accounting()["exact_range_reads"], 1)
            self.assertEqual(bank.accounting()["encoder_calls"], 0)
            row["text"] = "mutated copy"
            self.assertEqual(bank.records()[0]["text"], full)
            bank.verify_files()

    def test_missing_stale_invalid_range_and_changed_source_reject(self):
        with tempfile.TemporaryDirectory() as directory:
            paths, full = self.fixture(Path(directory), "abc")
            bank = FullSourceBank(*paths); row = bank.records()[0]
            cases = [("missing", row["source_version"], 0, 1, row["source_utf8_sha256"]),
                     ("issue1", "stale", 0, 1, row["source_utf8_sha256"]),
                     ("issue1", row["source_version"], 0, 1, "a" * 64),
                     ("issue1", row["source_version"], 0, len(full) + 1, row["source_utf8_sha256"]),
                     ("issue1", row["source_version"], True, 1, row["source_utf8_sha256"])]
            for case in cases:
                with self.subTest(case=case), self.assertRaises(ValueError):
                    bank.read_slice(*case)
            paths[1].write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "changed"):
                bank.verify_files()
            with self.assertRaises(ValueError):
                FullSourceBank(*paths)

    def test_source_revision_and_original_predictor_are_both_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            paths, _ = self.fixture(Path(directory), "abc")
            data = json.loads(paths[0].read_bytes()); data["rows"][0]["text"] = "altered"
            paths[0].write_bytes(canonical(data))
            report = json.loads(paths[2].read_bytes()); report["dataset_sha256"] = sha(paths[0].read_bytes())
            paths[2].write_bytes(canonical(report))
            with self.assertRaisesRegex(ValueError, "original bounded predictor"):
                FullSourceBank(*paths)


if __name__ == "__main__":
    unittest.main()
