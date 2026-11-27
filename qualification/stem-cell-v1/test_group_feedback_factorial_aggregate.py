"""Independent synthetic negatives for six fixed-seed pretrained factorial slots."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from group_feedback_factorial_aggregate import audit_six, SEEDS, PROFILES, FACTORS, COHORTS, MODES


def report(seed, profile):
    result = dict(schema='hepta.group.feedback-factorial-independent.v1',
        passed=True, authority='DENY_ALL', production_promotion_permitted=False,
        independently_future_tested=False, causal_quality_or_10t_equivalence_proven=False,
        equal_total_compute_demonstrated=False, protocol_seed=seed, training_profile=profile,
        reference='legacy_oracle',
        arm_protocol_sha256={factor:format(i + 2, '064x') for i, factor in enumerate(FACTORS)},
        costs={}, descriptive_paired={})
    for factor in FACTORS:
        result['costs'][factor] = dict(actual_lifecycle_cpu_ns=1000, encoder_cpu_ns=100,
          teacher_cpu_ns=20, critic_cpu_ns=10, train_cpu_ns=500,
          oracle_feedback_calls=0 if factor.endswith('no_verifier') else 6,
          terminal_supervised_steps=40 if factor.startswith('guarded') else 0,
          terminal_withheld_steps=8 if factor.startswith('guarded') else 0)
    for cohort in COHORTS:
        result['descriptive_paired'][cohort] = {}
        for mode in MODES:
            result['descriptive_paired'][cohort][mode] = {}
            for factor, correct in zip(FACTORS, (4, 3, 5, 6)):
                result['descriptive_paired'][cohort][mode][factor] = dict(
                    cases=8, correct=correct, rescued=max(correct - 4, 0),
                    harmed=max(4 - correct, 0), online_cpu_ns=120,
                    measured_steps=8, verifier_calls=0 if mode == 'attention' else 8)
    return result


class AggregateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.files = {}
        self.records = {}
        for seed in SEEDS:
            for profile in PROFILES:
                path = Path(self.temp.name)/f'{seed}-{profile}.json'
                value = report(seed, profile)
                path.write_text(json.dumps(value))
                self.files[seed, profile] = path
                self.records[seed, profile] = value

    def test_six_replay_no_promotion_and_exact_integer_interactions(self):
        result = audit_six(self.files)
        self.assertTrue(result['passed'])
        self.assertEqual(result['six_source_optimizer_blocks'], 6)
        self.assertEqual(result['physical_training_arms'], 24)
        self.assertEqual(result['total_prep_and_execution_cpu_ns'], 24000)
        self.assertFalse(result['winner_selected'])
        self.assertFalse(result['future_natural_task_efficacy_proven'])
        row = result['by_block'][0]
        self.assertEqual(row['guard_effect_oracle'], 1)
        self.assertEqual(row['guard_effect_no_verifier'], 3)
        self.assertEqual(row['interaction'], 2)

    def test_reject_missing_extra_or_duplicate_blocks(self):
        missing = dict(self.files)
        missing.pop(next(iter(missing)))
        with self.assertRaises(ValueError):
            audit_six(missing)
        missing['fake', 'sgd_v1'] = next(iter(self.files.values()))
        with self.assertRaises(ValueError):
            audit_six(missing)

    def test_reject_forged_shas_and_broken_provenance(self):
        for key, value in (
            ('authority', 'CAN_EXECUTE'),
            ('production_promotion_permitted', True),
            ('equal_total_compute_demonstrated', True),
            ('protocol_seed', 99),
            ('training_profile', 'posthoc'),
            ('independently_future_tested', True)):
            with self.subTest(key=key):
                self.mutate(lambda r: r.__setitem__(key, value))

    def mutate(self, mutator):
        original = self.records[41, 'sgd_v1']
        candidate = copy.deepcopy(original)
        mutator(candidate)
        self.files[41, 'sgd_v1'].write_text(json.dumps(candidate))
        with self.assertRaises(ValueError):
            audit_six(self.files)
        self.files[41, 'sgd_v1'].write_text(json.dumps(original))

    def test_reject_missing_modes_and_fake_paired_aggregates(self):
        self.mutate(lambda r: r['descriptive_paired']['test'].pop('attention_fixed'))
        self.mutate(lambda r: r['descriptive_paired']['test']['attention']['guarded_oracle'].update(correct=7))
        self.mutate(lambda r: r['descriptive_paired']['test']['attention']['legacy_no_verifier'].update(cases=5))

    def test_reject_mask_or_callback_budget_falsehoods(self):
        self.mutate(lambda r: r['costs']['guarded_oracle'].update(terminal_withheld_steps=0))
        self.mutate(lambda r: r['costs']['legacy_oracle'].update(oracle_feedback_calls=0))
        self.mutate(lambda r: r['costs']['guarded_no_verifier'].update(oracle_feedback_calls=1))
        self.mutate(lambda r: r['costs']['guarded_no_verifier'].update(actual_lifecycle_cpu_ns=0))

    def test_reject_duplicate_json_and_nan_using_original_strict_reader(self):
        p = self.files[41, 'sgd_v1']
        original = p.read_text()
        try:
            p.write_text('{"x": 1, "x": 2}')
            with self.assertRaises(ValueError): audit_six(self.files)
            p.write_text(original.replace('"cases": 8', '"cases": NaN'))
            with self.assertRaises(ValueError): audit_six(self.files)
        finally:
            p.write_text(original)

if __name__ == '__main__':
    unittest.main()
