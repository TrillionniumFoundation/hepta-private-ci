"""Original source-pinned three-seed negative and tamper regressions."""
import copy
from pathlib import Path
import unittest
import group_v2_independent_negative as ancestor
import group_v2_seedwise_contrast as stage

SOURCE=Path(__file__).with_name('GROUP_REASONING_V2_3SEED_20261015.json')

class SeedwiseOriginal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.actual=ancestor.read_original(SOURCE)
        cls.result=stage.evaluate(cls.actual)

    def test_real_three_seed_deltas(self):
        self.assertEqual([x['split_correct_delta'] for x in self.result['rows']],[-3,3,0])
        self.assertEqual([x['ndu_correct_delta'] for x in self.result['rows']],[-4,-1,0])

    def test_cpu_overheads_all_positive(self):
        for row in self.result['rows']:
            self.assertGreater(row['split_cpu_ratio'],6)
            self.assertGreater(row['ndu_cpu_ratio'],2)

    def test_all_three_split_selections_rejected(self):
        self.assertTrue(all(not row['split_admitted'] and row['selected_model']=='core'
                            for row in self.result['rows']))

    def test_original_report_stays_unpromoted(self):
        for name in ('split_winner','ndu_winner','natural_future_gain',
                     'production_accepted','true_equal_lifecycle_costs',
                     'original_archive_zip_reopened'):
            self.assertIs(self.result[name],False)

    def test_tampered_seed_correct_denied(self):
        b=copy.deepcopy(self.actual)
        b['runs']['41']['test']['split']['correct']+=1
        with self.assertRaises(ancestor.Denied):stage.evaluate(b)

    def test_tampered_seed_cost_denied(self):
        b=copy.deepcopy(self.actual)
        b['runs']['47']['test']['ndu']['cpu_ns']=0
        with self.assertRaises(ancestor.Denied):stage.evaluate(b)

    def test_false_split_admission_denied(self):
        b=copy.deepcopy(self.actual)
        b['runs']['53']['selected_model']='split'
        with self.assertRaises(ancestor.Denied):stage.evaluate(b)

    def test_missing_training_seed_denied(self):
        b=copy.deepcopy(self.actual)
        del b['runs']['53']
        with self.assertRaises(ancestor.Denied):stage.evaluate(b)

if __name__=='__main__':
    unittest.main()
