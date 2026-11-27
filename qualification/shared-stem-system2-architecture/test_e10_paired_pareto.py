"""Fixed-panel arithmetic, strict claims and independent two-reviewer parity."""
import copy
from fractions import Fraction
import json
from pathlib import Path
import unittest
from e10_paired_pareto import review,holm,exact_mcnemar

ROOT=Path(__file__).resolve().parent
# On GitHub all three sources live in this same qualified research directory.
PRIMARY=ROOT/'observations'/'E7_ORIGINAL_PHYSICAL_RETROSPECTIVE_20261015.json'
SECOND=ROOT/'observations'/'E7_INDEPENDENT_SECOND_ALGORITHM_20261015.json'


class E10PairedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.primary=json.loads(PRIMARY.read_text())
        cls.secondary=json.loads(SECOND.read_text())

    def test_exact_paired_null_and_tie(self):
        self.assertEqual(exact_mcnemar(0,0),Fraction(1))
        self.assertEqual(exact_mcnemar(5,5),Fraction(1))
        self.assertEqual(exact_mcnemar(3,7),Fraction(11,32))
        self.assertEqual(exact_mcnemar(3,13),Fraction(697,32768))
        self.assertEqual(exact_mcnemar(4,53),Fraction(106481,18014398509481984))

    def test_holm_monotonic(self):
        p={'mmbert_only':Fraction(1,1000),'gate_conf_075':Fraction(1,20),
           'gate_conf_090':Fraction(1,25),'gate_conf_098':Fraction(1,10)}
        result=holm(p)
        self.assertEqual(result['mmbert_only'],Fraction(1,250))
        self.assertGreaterEqual(result['gate_conf_090'],result['mmbert_only'])
        self.assertGreaterEqual(result['gate_conf_075'],result['gate_conf_090'])
        self.assertEqual(result['gate_conf_098'],Fraction(3,25))

    def test_invalid_discordance(self):
        for w,l in [(-1,1),(129,0),(1,128),(True,0),(0,1.5)]:
            with self.subTest(w=w,l=l),self.assertRaises(ValueError):exact_mcnemar(w,l)

    def test_all_registered_policies_dominated_historical_not_future(self):
        x=review(self.primary,self.secondary)
        self.assertTrue(x['all_four_policies_strictly_dominated_in_registered_historical_metrics'])
        self.assertEqual(x['original_label_oracle_upper_correct'],126)
        self.assertFalse(x['source_family_future_time_generalization'])
        self.assertEqual(x['decision'],'NO_GO_FOR_PROMOTION')
        self.assertEqual(x['models']['gate_conf_075']['delta_correct'],-4)
        self.assertEqual(x['models']['gate_conf_090']['holm_four_hypotheses_adjusted_p'],'697/16384')
        self.assertFalse(x['production_accepted'])

    def test_independent_reviewer_mismatch_rejected(self):
        for attr,value in [('correct',120),('archived_per_case_wall_proxy_ns_sum',4),
                           ('paired_recovered_from_granite',12),('hypothetical_secondary_model_calls',500)]:
            second=copy.deepcopy(self.secondary)
            second['arms']['gate_conf_075'][attr]=value
            with self.subTest(attr=attr),self.assertRaises(ValueError):
                review(self.primary,second)

    def test_false_future_authority_or_live_calls_rejected(self):
        primary=copy.deepcopy(self.primary)
        primary['actual_on_demand_encoder_calls_executed']=1
        with self.assertRaises(ValueError):review(primary,self.secondary)
        primary=copy.deepcopy(self.primary);primary['production_accepted']=True
        with self.assertRaises(ValueError):review(primary,self.secondary)
        second=copy.deepcopy(self.secondary);second['model_winner_selected']=True
        with self.assertRaises(ValueError):review(self.primary,second)

    def test_false_oracle_or_subset_rejected(self):
        second=copy.deepcopy(self.secondary)
        second['paired_correctness']['oracle_extra_correct_over_granite']=49
        with self.assertRaises(ValueError):review(self.primary,second)
        first=copy.deepcopy(self.primary);del first['arms']['gate_conf_075']
        with self.assertRaises(ValueError):review(first,self.secondary)

    def test_wrong_paired_counts_rejected(self):
        first=copy.deepcopy(self.primary)
        first['arms']['gate_conf_075']['paired_lost_from_granite']=18
        second=copy.deepcopy(self.secondary)
        second['arms']['gate_conf_075']['paired_lost_from_granite']=18
        with self.assertRaises(ValueError):review(first,second)


if __name__=='__main__':unittest.main()
