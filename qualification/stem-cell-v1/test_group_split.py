import copy
import unittest

from group_split import assess_split, freeze_split_policy, selection_manifest_sha256


def observations(n=1200, gain=True):
    return [dict(before_case_id=f"{cohort}:{i}", after_case_id=f"{cohort}:{i}",
                 source_group=f"source:{cohort}:{i}", cohort=cohort, split="selection",
                 objective_sha256="a" * 64, before_success=not gain, after_success=gain,
                 before_cpu_seconds=.01, after_cpu_seconds=.02,
                 before_wall_seconds=.02, after_wall_seconds=.03)
            for cohort in ("new", "old") for i in range(n)]


def frozen(pairs, **changes):
    args = dict(subject_id="episode:group", parent_candidate_id="cell:0", candidate_id="cell:1",
                generation=1, objective_sha256="a" * 64,
                selection_manifest_sha256=selection_manifest_sha256(pairs),
                prices=dict(cpu_second=.01, wall_second=.01, byte_second=1e-12),
                cpu_seconds_bound=1, wall_seconds_bound=1)
    return freeze_split_policy(**{**args, **changes})


def costs(pairs, **changes):
    return dict(training_cpu_seconds=1., training_wall_seconds=1., migration_cpu_seconds=.1,
                migration_wall_seconds=.1, resident_bytes=1024, resident_duration_seconds=10.,
                amortization_observed_count=len(pairs), **changes)


def evaluate(pairs, policy=None, overhead=None, **changes):
    policy = policy or frozen(pairs)
    args = dict(preregistered_policy_id=policy["policy_id"], independent_source_groups_declared=True)
    return assess_split(policy, pairs, overhead or costs(pairs), **{**args, **changes})


class GroupSplitTests(unittest.TestCase):
    def test_observed_positive_gain_is_advisory_and_charges_lifecycle(self):
        pairs = observations()
        result = evaluate(pairs)
        self.assertEqual(result["decision"], "retain_candidate")
        self.assertFalse(result["execution_authority"])
        self.assertAlmostEqual(result["lifecycle_utility_cost"], .02200001024)
        self.assertAlmostEqual(result["amortized_utility_cost"], .02200001024 / len(pairs))

    def test_small_or_undeclared_independent_sample_is_insufficient(self):
        for pairs, independent in ((observations(2), True), (observations(), False)):
            with self.subTest(n=len(pairs)):
                self.assertEqual(evaluate(pairs, independent_source_groups_declared=independent)
                                 ["decision"], "insufficient")

    def test_repeated_source_rows_do_not_create_independent_sample_size(self):
        pairs = observations(40)
        for pair in pairs:
            pair["source_group"] = pair["cohort"]
        result = evaluate(pairs)
        self.assertEqual(result["decision"], "insufficient")
        self.assertEqual(result["cohorts"]["new"]["source_groups"], 1)

    def test_duplicate_mismatched_missing_cost_and_test_labels_fail(self):
        base = observations(2)
        for mutation in (lambda p: p.append(dict(p[0])),
                         lambda p: p[0].update(after_case_id="unmatched"),
                         lambda p: p[0].pop("after_cpu_seconds"),
                         lambda p: p[0].update(split="test"),
                         lambda p: p[0].update(split="train")):
            pairs = copy.deepcopy(base)
            mutation(pairs)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                evaluate(pairs)

    def test_old_task_degradation_and_negative_gain_rejected(self):
        negative = observations(gain=False)
        old_loss = observations()
        for pair in old_loss:
            if pair["cohort"] == "old":
                pair.update(before_success=True, after_success=False)
        for pairs in (negative, old_loss):
            with self.subTest(old= pairs is old_loss):
                self.assertEqual(evaluate(pairs)["decision"], "reject_candidate")

    def test_old_retention_need_not_have_positive_gain(self):
        pairs = observations(4000)
        for pair in pairs:
            if pair["cohort"] == "old":
                pair.update(before_success=True, after_success=True)
        self.assertEqual(evaluate(pairs)["decision"], "retain_candidate")

    def test_overhead_can_erase_apparent_learning_gain(self):
        pairs = observations()
        overhead = costs(pairs)
        overhead["training_cpu_seconds"] = 1e7
        self.assertEqual(evaluate(pairs, overhead=overhead)["decision"], "reject_candidate")

    def test_threshold_or_manifest_changes_cannot_reuse_registration(self):
        pairs = observations(2)
        policy = frozen(pairs)
        for change in (dict(max_old_regression=.9), dict(minimum_net_gain=.1)):
            changed = copy.deepcopy(policy)
            changed.update(change)
            with self.assertRaises(ValueError):
                evaluate(pairs, changed)
        pairs.pop()
        with self.assertRaises(ValueError):
            evaluate(pairs, policy)

    def test_complete_costs_bound_and_observed_denominator_required(self):
        pairs = observations(2)
        for key, value in (("migration_cpu_seconds", None),
                           ("amortization_observed_count", 10_000)):
            overhead = costs(pairs)
            if value is None:
                overhead.pop(key)
            else:
                overhead[key] = value
            with self.assertRaises(ValueError):
                evaluate(pairs, overhead=overhead)
        pairs[0]["after_wall_seconds"] = 2
        with self.assertRaises(ValueError):
            evaluate(pairs)


if __name__ == "__main__":
    unittest.main()
