"""Original V6 genuine archived labels/probabilities, no new training or Torch."""
from pathlib import Path
import json
import math
import tempfile
import unittest
import zipfile

import bridge_portable_v74 as p
import bridge_portable_v74_review as r

from test_bridge_portable_v74 import PATHS


class GenuineArchivedScoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=p.originals(**PATHS)
        cls.rows=cls.source["source"]["reader_train"]
        cls.historical=[]
        with zipfile.ZipFile(PATHS["v6"]) as z:
            for seed in p.SEEDS:
                path=f"reader-v6-bridge/seed-{seed}/bridge/warmup-binding-train.json"
                cls.historical.append(json.loads(z.read(path)))

    def test_actual_archived_three_seed_train_accuracy(self):
        for item in self.historical:
            res=r.old_score(self.rows,item["probabilities"])
            self.assertEqual(res["original_candidate_correct"],128)
            self.assertEqual(res["original_world_pair_correct"],64)
            for key in ("accuracy","both_worlds_correct","evidence_switch_rate"):
                self.assertAlmostEqual(res[key],item["metrics"][key],places=12)

    def test_prediction_mutation_changes_metrics(self):
        x=list(self.historical[0]["probabilities"])
        x[0]=1.0-x[0]
        res=r.old_score(self.rows,x)
        self.assertEqual(res["original_candidate_correct"],127)
        self.assertEqual(res["original_world_pair_correct"],63)

    def test_incomplete_model_probabilities_refused(self):
        with self.assertRaisesRegex(ValueError,"complete finite"):
            r.old_score(self.rows,self.historical[0]["probabilities"][:-1])

    def test_nan_probability_refused(self):
        vals=list(self.historical[1]["probabilities"])
        vals[0]=float('nan')
        with self.assertRaisesRegex(ValueError,"finite"):
            r.old_score(self.rows,vals)

    def test_boolean_masquerading_as_probabilities_refused(self):
        vals=list(self.historical[0]["probabilities"])
        vals[0]=True
        with self.assertRaisesRegex(ValueError,"finite"):
            r.old_score(self.rows,vals)

    def test_unregistered_world_rejected(self):
        x=[dict(i) for i in self.rows]
        x[0]["paragraph_id"]="fabricated"
        with self.assertRaisesRegex(ValueError,"paired-world"):
            r.old_score(x,self.historical[0]["probabilities"])

    def test_duplicate_original_world_rejected(self):
        x=[dict(i) for i in self.rows]
        x[2]["paragraph_id"]=x[0]["paragraph_id"]
        with self.assertRaisesRegex(ValueError,"duplicate world"):
            r.old_score(x,self.historical[0]["probabilities"])

    def test_json_duplicate_property_denied(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"bad.json"
            path.write_text('{"status":"success","status":"DENY_ALL"}')
            with self.assertRaisesRegex(ValueError,"duplicate receipt"):
                r.read(path)

    def test_missing_nine_arm_output_denied_not_passed(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ValueError,"bounded real receipt"):
                r.read(Path(d)/"completed.json")

    def test_untruthful_future_flag_in_original_training_denied(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"completed.json"
            path.write_text('{"old_task_future_retention_verified":true}')
            payload=r.read(path)
            with self.assertRaisesRegex(ValueError,"self-certify"):
                r.deny_unobserved_future(payload)


if __name__=="__main__":
    unittest.main()
