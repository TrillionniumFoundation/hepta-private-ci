from __future__ import annotations

import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "hepta_learning_artifacts_exporter",
    ROOT / "scripts" / "hepta-learning-artifacts-exporter.py",
)
assert SPEC is not None and SPEC.loader is not None
EXPORTER = importlib.util.module_from_spec(SPEC)
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
            "oldestPendingAttemptAgeSeconds": None,
            "drainAgeSeconds": None,
            "pinnedBytes": None,
            "pendingPhysicalErasureBytes": 12,
            "retentionObservationDigest": None,
        }
        for field in EXPORTER.OPERATIONAL_COUNTERS:
            value[field] = 0
        for field in EXPORTER.OPERATIONAL_GAUGES:
            value[field] = 100
        return value

    def test_unknown_values_are_not_reported_as_zero(self) -> None:
        rendered = EXPORTER.render(self.command(), self.operational(), 110, 30).decode()
        self.assertIn("hepta_learning_artifact_owner_pinned_bytes_known 0", rendered)
        self.assertNotIn("hepta_learning_artifact_owner_pinned_bytes 0", rendered)
        self.assertIn(
            "hepta_learning_artifact_owner_pending_physical_erasure_bytes 12",
            rendered,
        )

    def test_stale_or_future_snapshot_fails_closed(self) -> None:
        with self.assertRaises(EXPORTER.SnapshotError):
            EXPORTER.render(self.command(), self.operational(), 1000, 30)
        with self.assertRaises(EXPORTER.SnapshotError):
            EXPORTER.render(self.command(), self.operational(), 90, 30)

    def test_negative_counter_rejects(self) -> None:
        command = self.command()
        command["commandFailures"] = -1
        with self.assertRaises(EXPORTER.SnapshotError):
            EXPORTER.render(command, self.operational(), 110, 30)


if __name__ == "__main__":
    unittest.main()
