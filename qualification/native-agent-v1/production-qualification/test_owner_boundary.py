"""A task/model pass cannot promote fixture costs into production total cost."""

from pathlib import Path
import tempfile
import unittest
from unittest import mock

from observed_live import observed_costs
from owner_boundary import lane_owner_boundary, matrix_owner_boundary, require_cost_scope


class OwnerBoundaryTests(unittest.TestCase):
    def test_successful_model_and_tasks_do_not_claim_product_cost_or_causality(self):
        rows = [{"lane": lane, "case": "edit", "repeat": 0, "status": "passed",
                 "capability_passed": True, "attempt_wall_ms": 100,
                 "product_total_cost": 1, "execution_layer_causal_attribution": True,
                 "model_accounting": {"complete": True, "exact_usage_total": {
                     "input_tokens": 2, "output_tokens": 1, "total_tokens": 3}}}
                for lane in ("native", "app-server", "facade")]
        report = observed_costs(rows)
        self.assertIsNone(report["product_total_cost"])
        self.assertFalse(report["execution_layer_causal_attribution"])
        self.assertFalse(report["owner_boundary"]["common_host_owner_boundary_established"])
        for cost in report["by_case_and_lane"]:
            self.assertIsNone(cost["product_total_cost"])
            self.assertFalse(cost["execution_layer_causal_attribution"])
            self.assertEqual(cost["all_attempt_wall_ms_per_observed_success"], 100)
            self.assertFalse(cost["owner_boundary"]["hepta_production_writer"])

    def test_same_thin_session_scope_retains_actual_owner_and_ui_differences(self):
        native, codex = (lane_owner_boundary(lane) for lane in ("native", "app-server"))
        self.assertEqual(native["qualification_owner"]["session_scope"], codex["qualification_owner"]["session_scope"])
        self.assertNotEqual(native["qualification_owner"]["handle_lifetime"], codex["qualification_owner"]["handle_lifetime"])
        self.assertFalse(native["codex_core_owner"]["present"])
        self.assertTrue(codex["codex_core_owner"]["present"])
        self.assertFalse(native["ui_delivery"]["production_core_ui_parity_established"])
        boundary = matrix_owner_boundary(["native", "app-server", "facade"])
        self.assertEqual(boundary["product_total_cost_gate"]["status"], "held")
        self.assertFalse(boundary["product_total_cost_gate"]["thin_session_owner_alignment_can_satisfy_owner_gate"])

    def test_product_total_gate_rejects_before_binaries_output_or_effects(self):
        import representative_compare as compare
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "must-not-exist"
            argv = ["representative_compare.py", "--output", str(output),
                    "--native", "/unused/native", "--codex", "/unused/codex", "--facade", "/unused/facade",
                    "--native-build-evidence", "/unused/native.json", "--codex-build-evidence", "/unused/codex.json",
                    "--mode", "live", "--cost-scope", "product-total"]
            with mock.patch("sys.argv", argv), mock.patch.object(compare, "verify_codex_build") as codex, \
                    mock.patch.object(compare, "verify_native_build") as native, \
                    mock.patch.object(compare, "run_case") as execute:
                with self.assertRaisesRegex(ValueError, "genuinely common product owner boundary"):
                    compare.main()
            codex.assert_not_called()
            native.assert_not_called()
            execute.assert_not_called()
            self.assertFalse(output.exists())
        self.assertIsNone(require_cost_scope("execution-observation", ["native"])["product_total_cost"])


if __name__ == "__main__":
    unittest.main()
