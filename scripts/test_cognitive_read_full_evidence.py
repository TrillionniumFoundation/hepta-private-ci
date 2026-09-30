from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import cognitive_read_full_evidence as full


class CognitiveReadFullEvidenceTests(unittest.TestCase):
    def test_complete_commands_are_read_only_and_cover_remaining_gates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Path(temporary)
            commands = full.commands("1" * 40, evidence)
        for label in (
            "revision-shadow-tests",
            "owner-currentness-e2e",
            "stale-generation-e2e",
            "consumer-intelligence-product-e2e",
            "sqlite-capacity",
            *full.CONSUMER_PACKAGES,
        ):
            self.assertIn(label, commands)
        flattened = "\n".join(" ".join(argv) for argv in commands.values())
        for forbidden in ("git push", "git commit", "gh pr merge", "cargo publish"):
            self.assertNotIn(forbidden, flattened)

    def test_sqlite_measurement_requires_candidate_process_and_distributions(self) -> None:
        distribution = {"p50_us": 1, "p95_us": 2, "p99_us": 3}
        value = {
            "schema": full.SQLITE_CAPACITY_SCHEMA,
            "records": 512,
            "requested_ids": 512,
            "iterations": 32,
            "authority": "deny_all",
            "sqlite_file_bytes": 1,
            "sqlite_page_count": 1,
            "sqlite_page_size_bytes": 4096,
            "sqlite_memory_revision_rows": 512,
            "sqlite_source_rows": 1,
            "sqlite_citation_rows": 512,
            "acquire_snapshot": distribution,
            "prepare_index": distribution,
            "read_ids": distribution,
            "revalidate": distribution,
            "process": {
                "user_cpu_ms": 1,
                "system_cpu_ms": 1,
                "elapsed_wall_ms": 1,
                "cpu_percent": 100,
                "maximum_rss_kib": 1,
            },
            "candidate": {"commit": "a" * 40, "tree": "b" * 40},
        }
        self.assertEqual(full.validate_measurement("sqlite-capacity", value), [])
        value = json.loads(json.dumps(value))
        value["process"]["maximum_rss_kib"] = 0
        self.assertIn(
            "sqlite-capacity: zero maximum RSS",
            full.validate_measurement("sqlite-capacity", value),
        )


if __name__ == "__main__":
    unittest.main()
