"""Actual tiny-Head fitting and common-member inference, with simulator inputs."""
import json
from pathlib import Path
import tempfile
import unittest

from fbsde_tracking_study import run
from fbsde_tracking_mixture_audit import audit
from four_gate_common import digest


class MixtureTensorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)/'study'
        cls.result=run(cls.root,feature_profile='local_participant_v2',record_profile='serialized_records_v2',
                       control_profile='shared_head_mixture_v2')
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_complete_outputs_independently_recomputed(self):
        r=audit(self.root)
        self.assertEqual(r['original_tasks'],192);self.assertEqual(r['audited_outputs'],1728)
        self.assertFalse(r['risk_calibrated'])

    def test_extra_heads_learn_and_are_small_not_new_encoders(self):
        fit=json.loads((self.root/'mixture-fit.json').read_bytes())
        self.assertEqual(fit['total_parameters'],6219)
        self.assertEqual(len(set(fit['members'])),3)
        for job in fit['jobs']:self.assertLess(job['last_loss'],job['first_loss'])
        self.assertGreater(self.result['additional_fit_and_features_cpu_ns'],0)

    def test_exact_control_and_full_verification_retained(self):
        r=self.result['summary']
        self.assertEqual(r['verify_all']['correct'],192)
        self.assertEqual(r['verify_all']['verification_calls'],960)
        self.assertEqual(r['exact_reverse']['correct'],192)

    def test_marginals_match_and_all_heads_share_each_feature_read(self):
        priors=json.loads((self.root/'mixture-priors.json').read_bytes())
        self.assertEqual(len(priors),192)
        proposals=json.loads((self.root/'mixture-proposals.json').read_bytes())
        self.assertEqual(len(proposals),1320) # 360 calibration + 960 events, not 3x that many encodes
        self.assertTrue(all(len(r['scores'])==3 for r in proposals))

    def test_relabelled_common_model_rejects(self):
        self.mutate('priors',lambda rows:rows[0]['binding'].update(model=digest('different')), 'binding')

    def test_false_no_check_posterior_rejects(self):
        def change(rows):rows[0]['member_weight_history'][0]=[1.,0.,0.]
        self.mutate('joint_ndu',change,'member posterior')

    def test_changed_decoded_result_rejects(self):
        self.mutate('joint_ndu',lambda rows:rows[0].update(text='Fabricated answer'),'decoded')

    def test_unpaid_verifications_reject(self):
        self.mutate('verify_all',lambda rows:rows[0].update(modeled_cost=0.),'cost identity')

    def test_shared_cost_cannot_be_divided_by_number_of_heads(self):
        def change(value):value['shared_proposal_cpu_ns']//=3
        self.mutate('results',change,'physical work')

    def mutate(self,name,change,error):
        p=self.root/('mixture-'+name+'.json');raw=p.read_bytes()
        try:
            value=json.loads(raw);change(value);p.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,error):audit(self.root)
        finally:p.write_bytes(raw)


if __name__=='__main__':unittest.main()
