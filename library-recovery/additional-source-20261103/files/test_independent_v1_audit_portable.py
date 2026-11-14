"""Portable positive and corrupt-evidence tests for independent_v1_audit.py."""
import copy
import hashlib
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from independent_v1_audit import audit_episode, cardinality_dp, cvar, text_values


class IndependentAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.artifacts = Path(self.temp.name)
        img = self.artifacts / "pending.png"
        Image.new("RGB", (20, 20), (16, 17, 18)).save(img)
        digest = hashlib.sha256(img.read_bytes()).hexdigest()
        img.rename(self.artifacts / (digest + ".png"))
        boxes = [[0.1, 0.1, 0.4, 0.4]]
        self.reference = {"task_id":"unit", "source_id":"source_1", "label":"dog", "count":1,
                          "largest_side":"left", "boxes":boxes, "image_size":[20,20]}
        self.observation = {"task_id":"unit", "target_category":"dog"}
        components = ["encoder","backbone","cell","controller","critic","verifier","render","communication"]
        costs = [{"component":name,"wall_seconds":0.01,"calls":int(name in ("encoder","backbone"))}
                 for name in components]
        self.ep = {"task_id":"unit","method":"base","seed":23, "boxes":boxes, "label":"dog",
                   "text":"There are 1 dog instances. The largest instance is on the left.",
                   "raw_text":"<loc_100><loc_400>","costs":costs,"actual_wall_seconds":0.08,
                   "budget_cap":10.0,"budget_unit":"wall_seconds","termination":"completed",
                   "artifact_sha256":digest,"score":{
                       "matches":1,"box_f1":1.0,"predicted_count":1,"reference_count":1,
                       "count_correct":True,"largest_side_correct":True,"label_correct":True,
                       "text_consistent":True,"artifact_valid":True,"model_calls":2,
                       "budget_spent":0.08,"budget_exceeded":False,"wall_seconds":0.08,
                       "coverage":1.0,"quality":1.0,"loss":0.0,"severe":0.0,"source_id":"source_1"}}

    def recalc(self, episode=None):
        return audit_episode(episode or self.ep,self.reference,self.observation,self.artifacts,{})

    def test_original_fixture_all_fields(self):
        result=self.recalc()
        self.assertAlmostEqual(result['original_quality'],1)
        self.assertAlmostEqual(result['grounding_only'],1)
        self.assertAlmostEqual(result['template_credit'],0.2)
        self.assertTrue(result['text_exact_template'])
        self.assertTrue(result['label_exact_input_category'])

    def test_non_greedy_global_optimum(self):
        reference=[[0.,0.,.5,.5],[.5,0.,1.,.5]]
        predicted=[[0.,0.,1.,.5],[0.,0.,.5,.5]]
        self.assertEqual(cardinality_dp(predicted,reference),2)

    def test_double_claim_reference_rejected(self):
        self.assertEqual(cardinality_dp([[0.,0.,.5,.5]]*2,[[0.,0.,.5,.5]]),1)

    def test_illogical_text_count(self):
        self.assertIsNone(text_values('There are 0 dog instances. The largest instance is on the left.'))

    def test_fractional_cvar_boundary(self):
        self.assertAlmostEqual(cvar([1.]*6+[0.5]+[0.]*57),(6+0.2)/6.4)

    def test_corrupt_quality_fails_closed(self):
        episode=copy.deepcopy(self.ep);episode['score']['quality']=0.75
        with self.assertRaisesRegex(ValueError,'mismatch'):self.recalc(episode)

    def test_corrupt_predicted_boxes_fails_closed(self):
        episode=copy.deepcopy(self.ep);episode['boxes']=[]
        with self.assertRaisesRegex(ValueError,'mismatch'):self.recalc(episode)

    def test_corrupt_target_label_fails_closed(self):
        episode=copy.deepcopy(self.ep);episode['label']='cat'
        with self.assertRaisesRegex(ValueError,'mismatch'):self.recalc(episode)

    def test_corrupt_wall_ledger_fails_closed(self):
        episode=copy.deepcopy(self.ep);episode['actual_wall_seconds']=0.12
        with self.assertRaisesRegex(ValueError,'wall ledger mismatch'):self.recalc(episode)

    def test_corrupt_artifact_digest_fails_closed(self):
        episode=copy.deepcopy(self.ep);episode['artifact_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'missing, linked, or oversized PNG'):self.recalc(episode)

    def test_missing_cost_component_fails_closed(self):
        episode=copy.deepcopy(self.ep);episode['costs']=episode['costs'][1:]
        with self.assertRaisesRegex(ValueError,'missing cost components'):self.recalc(episode)


if __name__ == '__main__':unittest.main()
