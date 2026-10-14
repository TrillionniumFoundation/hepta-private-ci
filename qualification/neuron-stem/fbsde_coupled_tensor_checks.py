"""Actual field learning and correction; no pretrained Encoder is used here."""
from dataclasses import replace
import unittest
import torch
from fbsde_coupled import CoupledProfile, continuation_fields
from fbsde_coupled_learning import experiment, fit_field, propose


class CoupledFieldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = experiment(None, training_steps=120)

    def test_corrected_neural_proposals_recover_original_problem(self):
        for row in self.result['rows']:
            self.assertLess(row['corrected_y_sup_error'], 1e-9)
            self.assertLessEqual(row['uncorrected_y_sup_error'],
                                 row['proposal_report']['y_error_bound_exact_arithmetic']+1e-11)

    def test_small_actual_model_and_nonzero_preparation(self):
        model = self.result['model']
        self.assertLess(model['parameters'], 2000)
        self.assertGreater(model['training_cpu_ns'], 0)
        self.assertLess(model['loss_first_last'][-1], model['loss_first_last'][0])
        self.assertEqual(self.result['future_uses_assumed_for_amortization'], 0)

    def test_no_encoder_or_automatic_acceptance(self):
        self.assertFalse(self.result['real_encoder_executed'])
        self.assertFalse(self.result['interval_arithmetic_certificate'])
        self.assertFalse(self.result['production_promotion_permitted'])

    def test_wrong_field_profile_rejected(self):
        p = CoupledProfile()
        fields = continuation_fields(p, .25)
        model, meta = fit_field(torch, p, fields, steps=2)
        with self.assertRaisesRegex(ValueError, 'profile mismatch'):
            propose(torch, replace(p, sigma=.2), .3, model, meta)

    def test_reset_terminal_cannot_be_training_truth(self):
        p = CoupledProfile()
        with self.assertRaisesRegex(ValueError, 'unaltered continuation'):
            fit_field(torch, p, continuation_fields(p, .25, reset_at=(2,)))


if __name__ == '__main__':
    unittest.main()
