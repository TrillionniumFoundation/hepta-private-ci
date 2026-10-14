"""Real cached native data and isolated contract tests; no Reader claims."""

from dataclasses import replace
import copy
import os
from pathlib import Path
import unittest

import torch

from selector_head import Features, Supervision, TrainingCut
from system2_ablation import model_digest
from system2_content_replay import audit_content, restore_rows, ARCHIVE
from system2_linear_solver import (
    aggregate,
    design,
    family_split,
    fit_head,
    inspect_head,
    RIDGE,
    RATE,
    STEPS,
)
from system2_native_receipt import strict_json, verified_archive


def fixture():
    rows = []
    for family, shift in (("a", 0.0), ("b", 0.1), ("c", -0.1)):
        # Large shared component makes score origin separable from pair rank.
        paired = torch.tensor([[10.0, 1.0 + shift], [10.0, -1.0 + shift]])
        f = Features(
            "q-" + family,
            family,
            "encoder",
            "pool-" + family,
            ("hit-" + family, "miss-" + family),
            frozenset({family}),
            paired,
            torch.tensor([-1.0, 2.0]),
        )
        rows.append(Supervision(f, (0,)))
    cut = TrainingCut(
        frozenset(r.features.question_id for r in rows),
        frozenset(("a", "b", "c")),
        frozenset(("a", "b", "c")),
        frozenset({"outside"}),
        "admitted",
    )
    return tuple(rows), cut


