"""Retrospective case-level uncertainty tests; real originals optional, never inferred."""
from __future__ import annotations
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np
import v18_source_first_uncertainty as m


class Mechanism(unittest.TestCase):
    def test_correlated_seeds_have_only_32_resampling_units(self):
        matrix=np.random.default_rng(m.RNG_SEED).integers(0,32,(m.RESAMPLES,32))
        result=m.paired_interval(np.zeros(32), matrix)
        self.assertEqual(result["case_mean"],0.)
        self.assertEqual(result["raw_descriptive_95"],[0.,0.])
        self.assertEqual(result["multiplicity_adjusted_descriptive_95"],[0.,0.])
        self.assertEqual(result["case_mean_ties"],32)

    def test_deterministic_case_resampling(self):
        a=np.random.default_rng(m.RNG_SEED).integers(0,32,(m.RESAMPLES,32))
        b=np.random.default_rng(m.RNG_SEED).integers(0,32,(m.RESAMPLES,32))
        self.assertTrue(np.array_equal(a,b))
        sample=np.linspace(-.1,.1,32)
        self.assertEqual(m.paired_interval(sample,a),m.paired_interval(sample,b))

    def test_negative_gain_is_disadvantage(self):
        matrix=np.arange(32)[None,:].repeat(m.RESAMPLES,axis=0)
        x=m.paired_interval(np.full(32,-.15),matrix)
        self.assertAlmostEqual(x["case_mean"],-.15)
        self.assertEqual(x["case_mean_losses"],32)

    def test_cases_and_scores_not_expanded_by_seed(self):
        self.assertEqual(m.RESAMPLES,4096)
        self.assertEqual(len(m.SEEDS),3)
        self.assertEqual(len(m.ARMS),12)
        self.assertNotIn(m.REFERENCE,m.ARMS)

    def test_wrong_probability_dimensions_denied(self):
        for rows in ([.25]*4,[[.25]*4]*31,[[.26]*4]*32,[[float("nan")]*4]*32):
            with self.subTest(shape=np.asarray(rows).shape):
                with self.assertRaises(ValueError):m.bounded_probabilities(rows)

    def test_create_only_archive_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            o=Path(tmp)/"out.json"
            o.write_text("{}")
            with self.assertRaises(FileExistsError):
                with o.open("xb") as f:f.write(m.canonical({"foo":1}))

    def test_known_model_digest_rules(self):
        self.assertEqual(m.predecessor.ARCHIVE,
            "0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7")


@unittest.skipUnless(all(os.environ.get(x) for x in ("HEPTA_V18_INPUTS","HEPTA_V18_V15","HEPTA_V18_V16","HEPTA_V18_V17")),
                     "exact original saved state is required; never count skips as original evidence")
class Original(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.paths=[Path(os.environ[x]) for x in ("HEPTA_V18_INPUTS","HEPTA_V18_V15","HEPTA_V18_V16","HEPTA_V18_V17")]
        cls.report=m.audit(*cls.paths)

    def test_original_82_saved_tensors_and_32_cases(self):
        self.assertEqual(self.report["independent_model_bytes_verified"],82)
        self.assertEqual(self.report["distinct_original_calibration_cases"],32)
        self.assertEqual(self.report["resampling_units"],32)
        self.assertEqual(self.report["candidate_arm_count"],12)
        self.assertFalse(self.report["source_family_independence_authenticated"])
        self.assertEqual(self.report["prospective_outcomes"],0)
        self.assertFalse(self.report["scientific_promotion_authorized"])
        self.assertFalse(self.report["production_authorized"])
        self.assertIsNone(self.report["model_selected"])
        self.assertIsNone(self.report["future_utility_gain"])

    def test_negative_alignment_and_small_infeasible_oracle(self):
        self.assertLess(self.report["arms"]["geo_aligned_oof"]["case_mean"],0)
        self.assertLess(self.report["arms"]["v16_final_loss_gate"]["case_mean"],0)
        self.assertGreater(self.report["infeasible_oracle"]["case_mean"],0)
        self.assertFalse(self.report["infeasible_oracle"]["deployable"])
        self.assertTrue(self.report["infeasible_oracle"]["uses_calibration_labels"])

    def test_two_archived_runs_identical_no_time_field(self):
        output=m.audit(*self.paths)
        self.assertEqual(m.canonical(output),m.canonical(self.report))

    def test_external_rehashed_calibration_prediction_detected(self):
        inputs,v15,v16,v17=self.paths
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/"v17"
            shutil.copytree(v17,out)
            data=json.loads((out/"sealed.json").read_bytes())
            data["seeds"]["41"]["calibration_probabilities"]["geo_aligned_oof"][0]=[1,0,0,0]
            (out/"sealed.json").write_bytes(m.canonical(data))
            with self.assertRaises(ValueError):m.audit(inputs,v15,v16,out)

    def test_fabricated_future_and_production_denied(self):
        inputs,v15,v16,v17=self.paths
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/"v17"
            shutil.copytree(v17,out)
            data=json.loads((out/"sealed.json").read_bytes())
            data["production_authorized"]=True
            (out/"sealed.json").write_bytes(m.canonical(data))
            with self.assertRaises(ValueError):m.audit(inputs,v15,v16,out)

    def test_hidden_holdout_label_injected_denied(self):
        inp,v15,v16,v17=self.paths
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/"inputs"
            shutil.copytree(inp,out)
            data=json.loads((out/"input.json").read_bytes())
            data["labels"][str(data["partitions"]["holdout"][0])]=0
            (out/"input.json").write_bytes(m.canonical(data))
            with self.assertRaises(ValueError):m.cases_from_validated_inputs(out)


if __name__ == "__main__":
    unittest.main()
