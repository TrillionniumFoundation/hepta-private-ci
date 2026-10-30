"""Check retained real qualification evidence; never substitute a mock runtime."""

import gzip
import json
import math
import os
from pathlib import Path
import unittest
import zipfile

from ..round4.runtime_owner import file_sha
from .qualifier import BINARY_SHA256, MODES, Q24, TAILS


class ActualQualification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        value = os.environ.get("HEPTA_QUALIFICATION_RESULT")
        if not value:
            raise RuntimeError("Set HEPTA_QUALIFICATION_RESULT to a completed actual qualifier result directory")
        cls.root = Path(value).resolve()
        cls.report = json.loads((cls.root / "RESULT.json").read_text())
        cls.checks = [json.loads(line) for line in (cls.root / "CHECKS.jsonl").read_text().splitlines()]

    def test_closed_actual_evidence_inventory(self):
        self.assertIs(self.report["passed"], True)
        self.assertEqual(self.report["binary_sha256"], BINARY_SHA256)
        self.assertEqual(self.report["checks"], len(self.checks))
        self.assertTrue(all(row["passed"] for row in self.checks))
        for name, expected in self.report["evidence_sha256"].items():
            self.assertEqual(file_sha(self.root / name), expected, name)
        manifest = json.loads((self.root / "OWNERS.manifest.json").read_text())["files"]
        import hashlib
        with zipfile.ZipFile(self.root / "OWNERS.zip") as archive:
            self.assertEqual(set(archive.namelist()), set(manifest))
            for name, expected in manifest.items():
                payload = archive.read(name)
                self.assertEqual({"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}, expected)

    def test_full_interruption_and_refusal_matrix(self):
        failures = [json.loads(line) for line in (self.root / "INTERRUPTIONS.jsonl").read_text().splitlines()]
        self.assertEqual(len(failures), 24)
        matrix = {(r["mode"], r["components"], r["stage"]) for r in failures}
        stages = ("after_packet", "after_first_native", "after_native", "after_commit")
        self.assertEqual(matrix, {(mode, k, stage) for mode in MODES for k in (1, 2) for stage in stages})
        for row in failures:
            expected = {"after_packet": 0, "after_first_native": 1,
                        "after_native": row["components"], "after_commit": row["components"]}[row["stage"]]
            self.assertEqual(row["actual_native_calls"], expected)
        names = {row["name"] for row in self.checks}
        for mode in MODES:
            for k in (1, 2):
                for label in ("stale checkpoint", "changed duplicate", "component-count change",
                              "seventeenth request", "decoder CRC", "decoder component-count change",
                              "decoder seventeenth request", "lost acknowledgement exact cached receipt"):
                    self.assertIn(f"{mode}/K{k}: {label}", names)
        self.assertTrue(all(r["new_native_attempts"] == 0 for r in self.checks if "new_native_attempts" in r))

    def test_fresh_process_continuation_and_native_accounting(self):
        self.assertEqual(len(self.report["recoveries"]), 6)
        self.assertEqual(self.report["in_process_native"]["successful_requests"], 212)
        self.assertEqual(self.report["in_process_native"]["attempted_requests"], 214)
        for mode in MODES:
            for k in (1, 2):
                job = json.loads((self.root / f"RESTART_{mode}_K{k}_JOB.json").read_text())
                result = json.loads((self.root / f"RESTART_{mode}_K{k}.json").read_text())
                self.assertEqual(result["cached"], job["cached"])
                self.assertEqual(result["before_continuation"]["attempted_requests"], 0)
                self.assertEqual(result["native"]["successful_requests"], k)
                self.assertEqual(result["native"]["original_sparse_ticks"], k)
                self.assertEqual(result["continued"]["checkpoint_before"], job["checkpoint"])
                self.assertEqual(result["continued"]["law"], job["cached"]["law"])
        self.assertIs(self.report["cross_owner_atomicity"], False)
        self.assertIs(self.report["production_activation"], False)

    def test_extreme_tail_release_and_actual_sixteen_step_bound(self):
        with gzip.open(self.root / "FORECASTS.json.gz", "rt") as stream:
            rows = json.load(stream)["owners"]
        self.assertEqual(len(rows), 135)
        self.assertEqual(sum(row["sequence"] == 16 for row in rows), 6)
        tails = [row for row in rows if row["source_law"] in TAILS]
        self.assertEqual(len(tails), 12)
        for row in tails:
            law = row["law"]
            self.assertTrue(all(math.isfinite(v) for v in law["physical_log_probabilities"]))
            self.assertEqual(sum(law["probabilities_q24"]), Q24)
            self.assertGreaterEqual(min(law["probabilities_q24"]), 1)
            self.assertEqual(min(law["raw_probabilities_q24"]), 0)
            self.assertLessEqual(max(abs(a-b) for a,b in zip(law["probabilities"], law["native_mixture_probabilities"])), 3/Q24)


if __name__ == "__main__":
    unittest.main()
