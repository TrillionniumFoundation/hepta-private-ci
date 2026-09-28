#!/usr/bin/env python3
"""Offline source/config drift checks; not proof of a deployed collector."""
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs/modules/auth.authbus"


class OperationsContract(unittest.TestCase):
    def test_dashboard_uses_the_native_exported_gauges(self):
        source = (ROOT / "codex-rs/hepta-authbus/src/metrics.rs").read_text()
        names = set(re.findall(r'"(hepta_authbus_[a-z_]+)"\s*,', source))
        self.assertEqual(len(names), 15)
        dashboard = json.loads((DOCS / "grafana-dashboard.json").read_text())
        expressions = " ".join(target["expr"] for panel in dashboard["panels"] for target in panel["targets"])
        self.assertEqual(names, set(re.findall(r"hepta_authbus_[a-z_]+", expressions)))
        self.assertEqual(len({panel["id"] for panel in dashboard["panels"]}), len(dashboard["panels"]))

    def test_alerts_cover_missing_stale_and_unsafe_state(self):
        rules = json.loads((DOCS / "prometheus.rules.json").read_text())["groups"][0]["rules"]
        names = {rule["alert"] for rule in rules}
        self.assertEqual(len(names), len(rules))
        self.assertTrue({"AuthBusExporterUnavailable", "AuthBusSnapshotMissing", "AuthBusSnapshotStale", "AuthBusCheckpointDirty", "AuthBusRecoveryRequired", "AuthBusExpiredActiveReservations"} <= names)
        for rule in rules:
            self.assertEqual(rule["labels"]["module"], "auth.authbus")
            self.assertIn(rule["labels"]["severity"], {"warning", "critical"})
            self.assertTrue(rule["annotations"]["summary"])

    def test_rule_thresholds_match_rust_default_policy(self):
        source = (ROOT / "codex-rs/hepta-authbus/src/operations.rs").read_text()
        rules = json.loads((DOCS / "prometheus.rules.json").read_text())["groups"][0]["rules"]
        by_name = {rule["alert"]: rule["expr"] for rule in rules}
        for field, alert in [("max_active_reservations", "AuthBusActiveCapacity"),
                             ("max_quota_utilization_basis_points", "AuthBusQuotaUtilization"),
                             ("max_oldest_active_reservation_age_ms", "AuthBusOldestReservation")]:
            value = int(re.search(rf"{field}:\s*([0-9_]+)", source).group(1).replace("_", ""))
            self.assertRegex(by_name[alert], rf">=\s*{value}\b")


if __name__ == "__main__":
    unittest.main(verbosity=2)
