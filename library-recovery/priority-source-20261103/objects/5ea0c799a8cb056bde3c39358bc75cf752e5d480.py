import unittest
from copy import deepcopy
from p1_real_training_attribution import estimate,TASKS
from fair_ablation import ARMS


def synthetic_complete_data():
    rows=[]
    for seed in (11,23,37):
        for arm in ARMS:
            parts=set() if arm=='control' else set(arm.split('+'))
            rows.append({'seed':seed,'arm':arm,
                         'initial_parameters_sha256':'abc',
                         'parameter_count':193,'train_set_sha256':'train',
                         'holdout_set_sha256':'holdout','training_steps':10,'train_tokens':200,
                         'holdout_accuracy':.5+.02*int('call' in parts)
                                             -.03*int('risk' in parts)+.01*int('margin' in parts)})
    return {'synthetic_fixture':{'seeds':[11,23,37],'rows':rows}}

class RealTrainingFactorial(unittest.TestCase):
    def test_all_7_factorial_effects(self):
        report=estimate(synthetic_complete_data())
        self.assertEqual(report['factorial_effect_count'],7)
        self.assertAlmostEqual(next(x for x in report['main_pair_triple_factorial_effects']
                                    if x['contrast']=='call')['mean_effect'],.02,places=10)
        self.assertFalse(report['any_holm_significant'])
        self.assertEqual(report['attribution_gate'],'DENY')

    def test_incomplete_or_mismatched_is_rejected(self):
        data=synthetic_complete_data()
        data['synthetic_fixture']['rows'].pop()
        with self.assertRaises(ValueError):estimate(data)
        data=synthetic_complete_data()
        data['synthetic_fixture']['rows'][1]['training_steps']=100
        with self.assertRaises(ValueError):estimate(data)

    def test_duplicate_is_rejected(self):
        data=synthetic_complete_data()
        data['synthetic_fixture']['rows'].append(deepcopy(data['synthetic_fixture']['rows'][0]))
        with self.assertRaises(ValueError):estimate(data)

if __name__=='__main__':unittest.main()
