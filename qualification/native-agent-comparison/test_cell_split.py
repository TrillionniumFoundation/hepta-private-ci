import copy
import unittest
from cell_split import ARMS, SCALES, GateError, compare


def fixture():
    h = lambda i: f"{i:064x}"
    tasks = [{"id": f"old-{i}", "family": "old", "group": "old", "split": "test", "seed": i,
              "fixture_digest": h(i+10), "oracle_digest": h(i+20)} for i in range(2)]
    tasks += [{"id": f"future-{i}", "family": f"unseen-{i}", "group": f"future-{i}",
               "split": "future", "seed": i, "fixture_digest": h(i+100),
               "oracle_digest": h(i+200)} for i in range(5)]
    plan = {"schema": "hepta.cell-split-comparison.v1", "arms": list(ARMS), "scales": list(SCALES),
            "source_digest": h(31), "model_profile_digest": h(32), "target_profile_digest": h(33),
            "objective_digest": h(34), "evaluation_code_digest": h(35), "bootstrap_seed": 19,
            "min_future_group_gain": 0, "max_old_task_regression": 0,
            "limits": {"wall_ms": 10000, "cpu_ms": 10000, "peak_rss_bytes": 100000000,
                       "input_tokens": 1000, "output_tokens": 1000, "tool_calls": 20},
            "tasks": tasks}
    receipts = []
    for scale in SCALES:
        for arm in ARMS:
            for t in tasks:
                r = {"schema": "hepta.cell-split-observation.v1", "task_id": t["id"],
                     "seed": t["seed"], "arm": arm, "scale": scale,
                     "fixture_digest": t["fixture_digest"], "oracle_digest": t["oracle_digest"],
                     "source_digest": h(31), "model_profile_digest": h(32),
                     "target_profile_digest": h(33), "objective_digest": h(34),
                     "evaluation_code_digest": h(35), "limits": copy.deepcopy(plan["limits"]),
                     "idempotency_replayed": False, "unknown_effects": 0,
                     "success": arm == "split" or t["split"] == "test", "tool_correct": True,
                     "observation_digest": h(44), "wall_ms": 100, "cpu_ms": 50,
                     "peak_rss_bytes": 4000, "input_tokens": 100, "output_tokens": 10,
                     "tool_calls": 1}
                receipts.append(r)
    return plan, receipts


class CellComparisonTest(unittest.TestCase):
    def test_complete_plan_is_only_structural(self):
        plan, rows = fixture()
        result = compare(plan, rows)
        self.assertTrue(result["all_scales_meet_structural_metrics"])
        self.assertFalse(result["independent_acceptance"])
        self.assertEqual(result["status"], "HOLD_NO_GO_INDEPENDENT_EVIDENCE_REQUIRED")

    def test_missing_pair_and_duplicate_fail_closed(self):
        p, rows = fixture()
        with self.assertRaisesRegex(GateError, "incomplete paired"):
            compare(p, rows[:-1])
        with self.assertRaisesRegex(GateError, "duplicate observation"):
            compare(p, rows + [rows[0]])

    def test_cross_split_group_and_future_family_leak(self):
        p, rows = fixture()
        p["tasks"][0]["group"] = "future-0"
        with self.assertRaisesRegex(GateError, "crosses data split"):
            compare(p, rows)
        p, rows = fixture()
        p["tasks"][2]["family"] = "old"
        with self.assertRaisesRegex(GateError, "family leaked"):
            compare(p, rows)

    def test_future_groups_must_be_independent_families(self):
        p, rows = fixture()
        p["tasks"][3]["family"] = p["tasks"][2]["family"]
        with self.assertRaisesRegex(GateError, "future family crosses independent groups"):
            compare(p, rows)

        p, rows = fixture()
        p["tasks"][3]["group"] = p["tasks"][2]["group"]
        with self.assertRaisesRegex(GateError, "future group mixes families"):
            compare(p, rows)

    def test_raw_original_fixture_identity_cannot_leak_between_cohorts(self):
        p, rows = fixture()
        p["tasks"][3]["fixture_digest"] = p["tasks"][2]["fixture_digest"]
        with self.assertRaisesRegex(GateError, "fixture reused across independent groups"):
            compare(p, rows)

        p, rows = fixture()
        p["tasks"][0]["fixture_digest"] = p["tasks"][2]["fixture_digest"]
        with self.assertRaisesRegex(GateError, "fixture reused across independent groups"):
            compare(p, rows)

    def test_same_source_within_one_group_allows_repeated_seed_measurements(self):
        p, rows = fixture()
        # Repeated seeds within one group are allowed; the bootstrap will
        # still count that source group once, not as independent groups.
        p["tasks"][1]["fixture_digest"] = p["tasks"][0]["fixture_digest"]
        for r in rows:
            if r["task_id"] == "old-1":
                r["fixture_digest"] = p["tasks"][0]["fixture_digest"]
        result = compare(p, rows)
        self.assertEqual(result["scales"]["64"]["future_group_count"], 5)

    def test_outcome_drift_and_effect_replay_denied(self):
        for field, value, reason in [
            ("unknown_effects", 1, "unsafe effect"),
            ("idempotency_replayed", True, "unsafe effect"),
            ("wall_ms", 10001, "over-budget wall_ms"),
            ("success", 1, "outcome format"),
            ("source_digest", "f"*64, "source_digest drift"),
        ]:
            p, rows = fixture()
            rows[0][field] = value
            with self.assertRaisesRegex(GateError, reason):
                compare(p, rows)

    def test_future_gain_and_old_regression_are_independent(self):
        p, rows = fixture()
        for r in rows:
            if r["task_id"] in ("future-0", "future-1", "future-2") and r["arm"] == "split":
                r["success"] = False
        self.assertFalse(compare(p, rows)["all_scales_meet_structural_metrics"])
        p, rows = fixture()
        for r in rows:
            if r["task_id"] == "old-0" and r["arm"] == "split":
                r["success"] = False
        self.assertFalse(compare(p, rows)["all_scales_meet_structural_metrics"])

    def test_no_fixture_is_no_go(self):
        p, rows = fixture()
        p["tasks"] = []
        with self.assertRaisesRegex(GateError, "frozen tasks missing"):
            compare(p, rows)


if __name__ == "__main__":
    unittest.main()
