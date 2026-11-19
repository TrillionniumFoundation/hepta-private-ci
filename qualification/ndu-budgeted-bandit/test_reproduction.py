import copy
import math
import unittest
from verify_reproduction import compare


class ReproductionTests(unittest.TestCase):
    def setUp(self):
        self.example = {'harness_wall_seconds_not_model_cost': 1.0,
                        'all_six_scientific_blockers_remain_open': True,
                        'policy': {'gain': -0.2, 'unsupported_choices': 3}}

    def test_only_root_harness_time_is_excluded(self):
        changed = copy.deepcopy(self.example)
        changed['harness_wall_seconds_not_model_cost'] = 9.0
        compare(changed, self.example)
        changed['policy']['gain'] = .2
        with self.assertRaises(ValueError):
            compare(changed, self.example)

    def test_missing_negative_or_changed_authority_rejected(self):
        for key in ('all_six_scientific_blockers_remain_open', 'policy'):
            changed = copy.deepcopy(self.example)
            del changed[key]
            with self.assertRaises(ValueError):
                compare(changed, self.example)
        changed = copy.deepcopy(self.example)
        changed['all_six_scientific_blockers_remain_open'] = False
        with self.assertRaises(ValueError):
            compare(changed, self.example)

    def test_nonfinite_numeric_results_rejected(self):
        for value in (math.nan, math.inf, -math.inf):
            changed = copy.deepcopy(self.example)
            changed['policy']['gain'] = value
            with self.assertRaises(ValueError):
                compare(changed, self.example)

    def test_counts_and_boolean_types_remain_exact(self):
        changed = copy.deepcopy(self.example)
        changed['policy']['unsupported_choices'] += 1
        with self.assertRaises(ValueError):
            compare(changed, self.example)
        changed = copy.deepcopy(self.example)
        changed['all_six_scientific_blockers_remain_open'] = 1
        with self.assertRaises(ValueError):
            compare(changed, self.example)

    def test_invalid_harness_duration_rejected(self):
        for value in (-1.0, math.nan, math.inf):
            changed = copy.deepcopy(self.example)
            changed['harness_wall_seconds_not_model_cost'] = value
            with self.assertRaises(ValueError):
                compare(changed, self.example)


if __name__ == '__main__':
    unittest.main()
