import tempfile
import unittest
from pathlib import Path

import numpy as np

from content_control.refiner import Capture, PATHS, Refiner
from content_control.run import inner_split, service
from independent.accounting import BudgetExceeded, WorkLedger, counted_model_class
from independent.learning import CachedObjective
from model import JointModel, softmax


class RefinerTests(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(77)
        self.features = (self.rng.normal(size=(3, 32)), self.rng.normal(size=(3, 12)),
                         self.rng.normal(size=(3, 12)))
        self.base = JointModel(202, 12, 192, seed=71)
        self.labels = np.array([0, 4, 11])

    def test_zero_refiner_preserves_base_and_nonzero_actions_change_states(self):
        refiner = Refiner()
        expected = softmax(self.features[1]), softmax(self.features[2])
        for path in PATHS:
            for actual, reference in zip(refiner.forward(self.features, path), expected):
                np.testing.assert_array_equal(actual, reference)
        for value in refiner.params.values():
            value[:] = self.rng.normal(0, .1, value.shape)
        outputs = {p: refiner.forward(self.features, p) for p in PATHS}
        self.assertFalse(np.allclose(outputs["TI"][0], outputs["IT"][0]))
        self.assertFalse(np.allclose(outputs["J"][1], outputs["TI"][1]))

    def test_all_paths_ce_and_additive_gradients_match_finite_differences(self):
        refiner = Refiner()
        for value in refiner.params.values():
            value[:] = self.rng.normal(0, .05, value.shape)
        for arm in ("H", "A"):
            objective = CachedObjective(arm, self.base)
            for path in PATHS:
                loss, grads = refiner.loss_and_gradients(self.features, self.labels, objective, (path,))
                for key, value in refiner.params.items():
                    index = tuple(0 for _ in value.shape)
                    original, eps = value[index], 1e-6
                    value[index] = original + eps
                    plus = refiner.loss_and_gradients(self.features, self.labels, objective, (path,))[0]
                    value[index] = original - eps
                    minus = refiner.loss_and_gradients(self.features, self.labels, objective, (path,))[0]
                    value[index] = original
                    self.assertAlmostEqual(grads[key][index], (plus - minus) / (2 * eps), places=8,
                                           msg=arm + path + key)

    def test_budget_refusal_is_atomic_and_paid_updates_move_real_parameters(self):
        refiner = Refiner()
        objective = CachedObjective("A", self.base)
        ledger = WorkLedger("refiner", total_cap=0)
        with self.assertRaises(BudgetExceeded):
            refiner.step(self.features, self.labels, objective, .003, ledger, Capture(ledger))
        self.assertEqual(refiner.updates, 0)
        self.assertTrue(all(np.count_nonzero(v) == 0 for v in refiner.params.values()))
        paid = WorkLedger("refiner")
        capture = Capture(paid)
        refiner.step(self.features, self.labels, objective, .003, paid, capture)
        self.assertEqual(refiner.updates, 1)
        self.assertTrue(all(np.linalg.norm(v) > 0 for v in capture.first_delta.values()))

    def test_physical_source_split_keeps_variants_and_commands_together(self):
        data = {"full": np.zeros((8, 202)), "labels": np.arange(8),
            "source_ids": ["a", "a", "b", "b", "c", "c", "d", "d"],
            "sources": {"a": {"index": 0}, "b": {"index": 1}, "c": {"index": 4}, "d": {"index": 7}}}
        fit, inner = inner_split(data)
        self.assertEqual((fit["source_ids"], inner["source_ids"]), (["b", "b", "d", "d"], ["a", "a", "c", "c"]))

    def test_explicit_base_clone_removes_automatic_accounting_wrapper(self):
        counted = counted_model_class(JointModel)(202, 12, 192, ledger=WorkLedger("decoder"))
        plain = JointModel.clone(counted)
        self.assertFalse(hasattr(plain, "ledger"))
        CachedObjective("S", plain).step(plain, np.zeros((1, 202)), np.array([0]), .003,
                                         ledger=WorkLedger("pretrain"))
        self.assertEqual(plain.updates, 1)

    def test_external_service_needs_no_labels_and_charges_real_png(self):
        refiner = Refiner()
        data = {"full": self.rng.uniform(0, 1, (1, 202))}
        with tempfile.TemporaryDirectory() as temp:
            ledger = WorkLedger("external")
            p, q, receipt = service(refiner, self.base, data, "J", ledger, Path(temp), 77, external=True)
            self.assertTrue((Path(temp) / "external-output.png").read_bytes().startswith(b"\x89PNG"))
            self.assertGreater(receipt["cpu_ns"], 0)
            self.assertEqual(ledger.totals["serialized_requests"], 1)
            self.assertEqual(p.shape, q.shape)


if __name__ == "__main__":
    unittest.main()
