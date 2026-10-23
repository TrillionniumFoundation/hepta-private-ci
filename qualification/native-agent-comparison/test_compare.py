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
        "mode_build_digests": {m: sha(80 + i) for i, m in enumerate(("A", "B", "C"))},
        "resource_limits": {"max_input_tokens": 500, "max_output_tokens": 200, "timeout_ms": 60000, "max_cpu_ms": 80000,
                            "max_rss_bytes": 1000000000, "max_gpu_memory_bytes": 1000000000,
                            "max_active_concurrency": 4096, "max_tool_calls": 30},
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
                "source_trees": {r: baseline["sources"][r]["tree"] for r in baseline["sources"]},
                "mode_build_digest": baseline["mode_build_digests"][mode],
                "observation_digest": sha(500 + len(receipts)),
                "task_success": True, "tool_correct": True, "recovery_pass": True,
                "idempotency_replayed": False, "unknown_effects_open": 0,
                "wall_ms": 150, "cpu_ms": 120, "peak_rss_bytes": 10000000,
                "peak_gpu_memory_bytes": 0, "active_concurrency": 1,
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

    def test_4096_failure_is_visible_in_scale_specific_summary(self):
        base, receipts = fixture()
        for receipt in receipts:
            if receipt["scale"] == 4096 and receipt["mode"] == "C":
                receipt["task_success"] = False
                receipt["wall_ms"] = 60000
                receipt["peak_rss_bytes"] = 999999999
        result = compare(base, receipts)
        self.assertEqual(result["mode_summaries"]["C"]["success_rate"], .75)
        self.assertEqual(result["scale_summaries"]["4096"]["C"]["success_rate"], 0)
        self.assertEqual(result["scale_summaries"]["4096"]["C"]["wall_p99_ms"], 60000)
        self.assertEqual(result["scale_summaries"]["4096"]["C"]["peak_rss_bytes"], 999999999)
        self.assertEqual(result["scale_summaries"]["64"]["C"]["success_rate"], 1)
        self.assertFalse(result["independent_acceptance"])
        self.assertFalse(result["concurrent_throughput_proven"])

    def test_four_scales_have_complete_separate_abc_counts(self):
        base, receipts = fixture()
        result = compare(base, receipts)
        self.assertEqual(set(result["scale_summaries"]), {"64", "256", "1024", "4096"})
        for by_mode in result["scale_summaries"].values():
            self.assertEqual(set(by_mode), {"A", "B", "C"})
            for mode in ("A", "B", "C"):
                self.assertEqual(by_mode[mode]["cases"], len(base["tasks"]))
                self.assertEqual(by_mode[mode]["wall_p95_ms"], 150)
                self.assertEqual(by_mode[mode]["wall_p99_ms"], 150)

    def test_missing_mode_rejected(self):
        base, receipts = fixture()
        with self.assertRaisesRegex(ComparisonError, "incomplete"):
            compare(base, receipts[:-1])

    def test_contradictory_tool_outcome_cannot_count_as_success(self):
        base, receipts = fixture()
        receipts[0]["tool_correct"] = False
        with self.assertRaisesRegex(ComparisonError, "task success conflicts with tool correctness"):
            compare(base, receipts)
        base, receipts = fixture()
        receipts[0]["task_success"] = False
        receipts[0]["tool_correct"] = False
        result = compare(base, receipts)
        self.assertEqual(result["scale_summaries"]["64"]["A"]["success_rate"], 0)
        self.assertFalse(result["independent_acceptance"])

    def test_success_does_not_require_tool_calls(self):
        base, receipts = fixture()
        for receipt in receipts:
            receipt["tool_calls"] = 0
        result = compare(base, receipts)
        self.assertEqual(result["scale_summaries"]["64"]["A"]["success_rate"], 1)
        self.assertEqual(result["scale_summaries"]["64"]["A"]["tool_correct_rate"], 1)
        self.assertFalse(result["independent_acceptance"])

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

    def test_source_tree_build_and_receipt_identity_are_bound(self):
        for field, value, reason in [
            ("source_trees", {"hepta": "f"*40, "runtime": "f"*40, "codex": "f"*40}, "source tree drift"),
            ("mode_build_digest", "e"*64, "built artifact"),
            ("observation_digest", "0"*64, "receipt digest invalid"),
        ]:
            base, receipts = fixture()
            receipts[0][field] = value
            with self.assertRaisesRegex(ComparisonError, reason):
                compare(base, receipts)
        base, receipts = fixture()
        receipts[1]["observation_digest"] = receipts[0]["observation_digest"]
        with self.assertRaisesRegex(ComparisonError, "duplicate observation receipt digest"):
            compare(base, receipts)

    def test_missing_mode_binary_pin_fails_closed(self):
        base, receipts = fixture()
        del base["mode_build_digests"]["C"]
        with self.assertRaisesRegex(ComparisonError, "executable and configuration manifests"):
            compare(base, receipts)

    def test_abc_variants_must_not_reuse_one_build_configuration(self):
        base, receipts = fixture()
        base["mode_build_digests"]["C"] = base["mode_build_digests"]["A"]
        with self.assertRaisesRegex(ComparisonError, "executable and configuration manifests"):
            compare(base, receipts)

    def test_cpu_gpu_and_active_concurrency_are_measured_and_bounded(self):
        for field, value, reason in [
            ("cpu_ms", 90000, "CPU budget overrun"),
            ("peak_gpu_memory_bytes", 1000000001, "GPU memory overrun"),
            ("active_concurrency", 65, "active Cell concurrency"),
            ("peak_gpu_memory_bytes", None, "metric peak_gpu_memory_bytes invalid"),
        ]:
            base, receipts = fixture()
            receipts[0][field] = value
            with self.assertRaisesRegex(ComparisonError, reason):
                compare(base, receipts)

    def test_4096_regression_cannot_hide_inside_pooled_metrics(self):
        base, receipts = fixture()
        for receipt in receipts:
            if receipt["mode"] == "C" and receipt["scale"] == 4096:
                receipt["wall_ms"] = 40000
                receipt["cpu_ms"] = 30000
        result = compare(base, receipts)
        self.assertEqual(result["scale_summaries"]["4096"]["C"]["wall_p99_ms"], 40000)
        self.assertEqual(result["scale_deltas"]["4096"]["C_vs_A"]["wall_p99_delta_ms"], 39850)
        self.assertEqual(result["scale_summaries"]["64"]["C"]["wall_p99_ms"], 150)
        self.assertFalse(result["independent_acceptance"])

    def test_oversized_integer_is_bounded_not_unhandled_exception(self):
        base, receipts = fixture()
        receipts[0]["cpu_ms"] = 10**500
        with self.assertRaisesRegex(ComparisonError, "CPU budget overrun"):
            compare(base, receipts)
        base, receipts = fixture()
        receipts[0]["wall_ms"] = 10**500
        with self.assertRaisesRegex(ComparisonError, "timeout exceeded"):
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
