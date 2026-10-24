"""Episodic interventions and actual runner fixtures, not native task efficacy."""

from dataclasses import replace
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

from selector_head import TrainingCut
from system2_fewshot_cells import (
    METHODS,
    delta_fit,
    episodes,
    neighbor_bank,
    predict,
    run,
    summarize,
    support_cut,
)
from system2_linear_solver import design, family_split
from system2_margin_transfer import solve_hinge
from test_system2_linear_solver import fixture


def cohort():
    base, _ = fixture()
    rows = tuple(
        replace(
            r,
            features=replace(
                r.features,
                question_id=r.features.question_id + str(i),
                pool_digest=r.features.pool_digest + str(i),
                paired=r.features.paired.clone(),
                frozen_scores=r.features.frozen_scores.clone(),
            ),
        )
        for r in base
        for i in range(3)
    )
    cut = TrainingCut(
        frozenset(r.features.question_id for r in rows),
        frozenset(r.features.family for r in rows),
        frozenset(r.features.family for r in rows),
        frozenset({"outside"}),
        "episodic-fixture",
    )
    return rows, cut


class FewshotTests(unittest.TestCase):
    def setUp(self):
        self.rows, self.original = cohort()
        self.query = self.rows[0].features
        self.support = self.rows[1:3]
        self.cut = support_cut(self.support, self.query, self.original)
        self.zero = torch.zeros(2)

    def test_episode_plan_stable_nested_and_label_free(self):
        original = episodes([r.features for r in self.rows])
        changed = [
            replace(r, positive_indices=(1,)).features for r in reversed(self.rows)
        ]
        self.assertEqual(original, episodes(changed))
        for one, two in zip(original[::2], original[1::2], strict=True):
            self.assertEqual(one["support_ids"], two["support_ids"][:1])
            self.assertNotIn(one["query_id"], two["support_ids"])

    def test_too_small_or_duplicate_family_cannot_change_census(self):
        for fs in ([r.features for r in self.rows[:2]], [self.query] * 3):
            with self.assertRaises(ValueError):
                episodes(fs)

    def test_local_cut_does_not_drop_original_forbidden_roots(self):
        self.assertEqual(self.cut.forbidden_roots, self.original.forbidden_roots)
        self.assertEqual(
            self.cut.question_ids,
            frozenset(r.features.question_id for r in self.support),
        )
        self.assertEqual(self.query.roots & self.cut.allowed_roots, self.query.roots)

    def test_query_or_other_family_cannot_become_local_support(self):
        for support in ((self.rows[0],), (self.rows[3],), (self.rows[1], self.rows[1])):
            with self.assertRaises(ValueError):
                support_cut(support, self.query, self.original)

    def test_original_forbidden_root_cannot_be_relabeled_local(self):
        with self.assertRaises(ValueError):
            support_cut(
                self.support,
                self.query,
                replace(self.original, forbidden_roots=frozenset({"a"})),
            )

    def test_global_prior_split_remains_root_disjoint(self):
        train, test, cut = family_split(self.rows, self.original, self.query.family)
        self.assertFalse(
            set().union(*(r.features.roots for r in train))
            & set().union(*(r.features.roots for r in test))
        )
        self.assertTrue(self.query.roots <= cut.forbidden_roots)

    def test_delta_optimizes_shifted_prior_objective(self):
        prior = torch.tensor([0.1, 0.2])
        frozen = prior.clone()
        a, b, _ = design(self.support, self.cut)
        expected, _ = solve_hinge(a, b - a @ prior.double())
        delta, fit = delta_fit(self.support, self.cut, prior)
        torch.testing.assert_close(delta.double(), expected, atol=1e-6, rtol=1e-6)
        self.assertTrue(torch.equal(prior, frozen))
        self.assertEqual(fit["training_ids"], sorted(self.cut.question_ids))

    def test_erasure_preserves_prior_not_frozen_baseline(self):
        prior = torch.tensor([0.0, 2.0])
        delta, _ = delta_fit(self.support, self.cut, prior, erased=True)
        self.assertTrue(torch.equal(delta, self.zero))
        original = predict(self.query, prior, self.zero, "encoder", {"b"})
        erased = predict(self.query, prior, delta, "encoder", {"b"})
        self.assertEqual(original, erased)
        self.assertNotEqual(
            original["selected"],
            predict(self.query, self.zero, self.zero, "encoder", set())["selected"],
        )

    def test_no_opportunity_is_zero_update_not_null_training(self):
        support = tuple(replace(r, positive_indices=()) for r in self.support)
        delta, fit = delta_fit(support, self.cut, self.zero)
        self.assertTrue(torch.equal(delta, self.zero))
        self.assertEqual(fit["status"], "no_pair_opportunity")
        self.assertEqual(fit["direct_solves"], 0)
        self.assertEqual(len(fit["disposition"]), len(support))

    def test_admission_before_disallowed_query_label_access(self):
        class Poison:
            features = self.query

            @property
            def positive_indices(self):
                raise AssertionError("query labels read during local fitting")

        with self.assertRaises(ValueError):
            delta_fit((*self.support, Poison()), self.cut, self.zero)

    def test_prediction_is_label_free_and_stop_is_still_allowed(self):
        delta, _ = delta_fit(self.support, self.cut, self.zero)
        before = self.query.seal()
        chosen = predict(
            self.query, self.zero, delta, "encoder", self.cut.allowed_roots
        )
        self.assertEqual(chosen["selected"], 0)
        negative = replace(self.query, frozen_scores=self.query.frozen_scores - 100)
        self.assertTrue(
            predict(negative, self.zero, delta, "encoder", self.cut.allowed_roots)[
                "empty"
            ]
        )
        self.assertEqual(before, self.query.seal())

    def test_prior_query_or_support_revocation_blocks(self):
        for revoked in ({"a"}, {"b"}):
            with self.assertRaises(ValueError):
                predict(
                    self.query,
                    self.zero,
                    self.zero,
                    "encoder",
                    {"a", "b"},
                    revoked=revoked,
                )
        with self.assertRaises(ValueError):
            delta_fit(self.support, self.cut, self.zero, revoked={"a"})
        with self.assertRaises(ValueError):
            predict(self.query, self.zero, self.zero, "wrong-encoder", set())

    def test_invalid_prior_and_inference_training_rejected(self):
        for prior in (
            self.zero.double(),
            self.zero * float("nan"),
            self.zero.clone().requires_grad_(),
        ):
            with self.assertRaises(ValueError):
                delta_fit(self.support, self.cut, prior)
        with torch.inference_mode(), self.assertRaises(ValueError):
            delta_fit(self.support, self.cut, self.zero)

    def test_neighbor_uses_support_and_retains_missing_class(self):
        bank = neighbor_bank(self.support, self.cut, 2)
        result = predict(self.query, self.zero, self.zero, "encoder", {"a"}, bank=bank)
        self.assertEqual(result["selected"], 0)
        self.assertFalse(result["neighbor_fallback"])
        absent = neighbor_bank(
            tuple(replace(r, positive_indices=()) for r in self.support), self.cut, 2
        )
        result = predict(
            self.query, self.zero, self.zero, "encoder", {"a"}, bank=absent
        )
        self.assertTrue(result["neighbor_fallback"])
        self.assertEqual(result["selected"], 1)

    def test_training_one_delta_does_not_change_prior_or_other_cell(self):
        prior, other = self.zero.clone(), torch.tensor([0.5, 0.4])
        before = predict(self.query, prior, other, "encoder", {"a"})
        delta_fit(self.support, self.cut, prior)
        self.assertEqual(before, predict(self.query, prior, other, "encoder", {"a"}))

    def test_actual_runner_seals_all_predictions_and_retains_failed_conditions(self):
        datasets = {48: (self.rows, self.original)}
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("system2_fewshot_cells.audit_content", return_value=(datasets, {})),
        ):
            out = Path(tmp) / "good"
            summary = run(
                Path("fixture.zip"),
                out,
                source_commit="a" * 40,
                execution_context="fixtures",
            )
            self.assertEqual(summary["recorded"], 9 * 2 * len(METHODS))
            self.assertEqual(summary["failed"], 0)
            self.assertEqual(summary["unique_queries"], 9)
            seal = json.loads((out / "prediction-seal.json").read_text())
            self.assertEqual(
                seal["sha256"],
                hashlib.sha256((out / "predictions.jsonl").read_bytes()).hexdigest(),
            )
            predictions = [
                json.loads(x)
                for x in (out / "predictions.jsonl").read_text().splitlines()
            ]
            self.assertTrue(all("weak_hit" not in r for r in predictions))
            scored = [
                json.loads(x) for x in (out / "scored.jsonl").read_text().splitlines()
            ]
            expected = {(r["query_id"], r["budget"], r["method"]) for r in scored}
            for changed in (scored[:-1], scored + scored[:1]):
                with self.assertRaises(ValueError):
                    summarize(changed, expected)
            changed = copy.deepcopy(scored)
            changed[0]["query_digest"] = "drift"
            with self.assertRaises(ValueError):
                summarize(changed, expected)
            with patch(
                "system2_fewshot_cells.delta_fit",
                side_effect=RuntimeError("fit failed"),
            ):
                out = Path(tmp) / "failed"
                with self.assertRaises(RuntimeError):
                    run(Path("fixture.zip"), out, source_commit="a" * 40)
                report = json.loads((out / "summary.json").read_text())
                self.assertEqual(report["recorded"], report["planned"])
                self.assertEqual(report["failed"], 9 * 2 * 3)
                self.assertEqual(
                    report["candidate_disposition"], "stop_no_controlled_fewshot_gain"
                )
                self.assertFalse(report["production_accepted"])


if __name__ == "__main__":
    unittest.main()
