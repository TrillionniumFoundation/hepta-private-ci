"""Actual supported-kernel chain with artificial publisher fixtures, not mmBERT."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fbsde_acquisition_study import run
from fbsde_acquisition_audit import audit
from fbsde_acquisition_data import INTENTS
from fbsde_acquisition_support import SUPPORTED_KERNEL
from fbsde_acquisition_observe import ViewBudgetExceeded
from four_gate_common import digest


class SupportedKernelTensorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); cls.root = Path(cls.temp.name)/'run'
        cls.parts = {}
        for split, per_class in (('fit', 3), ('kernel', 4), ('selection', 1), ('validation', 1), ('test', 2)):
            cls.parts[split] = [{'id': f'{split}-{label}-{i}',
                'text': f'please {name} request fixture {split} {i}', 'label': label,
                'text_sha256': digest(f'please {name} request fixture {split} {i}')}
                for label, name in enumerate(INTENTS) for i in range(per_class)]
        with patch('fbsde_acquisition_study.load_publisher', return_value={}), \
             patch('fbsde_acquisition_study.partition', return_value=cls.parts):
            cls.result = run(cls.root, kernel_profile=SUPPORTED_KERNEL)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_frozen_training_choice_and_strong_control_execute(self):
        self.assertEqual(len(self.result['metrics']), 10)
        self.assertIn('full_symbol', self.result['metrics'])
        self.assertTrue(self.result['compiled_vs_bsde_predictions_equal'])
        self.assertFalse(self.result['production_promotion_permitted'])
        self.assertEqual(len(json.loads((self.root/'kernel-selection.json').read_text())['scores']), 5)
        self.assertTrue(audit(self.root, self.parts)['original_arithmetic_recomputed'])

    def test_prior_mass_does_not_count_as_raw_support(self):
        for bins in self.result['posterior_support'].values():
            self.assertEqual(sum(x['cases'] for x in bins.values()), 16)
            if bins['zero']['cases']: self.assertEqual(bins['zero']['minimum_raw_support'], 0)

    def test_all_attempts_accounted_and_old_budget_unchanged(self):
        plan = json.loads((self.root/'plan.json').read_text())
        self.assertEqual(plan['prediction_cpu_limit_ns'], 100_000_000)
        for split in ('validation', 'test'):
            attempts = [json.loads(x) for x in (self.root/f'{split}-view-attempts.jsonl').read_text().splitlines()]
            self.assertTrue(all(a['status'] == 'returned' for a in attempts))
            self.assertEqual(len(attempts), sum(len(json.loads(row)['events'])
                for arm in plan['arms'] for row in (self.root/f'{split}-{arm}.jsonl').read_text().splitlines()))

    def test_changed_cv_result_cannot_pass_with_unchanged_kernel(self):
        path = self.root/'kernel-selection.json'; old = path.read_bytes()
        try:
            obj = json.loads(old); obj['selected'] = 'not-registered'; path.write_text(json.dumps(obj))
            with self.assertRaises(ValueError): audit(self.root, self.parts)
        finally: path.write_bytes(old)

    def test_missing_attempt_cannot_be_hidden_by_terminal_score(self):
        path = self.root/'test-view-attempts.jsonl'; old = path.read_bytes()
        try:
            path.write_bytes(b'\n'.join(old.splitlines()[:-1])+b'\n')
            with self.assertRaisesRegex(ValueError, 'attempt'): audit(self.root, self.parts)
        finally: path.write_bytes(old)

    def test_failed_trial_preserves_completed_preparation(self):
        destination = Path(self.temp.name)/'failed'
        with patch('fbsde_acquisition_study.load_publisher', return_value={}), \
             patch('fbsde_acquisition_study.partition', return_value=self.parts), \
             patch('fbsde_acquisition_study.observe_view', side_effect=ViewBudgetExceeded('forced fixture overrun')):
            with self.assertRaises(ViewBudgetExceeded): run(destination)
        for name in ('physical.json', 'candidate-head.pt', 'preparation-forwards.json', 'preparation-jobs.json', 'failure.json'):
            self.assertTrue((destination/name).is_file())
        self.assertFalse((destination/'results.json').exists())
        self.assertFalse(json.loads((destination/'failure.json').read_text())['run_complete'])


if __name__ == '__main__': unittest.main()
