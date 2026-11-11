"""New v2 analytical fixtures; no claim of recovery or reuse of the lost old24-test evidence."""
import copy
import unittest

from resource_arithmetic import core_table, cost_sum, first_best, first_crossing, matrix_metrics, roster


def rows(arm='hcsn'):
    return [{'name': name, 'arm': arm, 'seed': int(name.split('-s')[1].split('-')[0]),
             'learning_rate': float(name.split('-lr')[1]), 'quality': .4, 'quality_verified': True,
             'independent_adequate': True, 'full_chain_charged_wall_seconds': 100.,
             'known_chain_wall_lower_bound_seconds': 100., 'cumulative_full_CPU_seconds': None,
             'cumulative_CPU_lower_bound_seconds': 70., 'max_attempt_RSS_bytes': 1000,
             'first_observed_target_crossing': {'wall_seconds': 80., 'quality': .35, 'kind': 'complete_epoch'}}
            for name in roster(arm)]


class ArithmeticTests(unittest.TestCase):
    def test_missing_one_lr_candidate_withholds_HCSN_selection_but_keeps_all_costs(self):
        values = rows()
        values[-1].update(quality=None, quality_verified=False, independent_adequate=False)
        result = core_table('hcsn', values)
        self.assertIsNone(result['selected_common_learning_rate'])
        self.assertEqual(result['all_six_opportunity_cost']['all_opportunity_wall_seconds'], 600.)
        self.assertEqual(result['all_six_opportunity_cost']['opportunity_count'], 6)
        with self.assertRaises(ValueError):
            core_table('hcsn', values[:-1])

    def test_common_lr_tie_and_baseline_frozen_choice(self):
        result = core_table('hcsn', rows())
        self.assertEqual(result['selected_common_learning_rate'], .001)
        baseline = rows('gru')
        for row in baseline:
            row['quality'] = .1 if row['learning_rate'] == .001 else .9
        self.assertEqual(core_table('gru', baseline, .001)['selected_common_learning_rate'], .001)

    def test_inadequate_saved_quality_never_grants_training_adequacy(self):
        values = rows()
        values[0]['independent_adequate'] = False
        result = core_table('hcsn', values)
        self.assertEqual(result['selected_statistics']['mean'], .4)
        self.assertEqual(result['selected_independently_adequate_count'], 2)
        self.assertFalse(result['selected_trained_comparison_supported'])

    def test_first_strict_best_and_observed_crossing_exclude_before_training(self):
        points = [{'kind':'development_before','quality':.9,'wall_seconds':1.,'epoch':0},
                  {'kind':'complete_epoch','quality':.31,'wall_seconds':20.,'epoch':1},
                  {'kind':'complete_epoch','quality':.31,'wall_seconds':40.,'epoch':2}]
        self.assertEqual(first_best(points)['epoch'], 1)
        self.assertEqual(first_crossing(points)['wall_seconds'], 20.)

    def test_no_successful_seed_only_median(self):
        values = rows()
        values[0]['first_observed_target_crossing'] = None
        result = core_table('hcsn', values)
        self.assertEqual(result['selected_observed_crossing_count'], 2)
        self.assertIsNone(result['median_first_observed_target_seconds'])

    def test_missing_wrapper_bill_and_cpu_remain_unknown(self):
        values = rows()
        values[0].update(full_chain_charged_wall_seconds=None, known_chain_wall_lower_bound_seconds=30.)
        result = cost_sum(values)
        self.assertIsNone(result['all_opportunity_wall_seconds'])
        self.assertEqual(result['known_wall_lower_bound_seconds'], 530.)
        self.assertTrue(result['known_sum_is_lower_bound'])
        self.assertIsNone(result['all_opportunity_full_CPU_seconds'])
        self.assertEqual(result['known_CPU_lower_bound_seconds'], 420.)
        self.assertEqual(len(result['missing_full_CPU_names']), 6)

    def test_confusion_matrix_fixed_all11_denominator(self):
        cm = [[0]*11 for _ in range(11)]
        cm[0][0] = 7
        support, metrics = matrix_metrics(cm)
        self.assertEqual(support, [7]+[0]*10)
        self.assertEqual(metrics['accuracy'], 1.)
        self.assertEqual(metrics['macro_f1_11_classes'], 1/11)
        self.assertEqual(metrics['macro_f1_present_classes'], 1.)
        bad = copy.deepcopy(cm)
        bad[1][1] = True
        with self.assertRaises(ValueError):
            matrix_metrics(bad)


if __name__ == '__main__':
    unittest.main()
