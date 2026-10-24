import copy
import unittest

from prospective_action_ranking import rank_actions


def action(key, label, *, source=True, cost=10, commands=2, observations=None):
    return {"key": key, "source_id": "s-"+key if source else None, "label": label,
            "recorded_pair_wall_ns": cost, "physical_command_executions": commands,
            "complete_command_observations": commands if observations is None else observations}


def registry():
    return [{"group_id": "g1", "repo": "p1", "split": "holdout", "actions":
        [action("a", 0), action("b", 1, cost=20), action("c", None, cost=30)]},
        {"group_id": "g2", "repo": "p2", "split": "holdout", "actions":
        [action("d", 1, source=False, cost=None, commands=None), action("e", None, cost=5, commands=1)]},
        {"group_id": "g3", "repo": "p2", "split": "holdout", "actions": []}]


class ActionRankingTests(unittest.TestCase):
    def test_full_denominator_hash_ties_unknowns_and_positive_threshold(self):
        scores = {"s-a": {"score": .8, "eligible": True}, "s-b": {"score": .8, "eligible": True},
                  "s-c": {"score": .9, "eligible": True}, "s-e": {"score": .99, "eligible": False}}
        result = rank_actions(registry(), scores, method_kind="calibrated_probability", expected_group_ids=["g1", "g2", "g3"])
        first, second, empty = result["group_records"]
        self.assertEqual(first["ranked_action_keys"], ["c", "a", "b"])
        self.assertEqual(result["top_k"]["1"]["known_positive_hit_rate"], 0)
        self.assertEqual(result["top_k"]["3"]["known_positive_hit_rate"], 1/3)
        self.assertEqual(result["top_k"]["1"]["unknown_selections"], 1)
        self.assertEqual(result["top_k"]["1"]["abstained_groups"], 2)
        self.assertTrue(second["top_k"]["1"]["abstained"])
        self.assertTrue(empty["top_k"]["3"]["abstained"])
        self.assertEqual(result["positive_threshold_recommendation"]["unknown_selections"], 1)
        self.assertFalse(result["unknowns_relabelled_negative"])

    def test_replay_appends_unscored_and_retains_partial_or_unknown_cost(self):
        scores = {"s-a": {"score": .2, "eligible": True}}
        result = rank_actions(registry(), scores, method_kind="calibrated_probability", expected_group_ids=["g1", "g2", "g3"])
        first, second, _ = result["group_records"]
        self.assertEqual(first["full_order_replay"]["full_order"], ["a", "b", "c"])
        self.assertEqual(first["full_order_replay"]["replayed_action_keys"], ["a", "b"])
        self.assertEqual(first["full_order_replay"]["recorded_pair_work_ns"], 30)
        self.assertEqual(second["full_order_replay"]["incomplete_pair_cost_keys"], ["d"])
        self.assertFalse(second["full_order_replay"]["cost_complete_over_replayed_pairs"])
        self.assertEqual(result["positive_threshold_recommendation"]["abstained_groups"], 3)
        changed = registry()
        changed[1]["actions"][0]["label"] = None
        other = rank_actions(changed, scores, method_kind="calibrated_probability", expected_group_ids=["g1", "g2", "g3"])
        replay = other["group_records"][1]["full_order_replay"]
        self.assertIsNone(replay["actions_to_first_known_positive"])
        self.assertEqual(replay["unknown_outcome_keys"], ["d", "e"])
        self.assertEqual(replay["recorded_pair_work_ns"], 5)

    def test_jaccard_hash_and_oracle_are_explicit_ranking_controls(self):
        args = dict(expected_group_ids=["g1", "g2", "g3"])
        hashed = rank_actions(registry(), {}, method_kind="command_hash", **args)
        self.assertEqual(hashed["group_records"][0]["ranked_action_keys"], ["a", "b", "c"])
        self.assertEqual(hashed["top_k"]["1"]["known_positive_hit_rate"], 1/3)
        self.assertEqual(hashed["oracle_known_positive_top1_rate"], 2/3)
        self.assertTrue(hashed["group_records"][0]["known_positive_oracle"]["uses_outcome_labels"])
        lexical = rank_actions(registry(), {"s-b": {"score": .99, "eligible": True}}, method_kind="identifier_jaccard", **args)
        self.assertIsNone(lexical["positive_threshold"])
        self.assertIsNone(lexical["positive_threshold_recommendation"])
        self.assertEqual(lexical["top_k"]["1"]["known_positive_hit_rate"], 1/3)

    def test_two_physical_starts_one_observation_retains_incomplete_lower_bound(self):
        proposals = [{"group_id": "g1", "repo": "p1", "split": "holdout", "actions":
            [action("a", None, cost=13, commands=2, observations=1)]}]
        result = rank_actions(proposals, {}, method_kind="command_hash", expected_group_ids=["g1"])
        replay = result["group_records"][0]["full_order_replay"]
        self.assertEqual(replay["recorded_pair_work_ns"], 13)
        self.assertEqual(replay["physical_command_executions_replayed"], 2)
        self.assertEqual(replay["complete_command_observations_replayed"], 1)
        self.assertFalse(replay["cost_complete_over_replayed_pairs"])
        self.assertTrue(replay["recorded_work_is_lower_bound_when_incomplete"])
        self.assertEqual(replay["incomplete_pair_cost_keys"], ["a"])
        self.assertEqual(result["top_k"]["1"]["unknown_selections"], 1)
        del proposals[0]["actions"][0]["complete_command_observations"]
        self.assertFalse(rank_actions(proposals, {}, method_kind="command_hash", expected_group_ids=["g1"])
            ["group_records"][0]["full_order_replay"]["cost_complete_over_replayed_pairs"])

    def test_missing_groups_duplicate_sources_and_invalid_labels_are_rejected(self):
        with self.assertRaises(ValueError):
            rank_actions(registry()[:2], {}, method_kind="command_hash", expected_group_ids=["g1", "g2", "g3"])
        for field, value in (("source_id", "s-a"), ("label", -1), ("recorded_pair_wall_ns", -1)):
            broken = copy.deepcopy(registry())
            broken[0]["actions"][1][field] = value
            with self.assertRaises(ValueError):
                rank_actions(broken, {}, method_kind="command_hash", expected_group_ids=["g1", "g2", "g3"])
        with self.assertRaises(ValueError):
            rank_actions(registry(), {"unproposed": {"score": .5, "eligible": True}},
                         method_kind="calibrated_probability", expected_group_ids=["g1", "g2", "g3"])


if __name__ == "__main__":
    unittest.main()