class SolverTests(unittest.TestCase):
    def test_closed_form_normal_equation_and_better_objective(self):
        rows, cut = fixture()
        a, ra = fit_head(rows, cut, "ridge")
        _, rb = fit_head(rows, cut, "frozen")
        self.assertLess(ra["normal_equation_residual"], 1e-8)
        self.assertLess(ra["objective"], rb["objective"])
        self.assertEqual(ra["adaptable_parameters"], 2)
        self.assertTrue(torch.equal(a.null.weight, torch.zeros_like(a.null.weight)))
        self.assertEqual(float(a.readout.bias.detach()), 0.0)

    def test_dual_matches_primal_solution(self):
        rows, cut = fixture()
        a, b, _ = design(rows, cut)
        expected = torch.linalg.solve(
            a.T @ a + RIDGE * torch.eye(a.shape[1], dtype=a.dtype), a.T @ b
        )
        h, _ = fit_head(rows, cut, "ridge")
        torch.testing.assert_close(
            h.readout.weight.detach().flatten().double(), expected, atol=1e-6, rtol=1e-6
        )

    def test_explicit_sgd_matches_optimizer(self):
        rows, cut = fixture()
        a, b, _ = design(rows, cut)
        w = torch.nn.Parameter(torch.zeros(a.shape[1], dtype=a.dtype))
        optimizer = torch.optim.SGD([w], lr=RATE)
        for _ in range(STEPS):
            optimizer.zero_grad()
            loss = (a @ w - b).square().sum() + RIDGE * w.square().sum()
            loss.backward()
            optimizer.step()
        h, _ = fit_head(rows, cut, "sgd")
        torch.testing.assert_close(
            h.readout.weight.detach().flatten().double(),
            w.detach(),
            atol=1e-6,
            rtol=1e-6,
        )

    def test_erasure_preserves_frozen_scores_without_learning(self):
        rows, cut = fixture()
        h, receipt = fit_head(rows, cut, "ridge_erased")
        self.assertEqual(receipt["before"], receipt["after"])
        baseline, _ = fit_head(rows, cut, "frozen")
        self.assertEqual(inspect_head(h, rows), inspect_head(baseline, rows))

    def test_zero_mean_residual_keeps_rank_and_does_not_force_answer(self):
        rows, cut = fixture()
        h, _ = fit_head(rows, cut, "ridge")
        actual = inspect_head(h, rows)
        self.assertTrue(all(r["pair_accuracy"] == 1 for r in actual))
        negative = tuple(
            replace(
                r,
                features=replace(
                    r.features, frozen_scores=r.features.frozen_scores - 100
                ),
            )
            for r in rows
        )
        self.assertTrue(all(r["centered"]["empty"] for r in inspect_head(h, negative)))

    def test_perfect_ranking_can_still_have_all_null_raw_decisions(self):
        rows, cut = fixture()
        head, _ = fit_head(rows, cut, "frozen")
        with torch.no_grad():
            head.readout.weight.copy_(torch.tensor([[-1.0, 2.0]]))
        records = inspect_head(head, rows)
        self.assertTrue(all(r["pair_accuracy"] == 1 for r in records))
        self.assertTrue(all(r["raw"]["empty"] for r in records))
        self.assertTrue(all(r["centered"]["hit"] for r in records))

    def test_unknown_method_and_empty_training_are_rejected(self):
        rows, cut = fixture()
        with self.assertRaises(ValueError):
            fit_head(rows, cut, "unregistered")
        with self.assertRaises(ValueError):
            fit_head((), cut, "ridge")

    def test_origin_is_independent_of_source_labels(self):
        rows, cut = fixture()
        h, _ = fit_head(rows, cut, "ridge")
        changed = tuple(replace(r, positive_indices=(1,)) for r in rows)
        a, b = inspect_head(h, rows), inspect_head(h, changed)
        for x, y in zip(a, b):
            for mode in ("raw", "centered"):
                self.assertEqual(x[mode]["selected"], y[mode]["selected"])
                self.assertEqual(x[mode]["best_score"], y[mode]["best_score"])
            self.assertEqual(x["residual_mean"], y["residual_mean"])

    def test_inspection_does_not_mutate_weights_or_features(self):
        rows, cut = fixture()
        h, _ = fit_head(rows, cut, "ridge")
        stamps = [r.features.seal() for r in rows]
        before = model_digest(h)
        inspect_head(h, rows)
        self.assertEqual(before, model_digest(h))
        self.assertEqual(stamps, [r.features.seal() for r in rows])

    def test_family_split_blocks_holdout_before_fit(self):
        rows, cut = fixture()
        train, test, inner = family_split(rows, cut, "a")
        self.assertEqual(len(test), 1)
        with self.assertRaises(ValueError):
            fit_head((*train, *test), inner, "ridge")

    def test_heldout_labels_cannot_change_trained_weights(self):
        rows, cut = fixture()
        train, _, inner = family_split(rows, cut, "a")
        h, _ = fit_head(train, inner, "ridge")
        changed = tuple(
            replace(r, positive_indices=(1,)) if r.features.family == "a" else r
            for r in rows
        )
        train2, _, inner2 = family_split(changed, cut, "a")
        h2, _ = fit_head(train2, inner2, "ridge")
        self.assertEqual(model_digest(h), model_digest(h2))

    def test_cross_family_shared_root_rejected(self):
        rows, cut = fixture()
        drift = (
            *rows[:1],
            replace(
                rows[1], features=replace(rows[1].features, roots=frozenset({"a"}))
            ),
            rows[2],
        )
        with self.assertRaises(ValueError):
            family_split(drift, cut, "a")

    def test_no_opportunity_is_not_null_supervision(self):
        rows, cut = fixture()
        with self.assertRaises(ValueError):
            fit_head(tuple(replace(r, positive_indices=()) for r in rows), cut, "ridge")

    def test_invalid_cut_nonfinite_and_revoked_inputs_fail(self):
        rows, cut = fixture()
        with self.assertRaises(ValueError):
            fit_head(rows, replace(cut, question_ids=frozenset()), "ridge")
        with self.assertRaises(ValueError):
            fit_head(rows, cut, "ridge", revoked=frozenset({"a"}))
        broken = copy.deepcopy(rows)
        broken[1].features.paired[0, 0] = float("nan")
        with self.assertRaises(ValueError):
            fit_head(broken, cut, "ridge")

    def test_revoked_fitted_lineage_rejects_other_query(self):
        rows, cut = fixture()
        h, _ = fit_head(rows[:2], cut, "ridge")
        with self.assertRaises(ValueError):
            inspect_head(h, rows[2:], revoked=frozenset({"a"}))

    def test_census_retains_no_opportunity_and_rejects_duplicates(self):
        rows, cut = fixture()
        h, _ = fit_head(rows, cut, "frozen")
        changed = (replace(rows[0], positive_indices=()), *rows[1:])
        records = inspect_head(h, changed)
        summary = aggregate(records)
        self.assertEqual(summary["questions"], 3)
        self.assertEqual(summary["no_opportunity_questions"], 1)
        with self.assertRaises(ValueError):
            aggregate(records + records[:1])

    def test_singular_design_is_regularized(self):
        rows, cut = fixture()
        same = tuple(
            replace(
                r,
                features=replace(r.features, paired=torch.ones_like(r.features.paired)),
            )
            for r in rows
        )
        h, receipt = fit_head(same, cut, "ridge")
        self.assertEqual(receipt["normal_equation_residual"], 0)
        self.assertTrue(
            torch.equal(h.readout.weight, torch.zeros_like(h.readout.weight))
        )


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        path = os.environ.get("HEPTA_SYSTEM2_CONTENT_ARCHIVE")
        if not path:
            self.skipTest("pinned real content archive not supplied")
        self.path = Path(path)

    def test_real_weights_features_and_report_replay(self):
        data, audit = audit_content(self.path)
        self.assertEqual(list(data), [16, 32, 48])
        self.assertEqual(audit["manifest_entries"], 49)
        self.assertTrue(audit["replay_is_not_new_independent_evidence"])
        self.assertEqual(audit["new_reader_calls"], 0)

    def test_real_label_and_tensor_mutation_rejected(self):
        files = verified_archive(self.path, ARCHIVE)
        key = "native/content-probe-48/train-inputs.json"
        meta = strict_json(files[key])
        meta["rows"][0]["feature_digest"] = "0" * 64
        import json

        files[key] = json.dumps(meta).encode()
        with self.assertRaises(ValueError):
            restore_rows(files, 48)

    def test_real_extra_tensor_prefix_and_revocation_rejected(self):
        files = verified_archive(self.path, ARCHIVE)
        meta = strict_json(files["native/content-probe-48/train-inputs.json"])
        with self.assertRaises(ValueError):
            restore_rows(files, 48, revoked=frozenset(meta["rows"][0]["roots"]))
        meta["rows"][1]["tensor_prefix"] = meta["rows"][0]["tensor_prefix"]
        import json

        files["native/content-probe-48/train-inputs.json"] = json.dumps(meta).encode()
        with self.assertRaises(ValueError):
            restore_rows(files, 48)


if __name__ == "__main__":
    unittest.main()
