"""Exhaustive-support protocol tests; fixture readers/independent data not invented."""

from dataclasses import replace
import copy
import hashlib
import json
from math import comb
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


from system2_support_sensitivity import (
    METHODS,
    aggregate,
    enumerate_episodes,
    run,
    swapped_support,
)
from system2_fewshot_cells import support_cut
from test_system2_fewshot_cells import cohort


def fake_records(plan, hit=lambda e, m: False):
    return [
        e
        | dict(
            method=m, status="succeeded", weak_hit=hit(e, m), prediction={"selected": 0}
        )
        for e in plan
        for m in METHODS
    ]


class SupportSensitivityTests(unittest.TestCase):
    def setUp(self):
        self.rows, self.cut = cohort()
        self.plan = enumerate_episodes([r.features for r in self.rows])

    def test_all_subsets_are_counted_and_support_sets_reused(self):
        for k in (1, 2):
            eps = [e for e in self.plan if e["budget"] == k]
            self.assertEqual(len(eps), 3 * 3 * comb(2, k))
            self.assertEqual(len({e["snapshot_id"] for e in eps}), 3 * comb(3, k))
            self.assertTrue(all(e["query_id"] not in e["support_ids"] for e in eps))
            self.assertEqual(len([e for e in eps if e["anchor"]]), 9)

    def test_plan_is_permutation_invariant_and_not_chosen_by_labels(self):
        altered = [
            replace(r, positive_indices=()).features for r in reversed(self.rows)
        ]
        self.assertEqual(self.plan, enumerate_episodes(altered))
        changed = [
            replace(r.features, frozen_scores=r.features.frozen_scores + 10)
            for r in self.rows
        ]
        keys = lambda plan: [
            (e["query_id"], e["support_ids"], e["anchor"]) for e in plan
        ]
        self.assertEqual(keys(self.plan), keys(enumerate_episodes(changed)))

    def test_undersized_duplicate_or_mixed_encoder_reject(self):
        f = [r.features for r in self.rows]
        for features in (
            f[:2],
            f + f[:1],
            f[:-1] + [replace(f[-1], encoder_identity="other")],
        ):
            with self.assertRaises(ValueError):
                enumerate_episodes(features)

    def test_exhaustive_bound_does_not_silently_sample(self):
        features = [
            replace(self.rows[0].features, question_id=f"q{i}") for i in range(32)
        ]
        with self.assertRaisesRegex(ValueError, "resource bound"):
            enumerate_episodes(features)

    def test_label_swap_preserves_shape_and_no_opportunities(self):
        support = self.rows[1:3]
        cut = support_cut(support, self.rows[0].features, self.cut)
        swapped = swapped_support(support, cut, 2)
        self.assertEqual(
            [r.features.seal() for r in support], [r.features.seal() for r in swapped]
        )
        self.assertTrue(
            all(
                set(a.positive_indices).isdisjoint(b.positive_indices)
                for a, b in zip(support, swapped)
            )
        )
        empty = tuple(replace(r, positive_indices=()) for r in support)
        self.assertEqual(swapped_support(empty, cut, 2), empty)

    def test_swap_validates_admission_first(self):
        support = self.rows[1:3]
        cut = support_cut(support, self.rows[0].features, self.cut)
        with self.assertRaises(ValueError):
            swapped_support(support, replace(cut, question_ids=frozenset()), 2)

    def test_aggregation_does_not_weight_large_families_by_episode_count(self):
        base = self.rows[0].features
        features = [
            replace(base, question_id=f"{fam}{i}", family=fam)
            for fam, n in (("large", 4), ("small", 3))
            for i in range(n)
        ]
        plan = enumerate_episodes(features)
        summary = aggregate(
            fake_records(plan, lambda e, m: e["family"] == "large"), plan
        )
        row = summary["by_budget"][2]["frozen"]
        self.assertEqual(row["query_macro_bounds"], [4 / 7, 4 / 7])
        self.assertEqual(row["family_macro_bounds"], [0.5, 0.5])
        self.assertEqual(row["all_subset_hits"] / row["subset_predictions"], 0.8)

    def test_missing_duplicate_and_relabelled_rows_reject(self):
        records = fake_records(self.plan)
        tampered = copy.deepcopy(records)
        tampered[0]["support_ids"] = ["different"]
        for data in (records[:-1], records + records[:1], tampered):
            with self.assertRaises(ValueError):
                aggregate(data, self.plan)

    def test_invalid_success_score_rejects(self):
        for value in (1, 0.0, float("nan"), None):
            records = fake_records(self.plan)
            records[0]["weak_hit"] = value
            with self.assertRaises(ValueError):
                aggregate(records, self.plan)

    def test_all_failed_remains_full_uncertainty(self):
        records = fake_records(self.plan)
        for r in records:
            r["status"] = "failed"
            r.pop("weak_hit")
        result = aggregate(records, self.plan)
        self.assertEqual(result["recorded"], len(records))
        self.assertEqual(
            result["by_budget"][2]["differentiated"]["query_macro_bounds"], [0.0, 1.0]
        )
        self.assertEqual(
            result["differentiated_contrasts"][2]["frozen"][
                "query_macro_effect_bounds"
            ],
            [-1.0, 1.0],
        )
        self.assertFalse(result["support_robust_gain"])

    def test_a_lucky_anchor_cannot_hide_another_support_loss(self):
        base = self.rows[0].features
        plan = enumerate_episodes(
            [replace(base, question_id=f"q{i}") for i in range(4)]
        )
        records = fake_records(
            plan, lambda e, m: e["anchor"] if m == "differentiated" else not e["anchor"]
        )
        result = aggregate(records, plan)
        self.assertEqual(result["by_budget"][2]["differentiated"]["anchor_hits"], 4)
        self.assertGreater(
            result["differentiated_contrasts"][2]["frozen"]["subset_losses"], 0
        )
        self.assertFalse(result["support_robust_gain"])

    def test_swapped_label_gain_is_not_correct_supervision_gain(self):
        records = fake_records(
            self.plan, lambda e, m: m in ("differentiated", "swapped_labels")
        )
        self.assertFalse(aggregate(records, self.plan)["support_robust_gain"])

    def test_actual_runner_cache_seal_erasure_and_own_query_label_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            outputs = []
            for version in (
                self.rows,
                (replace(self.rows[0], positive_indices=(1,)),) + self.rows[1:],
            ):
                path = Path(tmp) / str(len(outputs))
                with patch(
                    "system2_support_sensitivity.audit_content",
                    return_value=({48: (version, self.cut)}, {"fixture": True}),
                ):
                    result = run(
                        Path("fixture.zip"),
                        path,
                        source_commit="a" * 40,
                        execution_context="fixture",
                    )
                raw = path.joinpath("predictions.jsonl").read_bytes()
                predictions = [json.loads(l) for l in raw.splitlines()]
                self.assertTrue(all("weak_hit" not in r for r in predictions))
                self.assertEqual(
                    hashlib.sha256(raw).hexdigest(), result["prediction_sha256"]
                )
                self.assertEqual(result["state_conditions"], 18 * len(METHODS))
                states = [
                    json.loads(l)
                    for l in path.joinpath("states.jsonl").read_text().splitlines()
                ]
                self.assertEqual(len(states), result["state_conditions"])
                self.assertEqual(
                    len({(r["snapshot_id"], r["method"]) for r in states}), len(states)
                )
                for r in states:
                    self.assertEqual(
                        hashlib.sha256(
                            path.joinpath(r["state_file"]).read_bytes()
                        ).hexdigest(),
                        r["state_sha256"],
                    )
                lookup = {(r["episode_id"], r["method"]): r for r in predictions}
                for e in self.plan:
                    self.assertEqual(
                        lookup[(e["episode_id"], "shared")]["prediction"]["selected"],
                        lookup[(e["episode_id"], "erased_update")]["prediction"][
                            "selected"
                        ],
                    )
                outputs.append(
                    [
                        r["prediction"]
                        for r in predictions
                        if r["query_id"] == self.rows[0].features.question_id
                    ]
                )
            self.assertEqual(outputs[0], outputs[1])

    def test_snapshot_failures_are_kept_for_every_dependent_query(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch(
                "system2_support_sensitivity.audit_content",
                return_value=({48: (self.rows, self.cut)}, {}),
            ),
            patch(
                "system2_support_sensitivity.delta_fit",
                side_effect=RuntimeError("fit failed"),
            ),
        ):
            out = Path(tmp) / "out"
            with self.assertRaises(RuntimeError):
                run(
                    Path("fixture.zip"),
                    out,
                    source_commit="a" * 40,
                    execution_context="fixture",
                )
            result = json.loads((out / "summary.json").read_text())
            self.assertEqual(result["recorded"], len(self.plan) * len(METHODS))
            self.assertEqual(result["failed"], len(self.plan) * 4)
            self.assertFalse(result["support_robust_gain"])

    def test_inference_state_mutation_cannot_reach_scoring(self):
        from system2_fewshot_cells import predict

        def corrupt(feature, prior, delta, *args, **kwargs):
            delta[0] += 0.01
            return predict(feature, prior, delta, *args, **kwargs)

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch(
                "system2_support_sensitivity.audit_content",
                return_value=({48: (self.rows, self.cut)}, {}),
            ),
            patch("system2_support_sensitivity.predict", side_effect=corrupt),
        ):
            out = Path(tmp) / "out"
            with self.assertRaisesRegex(ValueError, "mutated a frozen"):
                run(
                    Path("fixture.zip"),
                    out,
                    source_commit="a" * 40,
                    execution_context="fixture",
                )
            self.assertTrue((out / "predictions.jsonl").is_file())
            self.assertFalse((out / "scored.jsonl").exists())

    def test_revocation_precedes_fitting(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch(
                "system2_support_sensitivity.audit_content",
                return_value=({48: (self.rows, self.cut)}, {}),
            ),
            patch("system2_support_sensitivity.fit_margin") as fit,
        ):
            with self.assertRaises(ValueError):
                run(
                    Path("fixture.zip"),
                    Path(tmp) / "out",
                    source_commit="a" * 40,
                    revoked=frozenset({"a"}),
                )
            fit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
