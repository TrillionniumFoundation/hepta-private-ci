"""Behavioral tests for response, skill, clustering and freeze integrity gates."""

from copy import deepcopy
import unittest

from .gate_audit import audit, canonical_digest, fitting_rows_digest, MODES, SEEDS


def fixture():
    rows = []
    controllers = {str(seed): {mode: canonical_digest([seed, mode]) for mode in MODES}
                   for seed in SEEDS}
    for seed in SEEDS:
        for trajectory in range(16):
            for step in range(4):
                sign = 1 if (step + trajectory) % 2 else -1
                values = [.5, .5 + sign * .02, .5 - sign * .02, .495]
                row = {"seed": seed, "trajectory": trajectory, "step": step,
                       "partition": "fit" if trajectory < 8 else "audit",
                       "state_sha256": canonical_digest([seed, trajectory, step, "state"]),
                       "optimizer_sha256": canonical_digest([seed, trajectory, step, "momentum"]),
                       "schedule_sha256": canonical_digest([seed, trajectory, step, "schedule"]),
                       "current_value": .5, "action_values": values}
                if trajectory >= 8:
                    row["predictions"] = {mode: values[:] for mode in MODES}
                    row["prediction_controller_sha256"] = controllers[str(seed)]
                rows.append(row)
    freeze = {"fit_rows_sha256": fitting_rows_digest(rows), "controller_sha256": controllers,
              "decision_steps": [0, 1, 2, 3]}
    return rows, freeze


class GateAuditTests(unittest.TestCase):
    def test_predictive_action_policy_passes_varying_real_response(self):
        rows, freeze = fixture()
        result = audit(rows, freeze)
        self.assertEqual(result["gates"], {"audit_response": True,
            "field_prediction_skill": True, "field_decision_skill": True})
        self.assertAlmostEqual(result["field_mean_improvement"], .02)
        self.assertGreater(result["improvement_ci95"][0], 0)

    def test_constant_predictor_does_not_pass_from_small_error(self):
        rows, freeze = fixture()
        for row in rows:
            if row["partition"] == "audit":
                row["predictions"]["field"] = [row["current_value"]] * 4
        result = audit(rows, freeze)
        self.assertTrue(result["gates"]["audit_response"])
        self.assertFalse(result["gates"]["field_prediction_skill"])
        self.assertFalse(result["gates"]["field_decision_skill"])

    def test_flat_response_never_creates_beneficial_control_certificate(self):
        rows, freeze = fixture()
        for row in rows:
            row["action_values"] = [.5] * 4
            if row["partition"] == "audit":
                row["predictions"] = {mode: [.5] * 4 for mode in MODES}
        freeze["fit_rows_sha256"] = fitting_rows_digest(rows)
        result = audit(rows, freeze)
        self.assertFalse(result["gates"]["audit_response"])
        self.assertFalse(result["all_development_audit_gates_pass"])

    def test_audit_row_cannot_be_reclassified_into_fitting_trajectory(self):
        rows, freeze = fixture()
        next(row for row in rows if row["partition"] == "audit")["trajectory"] = 0
        with self.assertRaisesRegex(ValueError, "Repeated optimizer snapshot|both fit and audit"):
            audit(rows, freeze)

    def test_no_update_branch_must_preserve_current_fixed_panel_value(self):
        rows, freeze = fixture()
        rows[-1]["action_values"][0] += .0001
        with self.assertRaisesRegex(ValueError, "No-update branch"):
            audit(rows, freeze)

    def test_modified_fitting_values_fail_freeze(self):
        rows, freeze = fixture()
        rows[0]["action_values"][1] += .01
        with self.assertRaisesRegex(ValueError, "pre-audit freeze"):
            audit(rows, freeze)

    def test_changed_prediction_controller_fails(self):
        rows, freeze = fixture()
        rows = deepcopy(rows)
        next(row for row in rows if row["partition"] == "audit")["prediction_controller_sha256"] = {
            mode: "0" * 64 for mode in MODES}
        with self.assertRaisesRegex(ValueError, "different controller"):
            audit(rows, freeze)

    def test_partial_trajectory_does_not_shrink_cluster_silently(self):
        rows, freeze = fixture()
        del rows[-1]
        with self.assertRaisesRegex(ValueError, "incomplete or unequal"):
            audit(rows, freeze)

    def test_boundary_missing_from_every_trajectory_is_rejected(self):
        rows, freeze = fixture()
        rows = [row for row in rows if row["step"] != 2]
        with self.assertRaisesRegex(ValueError, "incomplete or unequal"):
            audit(rows, freeze)

    def test_duplicate_rows_cannot_inflate_sample_size(self):
        rows, freeze = fixture()
        rows.append(deepcopy(rows[-1]))
        with self.assertRaisesRegex(ValueError, "Repeated optimizer snapshot"):
            audit(rows, freeze)


if __name__ == "__main__":
    unittest.main()
