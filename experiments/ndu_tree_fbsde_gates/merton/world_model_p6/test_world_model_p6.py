"""P6 synthetic learned-world / NDU-budgeted-control adversarial tests."""
import copy
import json
import tempfile
import unittest
from fractions import Fraction as F
from pathlib import Path

import independent_audit as auditor
import world_model_p6 as core


class FrozenStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = core.study()
        cls.model = core.FittedWorldModel.train(core.rows("p6-train-v1", core.TRAIN_PER_REGIME))

    @staticmethod
    def reseal(doc):
        doc["seal"] = core.digest({k: v for k, v in doc.items() if k != "seal"})

    def test_exact_independent_reproduction_and_profile_parity(self):
        report = auditor.audit(self.original)
        self.assertEqual(report["online_policy_episodes"], 768)
        self.assertEqual(report["full_train_observation_calls"], 4096)
        self.assertEqual(report["score"]["ndu_discrete"], report["score"]["ordinary_same_profile"])
        self.assertEqual(report["score"]["direct"]["used_probe_calls"], 0)
        self.assertEqual(report["score"]["neutral"]["used_probe_calls"], 256)
        # Recorded result is deliberately a NEGATIVE NDU-superiority control.
        self.assertGreater(report["score"]["neutral"]["correct"], report["score"]["ndu_discrete"]["correct"])

    def test_exact_joint_model_not_product_of_independent_probe_marginals(self):
        state = core.Belief("easy")
        after_one = state.observe("bit0", 0)
        after_duplicate = after_one.observe("duplicate", 0)
        after_complement = after_one.observe("bit1", 0)
        mass_y = lambda s: sum((p for p, bits in self.model.posterior(s) if bits[0]), F(0))
        # The shared-noise duplicate does not contribute a second independent bit.
        self.assertLess(abs(mass_y(after_one)-mass_y(after_duplicate)), F(1, 10))
        self.assertGreater(abs(mass_y(after_one)-mass_y(after_complement)), F(1, 3))

    def test_world_model_training_is_data_dependent(self):
        first = self.model.wire()
        modified = list(core.rows("p6-train-v1", 512))
        r = modified[0]
        modified[0] = core.World(r.identity, r.regime, 1-r.label, r.signals)
        another = core.FittedWorldModel.train(tuple(modified)).wire()
        self.assertNotEqual(first["train_counts"], another["train_counts"])
        self.assertTrue(all(sum(v) == 512 + 32 for v in first["train_counts"].values()))

    def test_fixed_external_objective_and_legal_actions(self):
        for regime in core.REGIMES:
            for arm in core.ARMS:
                p = core.Planner(self.model, arm)
                s = core.Belief(regime)
                self.assertIn(p.choose(s), p.legal(s))
                for probe in core.PROBES:
                    if core.COST[probe] <= s.remaining_tokens:
                        t = s.observe(probe, 1)
                        self.assertIn(p.choose(t), p.legal(t))
                        self.assertNotIn(probe, p.legal(t))
                        self.assertTrue(F(0) <= core.alpha(arm, t, self.model) <= F(1, 2))
        self.assertEqual(core.Planner(self.model, "direct").choose(core.Belief("easy")) in ("submit0", "submit1"), True)

    def test_true_online_probe_costs_are_not_counterfactual_savings(self):
        for result in self.original["attempts"]:
            probes = [t for t in result["trace"] if t["action"] in core.PROBES]
            self.assertEqual(sum(core.COST[t["action"]] for t in probes), result["used_tokens"])
            self.assertEqual(len(probes), result["used_calls"])
            self.assertLessEqual(result["used_tokens"], 2)
            self.assertLessEqual(result["used_calls"], 2)
            self.assertNotIn("label", result)
            self.assertNotIn("correct", result)
        self.assertEqual(self.original["training_probes_collected"], 4096)
        self.assertIn("not_physical_token_savings", self.original["no_claims"])

    def test_reject_same_seed_train_held(self):
        with self.assertRaises(ValueError):
            core.study("bad-same-seed", "bad-same-seed")

    def test_invalid_nonanticipative_observations(self):
        with self.assertRaises(ValueError):
            core.Belief("easy").observe("bit0", True)
        with self.assertRaises(ValueError):
            core.Belief("easy").observe("bit0", 0).observe("bit0", 0)
        with self.assertRaises(ValueError):
            core.Belief("easy", remaining_calls=0).observe("bit0", 0)
        with self.assertRaises(ValueError):
            core.Belief("easy").observe("invented_tool", 1)

    def test_monotone_utility_conditions(self):
        self.assertEqual(core.utility(((F(1, 2), F(1)), (F(1, 2), F(0))), F(0)), F(1, 2))
        self.assertEqual(core.utility(((F(1, 2), F(1)), (F(1, 2), F(0))), F(1, 2)), F(1, 4))
        with self.assertRaises(ValueError):
            core.utility(((F(1, 2), F(1)),), F(0))
        with self.assertRaises(ValueError):
            core.utility(((F(1), F(1)),), F(3, 4))

    def test_reject_dirty_corpus_or_unsupported_actions(self):
        duplicate = list(core.rows("p6-train-v1", 4))
        duplicate[1] = duplicate[0]
        with self.assertRaises(ValueError):
            core.FittedWorldModel.train(tuple(duplicate))
        with self.assertRaises(ValueError):
            core.Planner(self.model, "self_certified_success")
        with self.assertRaises(ValueError):
            core.FittedWorldModel.train(())

    def reject_changed(self, mutation, phrase=None, reseal=True):
        doc = copy.deepcopy(self.original)
        mutation(doc)
        if reseal:
            self.reseal(doc)
        with self.assertRaisesRegex(ValueError, phrase or ".*"):
            auditor.audit(doc)

    def test_reject_digest_rewrite_without_correct_world_model(self):
        self.reject_changed(lambda d: d["model"]["train_counts"]["easy"].__setitem__(0, 999), "TRAIN model")

    def test_reject_forged_online_sensor_even_with_resealed_attempt(self):
        i = next(i for i, row in enumerate(self.original["attempts"]) if row["used_calls"])
        self.reject_changed(lambda d: d["attempts"][i]["trace"][0].__setitem__(
            "observed", 1-d["attempts"][i]["trace"][0]["observed"]), "forged sensor")

    def test_reject_forged_resource_meter_even_with_resealed_attempt(self):
        self.reject_changed(lambda d: d["attempts"][0].__setitem__("used_tokens", 1), "resource meter")
        self.reject_changed(lambda d: d["attempts"][0].__setitem__("used_tokens", True), "resource meter")

    def test_reject_policy_switch_and_source_reordering_even_resealed(self):
        self.reject_changed(lambda d: d["attempts"][0]["trace"][-1].__setitem__("action", "abstain"), "policy")
        self.reject_changed(lambda d: d["attempts"].__setitem__(slice(0, 2),
                            [d["attempts"][1], d["attempts"][0]]), "reordered")
        self.reject_changed(lambda d: d.__setitem__("held_seed", "alternate-seed"), "source")

    def test_reject_missing_or_unexpected_source_and_trace(self):
        self.reject_changed(lambda d: d["attempts"].pop(), "online actions")
        self.reject_changed(lambda d: d["attempts"][0].__setitem__("hidden_label", 1), "attempt shape")
        self.reject_changed(lambda d: d.__setitem__("selected_model", "production"), "manifest key")
        self.reject_changed(lambda d: d.__setitem__("posture", "ACTIVE"), "protocol")

    def test_reject_unsealed_modification(self):
        self.reject_changed(lambda d: d["attempts"][0].__setitem__("used_tokens", 2), "seal", reseal=False)

    def test_reject_duplicated_json_keys_and_non_finite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid.json"
            path.write_text('{"seal":"first","seal":"second"}', encoding="utf-8")
            with self.assertRaises(ValueError):
                auditor.open_json(path)
            with self.assertRaises(ValueError):
                core.read_json(path)
            path.write_text('{"value":NaN}', encoding="utf-8")
            with self.assertRaises(ValueError):
                auditor.open_json(path)

    def test_create_only_input_and_output_and_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "sealed.json"
            q = Path(tmp) / "audit.json"
            core.write_new(p, self.original)
            self.assertEqual(core.read_json(p), self.original)
            report = auditor.audit(auditor.open_json(p))
            auditor.emit(q, report)
            with self.assertRaises(FileExistsError):
                core.write_new(p, self.original)
            with self.assertRaises(FileExistsError):
                auditor.emit(q, report)

    def test_wrong_held_source_is_not_accepted_as_fresh_evidence(self):
        bad = copy.deepcopy(self.original)
        bad["train_seed"] = bad["held_seed"]
        self.reseal(bad)
        with self.assertRaises(ValueError):
            auditor.audit(bad)


if __name__ == "__main__":
    unittest.main()
