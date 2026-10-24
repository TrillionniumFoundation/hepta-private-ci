import copy
import unittest

import numpy as np

from prospective_action_compare import SEEDS, compare_action_conditions
from prospective_action_ranking import rank_actions


def proposals():
    return [{"group_id": f"g{i}", "repo": f"project-{i//2}", "split": "holdout", "actions": [
        {"key": f"g{i}-{y}", "source_id": f"s{i}-{y}", "label": y,
         "recorded_pair_wall_ns": 100, "physical_command_executions": 2} for y in (0, 1)]} for i in range(10)]


def condition(name, registry, *, policy="perfect", included=None):
    available = [(g["group_id"], a["source_id"], a["label"]) for g in registry for a in g["actions"]]
    allowed = {s for _, s, _ in available} if included is None else set(included)
    selected = [(g, s, y) for g, s, y in available if s in allowed]
    probabilities, rankings = {}, {}
    for seed in SEEDS:
        scores, rows = {}, []
        for _, source, label in selected:
            confidence = .5 if policy == "uniform" else (.51 if seed != 29 else .01) if policy == "two_good_fits" else .9
            p = [1-confidence, confidence] if label else [confidence, 1-confidence]
            rows.append(p)
            scores[source] = {"score": p[1], "eligible": True}
        probabilities[seed] = np.asarray(rows, dtype=np.float64).reshape(-1, 2)
        rankings[seed] = rank_actions(registry, scores, method_kind="calibrated_probability",
                                     expected_group_ids=[g["group_id"] for g in registry])
    return {"name": name, "source_ids": [s for _, s, _ in selected], "group_ids": [g for g, _, _ in selected],
            "labels": np.asarray([y for _, _, y in selected], int), "probabilities_by_seed": probabilities,
            "rankings_by_seed": rankings}


class ProspectiveActionComparisonTests(unittest.TestCase):
    def compare(self, left, right, registry=None):
        registry = proposals() if registry is None else registry
        return compare_action_conditions(left, right, proposal_registry=registry,
                                         expected_group_ids=[g["group_id"] for g in registry])

    def test_identical_predictions_have_exact_zero_paired_intervals(self):
        registry = proposals()
        left = condition("same-left", registry)
        right = condition("same-right", registry)
        result = self.compare(left, right, registry)
        for value in result["contrasts"].values():
            self.assertEqual(value["difference"], 0)
            for method in ("whole_bug_bootstrap", "project_cluster_bootstrap"):
                self.assertEqual(value[method]["ci95"], [0, 0])
                self.assertEqual(value[method]["valid_replicates"], 2000)
        self.assertEqual((result["support"]["proposed_groups"], result["support"]["project_count"]), (10, 5))

    def test_known_improvement_is_nonzero_for_group_and_project_replicates(self):
        registry = proposals()
        result = self.compare(condition("perfect", registry), condition("uniform", registry, policy="uniform"), registry)
        ba, nll, top = [result["contrasts"][key] for key in ("balanced_accuracy", "nll", "known_positive_top1")]
        self.assertAlmostEqual(ba["difference"], .5)
        self.assertAlmostEqual(nll["difference"], np.log(.5/.9))
        self.assertEqual(top["difference"], 1)
        for method in ("whole_bug_bootstrap", "project_cluster_bootstrap"):
            self.assertGreater(ba[method]["ci95"][0], 0)
            self.assertLess(nll[method]["ci95"][1], 0)
            self.assertEqual(top[method]["ci95"], [1, 1])

    def test_score_each_seed_before_averaging_not_argmax_of_mean_probability(self):
        registry = proposals()
        result = self.compare(condition("two-good-fits", registry, policy="two_good_fits"),
                              condition("uniform", registry, policy="uniform"), registry)
        self.assertAlmostEqual(result["contrasts"]["balanced_accuracy"]["left"], 2/3)
        self.assertAlmostEqual(result["contrasts"]["known_positive_top1"]["left"], 2/3)
        self.assertAlmostEqual(result["contrasts"]["nll"]["left"], (-2*np.log(.51)-np.log(.01))/3)
        self.assertEqual(result["bootstrap"]["fixed_fit_seeds"], [7, 17, 29])

    def test_project_clusters_keep_perfectly_correlated_bugs_together(self):
        registry = proposals()
        left = condition("project-dependent", registry)
        for seed in SEEDS:
            scores = {}
            for index, source in enumerate(left["source_ids"]):
                if int(left["group_ids"][index][1:]) >= 4:
                    left["probabilities_by_seed"][seed][index] = [.5, .5]
                scores[source] = {"score": float(left["probabilities_by_seed"][seed][index, 1]), "eligible": True}
            left["rankings_by_seed"][seed] = rank_actions(registry, scores, method_kind="calibrated_probability",
                expected_group_ids=[g["group_id"] for g in registry])
        result = self.compare(left, condition("uniform", registry, policy="uniform"), registry)
        contrast = result["contrasts"]["known_positive_top1"]
        bug = contrast["whole_bug_bootstrap"]["ci95"]
        project = contrast["project_cluster_bootstrap"]["ci95"]
        self.assertEqual(contrast["difference"], .4)
        self.assertEqual(project, [0, .8])
        self.assertGreater(project[1]-project[0], bug[1]-bug[0])

    def test_common_source_support_and_missing_effective_class_are_explicit(self):
        registry = proposals()
        full = condition("full", registry)
        keep = set(full["source_ids"])-{"s0-1", "s1-0", "s1-1"}
        partial = condition("partial", registry, policy="uniform", included=keep)
        result = self.compare(full, partial, registry)
        support = result["support"]
        self.assertEqual((support["common_valid_rows"], support["common_valid_groups"]), (17, 9))
        self.assertEqual(support["common_weighted_class_mass"], [5, 4])
        self.assertEqual(support["left_rows_outside_common"], 3)
        self.assertEqual(support["proposed_groups"], 10)
        negative = condition("negative-only", registry, included={f"s{i}-0" for i in range(10)})
        missing = self.compare(full, negative, registry)["contrasts"]["balanced_accuracy"]
        self.assertIsNone(missing["difference"])
        self.assertIsNone(missing["whole_bug_bootstrap"]["ci95"])
        self.assertEqual(missing["whole_bug_bootstrap"]["unavailable_replicates"], 2000)

    def test_ranking_only_hash_has_no_invented_probability_metrics(self):
        registry = proposals()
        hashed = rank_actions(registry, {}, method_kind="command_hash", expected_group_ids=[g["group_id"] for g in registry])
        control = {"name": "command-hash", "source_ids": [], "group_ids": [], "labels": [],
                   "probabilities_by_seed": None, "rankings_by_seed": {seed: hashed for seed in SEEDS}}
        result = self.compare(condition("perfect", registry), control, registry)
        self.assertIsNone(result["contrasts"]["nll"]["difference"])
        self.assertIsNone(result["contrasts"]["balanced_accuracy"]["difference"])
        self.assertEqual(result["contrasts"]["known_positive_top1"]["difference"], 1)

    def test_unpaired_labels_seeds_or_proposal_registries_are_rejected(self):
        registry = proposals()
        left = condition("left", registry)
        for change in ("label", "seed", "registry"):
            wrong = copy.deepcopy(condition("right", registry))
            if change == "label": wrong["labels"][0] = 1
            elif change == "seed": del wrong["probabilities_by_seed"][29]
            else: wrong["rankings_by_seed"][7]["proposal_registry_sha256"] = "0"*64
            with self.assertRaises(ValueError):
                self.compare(left, wrong, registry)


if __name__ == "__main__":
    unittest.main()
