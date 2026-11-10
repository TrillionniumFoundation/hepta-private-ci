"""Mechanism tests on declared fixtures; these are not policy-gain evidence."""

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from .critic_context import CriticContext, context_digest
from .metacontrol import ObservedContinuation, PublicControlState, fit_heads
from .metacontrol_checkpoint import load_heads, save_heads


# Manufactured dependency identities, not observed producer manifests.
CRITIC = CriticContext(
    **{name: "a" * 64 for name in CriticContext.__dataclass_fields__}
)


class MetacontrolTests(unittest.TestCase):
    def state(self, feature=1.0, *, pending=False):
        return PublicControlState(
            (feature,), (0.5, 0.5), pending, 0.0, ("WRITE_TEXT", "STOP"), 10.0
        )

    def rows(self, prefix, groups=12, *, cost=0.02, selected=True, effect=True):
        result = []
        for group in range(groups):
            for feature in (-1.0, 1.0):
                result.append(
                    ObservedContinuation(
                        source_group=f"{prefix}/{group}",
                        decision_id=f"{prefix}/{group}/{feature}",
                        state=self.state(feature),
                        action="WRITE_TEXT",
                        stop_quality=0.4,
                        continuation_quality=0.6 if feature > 0 else 0.2,
                        incremental_cost=cost,
                        full_cost_observed=False,
                        selected_used=selected,
                        effect_occurred=(feature > 0) if effect else None,
                        identity_receipt_sha256="a" * 64
                        if selected is not None
                        else None,
                        effect_receipt_sha256="b" * 64 if effect else None,
                        context=CRITIC,
                        evidence_context_sha256=context_digest(CRITIC),
                    )
                )
        return result

    def test_zero_reward_does_not_become_failed_execution(self):
        rows = self.rows("train")
        model = fit_heads(rows, context=CRITIC)
        wrong = model.predict(self.state(-1.0), "WRITE_TEXT", context=CRITIC)
        useful = model.predict(self.state(1.0), "WRITE_TEXT", context=CRITIC)
        self.assertGreater(wrong["selected_used_probability"], 0.9)
        self.assertLess(wrong["effect_occurred_probability"], 0.1)
        self.assertGreater(useful["effect_occurred_probability"], 0.9)
        self.assertLess(wrong["net_gain"], -0.2)
        self.assertGreater(useful["net_gain"], 0.17)
        self.assertEqual(
            model.identity_head["status"], "single_class_smoothed_base_rate"
        )
        self.assertEqual(model.effect_head["status"], "two_class_logistic")

    def test_missing_labels_and_missing_cost_are_not_zero_imputed(self):
        rows = self.rows("train", selected=None, effect=False)
        rows.append(
            replace(
                rows[0],
                decision_id="unknown",
                incremental_cost=None,
                source_group="unknown",
            )
        )
        model = fit_heads(rows, context=CRITIC)
        prediction = model.predict(self.state(), "WRITE_TEXT", context=CRITIC)
        self.assertIsNone(prediction["selected_used_probability"])
        self.assertIsNone(prediction["effect_occurred_probability"])
        self.assertEqual(model.receipt["known_cost_rows"], len(rows) - 1)
        model.calibrate(
            self.rows("calibration", selected=None, effect=False), context=CRITIC
        )
        future = model.diagnostics(
            self.rows("future", selected=None, effect=False), context=CRITIC
        )
        self.assertIsNone(future["selected_used"]["brier"])
        self.assertIsNone(future["effect_occurred"]["ece"])
        self.assertEqual(future["selected_used"]["missing_labels"], 24)
        self.assertFalse(future["full_cost_observed"])
        raw = json.dumps(model.snapshot()).encode()
        restored = load_heads(raw, hashlib.sha256(raw).hexdigest(), context=CRITIC)
        self.assertEqual(restored.identity(), model.identity())
        snapshot = model.snapshot()
        snapshot["identity"] = {**model.identity_head, "labelled_source_groups": 0}
        raw = json.dumps(snapshot).encode()
        with self.assertRaisesRegex(ValueError, "probability head field"):
            load_heads(raw, hashlib.sha256(raw).hexdigest(), context=CRITIC)

    def test_observed_cost_changes_stop_comparison_without_probability_product(self):
        cheap = fit_heads(self.rows("cheap"), context=CRITIC)
        expensive = fit_heads(self.rows("expensive", cost=0.5), context=CRITIC)
        bounds = {"WRITE_TEXT": 1.0}
        self.assertEqual(
            cheap.choose(self.state(), action_cost_bounds=bounds, context=CRITIC)[0],
            "WRITE_TEXT",
        )
        self.assertEqual(
            expensive.choose(self.state(), action_cost_bounds=bounds, context=CRITIC)[
                0
            ],
            "STOP",
        )
        # Value is fitted from unconditional observed net gain, not p(use)*gain.
        cheap.identity_head["constant"] = 0.01
        self.assertEqual(
            cheap.choose(self.state(), action_cost_bounds=bounds, context=CRITIC)[0],
            "WRITE_TEXT",
        )

    def test_source_separation_and_future_freeze(self):
        model = fit_heads(self.rows("train"), context=CRITIC)
        with self.assertRaisesRegex(ValueError, "Freeze calibration"):
            model.diagnostics(self.rows("future"), context=CRITIC)
        with self.assertRaisesRegex(ValueError, "disjoint"):
            model.calibrate(self.rows("train"), context=CRITIC)
        model.calibrate(self.rows("calibration"), context=CRITIC)
        frozen = model.identity()
        report = model.diagnostics(self.rows("future"), context=CRITIC)
        self.assertEqual(model.identity(), frozen)
        self.assertEqual(report["source_groups"], 12)
        self.assertLess(report["effect_occurred"]["brier"], 0.01)
        with self.assertRaisesRegex(ValueError, "overlap"):
            model.diagnostics(self.rows("calibration"), context=CRITIC)
        with self.assertRaisesRegex(ValueError, "frozen"):
            model.calibrate(self.rows("another-calibration"), context=CRITIC)

    def test_partial_cost_calibration_cannot_qualify_corrected_values(self):
        model = fit_heads(
            [replace(row, full_cost_observed=True) for row in self.rows("train")],
            context=CRITIC,
        )
        report = model.calibrate(self.rows("calibration"), context=CRITIC)
        self.assertEqual(
            (
                report["training_full_cost_observed"],
                report["calibration_full_cost_observed"],
            ),
            (True, False),
        )
        for mode in ("point", "conditional", "unconditional"):
            _, detail = model.choose(
                self.state(),
                mode=mode,
                action_cost_bounds={"WRITE_TEXT": 1.0},
                context=CRITIC,
            )
            self.assertEqual(detail["full_cost_observed"], mode == "point")
            if mode != "point":
                self.assertEqual(detail["cost_disposition"], "HOLD")
        raw = json.dumps(model.snapshot()).encode()
        restored = load_heads(raw, hashlib.sha256(raw).hexdigest(), context=CRITIC)
        self.assertEqual(restored.calibration, model.calibration)
        self.assertEqual(
            restored.calibration["records_sha256"], report["records_sha256"]
        )

    def test_nonfinite_derived_values_refuse_prediction_and_keep_fallback(self):
        for broken in ("vector", "value", "logit"):
            with self.subTest(broken=broken):
                model = fit_heads(self.rows("train"), context=CRITIC)
                if broken == "vector":
                    model.scale[0] = 1e-320
                elif broken == "value":
                    model.value_weights[:] = 1e308
                else:
                    model.effect_head["weights"] = [1e308] * len(model.value_weights)
                with self.assertRaisesRegex(ValueError, "Nonfinite"):
                    model.predict(self.state(), "WRITE_TEXT", context=CRITIC)
                action, detail = model.choose(
                    self.state(), action_cost_bounds={"WRITE_TEXT": 1.0}, context=CRITIC
                )
                self.assertEqual((action, detail["fallback"]), ("STOP", True))
        model = fit_heads(self.rows("train"), context=CRITIC)
        model.calibrate(self.rows("calibration"), context=CRITIC)
        model.value_weights[:] = 5e307
        model.calibration["unconditional"]["lower_residual"] = 1e308
        action, detail = model.choose(
            self.state(),
            mode="unconditional",
            action_cost_bounds={"WRITE_TEXT": 1.0},
            context=CRITIC,
        )
        self.assertEqual((action, detail["fallback"]), ("STOP", True))

    def test_conditional_support_counts_sources_not_repeated_decisions(self):
        model = fit_heads(self.rows("train"), context=CRITIC)
        # 24 rows within one source are still one calibration source.
        rows = [
            replace(row, source_group="one-source") for row in self.rows("calibration")
        ]
        report = model.calibrate(rows, context=CRITIC)
        self.assertEqual(report["unconditional"]["groups"], 1)
        self.assertIsNone(report["unconditional"]["lower_residual"])
        for mode in ("conditional", "unconditional"):
            action, detail = model.choose(
                self.state(),
                mode=mode,
                light_action="STOP",
                action_cost_bounds={"WRITE_TEXT": 1.0},
                context=CRITIC,
            )
            self.assertEqual(action, "STOP")
            self.assertTrue(detail["fallback"])

    def test_disjoint_calibration_can_support_both_residual_modes(self):
        model = fit_heads(self.rows("train"), context=CRITIC)
        model.calibrate(self.rows("calibration"), context=CRITIC)
        for mode in ("point", "conditional", "unconditional"):
            action, detail = model.choose(
                self.state(),
                mode=mode,
                action_cost_bounds={"WRITE_TEXT": 1.0},
                context=CRITIC,
            )
            self.assertEqual(action, "WRITE_TEXT")
            self.assertFalse(detail["fallback"])
            self.assertEqual(detail["production_update"], "no-update")

    def test_unobserved_context_and_actions_keep_light_fallback(self):
        model = fit_heads(self.rows("train"), context=CRITIC)
        model.calibrate(self.rows("calibration"), context=CRITIC)
        for state in (
            self.state(2.0),
            replace(self.state(), remaining_budget=20.0),
            replace(self.state(), legal_actions=("READ_ROI", "STOP")),
        ):
            action, detail = model.choose(
                state,
                mode="conditional",
                light_action="STOP",
                action_cost_bounds={"WRITE_TEXT": 1.0, "READ_ROI": 1.0},
                context=CRITIC,
            )
            self.assertEqual(action, "STOP")
            self.assertTrue(detail["fallback"])
        report = model.diagnostics(
            [replace(row, state=self.state(2.0)) for row in self.rows("future")],
            context=CRITIC,
        )
        self.assertEqual(report["unsupported_rows"], 24)
        self.assertIsNone(report["net_gain_mse"])

    def test_execution_labels_require_pins_and_not_all_actions_share_labels(self):
        rows = self.rows("train")
        with self.assertRaisesRegex(ValueError, "pinned"):
            replace(rows[0], identity_receipt_sha256=None)
        with self.assertRaisesRegex(ValueError, "pinned"):
            replace(rows[0], effect_receipt_sha256=None)
        read = [
            replace(
                row,
                state=replace(row.state, legal_actions=("READ_ROI", "STOP")),
                action="READ_ROI",
                decision_id="read/" + row.decision_id,
                selected_used=None,
                effect_occurred=None,
                identity_receipt_sha256=None,
                effect_receipt_sha256=None,
            )
            for row in rows
        ]
        model = fit_heads(rows + read, context=CRITIC)
        prediction = model.predict(read[0].state, "READ_ROI", context=CRITIC)
        self.assertIsNone(prediction["selected_used_probability"])
        self.assertIsNone(prediction["effect_occurred_probability"])

    def test_public_contract_excludes_targets_and_terminal_training(self):
        state = self.state()
        self.assertEqual(PublicControlState.from_wire(asdict(state)), state)
        with self.assertRaisesRegex(ValueError, "Unknown public"):
            PublicControlState.from_wire({**asdict(state), "expected_text": "hidden"})
        for changes in (
            {"features": (float("nan"),)},
            {"context_belief": (0.8, 0.8)},
            {"remaining_budget": -1},
            {"legal_actions": ("VERIFY", "STOP")},
            {"pending_evidence": 1},
        ):
            with self.assertRaises(ValueError):
                replace(state, **changes)
        with self.assertRaisesRegex(ValueError, "continuation"):
            replace(self.rows("train")[0], action="STOP")
        with self.assertRaisesRegex(ValueError, "Repeated decision"):
            fit_heads(self.rows("train") * 2, context=CRITIC)

    def test_unknown_or_exhausted_budget_never_uses_nonterminal_fallback(self):
        model = fit_heads(self.rows("train"), context=CRITIC)
        self.assertEqual(
            model.choose(self.state(), light_action="WRITE_TEXT", context=CRITIC)[0],
            "STOP",
        )
        for budget, cost, reserve in ((0.0, 1.0, 0.0), (10.0, 9.0, 2.0)):
            chosen, detail = model.choose(
                replace(self.state(), remaining_budget=budget),
                light_action="WRITE_TEXT",
                action_cost_bounds={"WRITE_TEXT": cost},
                finalization_reserve=reserve,
                context=CRITIC,
            )
            self.assertEqual(chosen, "STOP")
            self.assertTrue(detail["owner_predispatch_budget_check_required"])

    def test_repeating_one_source_does_not_change_fitted_value_or_probabilities(self):
        rows = self.rows("train")
        duplicated = rows + [
            replace(row, decision_id=row.decision_id + f"/copy/{index}")
            for index in range(5)
            for row in rows[:2]
        ]
        original, repeated = (
            fit_heads(rows, context=CRITIC),
            fit_heads(duplicated, context=CRITIC),
        )
        for feature in (-1.0, 1.0):
            left = original.predict(self.state(feature), "WRITE_TEXT", context=CRITIC)
            right = repeated.predict(self.state(feature), "WRITE_TEXT", context=CRITIC)
            for key in (
                "net_gain",
                "selected_used_probability",
                "effect_occurred_probability",
            ):
                self.assertAlmostEqual(left[key], right[key], places=9)

    def test_cold_checkpoint_preserves_predictions_and_rejects_invalid_profiles(self):
        model = fit_heads(self.rows("train"), context=CRITIC)
        model.calibrate(self.rows("calibration"), context=CRITIC)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "heads.json"
            pin = save_heads(model, path, context=CRITIC)
            restored = load_heads(path.read_bytes(), pin, context=CRITIC)
            self.assertEqual(restored.identity(), model.identity())
            self.assertEqual(
                restored.predict(self.state(), "WRITE_TEXT", context=CRITIC),
                model.predict(self.state(), "WRITE_TEXT", context=CRITIC),
            )
            with self.assertRaisesRegex(ValueError, "digest"):
                load_heads(path.read_bytes() + b" ", pin, context=CRITIC)
        for key, value in (
            ("shape", [9000, 2]),
            ("value", [float("nan")]),
            ("value", [1e308] * len(model.value_weights)),
            ("scale", [1e-300] * len(model.scale)),
            ("calibration_groups", ["train/0"]),
            ("identity", {**model.identity_head, "constant": 0.01}),
            ("identity", {**model.identity_head, "unknown": True}),
            ("effect", {**model.effect_head, "unknown": True}),
            ("receipt", {**model.receipt, "unknown": True}),
        ):
            raw = json.dumps({**model.snapshot(), key: value}).encode()
            with self.assertRaises(ValueError):
                load_heads(raw, hashlib.sha256(raw).hexdigest(), context=CRITIC)


if __name__ == "__main__":
    unittest.main()
