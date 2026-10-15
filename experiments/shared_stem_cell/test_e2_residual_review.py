"""Read-only E2 score reviewer faults on actually trained Torch synthetic features."""
from __future__ import annotations
import copy,hashlib,json,unittest
import e1_public_triplet_real_cpu as e1
import e2_feature_residual_study as e2
import e2_residual_review as r
from test_e1_public_triplet_real_cpu import panel as synthetic_panel


def fixture():
    import torch
    torch.set_num_threads(1)
    p=synthetic_panel();model='granite_97m_r2';width=384
    v={c['case_id']:[((int(c['case_id'][:4],16)%99)-50)/100]*width for c in p['cases']}
    fit=e1.fit_heads(p,model,v)
    panel_sha=e1.sha(e1.canonical(p))
    from e1e2_q24_identity import feature_inventory
    bank=feature_inventory([c['case_id'] for c in p['cases']],v)
    e1obj={'schema':'hepta.e1-english-public-pretrained-head.v1','model':model,
           'public_panel_sha256':panel_sha,'production_promotion_permitted':False,
           'actual_pretrained_local_weight_execution_claimed':True,
           'model_revision':e1.MODELS[model][1],'feature_width':width,'fitting':fit,
           'frozen_feature_bank_identity':bank}
    raw=json.dumps(e1obj,sort_keys=True).encode()+b'\n'
    e2obj=e2.study(p,model,v)
    e2obj.update(source_e1_report_sha256=hashlib.sha256(raw).hexdigest(),public_panel_sha256=panel_sha,
                 source_model_revision=e1.MODELS[model][1],existing_frozen_encoder_features_reused=True,
                 additional_encoder_model_loads=0,additional_encoder_feature_forwards=0)
    return p,e1obj,hashlib.sha256(raw).hexdigest(),e2obj

class TestReviewer(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.base=fixture()
    def data(self):return copy.deepcopy(self.base)
    def deny(self,mutate):
        args=list(self.data());mutate(args)
        with self.assertRaises((ValueError,KeyError,TypeError)):r.review(*args)
    def test_no_production_acceptance(self):
        o=r.review(*self.data())
        self.assertFalse(o['no_change_model_or_future_ndu_verified'])
        self.assertEqual(set(o['scores']),set(e2.HEAD_ARMS))
    def test_swapped_source_report(self):self.deny(lambda x:x[3].update(source_e1_report_sha256='f'*64))
    def test_hidden_initial_residual(self):self.deny(lambda x:x[3]['arms']['residual_2k'].update(initial_baseline_logits_identical=False))
    def test_trainable_parameter_overflow(self):self.deny(lambda x:x[3]['arms']['residual_2k'].update(trainable_parameters=2049))
    def test_changed_output_digest(self):self.deny(lambda x:x[3]['training']['residual_8k'].update(final_head_sha256='f'*64))
    def test_zero_optimizer_steps(self):self.deny(lambda x:x[3]['training']['residual_16k'].update(optimizer_steps=0))
    def test_missing_cosine(self):self.deny(lambda x:x[3]['arms'].pop('cosine_prototype'))
    def test_duplicate_prediction(self):self.deny(lambda x:x[3]['arms']['residual_2k']['predictions'].__setitem__(0,copy.deepcopy(x[3]['arms']['residual_2k']['predictions'][1])))
    def test_different_label_and_source(self):self.deny(lambda x:x[3]['arms']['from_zero']['predictions'][0].update(joint_input_digest='f'*64))
    def test_frozen_base_parameter_mismatch(self):self.deny(lambda x:x[3].update(frozen_base_parameters_counted_as_shared_storage=0))
    def test_fake_frozen_base_replication(self):self.deny(lambda x:x[3].update(frozen_base_weight_storage_shared_among_residual_arms=False))
    def test_e2_feature_case_tamper(self):
        def tamper(data):
            bank=data[3]['frozen_feature_bank_identity']['case_q24_sha256']
            bank[next(iter(bank))]='f'*64
        self.deny(tamper)
    def test_e1_feature_case_tamper(self):
        def tamper(data):
            bank=data[1]['frozen_feature_bank_identity']['case_q24_sha256']
            bank[next(iter(bank))]='f'*64
        self.deny(tamper)
    def test_e2_feature_inventory_missing(self):
        self.deny(lambda data:data[3].pop('frozen_feature_bank_identity'))
    def test_e2_feature_bank_digest_swap(self):
        self.deny(lambda data:data[3]['frozen_feature_bank_identity'].update(bank_q24_sha256='f'*64))
    def test_e1_feature_bank_incomplete(self):
        self.deny(lambda data:data[1]['frozen_feature_bank_identity']['case_q24_sha256'].pop(next(iter(data[1]['frozen_feature_bank_identity']['case_q24_sha256']))))
    def test_invented_extra_encoder_forward(self):self.deny(lambda x:x[3].update(additional_encoder_feature_forwards=1))
    def test_forged_no_change(self):self.deny(lambda x:x[3].update(independent_no_change_production_arm_present=True))

if __name__=='__main__':unittest.main()
