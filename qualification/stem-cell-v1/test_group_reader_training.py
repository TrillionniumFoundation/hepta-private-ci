import copy
from dataclasses import replace
import unittest

import torch

from group_reader import Reader
from group_reader_training import ReaderBatch, fit_reader
from test_group_reader import binding_fixture


class ReaderTrainingTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(17)
        torch.set_num_threads(1)
        facts, query, targets = binding_fixture()
        mask = torch.ones(24, 3, dtype=torch.bool)
        self.train = ReaderBatch(facts, query, mask, targets, tuple("train" + str(i) for i in range(24)))
        self.validation = ReaderBatch(facts.flip(1), query, mask, targets,
                                      tuple("validation" + str(i) for i in range(24)))

    def test_real_fit_freezes_preserves_source_and_measures_hop_gradients(self):
        model = Reader(8, 16, max_hops=3)
        original = copy.deepcopy(model.state_dict())
        trained, receipt = fit_reader(model, self.train, self.validation, steps=65, seed=6,
                                      batch_size=12, max_depth=2, learning_rate=.025)
        self.assertEqual(receipt["status"], "completed")
        self.assertLess(receipt["diagnostics"][-1]["train"]["binary_cross_entropy"],
                        receipt["diagnostics"][0]["train"]["binary_cross_entropy"] * .4)
        self.assertTrue(all(torch.equal(original[k], v) for k, v in model.state_dict().items()))
        self.assertTrue(all(not p.requires_grad for p in trained.parameters()))
        self.assertFalse(trained.training)
        self.assertEqual(receipt["validation_gradient_updates"], 0)
        self.assertTrue(receipt["train_validation_sources_verified"])
        self.assertGreater(receipt["optimizer_tensor_bytes"], 0)
        self.assertTrue(all(len(r["hop_state_gradient_l2"]) == r["depth"] for r in receipt["updates"]))
        self.assertTrue(any(all(g > 0 for g in r["hop_state_gradient_l2"]) for r in receipt["updates"]))
        self.assertEqual(receipt["work_observation"]["unknown_operators"], {})

    def test_counterfactual_ownership_and_training_only_feedback(self):
        counterfactual = replace(self.train, mask=torch.zeros_like(self.train.mask), targets=torch.zeros(24, dtype=torch.long))
        calls = []
        def feedback(batch, guesses):
            self.assertTrue(set(batch.source_groups) <= set(self.train.source_groups))
            calls.append(len(guesses))
            return torch.tensor([[0., float(guess != label), 0., 0.]
                                 for guess, label in zip(guesses, batch.targets.tolist())])
        _, receipt = fit_reader(Reader(8, 16), self.train, self.validation, steps=8, seed=7,
                                max_depth=3, batch_size=8, counterfactual_train=counterfactual,
                                feedback_fn=feedback)
        self.assertEqual(receipt["status"], "completed")
        self.assertGreater(receipt["actual_counterfactual_exposures"], 0)
        self.assertEqual(len(calls), receipt["training_feedback_calls"])
        self.assertGreater(len(calls), 0)
        with self.assertRaises(ValueError):
            fit_reader(Reader(8, 16), self.train, self.validation, steps=1, seed=1,
                       counterfactual_train=replace(counterfactual, source_groups=self.validation.source_groups))
        with self.assertRaises(ValueError):
            fit_reader(Reader(8, 16), self.train, replace(self.validation, source_groups=self.train.source_groups), steps=1, seed=1)

    def test_train_only_fit_gate_accepts_no_validation_and_periodic_diagnostics(self):
        _, receipt = fit_reader(Reader(8, 16), self.train, None, steps=5, seed=1,
                                max_depth=2, optimizer="Adam", diagnostic_interval=2)
        self.assertEqual([r["optimizer_step"] for r in receipt["diagnostics"]], [0, 2, 4, 5])
        self.assertTrue(all(r["validation"] is None for r in receipt["diagnostics"]))
        self.assertEqual(receipt["validation_gradient_updates"], 0)


if __name__ == "__main__":
    unittest.main()
