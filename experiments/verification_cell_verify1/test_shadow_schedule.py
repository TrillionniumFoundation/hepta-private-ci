import unittest
from dataclasses import asdict, replace

from .checker_effects import CheckerSpec, EffectScope, PairedPanel, fit_checker_effects
from .contracts import digest
from .shadow_risk import Prediction, Snapshot, Target
from .shadow_schedule import CheckObservation, observation_context, select_shadow_check


class ShadowScheduleTests(unittest.TestCase):
    def setUp(self):
        target = Target("artifact", "terminal_error", 4, digest("continuation"))
        self.snapshot = Snapshot("heldout-task", "test", digest("candidate"),
                                 target, 2, (1, 1))
        self.prediction = Prediction(self.snapshot, 0.2, digest("frozen-risk"))
        self.checkers = tuple(CheckerSpec(name, digest(name), 0.1)
                              for name in ("noisy", "duplicate"))
        self.scope = EffectScope(domain=target.domain, event=target.event,
                                 horizon_start=2, horizon_end=4,
                                 continuation_policy_sha256=target.continuation_policy_sha256,
                                 context_sha256=observation_context(self.snapshot))
        panels = []
        for truth, outcome, count in ((False, "pass", 18), (False, "fail", 2),
                                      (True, "pass", 2), (True, "fail", 18)):
            for _ in range(count):
                key = str(len(panels))
                panels.append(PairedPanel(key, "train", digest(key), self.scope,
                    tuple(c.checker_id for c in self.checkers),
                    tuple(c.version_sha256 for c in self.checkers),
                    (outcome, outcome), truth, digest("label" + key),
                    (digest("first" + key), digest("repeat" + key))))
        self.model = fit_checker_effects(panels, scope=self.scope, checkers=self.checkers,
                                        training_groups=("train",), heldout_groups=("test",))

    def choose(self, observations=(), prediction=None, model=None, **kwargs):
        return select_shadow_check(prediction or self.prediction, model or self.model,
            observations, ("accept", "reject", "repair"),
            ((0, 100), (5, 5), (2, 12)), 1,
            hard_checks_complete=kwargs.get("hard_checks_complete", True))

    def observation(self):
        return CheckObservation("noisy", digest("noisy"),
                                digest(asdict(self.snapshot)), "pass", digest("actual-read"))

    def test_joined_effect_model_values_first_check_but_not_duplicate(self):
        initial = self.choose()
        self.assertEqual(initial["status"], "check")
        after = self.choose((self.observation(),))
        self.assertEqual(after["status"], "defer")
        self.assertAlmostEqual(after["posterior_error"], 0.02 / 0.74)
        self.assertTrue(all(row["gross_value"] == 0 for row in after["selection"]["evaluations"]))
        self.assertEqual(after["production_authority"], "NONE")

    def test_mandatory_gate_and_unknown_risk_block_optional_selection(self):
        result = self.choose(hard_checks_complete=False)
        self.assertEqual((result["status"], result["selection"]), ("blocked", None))
        result = self.choose(prediction=replace(self.prediction, probability=None))
        self.assertEqual((result["status"], result["selection"]), ("unsupported", None))

    def test_scope_changes_refuse_and_history_rebinding_rejects(self):
        changed = replace(self.snapshot, features=(0, 1))
        self.assertEqual(self.choose(prediction=replace(self.prediction, snapshot=changed))["reason"],
                         "scope_mismatch")
        for observation in (replace(self.observation(), version_sha256=digest("other")),
                            replace(self.observation(), snapshot_sha256=digest("stale"))):
            with self.assertRaises(ValueError):
                self.choose((observation,))
        with self.assertRaises(ValueError):
            self.choose((self.observation(), self.observation()))

    def test_heldout_group_is_required_and_result_digest_binds_decision(self):
        with self.assertRaises(ValueError):
            self.choose(prediction=replace(self.prediction,
                        snapshot=replace(self.snapshot, source_group="train")))
        result = self.choose()
        self.assertEqual(result["decision_contract"], {
            "states": ("correct", "error"), "actions": ("accept", "reject", "repair"),
            "losses": ((0.0, 100.0), (5.0, 5.0), (2.0, 12.0)),
            "remaining_budget": 1.0, "hard_checks_complete": True,
            "cost_units": "declared_decision_loss"})
        claimed = result.pop("record_sha256")
        self.assertEqual(digest(result), claimed)
        result["pre_history_risk"] = 0.9
        self.assertNotEqual(digest(result), claimed)


if __name__ == "__main__":
    unittest.main()
