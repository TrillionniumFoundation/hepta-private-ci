"""New tiny integration fixtures; no final namespace or candidate selection."""

import unittest

import torch

from .ablation import banks
from .run import encoder, features
from .tasks import generate


class AblationTests(unittest.TestCase):
    def test_only_declared_channels_change_and_common_bank_is_preserved(self):
        model = encoder("first_passage")
        data = generate("development-unit-only/feature-bank/20261121", 2, "first_passage", "train", 4, 4)
        reference, names = features(model, data)
        bank, observed_names = banks(model, data)
        self.assertEqual(names, observed_names)
        torch.testing.assert_close(bank["same_generator"], reference, rtol=0, atol=0)
        affected = [i for i, name in enumerate(names) if name in
                    ("last.call", "last.risk", "mean.call", "mean.risk")]
        preserved = [i for i in range(len(names)) if i not in affected]
        for name in ("drop_value_risk", "ordinary_tanh"):
            torch.testing.assert_close(bank[name][:, preserved], reference[:, preserved], rtol=0, atol=0)
        self.assertEqual(int(torch.count_nonzero(bank["drop_value_risk"][:, affected])), 0)
        self.assertGreater(float((bank["ordinary_tanh"][:, affected]-reference[:, affected]).abs().max()), 1e-4)
        self.assertTrue(bool(torch.isfinite(bank["ordinary_tanh"]).all()))


if __name__ == "__main__":
    unittest.main()
