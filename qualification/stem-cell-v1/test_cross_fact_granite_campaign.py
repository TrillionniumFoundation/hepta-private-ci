"""Model-free gate tests; real Granite weights are never claimed by this suite."""
import tempfile
import unittest
from pathlib import Path

from cross_fact_granite_campaign import (
    ARMS, SEEDS, _digest, _write_once, full_fit_gate, matching_training_budgets, matched_fresh_gate,
)


def good_matrix():
    return {str(seed): {arm: dict(status='train_gate_passed', train_gate_passed=True,
        completed_steps=250, actual_training_exposures=4000,
        model_file_sha256='a' * 64, schedule_sha256='b' * 64,
        parameter_count=42562, optimizer_tensor_bytes=340496)
        for arm in ARMS} for seed in SEEDS}


class GraniteCampaignGateTests(unittest.TestCase):
    def test_full_fit_gate_demands_complete_seed_arm_cohort(self):
        matrix = good_matrix()
        self.assertTrue(full_fit_gate(matrix))
        self.assertTrue(matching_training_budgets(matrix))
        self.assertTrue(matched_fresh_gate(matrix))
        del matrix[str(SEEDS[2])]['local']
        self.assertFalse(full_fit_gate(matrix))
        self.assertFalse(matching_training_budgets(matrix))

    def test_failed_seed_or_broken_sha_never_opens_holdout(self):
        matrix = good_matrix()
        matrix['47']['cross_fact']['train_gate_passed'] = False
        self.assertFalse(full_fit_gate(matrix))
        matrix = good_matrix()
        matrix['53']['local']['model_file_sha256'] = 'Q' * 64
        self.assertFalse(full_fit_gate(matrix))
        matrix = good_matrix()
        matrix['41']['local']['completed_steps'] = 8001
        self.assertFalse(full_fit_gate(matrix))

    def test_plan_equality_is_not_a_claim_of_equal_actual_training(self):
        matrix = good_matrix()
        matrix['53']['local']['completed_steps'] = 500
        matrix['53']['local']['actual_training_exposures'] = 8000
        self.assertTrue(full_fit_gate(matrix))
        self.assertFalse(matching_training_budgets(matrix))
        self.assertFalse(matched_fresh_gate(matrix))
        matrix = good_matrix()
        matrix['41']['local']['schedule_sha256'] = 'c' * 64
        self.assertFalse(matching_training_budgets(matrix))

    def test_identical_fits_with_unequal_optimizer_storage_must_not_open_fresh(self):
        matrix = good_matrix()
        matrix['47']['local']['optimizer_tensor_bytes'] += 8
        self.assertTrue(full_fit_gate(matrix))
        self.assertFalse(matching_training_budgets(matrix))
        self.assertFalse(matched_fresh_gate(matrix))
        matrix = good_matrix()
        matrix['53']['cross_fact']['parameter_count'] += 1
        self.assertFalse(matched_fresh_gate(matrix))

    def test_missing_or_invalid_actual_cost_is_not_equal_budget(self):
        matrix = good_matrix()
        for key, value in [('optimizer_tensor_bytes', None), ('parameter_count', 0),
                           ('schedule_sha256', 'not-a-digest'), ('completed_steps', True)]:
            changed = good_matrix()
            changed['41']['local'][key] = value
            self.assertFalse(matching_training_budgets(changed))

    def test_nonboolean_gate_cannot_open_fresh(self):
        matrix = good_matrix()
        matrix['41']['local']['train_gate_passed'] = 'true'
        self.assertFalse(full_fit_gate(matrix))
        self.assertFalse(matched_fresh_gate(matrix))

    def test_untrusted_serialized_flags_are_not_sufficient_without_identity(self):
        self.assertFalse(full_fit_gate({'41': {'local': {'train_gate_passed': True}}}))
        self.assertFalse(full_fit_gate({str(seed): {arm: True for arm in ARMS} for seed in SEEDS}))

    def test_write_once_preserves_original_bytes_and_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / 'evidence.json'
            _write_once(destination, {'b': 2, 'a': 1})
            before = destination.read_bytes()
            self.assertEqual(len(_digest(destination)), 64)
            with self.assertRaises(FileExistsError):
                _write_once(destination, {'a': 2})
            self.assertEqual(destination.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
