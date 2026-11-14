from pathlib import Path
import copy,json,unittest
import hepta_p0_partial_three_model_audit_20261016 as m
R=Path('/mnt/data')

class ThreeOfFourNoLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fit=m.source_file(R/'p0_multirc_fit_38868208650.zip','fit.json')
        cls.blind=m.source_file(R/'p0_multirc_blind_38868208650.zip','blind.json')
        cls.laya=m.source_file(R/'p0_laya_38868208650.zip','laya421_nochange.json')
        cls.granite=json.loads((R/'hepta_p0_granite97_numeric_replay_38868208650.json').read_text())
        cls.gemma=json.loads((R/'hepta_p0_gemma_independent_numeric_replay_38868208650.json').read_text())
        cls.mmbert=m.source_file(R/'p0_mmbert_failed_38868208650.zip','attempt-mmbert_small.json')
    def check(self,**patch):
        return m.combined(patch.get('fit',self.fit),patch.get('blind',self.blind),
                          patch.get('laya',self.laya),patch.get('granite',self.granite),
                          patch.get('gemma',self.gemma),patch.get('mmbert',self.mmbert))
    def test_real_3_of_4_census_cannot_promote(self):
        r=self.check()
        self.assertEqual(r['source_run_id'],38868208650)
        self.assertEqual(set(r['observed']),set(m.REVISIONS)|{'mmbert_small'})
        self.assertEqual(r['original_blind_case_count'],116)
        self.assertFalse(r['full_original_four_model_population_admitted'])
        self.assertFalse(r['final_use_authorized'])
        self.assertFalse(r['original_held_human_labels_read'])
        self.assertEqual(r['authority'],'DENY_ALL')
    def test_laya_is_native_nochange_not_trained_equal_head(self):
        r=self.check()['observed']['laya421_nochange']
        self.assertEqual(r['original_native_prediction_cases'],116)
        self.assertFalse(r['native_nochange_Head_replay_possible'])
    def test_duplicate_laya_prediction_denied(self):
        r=copy.deepcopy(self.laya)
        x=r['control']['laya_native_nochange']['predictions']
        x[1]=copy.deepcopy(x[0])
        with self.assertRaises(m.Invalid):self.check(laya=r)
    def test_held_label_in_laya_blind_denied(self):
        b=copy.deepcopy(self.blind);b['cases'][0]['label']=1
        with self.assertRaisesRegex(m.Invalid,'label leakage'):self.check(blind=b)
    def test_mmbert_failed_cannot_be_rebranded_success(self):
        f=copy.deepcopy(self.mmbert);f['outcome']='model_report_written'
        with self.assertRaises(m.Invalid):self.check(mmbert=f)
    def test_two_model_source_receipts_binding_immutable(self):
        for model in ('granite','gemma'):
            r=copy.deepcopy(getattr(self,model));r['source_head_sha']='e'*40
            with self.subTest(model=model),self.assertRaises(m.Invalid):self.check(**{model:r})
    def test_laya_spoofed_model_or_training_denied(self):
        r=copy.deepcopy(self.laya);r['training']={'parameter_count':4145}
        with self.assertRaises(m.Invalid):self.check(laya=r)
    def test_laya_probability_and_timing_denied(self):
        for change in ('nan','outside','negative_ms'):
            r=copy.deepcopy(self.laya);p=r['control']['laya_native_nochange']['predictions'][0]
            if change=='nan':p['positive_probability']=float('nan')
            elif change=='outside':p['positive_probability']=-.2
            else:p['full_request_ms']=-1.
            with self.subTest(change=change),self.assertRaises(m.Invalid):self.check(laya=r)

if __name__=='__main__':unittest.main()
