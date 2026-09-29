"""Closed-label policy evaluation for channel.matrix durable diagnostics."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import channel_matrix_alerts as alerts


def zero(labels):
    return dict.fromkeys(labels, 0)


class AlertPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = json.loads(
            (ROOT / "docs/modules/channel.matrix/ALERT_POLICY.json").read_text()
        )
        self.snapshot = {
            "schema": alerts.SNAPSHOT_SCHEMA,
            "observed_at_ms": 1_000_000,
            "outbox": zero(alerts.OUTBOX),
            "dispatch": zero(alerts.LEDGER),
            "active_claims": {"claimed": 0, "authorized": 0, "dispatching": 0},
            "failures_last_300s": zero(alerts.FAILURES),
            "recovery_failures": zero(alerts.RECOVERY_FAILURES),
            "unresolved": 0,
            "sync_checkpoint_age_ms": 1,
            "oldest_queue_age_ms": None,
            "oldest_indeterminate_age_ms": None,
            "alerts": [],
            "authority_granted": False,
        }

    def test_empty_healthy_snapshot_is_ok(self):
        row = alerts.evaluate(self.snapshot, self.policy)
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["alerts"], [])
        self.assertFalse(row["authority_granted"])

    def test_unresolved_dispatch_requires_live_sync_even_without_pending_queue(self):
        self.snapshot["dispatch"]["indeterminate"] = 1
        self.snapshot["unresolved"] = 1
        self.snapshot["sync_checkpoint_age_ms"] = self.policy["syncStaleMs"]
        row = alerts.evaluate(self.snapshot, self.policy)
        self.assertEqual(row["status"], "critical")
        self.assertEqual(
            row["alerts"][0]["code"],
            "sync_checkpoint_stale_with_unresolved_work",
        )

    def test_unknown_effect_and_failure_pressure_are_actionable(self):
        self.snapshot["dispatch"]["indeterminate"] = 1
        self.snapshot["unresolved"] = 1
        self.snapshot["sync_checkpoint_age_ms"] = 1
        self.snapshot["oldest_indeterminate_age_ms"] = self.policy[
            "indeterminateAgeWarningMs"
        ]
        self.snapshot["failures_last_300s"]["rate_limited"] = self.policy[
            "rateLimitedEventsWarning"
        ]
        self.snapshot["failures_last_300s"]["response_lost"] = self.policy[
            "responseLostEventsWarning"
        ]
        self.snapshot["failures_last_300s"]["authority_denied"] = self.policy[
            "authorityDeniedEventsCritical"
        ]
        self.snapshot["recovery_failures"]["dependency_unavailable"] = self.policy[
            "inboxDependencyUnavailableWarning"
        ]
        row = alerts.evaluate(self.snapshot, self.policy)
        self.assertEqual(row["status"], "critical")
        self.assertEqual(
            {item["code"] for item in row["alerts"]},
            {
                "indeterminate_age",
                "rate_limit_pressure",
                "response_loss_pressure",
                "authority_denial_pressure",
                "inbox_dependency_pressure",
            },
        )
        text = alerts.prometheus(row)
        self.assertNotIn("transaction", text)
        self.assertIn('code="authority_denial_pressure"', text)

    def test_built_in_alerts_are_retained_without_open_labels(self):
        self.snapshot["alerts"] = [
            {
                "code": "expired_claims",
                "severity": "warning",
                "action": "inspect_process_lease_never_edit_claim",
            }
        ]
        row = alerts.evaluate(self.snapshot, self.policy)
        self.assertEqual(row["alerts"], self.snapshot["alerts"])
        bad = copy.deepcopy(self.snapshot)
        bad["alerts"][0]["code"] = "user-controlled-label"
        with self.assertRaises(ValueError):
            alerts.evaluate(bad, self.policy)

    def test_inconsistent_counts_and_unknown_failure_labels_fail_closed(self):
        self.snapshot["dispatch"]["accepted"] = 1
        with self.assertRaises(ValueError):
            alerts.evaluate(self.snapshot, self.policy)
        self.snapshot["unresolved"] = 1
        self.snapshot["failures_last_300s"]["invented"] = 1
        with self.assertRaises(ValueError):
            alerts.evaluate(self.snapshot, self.policy)

    def test_policy_is_closed_and_canonical(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / "policy.json"
            path.write_text(json.dumps(self.policy))
            self.assertEqual(alerts.load_policy(path), self.policy)
            changed = dict(self.policy)
            changed["unexpected"] = 1
            path.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                alerts.load_policy(path)


if __name__ == "__main__":
    unittest.main()