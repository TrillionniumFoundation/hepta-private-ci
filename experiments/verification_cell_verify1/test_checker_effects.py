"""Paired evidence and downstream VOI tests for learned checker channels."""

from dataclasses import FrozenInstanceError, replace
import unittest

from .checker_effects import CheckerSpec, EffectScope, PairedPanel, fit_checker_effects
from .check_voi import DecisionProblem, evaluate_check
from .contracts import digest


class CheckerEffectsTests(unittest.TestCase):
    def setUp(self):
        self.scope = EffectScope(domain="documents", event="terminal_error", horizon_start=0,
                                 horizon_end=3, continuation_policy_sha256=digest("fixed-policy"),
                                 context_sha256=digest({"tick": 0, "ack": []}))
        self.checkers = tuple(CheckerSpec(name, digest(name), 0.05) for name in ("a", "b"))
        self.panels = []
        for label, pass_count in ((False, 6), (True, 2)):
            for index in range(8):
                outcome = "pass" if index < pass_count else "fail"
                self.add(label, (outcome, outcome))

    def add(self, label, outcomes):
        panel_id = f"panel-{len(self.panels):03}"
        self.panels.append(PairedPanel(
            panel_id=panel_id, source_group="train", snapshot_sha256=digest([panel_id, "snapshot"]),
            scope=self.scope, checker_ids=tuple(c.checker_id for c in self.checkers),
            checker_versions=tuple(c.version_sha256 for c in self.checkers), outcomes=outcomes,
            error=label, label_evidence_sha256=digest([panel_id, "label"]) if label is not None else None,
            checker_evidence_sha256=tuple(digest([panel_id, c.checker_id, "evidence"]) for c in self.checkers),
            missing_label_reason="evaluator_unavailable" if label is None else None))

    def fit(self, panels=None, **kwargs):
        return fit_checker_effects(
            self.panels if panels is None else panels, scope=self.scope,
            checkers=self.checkers, training_groups=("train",),
            heldout_groups=("confirmation",), **kwargs)

    def test_correlated_repeat_has_no_incremental_value(self):
        model = self.fit()
        initial = model.condition(0.5, scope=self.scope)
        self.assertEqual(initial.channels[0].likelihoods, ((0.75, 0.25, 0), (0.25, 0.75, 0)))
        conditioned = model.condition(0.5, {"a": "pass"}, scope=self.scope)
        self.assertEqual((conditioned.status, conditioned.posterior_error,
                          conditioned.class_counts, conditioned.history_counts),
                         ("supported", 0.25, (8, 8), (6, 2)))
        self.assertEqual(conditioned.channels[1].likelihoods, ((1, 0, 0), (1, 0, 0)))
        problem = DecisionProblem(("correct", "error"), (0.75, 0.25),
                                  ("accept", "reject"), ((0, 4), (1, 1)))
        result = evaluate_check(problem, conditioned.channels[1])
        self.assertEqual((result.gross_value, result.net_value), (0, -0.05))

    def test_unknown_is_observation_missing_label_is_not_clean(self):
        for label in (False, True):
            for _ in range(2):
                self.add(label, ("unknown", "unknown"))
        self.add(None, ("pass", "fail"))
        model = self.fit()
        result = model.condition(0.4, {"a": "unknown"}, scope=self.scope)
        self.assertAlmostEqual(result.posterior_error, 0.4)
        self.assertEqual(result.history_counts, (2, 2))
        self.assertEqual(result.channels[1].likelihoods, ((0, 0, 1), (0, 0, 1)))
        report = model.diagnostics()
        self.assertEqual(report["missing_labels_excluded"], 1)
        self.assertEqual(report["observed_group_counts"], {"train": {"known_labels": 20, "missing_labels": 1}})
        self.assertEqual(report["checkers"][0]["sensitivity"],
                         {"numerator": 6, "denominator": 10, "value": 0.6})
        self.assertEqual(report["checkers"][0]["false_positive_rate"]["numerator"], 2)
        self.assertEqual(report["paired_errors"][0]["common_miss_including_unknown"]["numerator"], 4)
        self.assertEqual(report["paired_errors"][0]["common_false_pass"]["numerator"], 2)
        self.assertFalse(report["full_physical_cost_complete"])

    def test_unseen_history_and_small_samples_refuse(self):
        result = self.fit().condition(0.5, {"a": "pass", "b": "fail"}, scope=self.scope)
        self.assertEqual((result.status, result.reason, result.channels, result.posterior_error),
                         ("unsupported", "insufficient_history_support", (), None))
        result = self.fit(self.panels[:8]).condition(0.5, scope=self.scope)
        self.assertEqual((result.reason, result.history_counts), ("insufficient_class_support", (8, 0)))
        result = self.fit(min_class_count=3).condition(0.5, {"a": "pass"}, scope=self.scope)
        self.assertEqual(result.reason, "insufficient_history_support")

    def test_scope_drift_refuses_even_with_supported_counts(self):
        model = self.fit()
        for change in ({"domain": "images"}, {"event": "prefix_error"},
                       {"horizon_end": 4}, {"continuation_policy_sha256": digest("new")},
                       {"context_sha256": digest("other public context")}):
            result = model.condition(0.5, scope=replace(self.scope, **change))
            self.assertEqual((result.reason, result.channels), ("scope_mismatch", ()))

    def test_split_roster_and_physical_panel_identity_are_bound(self):
        first = self.panels[0]
        bad = (replace(first, source_group="confirmation"),
               replace(first, checker_ids=("b", "a")),
               replace(first, checker_versions=(digest("changed"), self.checkers[1].version_sha256)))
        for panel in bad:
            with self.assertRaises(ValueError):
                self.fit([panel, *self.panels[1:]])
        with self.assertRaisesRegex(ValueError, "duplicate candidate snapshot"):
            self.fit(self.panels + [replace(first, panel_id="new-id")])
        with self.assertRaises(ValueError):
            fit_checker_effects(self.panels, scope=self.scope, checkers=self.checkers,
                                training_groups=("train",), heldout_groups=("train",))
        with self.assertRaisesRegex(ValueError, "match observed groups"):
            fit_checker_effects(self.panels, scope=self.scope, checkers=self.checkers,
                                training_groups=("train", "unobserved"), heldout_groups=("confirmation",))

    def test_digests_are_permutation_invariant_and_bind_cost_and_evidence(self):
        model = self.fit()
        self.assertEqual(model, self.fit(list(reversed(self.panels))))
        changed = self.panels.copy()
        changed[0] = replace(changed[0], label_evidence_sha256=digest("other evidence"))
        self.assertNotEqual(model.data_sha256, self.fit(changed).data_sha256)
        self.checkers = (replace(self.checkers[0], cost=0.2), self.checkers[1])
        other = self.fit()
        self.assertEqual(model.data_sha256, other.data_sha256)
        self.assertNotEqual(model.model_sha256, other.model_sha256)
        with self.assertRaises(FrozenInstanceError):
            model.missing_labels = 100

    def test_invalid_labels_channels_and_history_rejected(self):
        for change in ({"error": 1}, {"outcomes": ("pass", "not_run")},
                       {"label_evidence_sha256": None}, {"checker_evidence_sha256": ("invalid", digest("b"))}):
            with self.assertRaises(ValueError):
                replace(self.panels[0], **change)
        for prior in (True, float("nan"), -0.1, 10**1000):
            with self.assertRaises(ValueError):
                self.fit().condition(prior, scope=self.scope)
        for history in ({"unknown-checker": "pass"}, {"a": "not_run"}, [("a", "pass")]):
            with self.assertRaises(ValueError):
                self.fit().condition(0.5, history, scope=self.scope)


if __name__ == "__main__":
    unittest.main()
