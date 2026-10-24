"""Exact convex checks and real runner fixtures, not independent task evidence."""

import copy
from dataclasses import replace
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

from system2_ablation import model_digest
from system2_linear_solver import design, family_split
from system2_margin_transfer import (
    METHODS,
    fit_margin,
    observe,
    paired_changes,
    run,
    solve_hinge,
    summarize,
)
from test_system2_linear_solver import fixture


class MarginTests(unittest.TestCase):
    def test_already_sufficient_margins_are_not_forced_down(self):
        a, b = (
            torch.tensor([[1.0]], dtype=torch.float64),
            torch.tensor([-2.0], dtype=torch.float64),
        )
        w, receipt = solve_hinge(a, b)
        self.assertTrue(torch.equal(w, torch.zeros_like(w)))
        self.assertEqual(receipt["direct_solves"], 0)
        self.assertEqual(receipt["objective"], 0.0)
        ridge = a.T @ torch.linalg.solve(
            a @ a.T + 0.01 * torch.eye(1, dtype=a.dtype), b
        )
        self.assertLess(float(ridge[0]), -1.0)

    def test_initially_sufficient_pair_can_become_active(self):
        a = torch.tensor([[1.0], [-1.0]], dtype=torch.float64)
        b = torch.tensor([2.0, -1.0], dtype=torch.float64)
        w, _ = solve_hinge(a, b)
        self.assertAlmostEqual(float(w[0]), 3 / 2.01)

    def test_dual_matches_exhaustive_active_sets(self):
        g = torch.Generator().manual_seed(907)
        for _ in range(8):
            a = torch.randn(5, 3, dtype=torch.float64, generator=g)
            b = torch.randn(5, dtype=torch.float64, generator=g)
            w, receipt = solve_hinge(a, b)
            best = float("inf")
            for bits in itertools.product((False, True), repeat=len(b)):
                active = torch.tensor(bits)
                aa, bb = a[active], b[active]
                ww = torch.linalg.solve(
                    aa.T @ aa + 0.01 * torch.eye(3, dtype=a.dtype), aa.T @ bb
                )
                value = float(
                    torch.relu(b - a @ ww).square().sum() + 0.01 * ww.square().sum()
                )
                best = min(best, value)
            self.assertAlmostEqual(receipt["objective"], best, places=8)
            self.assertLess(receipt["stationarity_residual"], 1e-8)
            self.assertTrue(torch.isfinite(w).all())

    def test_gradient_agrees_with_autograd(self):
        rows, cut = fixture()
        a, b, _ = design(rows, cut)
        w, _ = solve_hinge(a, b)
        w.requires_grad_(True)
        (torch.relu(b - a @ w).square().sum() + 0.01 * w.square().sum()).backward()
        self.assertLess(float(w.grad.norm()), 1e-8)

    def test_zero_and_singular_designs_regularized(self):
        for a in (
            torch.zeros(3, 2, dtype=torch.float64),
            torch.ones(3, 2, dtype=torch.float64),
        ):
            _, receipt = solve_hinge(a, torch.ones(3, dtype=a.dtype))
            self.assertLess(receipt["dual_kkt_residual"], 1e-8)

    def test_budget_failure_retains_solve_count(self):
        with self.assertRaisesRegex(RuntimeError, "after 1 solves"):
            solve_hinge(
                torch.eye(2, dtype=torch.float64),
                torch.ones(2, dtype=torch.float64),
                max_solves=1,
            )

    def test_invalid_profile_or_matrix_rejected(self):
        a, b = torch.eye(2, dtype=torch.float64), torch.ones(2, dtype=torch.float64)
        for kwargs in (
            {"ridge": 0},
            {"ridge": True},
            {"ridge": float("nan")},
            {"max_solves": True},
        ):
            with self.assertRaises(ValueError):
                solve_hinge(a, b, **kwargs)
        for aa, bb in (
            (a.float(), b),
            (a, b[:1]),
            (a * float("nan"), b),
            (a.requires_grad_(), b),
        ):
            with self.assertRaises(ValueError):
                solve_hinge(aa, bb)

    def test_only_readout_weights_change(self):
        rows, cut = fixture()
        baseline, _ = fit_margin(rows, cut, "frozen")
        head, receipt = fit_margin(rows, cut, "squared_hinge")
        changed = [
            k
            for k, v in head.state_dict().items()
            if not torch.equal(v, baseline.state_dict()[k])
        ]
        self.assertEqual(changed, ["readout.weight"])
        self.assertEqual(receipt["trainable_parameters"], 2)

    def test_erased_residual_is_frozen_and_stop_unchanged(self):
        rows, cut = fixture()
        a, _ = fit_margin(rows, cut, "frozen")
        b, _ = fit_margin(rows, cut, "hinge_erased")
        self.assertEqual(model_digest(a), model_digest(b))
        self.assertEqual(observe(a, rows), observe(b, rows))

    def test_stop_is_independent_of_fitted_score_origin(self):
        rows, cut = fixture()
        head, _ = fit_margin(rows, cut, "squared_hinge")
        before = observe(head, rows)
        with torch.no_grad():
            head.readout.bias.fill_(-100)
        after = observe(head, rows)
        self.assertEqual(
            [r["frozen_stop"] for r in before], [r["frozen_stop"] for r in after]
        )
        self.assertTrue(all(r["raw"]["empty"] for r in after))

    def test_fixed_stop_can_still_abstain(self):
        rows, cut = fixture()
        head, _ = fit_margin(rows, cut, "squared_hinge")
        negative = tuple(
            replace(
                r,
                features=replace(
                    r.features, frozen_scores=r.features.frozen_scores - 100
                ),
            )
            for r in rows
        )
        self.assertTrue(all(r["frozen_stop"]["empty"] for r in observe(head, negative)))

    def test_labels_do_not_choose_stop_or_fit_on_heldout(self):
        rows, cut = fixture()
        train, test, inner = family_split(rows, cut, "a")
        head, _ = fit_margin(train, inner, "squared_hinge")
        changed = tuple(replace(r, positive_indices=(1,)) for r in test)
        a, b = observe(head, test), observe(head, changed)
        self.assertEqual(
            a[0]["frozen_stop"]["selected"], b[0]["frozen_stop"]["selected"]
        )
        with self.assertRaises(ValueError):
            fit_margin((*train, *changed), inner, "squared_hinge")

    def test_admission_and_revocation_before_changes(self):
        rows, cut = fixture()
        with self.assertRaises(ValueError):
            fit_margin(rows, replace(cut, question_ids=frozenset()), "squared_hinge")
        head, _ = fit_margin(rows[:2], cut, "squared_hinge")
        with self.assertRaises(ValueError):
            observe(head, rows[2:], revoked=frozenset({"a"}))

    def test_all_no_opportunity_retained_not_null_training(self):
        rows, cut = fixture()
        head, _ = fit_margin(rows, cut, "frozen")
        unknown = tuple(replace(r, positive_indices=()) for r in rows)
        summary = summarize(observe(head, unknown))
        self.assertEqual(summary["questions"], 3)
        self.assertEqual(summary["no_opportunity_questions"], 3)
        with self.assertRaises(ValueError):
            fit_margin(unknown, cut, "squared_hinge")

    def test_paired_census_and_source_drift_rejected(self):
        rows, cut = fixture()
        head, _ = fit_margin(rows, cut, "frozen")
        data = observe(head, rows)
        for changed in (data[:-1], data + data[:1]):
            with self.assertRaises(ValueError):
                paired_changes(data, changed, "frozen_stop")
        other = copy.deepcopy(data)
        other[0]["feature_digest"] = "changed"
        with self.assertRaises(ValueError):
            paired_changes(data, other, "frozen_stop")

    def test_real_runner_writes_all_conditions_and_failed_rows(self):
        rows, cut = fixture()
        # Tiny fixture ports exercise the actual runner, not native model efficacy.
        datasets = {16: (rows, cut), 32: (rows, cut), 48: (rows, cut)}
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch(
                "system2_margin_transfer.audit_content",
                return_value=(datasets, {"fixture": True}),
            ),
        ):
            output = Path(tmp) / "success"
            result = run(
                Path("fixture.zip"),
                output,
                source_commit="a" * 40,
                execution_context="hermetic-fixtures",
            )
            self.assertEqual(result["recorded"], 6 * len(METHODS))
            self.assertEqual(result["failed"], 0)
            with patch(
                "system2_margin_transfer.fit_margin",
                side_effect=RuntimeError("fit failure"),
            ):
                output = Path(tmp) / "failed"
                with self.assertRaises(RuntimeError):
                    run(
                        Path("fixture.zip"),
                        output,
                        source_commit="a" * 40,
                        execution_context="hermetic-fixtures",
                    )
                report = json.loads((output / "summary.json").read_text())
                self.assertEqual(report["failed"], report["planned"])
                self.assertEqual(report["recorded"], report["planned"])
                self.assertFalse(report["production_accepted"])


if __name__ == "__main__":
    unittest.main()
