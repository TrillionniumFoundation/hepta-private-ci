"""Operational pressure signals for channel.matrix."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import channel_matrix_alerts as alerts

spec = importlib.util.spec_from_file_location(
    "matrix_diagnostics", ROOT / "scripts/channel_matrix_diagnostics.py"
)
diag = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(diag)


def zero(labels):
    return dict.fromkeys(labels, 0)


class OperationalPressureTests(unittest.TestCase):
    def test_policy_pages_closed_parked_claim_and_redaction_signals(self):
        policy = json.loads(
            (ROOT / "docs/modules/channel.matrix/ALERT_POLICY.json").read_text()
        )
        snapshot = {
            "schema": alerts.SNAPSHOT_SCHEMA,
            "observed_at_ms": 1_000_000,
            "outbox": zero(alerts.OUTBOX),
            "dispatch": zero(alerts.LEDGER),
            "failures_last_300s": zero(alerts.FAILURES),
            "recovery_failures": zero(alerts.RECOVERY_FAILURES),
            "unresolved": 0,
            "parked_queue": policy["parkedQueueWarning"],
            "expired_claims": policy["expiredClaimCountWarning"],
            "sync_checkpoint_age_ms": 1,
            "oldest_queue_age_ms": None,
            "oldest_indeterminate_age_ms": None,
            "oldest_parked_age_ms": policy["parkedAgeWarningMs"],
            "oldest_expired_claim_age_ms": policy["expiredClaimAgeWarningMs"],
            "redaction_propagation_max_last_300s_ms": policy[
                "redactionPropagationWarningMs"
            ],
            "alerts": [],
            "authority_granted": False,
        }
        row = alerts.evaluate(snapshot, policy)
        self.assertEqual(
            {item["code"] for item in row["alerts"]},
            {
                "claim_expiry_pressure",
                "parked_work_pressure",
                "redaction_propagation_lag",
            },
        )
        self.assertFalse(row["authority_granted"])

    def test_diagnostics_measure_parked_age_and_recent_redaction_latency(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / "matrix.sqlite3"
            db = sqlite3.connect(path)
            self.addCleanup(db.close)
            db.execute("PRAGMA foreign_keys=ON")
            db.execute(
                "CREATE TABLE _sqlx_migrations(version INTEGER, success INTEGER)"
            )
            for migration in sorted(
                (ROOT / "codex-rs/hepta-matrix-store/migrations").glob("*.sql")
            ):
                db.executescript(migration.read_text())
                db.execute(
                    "INSERT INTO _sqlx_migrations VALUES (?,1)",
                    (int(migration.name[:4]),),
                )
            db.execute(
                "INSERT INTO room_bindings VALUES ('!r:t', ?, '@a:t',1,1,1)",
                ("0" * 36,),
            )
            db.execute(
                """INSERT INTO outbox_messages(
                    stable_txn_id,room_id,kind,payload,payload_sha256,
                    logical_txn_count,binding_revision,generation,state,attempts,
                    next_attempt_at_ms,created_at_ms,updated_at_ms,logical_outbox_id)
                VALUES ('txn','!r:t','final',?, ?,1,1,1,'retry_scheduled',1,?,1,1,'logical')""",
                (b"body", "a" * 64, diag.MAX_I64),
            )
            db.execute(
                """INSERT INTO matrix_dispatch_ledger(
                    stable_txn_id,operation_id,logical_outbox_id,room_id,
                    binding_revision,generation,payload_sha256,state,attempts,
                    prepared_at_ms,updated_at_ms)
                VALUES ('txn','op','logical','!r:t',1,1,?,'indeterminate',1,1,1)""",
                ("a" * 64,),
            )
            db.execute(
                """INSERT INTO matrix_dispatch_observations(
                    stable_txn_id,observation_kind,attempt,event_id,
                    observation_sha256,observed_at_ms)
                VALUES ('txn','homeserver_event',1,'$send',?,100000)""",
                ("b" * 64,),
            )
            db.execute(
                """INSERT INTO matrix_dispatch_observations(
                    stable_txn_id,observation_kind,attempt,event_id,
                    observation_sha256,observed_at_ms)
                VALUES ('txn','redaction',1,'$redaction',?,350000)""",
                ("c" * 64,),
            )
            db.commit()
            row = diag.inspect(path, 400_000)
            self.assertEqual(row["parked_queue"], 1)
            self.assertEqual(row["oldest_parked_age_ms"], 399_999)
            self.assertEqual(
                row["redaction_propagation_max_last_300s_ms"], 250_000
            )
            self.assertNotIn("redaction_propagation_latency", row["not_in_snapshot"])
            self.assertIn("hepta_matrix_oldest_parked_age_ms 399999", diag.prometheus(row))


if __name__ == "__main__":
    unittest.main()
