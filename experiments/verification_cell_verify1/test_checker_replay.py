"""Replay contracts use synthetic values here; no inference or remote effects."""

import copy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from .checker_effects import CheckerSpec, PairedPanel
from .check_voi import DecisionProblem, evaluate_check
from .checker_replay import ROSTER, _heldout_report, _observation, effect_scope, fit_diagnostic, run
from .model_protocol import digest, public_view
from .shadow_risk import Snapshot, Target, TerminalLabel, fit_risk_table
from .shadow_schedule import select_shadow_check


def panel_fixture(informative=False):
    target = Target("unit-pilot", "terminal-error", 3, digest("policy"))
    scope = effect_scope(Snapshot("panel", "cal/group", digest("candidate"), target, 0, ()))
    checkers = tuple(CheckerSpec(name, digest(name), 0) for name, _, _ in ROSTER)
    panels = []
    for index, error in enumerate((False, False, True, True)):
        outcome = "fail" if informative and error else "pass"
        panels.append(PairedPanel(str(index), "cal/group", digest(["snapshot", index]), scope,
                      tuple(c.checker_id for c in checkers), tuple(c.version_sha256 for c in checkers),
                      (outcome,) * len(checkers), error, digest(["label", index]),
                      tuple(digest([index, c.checker_id]) for c in checkers)))
    return scope, checkers, panels


def member_fixture(score=.5):
    context = {"split": "calibration", "case_id": "c", "arm": "single", "tick": 0}
    view = public_view([])
    member = {"operation_id": "member", "base_sha256": digest("base"), "adapter_sha256": None,
              "prompt_sha256": digest("prompt"), "evidence_sha256": digest(view), "score": score}
    assessment = {"assessment_id": "aggregate", "context": context, "arm": "single", "view": view,
                  "evidence_sha256": digest(view), "members": [member], "score": score}
    operations = {"member": {**member, "kind": "model_score", "status": "completed", "context": context,
                              "model": "qwen", "role": "neutral", "view": view, "prompt": "prompt", "decoder": {"sampling": False}},
                  "aggregate": {**assessment, "operation_id": "aggregate", "kind": "score_aggregation", "status": "completed"}}
    data = {"plan": {"decoder": {"sampling": False}}, "cases": {"calibration": {"c": {"source_group": "cal/group"}}},
            "host_rows": {("calibration", "c", "calibration/uninterrupted_panel"): {"effects": [{"operation_id": "effect"}]}}}
    return data, {("calibration", "c", "single"): assessment}, operations, {"member": 1, "aggregate": 2, "effect": 3}


