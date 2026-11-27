"""Synthetic contract checks only; no independent task or efficacy evidence."""
from dataclasses import replace
import unittest

from source_contrast import (
    ARMS, ContractError, Information, Observation, PlannedBlock, SourcePlan,
    TrialRow, digest, learning_progress, source_contrast,
)


def fixture(seeds=1):
    blocks = tuple(PlannedBlock(f"e{s}", s, "f", digest("task"), digest("source"),
                               ability_digest=digest("ability"),
                               evaluator_digest=digest("evaluator"),
                               opportunity=(16, 2, 4, 100))
                   for s in range(seeds))
    plan = SourcePlan(blocks, ("early", "late"), (1, 0), "monotonic", "boot", 100)
    info = tuple(Information(digest(i), digest("origin"), 20 + i, bytes([i]))
                 for i in range(2))
    rows = []
    for b in blocks:
        for arm in ARMS:
            trial = TrialRow(b.episode_id, b.seed, b.family, arm, b.workload_digest,
                             digest("ability"), digest("evaluator"), 16, 2, 4, 100,
                             1.0 if arm == "routed" else 0.5, 0.1, 0.8, False,
                             digest([b.episode_id, b.seed, arm]))
            route = (0, 1) if arm == "routed" else (1, 0) if arm == "shuffled" else ()
            rows.append(Observation(b.episode_id, b.seed, b.family, arm, "KNOWN",
                                    trial, info, route, plan.clock_domain, plan.boot_id))
    return plan, rows


class SourceContrastTests(unittest.TestCase):
    def test_clock_boot_and_availability_cannot_change_under_same_bytes(self):
        plan, rows = fixture()
        original = rows[1]
        changed = [replace(original, clock_domain="another-clock"),
                   replace(original, boot_id="another-boot"),
                   replace(original, information=(replace(original.information[0],
                           available_us=19), original.information[1]))]
        for candidate in changed:
            with self.subTest(candidate=candidate), self.assertRaises(ContractError):
                source_contrast(plan, [rows[0], candidate, *rows[2:]])

    def test_equal_bits_and_ids_do_not_substitute_payload(self):
        plan, rows = fixture()
        rows[1] = replace(rows[1], information=(replace(rows[1].information[0],
                           payload=b"z"), rows[1].information[1]))
        with self.assertRaises(ContractError):
            source_contrast(plan, rows)

    def test_route_must_match_preregistered_permutation(self):
        plan, rows = fixture()
        rows[1] = replace(rows[1], route=(0, 1))
        with self.assertRaises(ContractError):
            source_contrast(plan, rows)

    def test_workload_cannot_be_relabelled_as_another_source(self):
        plan, rows = fixture(2)
        plan = replace(plan, blocks=(plan.blocks[0], replace(plan.blocks[1],
                       source_cluster_digest=digest("alias"))))
        with self.assertRaises(ContractError):
            source_contrast(plan, rows)

    def test_all_arms_cannot_drift_from_frozen_design(self):
        plan, rows = fixture()
        changes = {"ability_digest": digest("other"), "evaluator_digest": digest("other"),
                   "feedback_budget_bits": 17, "query_budget": 3,
                   "training_budget": 5, "compute_budget_us": 101}
        for field, value in changes.items():
            changed = [replace(r, trial=replace(r.trial, **{field: value})) for r in rows]
            with self.subTest(field=field), self.assertRaises(ContractError):
                source_contrast(plan, changed)

    def test_eight_seeds_remain_one_declared_source(self):
        plan, rows = fixture(8)
        report = source_contrast(plan, rows)
        self.assertEqual((report["training_seeds"], report["declared_source_clusters"],
                          len(report["statistics"]["source_differences"])), (8, 1, 1))
        self.assertIsNone(report["confirmatory_p"])

    def test_canonical_order_and_future_suffix_preserve_digest(self):
        plan, rows = fixture(2)
        expected = source_contrast(plan, rows)
        future = Information("invalid-future-id", "invalid-future-source", 101, b"x")
        changed = [replace(r, information=(*reversed(r.information), future))
                   for r in reversed(rows)]
        self.assertEqual(source_contrast(replace(plan, blocks=tuple(reversed(plan.blocks))),
                                         changed), expected)

    def test_unknown_and_missing_preserve_denominator_without_mean(self):
        plan, rows = fixture()
        rows[0] = replace(rows[0], status="UNKNOWN", trial=None)
        report = source_contrast(plan, rows[:-1])
        self.assertEqual(report["planned_rows"], 4)
        self.assertEqual(report["status_counts"], dict(KNOWN=2, UNKNOWN=1,
                         UNAVAILABLE=0, FAILED=0, NOT_RUN=0, MISSING=1))
        self.assertIsNone(report["statistics"])
        self.assertIsNone(report["confirmatory_p"])

    def test_missing_scalar_retention_withholds_full_retention_panel(self):
        plan, rows = fixture()
        rows[2] = replace(rows[2], trial=replace(rows[2].trial, retention_value=None))
        self.assertIsNone(source_contrast(plan, rows)["statistics"]["mean_retention_difference"])

    def test_learning_nonattainment_remains_right_censored(self):
        self.assertEqual(learning_progress([(1, 10, 0.2), (5, 50, 0.5)], target=0.8),
                         {"censoring": "right", "lower": (5, 50), "upper": None})

    def test_learning_first_crossing_is_interval_censored(self):
        self.assertEqual(learning_progress([(1, 10, 0.2), (5, 50, 0.9),
                                            (8, 80, 0.1)], target=0.8),
                         {"censoring": "interval", "lower": (1, 10), "upper": (5, 50)})


if __name__ == "__main__":
    unittest.main()
