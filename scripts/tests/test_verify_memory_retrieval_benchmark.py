from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.verify_memory_retrieval_benchmark import build_receipt
from scripts.verify_memory_retrieval_benchmark import enforce
from scripts.verify_memory_retrieval_benchmark import parse_log


class MemoryRetrievalBenchmarkTests(unittest.TestCase):
    def test_parse_and_enforce(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "probe.log"
            log.write_text(
                'noise\n{"schema":"hepta.memory-retrieval.target-host.v1","phase":"hnmf","p95_us":10}\n'
                "User time (seconds): 1.25\nMaximum resident set size (kbytes): 2048\n",
                encoding="utf-8",
            )
            parsed = parse_log(log)
            self.assertEqual(parsed["record"]["phase"], "hnmf")
            self.assertEqual(parsed["resource"]["max_rss_kb"], 2048)
            enforce([parsed], {"phases": {"hnmf": {"maximum": {"p95_us": 20}}}})
            with self.assertRaisesRegex(ValueError, "exceeds"):
                enforce([parsed], {"phases": {"hnmf": {"maximum": {"p95_us": 5}}}})

    def test_receipt_binds_source_host_limits_and_logs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "probe.log"
            log.write_text('{"schema":"hepta.memory-retrieval.target-host.v1","phase":"hnmf","p95_us":10}\n', encoding="utf-8")
            limits = root / "limits.json"
            limits.write_text(json.dumps({"phases": {"hnmf": {"maximum": {"p95_us": 20}}}}), encoding="utf-8")
            host = root / "host.txt"
            host.write_text("host", encoding="utf-8")
            receipt = build_receipt([log], limits, host, source_commit="a" * 40, source_tree="b" * 40)
            self.assertEqual(receipt["decision"], "qualification_limits_passed")
            self.assertEqual(receipt["sourceCommit"], "a" * 40)
            self.assertEqual(len(receipt["measurements"]), 1)


if __name__ == "__main__":
    unittest.main()
