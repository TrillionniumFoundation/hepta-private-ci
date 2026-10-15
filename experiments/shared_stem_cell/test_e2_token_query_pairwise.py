"""Model-free paired source and unadjusted significance fault injection."""
import unittest

from e2_pairwise_evidence import paired, Invalid


class Tests(unittest.TestCase):
    def setUp(self):
        self.rows=[{"case_id":str(i),"label":int(i%2),"source_group":f"g{i}"}
                   for i in range(64)]
        self.y={r["case_id"]:float(r["label"]) for r in self.rows}

    def test_perfect_vs_zero_exact_mcnemar_no_authority(self):
        x=paired(self.rows,self.y,{k:1-v for k,v in self.y.items()})
        self.assertEqual((x["left_only_correct"],x["right_only_correct"]),(64,0))
        self.assertAlmostEqual(x["exact_mcnemar_two_sided_unadjusted_p"],2.0**-63)
        self.assertEqual(x["left_minus_right_accuracy"],1)
        self.assertFalse(x["statistical_stem_winner_selected"])
        self.assertFalse(x["independent_ndu_benefit_verified"])
        self.assertEqual(x["authority"],"DENY_ALL")

    def test_equal_predictions_and_empty_discordance(self):
        x=paired(self.rows,self.y,self.y)
        self.assertEqual(x["both_correct"],64)
        self.assertEqual(x["exact_mcnemar_two_sided_unadjusted_p"],1.0)
        self.assertEqual(x["left_minus_right_brier"],0)

    def test_one_discordance_is_not_significant(self):
        bad=self.y.copy();bad["0"]=1.0
        x=paired(self.rows,self.y,bad)
        self.assertEqual((x["left_only_correct"],x["right_only_correct"]),(1,0))
        self.assertEqual(x["exact_mcnemar_two_sided_unadjusted_p"],1.0)

    def test_brier_delta_without_accuracy_delta(self):
        calibrated={k:(.6 if v else .4) for k,v in self.y.items()}
        x=paired(self.rows,self.y,calibrated)
        self.assertEqual(x["left_minus_right_accuracy"],0)
        self.assertLess(x["left_minus_right_brier"],0)

    def test_reject_missing_duplicate_nonfinite_bool_or_missing_group(self):
        missing={k:v for k,v in self.y.items() if k!="0"}
        tampered=[{**self.y,"extra":.25},missing,
                  {**self.y,"0":float("nan")},{**self.y,"0":True}]
        for x in tampered:
            with self.assertRaises(Invalid):
                paired(self.rows,self.y,x)
        with self.assertRaises(Invalid):
            paired(self.rows+[self.rows[0]],self.y,self.y)
        with self.assertRaises(Invalid):
            paired([{**self.rows[0],"source_group":""}],{"0":1.0},{"0":.5})
        with self.assertRaises(Invalid):
            paired([{**self.rows[0],"label":True}],{"0":1.0},{"0":.5})


if __name__=="__main__":
    unittest.main()
