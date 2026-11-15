import copy
import unittest

from next_round_matrix import build_plan
from paired_execution import COMPONENTS, PHASES, audit_pair, freeze_contract, validate_contract


class PairedExecutionTests(unittest.TestCase):
    def setUp(self):
        self.plan = build_plan(reader_id="r", task_set_id="t")
        self.contract = freeze_contract(
            self.plan, source_sha="a" * 40, workload_sha256="b" * 64,
            task_ids=["t0", "t1"], device_id="test-device", observer_id="independent",
            train_cutoff_ns=10, eval_start_ns=20, eval_end_ns=30,
            flops_caps=dict.fromkeys(PHASES, 1000))
        self.left = self.receipt("shared_421m_sparse_direct32_no_ndu")
        self.right = self.receipt("shared_421m_sparse_split_no_ndu")

    def receipt(self, arm):
        # Explicit test-only fabricated export; never written as real evidence.
        return dict(schema="hepta.stem.paired-run-export.v1", arm_id=arm,
                    contract_id=self.contract["contract_id"], source_sha="a" * 40,
                    device_id="test-device", workload_sha256="b" * 64,
                    head_params=32_000_000, trainable_params=32_000_010,
                    peak_trainable_params=32_000_010, unique_weight_bytes=900_000_000,
                    phase_flops=dict.fromkeys(PHASES, 100),
                    flop_profile="test-only-complete-counter", flop_components=list(COMPONENTS),
                    execution_kind="pretrained_local_weights", weight_receipt_sha256="c" * 64,
                    observer_receipt_sha256="d" * 64,
                    requests=[dict(task_id=t, status="completed", latency_ns=ns,
                                   energy_joules=1.0, peak_memory_bytes=100,
                                   outcome=1.0, observed_at_ns=21, observer_id="independent")
                              for t, ns in (("t0", 1_000_000), ("t1", 3_000_000))])

    def audit(self):
        return audit_pair(self.plan, self.contract, "adaptive_split", self.left, self.right)

    def test_complete_pair_is_only_structurally_comparable_not_attested(self):
        result = self.audit()
        self.assertEqual(result["status"], "structurally_comparable_unattested")
        self.assertEqual(result["blockers"], [])
        self.assertFalse(result["production_authorized"])
        self.assertFalse(result["statistical_superiority_established"])
        self.assertEqual(result["summaries"][0]["p99_latency_ms"], 3)

    def test_each_compute_phase_is_checked_separately(self):
        for phase in PHASES:
            with self.subTest(phase=phase):
                self.right["phase_flops"] = dict.fromkeys(PHASES, 100)
                self.right["phase_flops"][phase] = 200
                pool = "online" if phase in ("search", "inference") else "offline"
                self.assertIn(f"unmatched_measured_{pool}_flops", self.audit()["blockers"])

    def test_useful_work_and_head_critic_tradeoffs_do_not_require_dummy_work(self):
        self.right["phase_flops"].update(search=50, inference=150, train=50, migration=150)
        self.right["head_params"] -= 10
        self.assertEqual(self.audit()["blockers"], [])
        # Equal grand totals are insufficient if online cost increases.
        self.right["phase_flops"].update(search=150, inference=150, train=0, migration=100)
        self.assertIn("unmatched_measured_online_flops", self.audit()["blockers"])
        self.assertIn("unmatched_measured_offline_flops", self.audit()["blockers"])

    def test_missing_counters_are_not_zero(self):
        self.right["phase_flops"]["search"] = None
        self.right["requests"][1]["energy_joules"] = None
        self.right["requests"][1]["peak_memory_bytes"] = None
        result = self.audit()
        self.assertEqual(result["status"], "blocked")
        self.assertIsNone(result["summaries"][1]["energy_joules"])
        self.assertIsNone(result["summaries"][1]["peak_memory_bytes"])
        self.assertIn("candidate:missing_search_flops", result["blockers"])

    def test_failed_and_timeout_requests_stay_in_denominator(self):
        self.right["requests"][1].update(status="timed_out", latency_ns=50_000_000, outcome=0)
        result = self.audit()
        self.assertEqual(result["summaries"][1]["requests"], 2)
        self.assertEqual(result["summaries"][1]["mean_outcome"], .5)
        self.assertEqual(result["summaries"][1]["p95_latency_ms"], 50)
        self.right["requests"].pop()
        with self.assertRaises(ValueError):
            self.audit()

    def test_future_window_and_observer_leakage_rejected(self):
        for key, value in (("observed_at_ns", 10), ("observed_at_ns", 30),
                           ("observer_id", "self"), ("task_id", "future-label-task")):
            with self.subTest(key=key, value=value):
                previous = self.right["requests"][0][key]
                self.right["requests"][0][key] = value
                with self.assertRaises(ValueError):
                    self.audit()
                self.right["requests"][0][key] = previous

    def test_actual_router_critic_and_peak_counts_must_match(self):
        self.right["trainable_params"] += 1
        self.right["peak_trainable_params"] += 2
        result = self.audit()
        self.assertIn("unmatched_actual_trainable_params", result["blockers"])
        self.assertIn("unmatched_actual_peak_trainable_params", result["blockers"])

    def test_nonfinite_boolean_and_fractional_counts_reject(self):
        for key, value in (("outcome", float("nan")), ("energy_joules", True),
                           ("peak_memory_bytes", 1.5), ("latency_ns", 0)):
            with self.subTest(key=key):
                previous = self.right["requests"][0][key]
                self.right["requests"][0][key] = value
                with self.assertRaises(ValueError):
                    self.audit()
                self.right["requests"][0][key] = previous

    def test_source_device_or_profiler_change_cannot_pass(self):
        for key, value in (("source_sha", "e" * 40), ("device_id", "other"),
                           ("contract_id", "f" * 64)):
            with self.subTest(key=key):
                old = self.right[key]
                self.right[key] = value
                with self.assertRaises(ValueError):
                    self.audit()
                self.right[key] = old
        self.right["flop_profile"] = "different counter"
        self.assertIn("incompatible_flop_profiles", self.audit()["blockers"])

    def test_budget_and_coverage_controls(self):
        self.right["phase_flops"]["train"] = 2000
        self.right["flop_components"] = ["head"]
        blockers = self.audit()["blockers"]
        self.assertIn("candidate:train_budget_exceeded", blockers)
        self.assertIn("candidate:incomplete_flop_coverage", blockers)

    def test_mock_runs_and_missing_materials_block(self):
        self.right["execution_kind"] = "mechanism_fixture"
        self.right["weight_receipt_sha256"] = None
        blockers = self.audit()["blockers"]
        self.assertIn("candidate:not_pretrained_model_execution", blockers)
        self.assertIn("candidate:missing_weight_receipt_sha256", blockers)

    def test_contract_is_content_bound_and_cannot_be_relaxed_afterward(self):
        bad = copy.deepcopy(self.contract)
        bad["tolerance_ppm"] += 1
        with self.assertRaises(ValueError):
            validate_contract(self.plan, bad)

    def test_unknown_fields_and_arms_reject(self):
        self.right["promotion_authorized"] = True
        with self.assertRaises(ValueError):
            self.audit()
        self.right.pop("promotion_authorized")
        self.right["arm_id"] = self.left["arm_id"]
        with self.assertRaises(ValueError):
            self.audit()


if __name__ == "__main__":
    unittest.main()
