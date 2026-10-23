#!/usr/bin/env python3
"""Regression tests for the site-owned hot-path decision gate."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
SPEC = importlib.util.spec_from_file_location(
    "kernel_authority_hot_path_gate",
    ROOT / "hot_path_gate.py",
)
assert SPEC is not None and SPEC.loader is not None
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


class HotPathGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = GATE.capacity.validate_plan(
            GATE.capacity.plan(
                "a" * 40,
                "b" * 40,
                "target-profile",
                100,
            )
        )
        history = {
            "empty": 0,
            "1k": 1_000,
            "8k": 8_000,
            "90_percent": 14_745,
            "max": 16_384,
        }
        self.rows = []
        self.policy_limits = []
        for metric in GATE.METRICS:
            p99 = {point: max(units, 1) for point, units in history.items()}
            touched = {
                point: max(units, 1) * 2
                for point, units in history.items()
            }
            for point in GATE.POINTS:
                self.rows.append(
                    {
                        "metric": metric,
                        "point": point,
                        "p99Us": p99[point],
                        "bytesTouched": touched[point],
                        "historyUnits": history[point],
                    }
                )
            self.policy_limits.append(
                {
                    "metric": metric,
                    "maxP99UsByPoint": {
                        point: value * 2 for point, value in p99.items()
                    },
                    "maxBytesTouchedByPoint": {
                        point: value * 2 for point, value in touched.items()
                    },
                    "maxTimePerHistoryGrowthPermille": 1_100,
                    "maxBytesPerHistoryGrowthPermille": 1_100,
                }
            )

    def policy(self) -> dict[str, object]:
        return {
            "schema": GATE.POLICY_SCHEMA,
            "schemaVersion": 1,
            "candidate": self.plan["candidate"],
            "profileId": self.plan["profileId"],
            "limits": copy.deepcopy(self.policy_limits),
            "runtimeOptimizationAuthorized": False,
            "productionSloGranted": False,
            "independentAcceptance": False,
            "activationGranted": False,
            "releaseGranted": False,
        }

    def validated_limits(self) -> dict[str, dict[str, object]]:
        _policy, limits = GATE.validate_policy(self.policy(), self.plan)
        return limits

    def test_linear_history_and_site_budgets_pass(self) -> None:
        results, investigations = GATE.evaluate_diagnostics(
            self.rows,
            self.validated_limits(),
        )
        self.assertTrue(all(row["passed"] for row in results))
        self.assertEqual(investigations, [])

    def test_superlinear_history_work_is_rejected(self) -> None:
        rows = copy.deepcopy(self.rows)
        for row in rows:
            if (
                row["metric"] == "final_use_frontier_hash"
                and row["point"] == "max"
            ):
                row["p99Us"] = 1_000_000
                break
        results, investigations = GATE.evaluate_diagnostics(
            rows,
            self.validated_limits(),
        )
        frontier = next(
            row for row in results
            if row["metric"] == "final_use_frontier_hash"
        )
        self.assertFalse(frontier["passed"])
        self.assertTrue(investigations)

    def test_missing_policy_metric_and_authority_claim_fail(self) -> None:
        missing = self.policy()
        missing["limits"].pop()
        with self.assertRaises(GATE.Invalid):
            GATE.validate_policy(missing, self.plan)

        overclaim = self.policy()
        overclaim["runtimeOptimizationAuthorized"] = True
        with self.assertRaises(GATE.Invalid):
            GATE.validate_policy(overclaim, self.plan)

    def test_decision_never_authorizes_runtime_or_release(self) -> None:
        results, investigations = GATE.evaluate_diagnostics(
            self.rows,
            self.validated_limits(),
        )
        result = GATE.decision(
            self.plan,
            {"host": GATE.capacity.fake_host()},
            "c" * 64,
            "d" * 64,
            results,
            investigations,
        )
        self.assertTrue(result["passed"])
        for field in GATE.NON_AUTHORITY_FIELDS:
            self.assertFalse(result[field])


if __name__ == "__main__":
    unittest.main()
