"""Independent finite Bellman audit regressions."""
import hashlib
import json
import unittest
from unittest.mock import patch

from portfolio import Config, Controller, State, STOP
from snapshot_policy import (
    compile_optimal_snapshot, current_source_digest, export_snapshot_bytes,
    load_snapshot_bytes, rollout_snapshot,
)
from independent_optimality import (
    IndependentFiniteOracle, audit_snapshot_optimality,
)


def reseal(payload):
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()
    envelope = {
        "payload": payload,
        "policy_sha256": hashlib.sha256(data).hexdigest(),
    }
    return json.dumps(envelope, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


class AuditTests(unittest.TestCase):
    def test_reference_checks_published_policies(self):
        for cfg, initial in (
            (Config(horizon=1, risk_aversion=0), State((0, 0, 0, 0), 12)),
            (Config(horizon=2, risk_aversion=0.5), State((0, 0, 0, 0), 12)),
            (Config(horizon=2, risk_aversion=2), State((1, 0, 1, 0), 10)),
        ):
            digest = current_source_digest()
            snap = compile_optimal_snapshot(initial, cfg, digest)
            receipt = audit_snapshot_optimality(
                export_snapshot_bytes(snap), cfg, initial, digest)
            self.assertEqual(receipt.checked_policy_states, len(snap.entries))
            self.assertLessEqual(receipt.maximum_absolute_value_error, 1e-8)

    def test_modified_initial_stop_requires_independent_check(self):
        cfg = Config(horizon=2, risk_aversion=0)
        state = State((0, 0, 0, 0), 12)
        digest = current_source_digest()
        snap = compile_optimal_snapshot(state, cfg, digest)
        self.assertNotEqual(snap.choose(
            state, cfg, digest, "FINITE_SYNTHETIC_DENY_ALL")[0], STOP)
        payload = json.loads(export_snapshot_bytes(snap))["payload"]
        initial_entry = next(row for row in payload["entries"]
                             if row["state"]["step"] == 0)
        initial_entry["allocation"] = list(STOP.units)
        payload["entries"] = [initial_entry]
        changed = reseal(payload)
        loaded = load_snapshot_bytes(changed, cfg, state)
        self.assertEqual(loaded.choose(
            state, cfg, digest, "FINITE_SYNTHETIC_DENY_ALL")[0], STOP)
        with self.assertRaisesRegex(ValueError, "nonoptimal action"):
            audit_snapshot_optimality(changed, cfg, state, digest)

    def test_modified_value_is_not_a_valid_optimality_certificate(self):
        cfg = Config(horizon=1)
        state = State((0, 0, 0, 0), 10)
        digest = current_source_digest()
        payload = json.loads(export_snapshot_bytes(
            compile_optimal_snapshot(state, cfg, digest)))["payload"]
        payload["entries"][0]["value_hex"] = (-999.0).hex()
        changed = reseal(payload)
        load_snapshot_bytes(changed, cfg, state)
        with self.assertRaisesRegex(ValueError, "nonoptimal value"):
            audit_snapshot_optimality(changed, cfg, state, digest)

    def test_reference_is_solver_independent_and_resource_bounded(self):
        cfg = Config(horizon=2)
        state = State((0, 0, 0, 0), 12)
        digest = current_source_digest()
        raw = export_snapshot_bytes(compile_optimal_snapshot(state, cfg, digest))
        with patch.object(Controller, "solve",
                          side_effect=AssertionError("unexpected solver")):
            self.assertGreater(audit_snapshot_optimality(
                raw, cfg, state, digest).independent_expansions, 0)
        with patch("independent_optimality.MAX_AUDIT_STATES", 1):
            with self.assertRaisesRegex(ValueError, "state cap"):
                IndependentFiniteOracle(cfg).best(state)
        with patch("independent_optimality.MAX_AUDIT_BRANCHES", 2):
            with self.assertRaisesRegex(ValueError, "branch cap"):
                IndependentFiniteOracle(cfg).best(state)

    def test_source_and_finite_rollout_parity(self):
        cfg = Config(horizon=2, risk_aversion=0)
        state = State((0, 0, 0, 0), 12)
        digest = current_source_digest()
        snap = compile_optimal_snapshot(state, cfg, digest)
        raw = export_snapshot_bytes(snap)
        with self.assertRaisesRegex(ValueError, "source mismatch"):
            audit_snapshot_optimality(raw, cfg, state, "0" * 64)
        loaded = load_snapshot_bytes(raw, cfg, state)
        for seed in range(8):
            self.assertEqual(rollout_snapshot(snap, cfg, digest, seed),
                             rollout_snapshot(loaded, cfg, digest, seed))


if __name__ == "__main__":
    unittest.main()
