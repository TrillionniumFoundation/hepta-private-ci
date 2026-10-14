"""Full model learning + conditional verification; explicit generated data."""
import json
from pathlib import Path
import tempfile
import unittest
from fbsde_tracking_study import run
from fbsde_tracking_control_audit import audit

class ControllerTensorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.path=Path(cls.temp.name)/'run'
        cls.report=run(cls.path,feature_profile='local_participant_v2',
                       record_profile='serialized_records_v2',control_profile='learned_belief_v1')
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_sealed_original_predictions_audit(self):
        r=audit(self.path)
        self.assertEqual(r['original_tasks'],192);self.assertEqual(r['audited_outputs'],1344)
        self.assertFalse(r['risk_qualification_passed'])

    def test_exact_reference_and_all_verify_still_match(self):
        a=self.report['summary']
        self.assertEqual(a['verify_all']['correct'],192)
        self.assertEqual(a['exact_reverse']['correct'],192)
        self.assertEqual(a['verify_all']['verification_calls'],960)

    def test_rehashed_wrong_conditional_law_rejected(self):
        p=self.path/'controller-priors.json';raw=p.read_bytes()
        try:
            rows=json.loads(raw);rows[0]['laws'][0].reverse();p.write_text(json.dumps(rows))
            with self.assertRaisesRegex(ValueError,'binding'):audit(self.path)
        finally:p.write_bytes(raw)

    def test_changed_answer_not_counted_correct(self):
        p=self.path/'controller-ndu_two_step.json';raw=p.read_bytes()
        try:
            rows=json.loads(raw);rows[0]['text']='unsupported conclusion';p.write_text(json.dumps(rows))
            with self.assertRaisesRegex(ValueError,'decoded'):audit(self.path)
        finally:p.write_bytes(raw)

    def test_unpaid_verifications_rejected(self):
        p=self.path/'controller-verify_all.json';raw=p.read_bytes()
        try:
            rows=json.loads(raw);rows[0]['modeled_cost']=0;p.write_text(json.dumps(rows))
            with self.assertRaisesRegex(ValueError,'cost'):audit(self.path)
        finally:p.write_bytes(raw)

    def test_simulator_calibration_and_no_benchmark_training(self):
        r=json.loads((self.path/'controller-calibration.json').read_text())
        self.assertFalse(r['benchmark_rows_used']);self.assertEqual(r['fit']['rows'],360)
        self.assertFalse(self.report['learned_ndu_superiority_claimed'])

if __name__=='__main__':unittest.main()
