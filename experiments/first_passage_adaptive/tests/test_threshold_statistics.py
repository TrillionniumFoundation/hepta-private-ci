import copy
import json
from pathlib import Path
import unittest

import numpy as np

from experiments.first_passage_adaptive.threshold_statistics import summarize
from experiments.first_passage_adaptive.review.paired_cluster_reference import summarize as independent_reference


def artificial(config, *, varying=False):
    rng = np.random.default_rng(9983)
    records,effects,fits,strata = [],[],[],[]
    for fi,fit in enumerate(config["fit_seeds"]):
        for si,(stratum,count) in enumerate(zip(config["strata"],(1,2,5))):
            for _ in range(count):
                delta = np.array([.02+.01*fi+.03*si,.04+.02*fi+.01*si])
                if varying:
                    delta += rng.normal(0,.002,size=2)
                value = float(rng.normal())
                records.append({"fit_seed":fit,"stratum":stratum,"arms":{
                    "fixed_threshold":{"mean_utility":value-delta[0]},
                    "ordinary_context_threshold":{"mean_utility":value-delta[1]},
                    "value_threshold":{"mean_utility":value}}})
                effects.append(delta)
                fits.append(fit)
                strata.append(stratum)
    return records,np.asarray(effects),fits,strata


class RegisteredBootstrapTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1]/"ADAPTIVE_PROTOCOL.json"
        self.config = json.loads(path.read_text())["threshold_study"]

    def test_artificial_contexts_match_independent_reference(self):
        records,effects,fits,strata = artificial(self.config,varying=True)
        actual = summarize(records,self.config)
        reference = independent_reference(effects,fits,strata,fit_order=self.config["fit_seeds"],
                                          stratum_order=self.config["strata"])
        for name in ("counts_by_fit_stratum","per_fit_pooled_means","pooled_effects",
                     "pooled_intervals","stratum_effects","stratum_intervals"):
            np.testing.assert_allclose(actual[name],reference[name],rtol=0,atol=1e-14)
        self.assertEqual(actual["primary_gate"],reference["primary_gate"])
        self.assertEqual(actual["cross_stratum_gate"],reference["cross_stratum_gate"])

    def test_unequal_cell_counts_do_not_change_registered_equal_weights(self):
        records,effects,_,_ = artificial(self.config)
        result = summarize(records,self.config)
        np.testing.assert_allclose(result["pooled_effects"],[.06,.07],atol=1e-15)
        self.assertFalse(np.allclose(effects.mean(axis=0),result["pooled_effects"]))
        self.assertTrue(result["primary_gate"] and result["cross_stratum_gate"])

    def test_negative_fit_is_veto_even_when_pooled_bounds_pass(self):
        records,_,_,_ = artificial(self.config)
        for row in records:
            if row["fit_seed"] == self.config["fit_seeds"][0]:
                row["arms"]["value_threshold"]["mean_utility"] -= .1
        result = summarize(records,self.config)
        self.assertTrue(np.all(np.asarray(result["pooled_intervals"])[:,0] > .005))
        self.assertFalse(result["primary_gate"])
        self.assertFalse(result["cross_stratum_gate"])

    def test_cross_stratum_gate_cannot_hide_a_bad_stratum(self):
        records,_,_,_ = artificial(self.config)
        for row in records:
            row["arms"]["value_threshold"]["mean_utility"] += (.1 if row["stratum"] != self.config["strata"][0] else -.15)
        result = summarize(records,self.config)
        self.assertTrue(result["primary_gate"])
        self.assertFalse(result["cross_stratum_gate"])

    def test_pairing_preserves_common_context_noise(self):
        records,_,_,_ = artificial(self.config,varying=True)
        original = summarize(records,self.config)
        for index,row in enumerate(records):
            for arm in row["arms"].values():
                arm["mean_utility"] += 10*index
        changed = summarize(records,self.config)
        np.testing.assert_allclose(original["pooled_intervals"],changed["pooled_intervals"],atol=1e-12)
        np.testing.assert_allclose(original["stratum_intervals"],changed["stratum_intervals"],atol=1e-12)

    def test_missing_cells_and_nonfinite_utilities_are_rejected(self):
        records,_,_,_ = artificial(self.config)
        with self.assertRaises(ValueError):
            summarize(records[1:],self.config)
        broken = copy.deepcopy(records)
        broken[0]["arms"]["value_threshold"]["mean_utility"] = float("nan")
        with self.assertRaises(ValueError):
            summarize(broken,self.config)
        broken = copy.deepcopy(self.config)
        broken["family_comparisons"] = 7
        with self.assertRaises(ValueError):
            summarize(records,broken)


if __name__ == "__main__":
    unittest.main()
