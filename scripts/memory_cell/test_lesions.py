import unittest

import numpy as np
import torch

from composition import fit, state_digest
from lesions import LESIONS, clean_circuit, evaluate_lesions


class LesionTests(unittest.TestCase):
    def inputs(self):
        rng = np.random.default_rng(91)
        x = rng.normal(size=(48, 8)).astype(np.float32)
        y = ((x[:, 0] > 0) ^ (x[:, 1] > 0)).astype(int)
        phases = ["train"] * 24 + ["select"] * 12 + ["test"] * 12
        families = [f"{phase}-{i // 6}" for i, phase in enumerate(phases)]
        return x, y, phases, families

    def test_post_training_lesions_do_not_relearn_or_mix_consumers(self):
        x, y, phases, families = self.inputs()
        model = fit(x, y, phases, family_ids=families, steps=8)["joint"][0]
        before = state_digest(model)
        result = evaluate_lesions(model, x)
        self.assertEqual(set(result["probabilities"]), set(LESIONS))
        self.assertEqual(result["parameter_updates"], 0)
        np.testing.assert_allclose(result["probabilities"]["intact"], model(torch.tensor(x)).sigmoid().detach().numpy())
        self.assertFalse(np.array_equal(result["probabilities"]["intact"], result["probabilities"]["no_semantic_message"]))
        single = evaluate_lesions(model, x[:1])["probabilities"]
        for key in LESIONS:
            np.testing.assert_allclose(single[key], result["probabilities"][key][:1], rtol=1e-6)
        clean = clean_circuit(model)
        self.assertEqual(state_digest(clean), before)
        self.assertTrue(all(p.grad is None for p in clean.parameters()))
        self.assertEqual(state_digest(model), before)

    def test_family_leakage_is_rejected_before_any_learning(self):
        x, y, phases, families = self.inputs()
        families[-1] = families[0]
        with self.assertRaisesRegex(ValueError, "crosses"):
            fit(x, y, phases, family_ids=families, steps=2)

    def test_family_weighted_duplication_and_rng_isolation(self):
        x, y, phases, families = self.inputs()
        state = torch.random.get_rng_state().clone()
        base = fit(x, y, phases, family_ids=families, steps=2)
        self.assertTrue(torch.equal(torch.random.get_rng_state(), state))
        # Duplicating every sample of one correlated family must not buy it
        # extra training weight or manufacture independent source support.
        ix = [i for i, f in enumerate(families) if f == families[0]]
        other = fit(np.concatenate([x, x[ix]]), np.concatenate([y, y[ix]]),
                    phases + [phases[i] for i in ix], family_ids=families + [families[i] for i in ix], steps=2)
        for name in base:
            for key, value in base[name][0].state_dict().items():
                torch.testing.assert_close(value, other[name][0].state_dict()[key], atol=2e-6, rtol=2e-6)
        self.assertEqual(base["joint"][2]["training_source_families"], other["joint"][2]["training_source_families"])
