from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "hepta_learning_artifacts_exporter",
    ROOT / "scripts" / "hepta-learning-artifacts-exporter.py",
)
assert SPEC is not None and SPEC.loader is not None
EXPORTER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = EXPORTER
SPEC.loader.exec_module(EXPORTER)


class ExporterTests(unittest.TestCase):
    def command(self) -> dict[str, object]:
        value: dict[str, object] = {"schema": EXPORTER.COMMAND_SCHEMA}
        for field in EXPORTER.COMMAND_COUNTERS:
            value[field] = 0
        return value

    def operational(self) -> dict[str, object]:
        value: dict[str, object] = {
            "schema": EXPORTER.OPERATIONAL_SCHEMA,
            "base": self.command(),
            "oldestPendingAttemptAgeSeconds": None,
            "drainAgeSeconds": None,
            "retention": {
                "pinnedBytes": 9,
                "pendingPhysicalEraseBytes": 12,
                "observedAt": 100,
                "sourceDigest": "a" * 64,
            },
            "stageSummaries": {},
        }
        for field in EXPORTER.OPERATIONAL_COUNTERS:
            value[field] = 0
        return value

    def test_real_nested_schema_is_projected(self) -> None:
        rendered = EXPORTER.render(self.operational(), 110, None).decode()
        self.assertIn("hepta_learning_artifact_owner_pinned_bytes 9", rendered)
        self.assertIn(
            "hepta_learning_artifact_owner_pending_physical_erasure_bytes 12",
            rendered,
        )
        self.assertIn("hepta_learning_artifact_owner_quarantine_items_known 0", rendered)

    def test_unknown_retention_is_not_reported_as_zero(self) -> None:
        operational = self.operational()
        operational["retention"] = None
        rendered = EXPORTER.render(operational, 110, None).decode()
        self.assertIn("hepta_learning_artifact_owner_pinned_bytes_known 0", rendered)
        self.assertNotIn("hepta_learning_artifact_owner_pinned_bytes 0", rendered)

    def test_stale_or_future_snapshot_fails_closed(self) -> None:
        with self.assertRaises(EXPORTER.SnapshotError):
            EXPORTER._require_fresh(100, 1000, 30, "fixture")
        with self.assertRaises(EXPORTER.SnapshotError):
            EXPORTER._require_fresh(100, 90, 30, "fixture")

    def test_negative_counter_rejects(self) -> None:
        operational = self.operational()
        operational["base"]["commandFailures"] = -1
        with self.assertRaises(EXPORTER.SnapshotError):
            EXPORTER.render(operational, 110, None)

    def test_quarantine_requires_digest_bound_fresh_observation(self) -> None:
        quarantine = EXPORTER.QuarantineObservation(105, 3, "b" * 64)
        rendered = EXPORTER.render(self.operational(), 110, quarantine).decode()
        self.assertIn("hepta_learning_artifact_owner_quarantine_items 3", rendered)
        with self.assertRaises(EXPORTER.SnapshotError):
            EXPORTER._digest("not-a-digest", "quarantine.sourceDigest")


if __name__ == "__main__":
    unittest.main()
