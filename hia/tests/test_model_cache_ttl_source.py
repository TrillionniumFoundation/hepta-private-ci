"""Static-only checks for the proposed model-cache HIA TTL comparator.

This does NOT execute a HIA compiler, native object, or original Rust oracle.
"""

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "model_cache_ttl_oracle_inputs.json"
SOURCE = ROOT / "model_cache_ttl.hepta"


class ModelCacheTtlSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = json.loads(FIXTURES.read_text(encoding="utf-8"))

    def test_complete_literal_decisions(self):
        rows = self.corpus["cases"]
        self.assertEqual(len(rows), 18)
        self.assertEqual(len({row["label"] for row in rows}), len(rows))
        for row in rows:
            with self.subTest(row=row["label"]):
                age = row["age_seconds"] * 1_000_000_000 + row["age_nanos"]
                ttl = row["ttl_seconds"] * 1_000_000_000 + row["ttl_nanos"]
                self.assertEqual((ttl > 0) and (age <= ttl), row["expected_fresh"])
                self.assertLessEqual(abs(row["age_nanos"]), 999_999_999)
                self.assertLessEqual(row["ttl_nanos"], 999_999_999)
                if row["age_seconds"] != 0 and row["age_nanos"] != 0:
                    self.assertEqual(row["age_seconds"] < 0, row["age_nanos"] < 0)

    def test_malformed_packet_statuses_are_literal(self):
        rows = self.corpus["error_cases"]
        self.assertEqual(len(rows), 8)
        self.assertEqual(len({row["label"] for row in rows}), len(rows))
        for row in rows:
            expected = 0xFFFF_FFFE if row["output_bytes"] < 8 else 0xFFFF_FFFF
            self.assertEqual(row["expected_status"], expected)

    def test_source_is_separate_unregistered_candidate(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertTrue(source.startswith("hia-asm.v1 hepta.hia.program.v9 codex_model_cache_ttl\n"))
        self.assertIn("fn f0(source:readbuf,output:mutbuf,workspace:mutbuf)", source)
        self.assertIn("branch zero_ttl stale(z_output)", source)
        self.assertIn("branch signed_consistent ttl_zero(", source)
        self.assertIn("  ret(successful_bytes)", source)
        self.assertEqual(source.count("buffer.store.u64.le"), 1)
        self.assertIn("4294967294", source)
        self.assertIn("4294967295", source)
        self.assertTrue(source.endswith("end\n"))


if __name__ == "__main__":
    unittest.main()
