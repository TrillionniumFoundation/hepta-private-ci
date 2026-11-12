"""Manufactured frozen-policy regressions, not prospective policy evidence."""

from dataclasses import replace
import hashlib
import json
import unittest
from unittest.mock import patch

from .critic_context import CriticContext, CriticContextError, context_digest
from .macro_policy import ACTION_SHA256, METHODS, fit, load, source_sha256
from .metacontrol_macro_contract import SEQUENCES, digest

CONTEXT = CriticContext(
    **{
        name: ACTION_SHA256 if name == "action_sha256" else "a" * 64
        for name in CriticContext.__dataclass_fields__
    }
)


def state(feature=0.5):
    return {
        "features": [feature],
        "context_belief": [1.0],
        "pending_evidence": False,
        "freshness_seconds": 0.0,
        "remaining_seconds": 10.0,
        "legal_macros": ["STOP", "READ"],
    }


def pair(source, name, feature=0.5):
    return {
        "schema": "ndu.ctrl.macro-pair.v1",
        "source_id": source,
        "source_sha256": digest(["registered-source", source]),
        "decision_id": name,
        "context_sha256": context_digest(CONTEXT),
        "state": state(feature),
        "branches": {
            macro: {
                "status": "COMPLETED",
                "quality": 0.1 if macro == "STOP" else 0.6,
                "cost": 0.1,
                "full_cost_observed": True,
                "evidence_sha256": digest([name, macro]),
                "initial_public_state_sha256": digest(state(feature)),
                "public_state_sha256": digest(state(feature)),
                "actions": list(actions),
            }
            for macro, actions in SEQUENCES.items()
        },
        "labels": {
            name: None for name in ("acquired", "selected_used", "effect_occurred")
        },
        "label_receipts": {
            name: None for name in ("acquired", "selected_used", "effect_occurred")
        },
    }


