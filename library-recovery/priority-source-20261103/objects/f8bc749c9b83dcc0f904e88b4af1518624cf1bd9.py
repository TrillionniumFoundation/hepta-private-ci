"""Local proof that loss-proxy mixing can violate a *decoded* hard CVaR cap."""
import copy
import unittest

import numpy as np

from decoded_risk import Criterion, OutputEvidenceError, cvar90, compare_actual_decoded_output


class DecodedRiskTests(unittest.TestCase):
    def setUp(self):
        # Nonlinear decoder D(z)=z^2. Both individual endpoints -1,+1
        # score zero external loss against target=1, yet their midpoint=0
        # is factually wrong. This cannot be detected by linearly blending
        # standalone portfolio-loss vectors.
        self.z_base = -np.ones(11)
        self.inputs = {"z": self.z_base, "delta": np.full(11, 2.)}
        self.targets = np.ones(11)
        self.criteria = Criterion(max_cvar90=.4, max_ambiguity=.5,
                                  min_quality=.5, max_inconsistency=.5,
                                  max_wall_seconds_per_episode=10.,
                                  max_quality_drop=.2, max_cvar_increase=.4)

    @staticmethod
    def generator(public_inputs, weights):
        z = public_inputs["z"] + weights[0] * public_inputs["delta"]
        return {m:z*z for m in ("text", "audio", "image", "video")}  # actual raw decoder

    @staticmethod
    def assessor(predictions, targets):
        error = np.square(predictions["text"] - targets)
        return {"loss": error, "quality": np.float64(error < .01),
                "ambiguity": np.float64(np.zeros_like(error)),
                "inconsistency": np.float64(np.zeros_like(error))}

    def run_record(self, weights=(.5,), **kwargs):
        params = dict(public_inputs=self.inputs, independent_targets=self.targets,
                      episode_ids=[f"world-{i}" for i in range(11)],
                      draw_episode_ids=[f"world-{i}" for i in range(11)], draws_per_episode=1,
                      weights=weights, generate=self.generator,
                      external_score=self.assessor, objective_digest="objective-v1",
                      frozen_model_digest="model-locked-v1", input_cohort_digest="holdout-frozen-v1",
                      criteria=self.criteria)
        params.update(kwargs)
        return compare_actual_decoded_output(**params)

    def test_non_linear_decoded_mix_rejects_false_safety(self):
        rec = self.run_record()
        self.assertEqual(rec["status"], "REJECT_OBSERVED_OUTPUT")
        self.assertAlmostEqual(rec["baseline"]["cvar90"], 0.)
        self.assertAlmostEqual(rec["selected"]["cvar90"], 1.)
        self.assertFalse(rec["passed_local_checks"]["hard_tail"])
        self.assertFalse(rec["passed_local_checks"]["hard_quality"])
        self.assertEqual(rec["authority"], "DENY_ALL")
        self.assertFalse(rec["independent_evidence_authenticated"])
        self.assertFalse(rec["scientific_superiority_proven"])

    def test_full_cell_recovers_correct_end_point_without_granting_authority(self):
        rec = self.run_record(weights=(1.,))
        self.assertEqual(rec["status"], "ADVISORY_ONLY")
        self.assertEqual(rec["selected"]["cvar90"], 0)
        self.assertEqual(rec["authority"], "DENY_ALL")

    def test_fractional_CVaR90_tail_mass(self):
        self.assertAlmostEqual(cvar90([0]*10+[10]), 10/1.1)
        self.assertAlmostEqual(cvar90([0]*13+[4,10]), 8.)
        self.assertEqual(cvar90([0]*19+[10]), 5.)

    def test_episode_aggregation_before_CVaR(self):
        inputs = {"z": np.repeat(self.z_base, 4), "delta": np.full(44, 2.)}
        targets = np.ones(44)
        rec = self.run_record(public_inputs=inputs, independent_targets=targets, draws_per_episode=4,
                              draw_episode_ids=[f"world-{i}" for i in range(11) for _ in range(4)])
        self.assertEqual(rec["episode_count"],11)
        self.assertEqual(rec["draws_per_episode"],4)
        self.assertEqual(rec["selected"]["cvar90"],1.)

    def test_missing_raw_modality_rejected_before_scoring(self):
        def missing_audio(x,weights):
            return {"text": np.zeros(11), "image": np.zeros(11), "video": np.zeros(11)}
        with self.assertRaisesRegex(OutputEvidenceError, "missing decoded output modality"):
            self.run_record(generate=missing_audio)

    def test_missing_unpaired_external_metrics_rejected(self):
        def bad_assessor(y,truth): return {"loss": np.square(y["text"]-truth)}
        with self.assertRaisesRegex(OutputEvidenceError,"four metrics"):
            self.run_record(external_score=bad_assessor)

    def test_nan_external_loss_and_out_of_range_quality_rejected(self):
        def bad_assessor(y,truth):
            rows=self.assessor(y,truth)
            rows["loss"][0]=np.nan
            return rows
        with self.assertRaisesRegex(OutputEvidenceError,"finite"):
            self.run_record(external_score=bad_assessor)
        def bad_quality(y,truth):
            rows=self.assessor(y,truth)
            rows["quality"][:] = 1.1
            return rows
        with self.assertRaisesRegex(OutputEvidenceError,"fraction"):
            self.run_record(external_score=bad_quality)

    def test_disallow_unpaired_draw_order(self):
        inputs = {"z": np.repeat(self.z_base, 4), "delta": np.full(44, 2.)}
        targets = np.ones(44)
        shuffled = [f"world-{i%11}" for i in range(44)]
        with self.assertRaisesRegex(OutputEvidenceError, "unaligned"):
            self.run_record(public_inputs=inputs, independent_targets=targets,
                            draws_per_episode=4, draw_episode_ids=shuffled)

    def test_disallow_overallocated_or_duplicated_sessions(self):
        with self.assertRaisesRegex(OutputEvidenceError,"overbudget"):
            self.run_record(weights=(.8,.4))
        with self.assertRaisesRegex(OutputEvidenceError,"duplicated"):
            self.run_record(episode_ids=["same-world"]*11)

    def test_source_and_truth_independence_not_falsely_attested(self):
        rec=self.run_record(weights=(0,))
        self.assertFalse(rec["independent_evidence_authenticated"])
        self.assertIn("caller-supplied",rec["observed_evaluation_limits"][0])
        self.assertEqual(rec["cell_weights"],[0.])

    def test_observed_hard_resource_budget(self):
        crit=Criterion(max_cvar90=2, max_ambiguity=1, min_quality=0,
                       max_inconsistency=1, max_wall_seconds_per_episode=1e-15,
                       max_quality_drop=1., max_cvar_increase=10.)
        rec=self.run_record(criteria=crit,weights=(1.,))
        self.assertFalse(rec["passed_local_checks"]["hard_generation_wall"])
        self.assertEqual(rec["status"],"REJECT_OBSERVED_OUTPUT")


if __name__ == '__main__':
    unittest.main()
