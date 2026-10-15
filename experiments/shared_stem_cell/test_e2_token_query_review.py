"""Independent E2 reviewer fault tests. All receipts are synthetic."""
import copy
import unittest
import torch
import e2_token_query_review as review
import e2_token_query_ablation as learn
from test_e2_token_query_ablation import fixture


def synthetic_reports():
    rows,prototype=fixture()
    panel={'schema':'hepta.stem.agnews-binary-capability-panel.v1',
           'cross_sectional_not_future':True,'case_count':224,'cases':rows}
    parents={};runs={};digests={}
    for j,(model,(revision,width)) in enumerate(review.MODELS.items()):
        cases,bank=fixture(width)
        for point in bank.values():
            point['native_pooled'][0]+=j/learn.Q24
        head=learn.study(cases,bank,width=width)
        resource={'observed_model_module_forward_hooks':28,'observed_backend_forward_calls':28,
                  'actual_unique_input_count':224,'microbatch_size_bound':8,
                  'min_tokens_per_input':4,'max_tokens_per_input':6,
                  'native_pool_and_token_query_derived_from_same_hidden_tensor':True,
                  'independent_model_module_execution_attested':False,
                  'producer_observed_encode_wall_ms':32,
                  'encoder_forward_elapsed_ms_by_case_amortized':{r['case_id']:.1 for r in cases}}
        run={'schema':'hepta.stem.e2-paired-actual-encoder-heads.v1',
             'model':model,'model_revision':revision,
             'parent_e1_report_sha256':'b'*64,'panel_sha256':review.PANEL_SHA,
             'authority':'DENY_ALL','production_promotion_permitted':False,
             'stem_winner_selected':False,'physically_shared_across_production_cells_verified':False,
             'independent_model_source_attestation':False,'real_future_ndu_verified':False,
             'production_no_change_verified':False,
             'feature_bank':head['feature_bank'],'head_study':head,
             'physical':resource,'model_load_ms':100,'total_wall_ms':10000,
             'cpu_process_ms':2000,'process_lifetime_peak_rss_bytes':2**20}
        parents[model]={'model':model,'model_revision':revision,'public_panel_sha256':review.PANEL_SHA,
                        'authority':'DENY_ALL','production_promotion_permitted':False}
        runs[model]=run;digests[model]='b'*64
    return panel,parents,runs,digests


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.data=synthetic_reports()

    def test_descriptive_only(self):
        answer=review.review(*self.data)
        self.assertEqual(len(answer['models']),3)
        self.assertEqual(answer['models']['modernbert_base']['token_query']['n'],64)
        self.assertFalse(answer['future_ndu_utility_verified'])
        self.assertFalse(answer['production_promotion_permitted'])

    def deny(self,edit):
        data=copy.deepcopy(self.data)
        edit(*data)
        with self.assertRaises((review.Invalid,TypeError,KeyError)):
            review.review(*data)

    def test_reject_fake_future(self):
        self.deny(lambda p,a,r,h:r['mmbert_small'].update(real_future_ndu_verified=True))

    def test_reject_fake_batch(self):
        self.deny(lambda p,a,r,h:r['modernbert_base']['physical'].update(observed_model_module_forward_hooks=0))

    def test_reject_head_budget(self):
        self.deny(lambda p,a,r,h:r['modernbert_base']['head_study']['arms']['token_query']['train_receipt'].update(trainable_parameters=770))

    def test_reject_missing_prediction(self):
        self.deny(lambda p,a,r,h:r['granite_97m_r2']['head_study']['arms']['pooled_gated']['predictions'].pop())

    def test_reject_fake_source(self):
        self.deny(lambda p,a,r,h:r['granite_97m_r2'].update(parent_e1_report_sha256='f'*64))


if __name__=='__main__':unittest.main()
