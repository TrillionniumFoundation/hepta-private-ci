import copy
import unittest

from compare import ComparisonError, compare


def fixture():
    def sha(n):
        return f"{n:064x}"

    def h40(n):
        return f"{n:040x}"

    baseline = {
        "schema": "hepta.native-abc.v1",
        "sources": {k: {"commit": h40(i), "tree": h40(i + 10)} for i, k in enumerate(("hepta", "runtime", "codex"), 1)},
        "modes": ["A", "B", "C"],
        "scales": [64, 256, 1024, 4096],
        "target_profile_digest": sha(99),
        "model_profile_digest": sha(98),
        "resource_limits": {"max_input_tokens": 500, "max_output_tokens": 200, "timeout_ms": 60000, "max_rss_bytes": 1000000000, "max_tool_calls": 30},
        "tasks": [{"task_id": "read-file", "fixture_digest": sha(5), "answer_oracle_digest": sha(6), "seed": 13}],
    }
    receipts = []
    for scale in baseline["scales"]:
        for mode in baseline["modes"]:
            receipts.append({
                "schema": "hepta.native-abc-observation.v1", "mode": mode,
                "scale": scale, "task_id": "read-file", "seed": 13,
                "fixture_digest": sha(5), "answer_oracle_digest": sha(6),
                "target_profile_digest": sha(99),
                "model_profile_digest": sha(98),
                "resource_limits": copy.deepcopy(baseline["resource_limits"]),
                "source_commits": {r: baseline["sources"][r]["commit"] for r in baseline["sources"]},
                "task_success": True, "tool_correct": True, "recovery_pass": True,
                "idempotency_replayed": False, "unknown_effects_open": 0,
                "wall_ms": 150, "peak_rss_bytes": 10000000,
                "input_tokens": 100, "output_tokens": 5, "tool_calls": 1,
            })
    return baseline, receipts


class ComparatorTests(unittest.TestCase):
    def test_complete_is_only_structural_evidence(self):
        base, receipts = fixture()
        result = compare(base, receipts)
        self.assertFalse(result["independent_acceptance"])
        self.assertFalse(result["physical_execution_proven"])
        self.assertEqual(result["paired_case_count"], 4)
        self.assertEqual(result["mode_summaries"]["B"]["success_rate"], 1)

    def test_missing_mode_rejected(self):
        base, receipts = fixture()
        with self.assertRaisesRegex(ComparisonError, "incomplete"):
            compare(base, receipts[:-1])

    def test_duplicate_rejected(self):
        base, receipts = fixture()
        with self.assertRaisesRegex(ComparisonError, "duplicate"):
            compare(base, receipts + [receipts[0]])

    def test_budget_drift_rejected(self):
        base, receipts = fixture()
        receipts[0]["resource_limits"]["max_output_tokens"] += 1
        with self.assertRaisesRegex(ComparisonError, "resource envelope drift"):
            compare(base, receipts)

    def test_unresolved_effect_is_not_success(self):
        base, receipts = fixture()
        receipts[0]["unknown_effects_open"] = 1
        with self.assertRaisesRegex(ComparisonError, "unresolved effect"):
            compare(base, receipts)

    def test_source_drift_rejected(self):
        base, receipts = fixture()
        receipts[0]["source_commits"]["codex"] = "f" * 40
        with self.assertRaisesRegex(ComparisonError, "source identity drift"):
            compare(base, receipts)

    def test_placeholder_baseline_fails_closed(self):
        base, receipts = fixture()
        base["tasks"] = []
        with self.assertRaisesRegex(ComparisonError, "HOLD_NO_GO"):
            compare(base, receipts)

    def test_nonfinite_and_over_limit_rejected(self):
        base, receipts = fixture()
        receipts[0]["wall_ms"] = float("nan")
        with self.assertRaisesRegex(ComparisonError, "metric wall_ms"):
            compare(base, receipts)
        _, receipts = fixture()
        receipts[0]["wall_ms"] = 90000
        with self.assertRaisesRegex(ComparisonError, "timeout exceeded"):
            compare(base, receipts)


if __name__ == "__main__":
    unittest.main()
