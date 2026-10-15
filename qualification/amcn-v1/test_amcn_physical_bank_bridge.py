"""Real CPU torch original #1968 Head training/reload on *synthetic* features.

Not pretrained Encoder performance, original task success or signed evidence.
"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

import torch

from amcn_typed_budget import (seal_detached_typed_bank, train_typed_budget,
                               type_inventory_digest)
from test_amcn_typed_budget import trial
from amcn_causal_physical_bank_bridge import replay_and_bind_original_bank


def pin(x):
    return sha256(x.encode()).hexdigest()


class OriginalPhysicalBankBridgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.matrix, cls.types, cls.train, cls.withheld = trial()
        cls.fitted = train_typed_budget(cls.matrix, cls.train, cls.types,
                                       expected_type_digest=type_inventory_digest(
                                           cls.matrix, cls.types),
                                       kind="gated", steps=4, batch=2, seed=17)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.location = Path(self.temp.name) / "original-bank"
        self.source = pin("synthetic-source-issuer-is-unqualified")
        self.original = seal_detached_typed_bank(
            self.fitted, self.matrix, self.types, self.location,
            source_binding_sha256=self.source)

    def bridge(self, receipt=None, predictions=None, **overrides):
        kwargs = dict(
            expected_manifest_sha256=self.original["manifest_sha256"],
            expected_source_binding_sha256=self.source,
            expected_predictions_sha256=self.fitted["receipt"]["metrics"]["prediction_sha256"],
        )
        kwargs.update(overrides)
        return replay_and_bind_original_bank(
            self.matrix, self.types,
            receipt if receipt is not None else self.fitted["receipt"],
            predictions if predictions is not None else self.fitted["predictions"],
            self.location, **kwargs)

    def test_real_cpu_six_tensor_heads_reforward_every_original_prediction(self):
        report = self.bridge()
        n = len(self.fitted["predictions"])
        self.assertEqual(report["types"], ["procedural", "semantic"])
        self.assertEqual(report["physical_head_forward_replay"]["verified_predictions"], n)
        self.assertEqual(report["physical_head_forward_replay"]["physical_model_forward_calls"], 5*n)
        self.assertLessEqual(report["physical_head_forward_replay"]["maximum_absolute_probability_error"], 1e-6)
        banks = report["capacity"]
        self.assertEqual(banks["shared"]["total_trainable_parameters"],
                         banks["typed"]["total_trainable_parameters"])
        self.assertEqual(banks["shared"]["optimizer_steps"], banks["typed"]["optimizer_steps"])
        self.assertEqual(banks["shared"]["minibatch_examples"],
                         banks["typed"]["minibatch_examples"])
        self.assertEqual(banks["typed"]["trainable_head_count"], 2)
        self.assertNotEqual(banks["shared"]["head_sha256_by_type"],
                            banks["typed"]["head_sha256_by_type"])
        self.assertFalse(report["production_accepted"])
        self.assertFalse(report["superiority_claim"])
        self.assertEqual(report["future_reader_answers_generated"], 0)

    def test_tampered_actual_head_bytes_refuse(self):
        target = self.location / "typed_equal_budget__semantic.safetensors"
        target.write_bytes(target.read_bytes() + b"TAMPER")
        with self.assertRaises(ValueError):
            self.bridge()

    def test_fake_training_work_is_not_reconciled(self):
        changed = deepcopy(self.fitted["receipt"])
        changed["metrics"]["typed_budget"]["parameters"] += 3
        with self.assertRaises(ValueError):
            self.bridge(receipt=changed)

    def test_forged_original_prediction_does_not_survive_real_head_forward(self):
        changed = deepcopy(self.fitted["predictions"])
        changed[0]["probabilities"]["typed_equal_budget"] = 1.0
        from amcn_core import digest
        with self.assertRaises(ValueError):
            self.bridge(predictions=changed, expected_predictions_sha256=digest(changed))

    def test_source_or_feature_pin_changes_block_replay(self):
        with self.assertRaises(ValueError):
            self.bridge(expected_source_binding_sha256=pin("wrong"))
        with self.assertRaises(ValueError):
            self.bridge(expected_manifest_sha256=pin("different bank"))

    def test_no_unrecorded_type_appears_from_model_weights(self):
        altered = deepcopy(self.fitted["receipt"])
        altered["metrics"]["functional_types"] = ["episodic", "semantic"]
        with self.assertRaises(ValueError):
            self.bridge(receipt=altered)


if __name__ == "__main__":
    unittest.main()
