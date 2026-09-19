import unittest
from hepta_ledger_scale import METRICS, validate


class ScaleOutputTests(unittest.TestCase):
    def sample(self):
        return {'schema': 'hepta.ledger-core-scale.v1', 'records': 10,
                'persistence_measured': False, **{key: 0 for key in METRICS}}

    def test_native_example_metric_names(self):
        value = self.sample()
        self.assertIs(validate(value, 10), value)
        self.assertIn('retry_1000_ns', METRICS)
        self.assertIn('lookup_10000_ns', METRICS)
        self.assertIn('full_recovery_ns', METRICS)

    def test_count_mismatch(self):
        with self.assertRaises(ValueError):
            validate(self.sample(), 11)

    def test_no_manufactured_persistence_claim(self):
        value = self.sample()
        value['persistence_measured'] = True
        with self.assertRaises(ValueError):
            validate(value, 10)

    def test_missing_or_non_numeric_metrics(self):
        for invalid in (None, True, -1, '123', 1.2):
            value = self.sample()
            value['append_ns'] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate(value, 10)

    def test_unrelated_json_is_not_evidence(self):
        for value in ([], {}, {'schema': 'other'}, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate(value, 10)


if __name__ == '__main__':
    unittest.main()