class CheckerReplayTests(unittest.TestCase):
    def test_trained_risk_and_effects_compose_at_the_same_initial_context(self):
        scope, checkers, panels = panel_fixture()
        target = Target(scope.domain, scope.event, scope.horizon_end, scope.continuation_policy_sha256)
        training = [Snapshot(str(i), "prior/group", digest(i), target, 0, ()) for i in range(4)]
        labels = [TerminalLabel(row.trajectory_id, row.source_group, row.subject_sha256, target,
                  "unknown", i >= 2, 3, digest(["label", i]), None) for i, row in enumerate(training)]
        risk = fit_risk_table(training, labels, target, ("prior/group",), ("test/group",))
        prediction = risk.predict(Snapshot("heldout", "test/group", digest("heldout"), target, 0, ()))
        effects, _ = fit_diagnostic(panels, scope=scope, checkers=checkers,
                    training_groups=("cal/group",), heldout_groups=("test/group",), prior_error=prediction.probability)
        result = select_shadow_check(prediction, effects, (), ("accept", "reject"), ((0, 1), (1, 0)),
                                     0, hard_checks_complete=True)
        self.assertEqual((result["status"], result["reason"]), ("defer", "no_affordable_positive_value"))
        self.assertEqual(result["scope"]["context_sha256"], effects.scope.context_sha256)
        self.assertEqual(result["production_authority"], "NONE")

    def test_same_view_constant_votes_have_zero_gross_value(self):
        scope, checkers, panels = panel_fixture()
        model, result = fit_diagnostic(panels, scope=scope, checkers=checkers,
                                      training_groups=("cal/group",), heldout_groups=("test/group",), prior_error=.5)
        self.assertTrue(result["all_gross_values_zero"])
        self.assertEqual(result["selection"]["status"], "defer")
        self.assertEqual(result["repeat_after_neutral"][0]["evaluation"]["gross_value"], 0)
        problem = DecisionProblem(("correct", "error"), (.5, .5), ("accept", "reject"), ((0, 1), (1, 0)))
        for channel in model.condition(.5, scope=scope).channels:
            self.assertEqual(evaluate_check(problem, replace(channel, cost=.37)).net_value, -.37)

    def test_discriminative_panels_are_not_forced_to_zero(self):
        scope, checkers, panels = panel_fixture(informative=True)
        _, result = fit_diagnostic(panels, scope=scope, checkers=checkers,
                                  training_groups=("cal/group",), heldout_groups=("test/group",), prior_error=.5)
        self.assertFalse(result["all_gross_values_zero"])
        self.assertTrue(all(item["gross_value"] == .5 for item in result["evaluations"]))
        self.assertEqual(result["selection"]["status"], "check")
        self.assertTrue(all(row["status"] == "unsupported" for row in result["repeat_after_neutral"]))

    def test_threshold_and_exact_operation_binding(self):
        for score, expected in ((.499999, "pass"), (.5, "fail")):
            fixture = member_fixture(score)
            observation = _observation(*fixture, "calibration", "c", ROSTER[0])
            self.assertEqual(observation["outcome"], expected)
            self.assertEqual(observation["operation_sha256"], digest(fixture[2]["member"]))

    def test_altered_score_prompt_role_and_late_assessment_are_rejected(self):
        mutations = (
            lambda f: f[2]["member"].update(score=.4),
            lambda f: f[2]["member"].update(prompt="changed"),
            lambda f: f[2]["member"].update(role="auditor"),
            lambda f: f[2]["member"].update(kind="host_effect"),
            lambda f: f[2]["member"].update(decoder={"sampling": True}),
            lambda f: f[2]["member"].update(decoder={"sampling": 0}),
            lambda f: f[3].update(effect=1),
        )
        for mutate in mutations:
            fixture = copy.deepcopy(member_fixture())
            mutate(fixture)
            with self.assertRaises(ValueError):
                _observation(*fixture, "calibration", "c", ROSTER[0])
        for score in (True, float("nan"), 1.1):
            with self.assertRaises(ValueError):
                _observation(*member_fixture(score), "calibration", "c", ROSTER[0])

    def test_versions_bind_base_adapter_prompt_and_repeat_identity(self):
        fixture = member_fixture()
        first = _observation(*fixture, "calibration", "c", ROSTER[0])
        for field in ("base_sha256", "adapter_sha256", "prompt_sha256"):
            changed = copy.deepcopy(fixture)
            changed[1]["calibration", "c", "single"]["members"][0][field] = digest("changed")
            changed[2]["member"][field] = digest("changed")
            if field == "prompt_sha256":
                changed[2]["member"]["prompt"] = "changed"
            self.assertNotEqual(_observation(*changed, "calibration", "c", ROSTER[0])["version_sha256"], first["version_sha256"])
        repeated = _observation(*fixture, "calibration", "c", ("qwen-repeat", "single", 0))
        self.assertEqual(repeated["version_sha256"], first["version_sha256"])

    def test_missing_horizon_truth_stays_out_of_error_denominators(self):
        rows = [{"score": .8, "outcome": "fail", "error": True, "accepted": False},
                {"score": .4, "outcome": "pass", "error": False, "accepted": True},
                {"score": .7, "outcome": "fail", "error": None, "accepted": False},
                {"score": None, "outcome": None, "error": None, "accepted": False}]
        result = _heldout_report(rows)
        self.assertEqual((result["scored"], result["missing_horizon_labels"], result["missing_forecasts"]), (2, 2, 1))
        self.assertEqual(result["sensitivity"], {"detected": 1, "errors": 1})
        self.assertAlmostEqual(result["raw_score_brier"], .1)
        self.assertEqual(result["original_arm_acceptance_coverage"], .25)
        self.assertIsNone(_heldout_report([{**row, "accepted": False} for row in rows])["accepted_error_missing_label_bounds"])

    def test_create_only_failure_receipt_and_input_protection(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "original"
            source.mkdir()
            with self.assertRaises(ValueError):
                run(source, source / "output")
            output = Path(temporary) / "result"
            with self.assertRaises(FileNotFoundError):
                run(source, output)
            self.assertTrue((output / "failure.json").exists())
            self.assertFalse((output / "result.json").exists())
            with self.assertRaises(FileExistsError):
                run(source, output)


if __name__ == "__main__":
    unittest.main()