class MacroPolicyTest(unittest.TestCase):
    def setUp(self):
        self.train = [
            pair("a", "a0", 0),
            pair("a", "a1", 1),
            pair("b", "b0", 0),
            pair("b", "b1", 1),
        ]
        self.cal = [pair("c" + str(i), "cal" + str(i)) for i in range(10)]

    def fitted(self):
        return fit(
            self.train,
            self.cal,
            context=CONTEXT,
            expected_source_sha256=source_sha256(),
        )

    def choose(self, model, policy="point", public=None, context=CONTEXT, **bounds):
        return model.choose(
            public or state(),
            policy,
            context=context,
            read_seconds_bound=bounds.get("read", 2),
            finalizer_seconds_reserve=bounds.get("reserve", 1),
        )

    def test_fit_freeze_load_and_all_six_methods(self):
        model = self.fitted()
        restored = load(model.to_bytes(), model.sha256, context=CONTEXT)
        actions = {method: self.choose(restored, method)[0] for method in METHODS}
        self.assertEqual(
            actions,
            {method: "STOP" if method == "STOP" else "READ" for method in METHODS},
        )
        self.assertEqual(restored.to_bytes(), model.to_bytes())
        self.assertEqual(
            self.choose(model)[1]["probabilities"],
            {"acquired": None, "selected_used": None, "effect_occurred": None},
        )

    def test_unknown_cost_is_retained_and_never_zero(self):
        self.train.append(pair("a", "missing"))
        self.train[-1]["branches"]["READ"].update(cost=None, full_cost_observed=False)
        model = self.fitted()
        self.assertEqual(model.data["counts"]["fit"], 5)
        self.assertEqual(model.data["counts"]["fit_known_value"], 4)
        self.assertFalse(model.data["full_cost_observed"])
        self.train[0]["branches"]["READ"].update(cost=None, full_cost_observed=False)
        with self.assertRaises(ValueError):
            self.fitted()

    def test_observed_failure_costs_enter_value(self):
        for row in self.train + self.cal:
            row["branches"]["READ"].update(
                status="FAILED", quality=0, cost=0.4, actions=["PREPARE_ROI"]
            )
        self.assertEqual(self.choose(self.fitted())[0], "STOP")

    def test_unknown_terminal_does_not_become_observed_zero(self):
        extra = pair("a", "unknown")
        extra["branches"]["READ"]["status"] = "UNKNOWN"
        self.train.append(extra)
        model = self.fitted()
        self.assertEqual(model.data["counts"]["fit_known_value"], 4)
        self.assertFalse(model.data["full_cost_observed"])

    def test_no_second_multiplication_by_realization_probability(self):
        for row in self.train:
            row["labels"]["selected_used"] = False
            row["label_receipts"]["selected_used"] = digest(
                [row["decision_id"], "selected"]
            )
        action, detail = self.choose(self.fitted())
        self.assertEqual(action, "READ")
        self.assertGreater(detail["score"], 0.49)
        self.assertLess(detail["probabilities"]["selected_used"], 0.5)

    def test_source_overlap_and_physical_evidence_reuse_refused(self):
        self.cal[0]["source_id"] = "a"
        with self.assertRaises(ValueError):
            self.fitted()
        self.cal[0]["source_id"] = "c0"
        self.cal[0]["branches"]["READ"]["evidence_sha256"] = self.train[0]["branches"][
            "READ"
        ]["evidence_sha256"]
        with self.assertRaises(ValueError):
            self.fitted()

    def test_original_source_bytes_cannot_be_renamed_or_split(self):
        self.cal[0]["source_sha256"] = self.train[0]["source_sha256"]
        with self.assertRaises(ValueError):
            self.fitted()
        self.cal[0] = pair("c0", "cal0")
        self.train[1]["source_sha256"] = digest("different source bytes")
        with self.assertRaises(ValueError):
            self.fitted()

    def test_context_drift_and_future_field_refused(self):
        model = self.fitted()
        drift = replace(CONTEXT, answer_sha256="b" * 64)
        self.assertEqual(
            self.choose(model, context=drift)[1]["reason"], "recalibration_required"
        )
        with self.assertRaises(CriticContextError):
            load(model.to_bytes(), model.sha256, context=drift)
        with self.assertRaises(ValueError):
            self.choose(model, public={**state(), "reference": "future answer"})

    def test_primitive_action_cannot_be_relabelled_macro(self):
        self.train[0]["branches"]["READ"]["actions"] = ["READ_ROI", "STOP"]
        with self.assertRaises(ValueError):
            self.fitted()
        self.train[0] = pair("a", "a0", 0)
        model = self.fitted()
        with self.assertRaises(ValueError):
            self.choose(model, public={**state(), "legal_macros": ["STOP", "READ_ROI"]})

    def test_observed_read_requires_current_legal_macro_support(self):
        row = self.train[0]
        row["state"]["legal_macros"] = ["STOP"]
        for branch in row["branches"].values():
            branch["public_state_sha256"] = digest(row["state"])
        with self.assertRaises(ValueError):
            self.fitted()

    def test_insufficient_calibration_and_reserves_stop(self):
        self.cal = self.cal[:2]
        model = self.fitted()
        self.assertEqual(
            self.choose(model, "conditional")[1]["reason"], "insufficient_calibration"
        )
        self.assertEqual(self.choose(model, read=10)[0], "STOP")
        with self.assertRaises(ValueError):
            self.choose(model, reserve=11)

    def test_mutated_model_bytes_or_source_refused(self):
        model = self.fitted()
        with self.assertRaises(ValueError):
            load(model.to_bytes() + b" ", model.sha256, context=CONTEXT)
        model.data["value"][0] += 1
        with self.assertRaises(ValueError):
            self.choose(model)
        model = self.fitted()
        with patch(
            "ndu_real_runtime.macro_policy.source_sha256", return_value="0" * 64
        ):
            with self.assertRaises(ValueError):
                self.choose(model)

    def test_observed_cheaper_read_is_not_clamped_away(self):
        for row in self.train + self.cal:
            row["branches"]["READ"].update(quality=0.1, cost=0.05)
            row["branches"]["STOP"]["cost"] = 0.2
        self.assertGreater(self.choose(self.fitted())[1]["score"], 0.14)

    def test_original_public_state_projection_is_bound(self):
        self.train[0]["state"]["features"] = [0.25]
        with self.assertRaises(ValueError):
            self.fitted()

    def test_label_without_original_witness_refused(self):
        self.train[0]["labels"]["acquired"] = False
        with self.assertRaises(ValueError):
            self.fitted()

    def test_cold_load_checks_denominators_and_probabilities(self):
        model = self.fitted()
        for kind in ("full_cost", "calibration", "probability", "light"):
            with self.subTest(kind=kind):
                data = json.loads(model.to_bytes())
                if kind == "full_cost":
                    data["counts"]["fit"] += 1
                elif kind == "calibration":
                    data["counts"]["calibration_known_value"] -= 1
                    data["full_cost_observed"] = False
                elif kind == "probability":
                    data["probability_heads"]["acquired"]["constant"] = 1
                else:
                    data["light"][next(iter(data["light"]))] = 1e100
                raw = json.dumps(data).encode()
                with self.assertRaises(ValueError):
                    load(raw, hashlib.sha256(raw).hexdigest(), context=CONTEXT)

    def test_only_value_observed_states_bound_critic_envelope(self):
        extra = pair("a", "unpriced", 100)
        extra["branches"]["READ"].update(cost=None, full_cost_observed=False)
        self.train.append(extra)
        model = self.fitted()
        self.assertEqual(
            self.choose(model, public=state(50))[1]["reason"],
            "outside_observed_feature_envelope",
        )
        self.assertEqual(self.choose(model, "tuned-fixed", state(50))[0], "READ")


if __name__ == "__main__":
    unittest.main()
