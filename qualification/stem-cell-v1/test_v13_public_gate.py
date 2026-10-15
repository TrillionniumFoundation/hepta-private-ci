"""Synthetic denial suite; never counts as pretrained task evidence."""
import copy
import unittest
from v13_public_gate import gate,ARMS,CORPUS,PRIOR,DELTA,d

class TestPublicNoGo(unittest.TestCase):
    def setUp(self):
        fam={"conv-47":190,"conv-48":239,"conv-49":196,"conv-50":204}
        base={"conv-47":76,"conv-48":124,"conv-49":91,"conv-50":81}
        self.report=dict(schema='hepta.stem.v13.cheap-original-retrieval.shadow.v1.public-negative.v1',
            original_dataset_sha256=CORPUS,source_sha256='a'*64,raw_rank_sha256='b'*64,
            plan_sha256='c'*64,primary_precommitted='phrase_char',fixed_arms=list(ARMS),
            heldout_question_count=829,total_questions=1986,independent_heldout_source_groups=4,publisher_unknown_heldout=7,
            per_arm={},per_family_pairwise_vs_bm25={f:{} for f in fam},
            trained_head_updates=0,pretrained_encoder_forwards=0,original_reader_calls=0,future_calendar_windows=0,
            independent_semantic_qa=None,equal_full_lifecycle_cost_to_v11=False,full_task_superiority_verified=False,
            stem_winner_verified=False,production_authorized=False,original_v6_seed41_retention_closed=False)
        for arm in ARMS:
            hit={f:base[f]+(DELTA[f] if arm=='phrase_char' else 0) for f in fam}
            self.report['per_arm'][arm]=dict(heldout_any_hit3=sum(hit.values()),heldout_any_hit16=560,
                heldout_any_hit32=600,heldout_all_hit3=250,train_any_hit3=520,
                family_hit3=hit,family_delta_vs_bm25={f:hit[f]-base[f] for f in fam})
            if arm!='bm25':
                for f in fam:
                    delta=DELTA[f] if arm=='phrase_char' else 0
                    self.report['per_family_pairwise_vs_bm25'][f][arm]=dict(gain_vs_bm25=max(0,delta),loss_vs_bm25=max(0,-delta),membership_changed=abs(delta)+1)
        self.review=dict(schema='hepta.stem.v13.independent-original-source-review.v1',original_corpus_sha256=CORPUS,
            source_sha256='a'*64,routes_sha256='b'*64,score_sha256=d(self.report),audit_status='COUNTS_CONSISTENT_NOT_MODEL_SUPERIORITY',
            independent_recounted_questions=1986,rechecked_original_bm25_questions=829,
            publisher_unknown_heldout=7,source_independent_heldout_roots=4,bm25_heldout_hit3=372,
            primary_heldout_hit3=383,per_family_primary_delta=DELTA,semantic_correctness=None,
            model_training_executed=False,production_authorized=False)
    def refresh(self):self.review['score_sha256']=d(self.report)
    def test_legitimate_source_only_negative(self):self.assertEqual(gate(self.report,self.review)['delta_weak_hit3'],11)
    def test_completely_missing_source_root(self):
        del self.report['per_arm']['phrase_char']['family_hit3']['conv-50'];self.refresh()
        with self.assertRaises(ValueError):gate(self.report,self.review)
    def test_changed_corpus_pin(self):
        self.report['original_dataset_sha256']='0'*64;self.refresh()
        with self.assertRaises(ValueError):gate(self.report,self.review)
    def test_forged_human_semantic_score(self):
        self.report['independent_semantic_qa']=.88;self.refresh()
        with self.assertRaises(ValueError):gate(self.report,self.review)
    def test_forged_future_windows(self):
        self.report['future_calendar_windows']=3;self.refresh()
        with self.assertRaises(ValueError):gate(self.report,self.review)
    def test_forged_reader_calls(self):
        self.report['original_reader_calls']=8;self.refresh()
        with self.assertRaises(ValueError):gate(self.report,self.review)
    def test_forged_pretrained_forward(self):
        self.report['pretrained_encoder_forwards']=4;self.refresh()
        with self.assertRaises(ValueError):gate(self.report,self.review)
    def test_forged_training_updates(self):
        self.report['trained_head_updates']=900;self.refresh()
        with self.assertRaises(ValueError):gate(self.report,self.review)
    def test_fake_model_winner(self):
        self.report['stem_winner_verified']=True;self.refresh()
        with self.assertRaises(ValueError):gate(self.report,self.review)
    def test_false_full_cost_match(self):
        self.report['equal_full_lifecycle_cost_to_v11']=True;self.refresh()
        with self.assertRaises(ValueError):gate(self.report,self.review)
    def test_fake_seed41_fix(self):
        self.report['original_v6_seed41_retention_closed']=True;self.refresh()
        with self.assertRaises(ValueError):gate(self.report,self.review)
    def test_score_reviewer_changed(self):
        self.review['primary_heldout_hit3']=400
        with self.assertRaises(ValueError):gate(self.report,self.review)
    def test_digest_changed(self):
        self.review['score_sha256']='0'*64
        with self.assertRaises(ValueError):gate(self.report,self.review)
    def test_primary_swapped_posthoc(self):
        self.report['primary_precommitted']='char_only';self.refresh()
        with self.assertRaises(ValueError):gate(self.report,self.review)
    def test_ceiling_violated(self):
        self.report['per_arm']['bm25']['heldout_any_hit16']=100;self.refresh()
        with self.assertRaises(ValueError):gate(self.report,self.review)
    def test_pseudoreplication(self):
        self.report['independent_heldout_source_groups']=829;self.refresh()
        with self.assertRaises(ValueError):gate(self.report,self.review)
    def test_missing_weak_gold_unknown(self):
        self.report['publisher_unknown_heldout']=0;self.refresh()
        with self.assertRaises(ValueError):gate(self.report,self.review)
    def test_wrong_pairwise_gain(self):
        self.report['per_family_pairwise_vs_bm25']['conv-50']['phrase_char']['gain_vs_bm25']+=1;self.refresh()
        with self.assertRaises(ValueError):gate(self.report,self.review)

if __name__=='__main__':unittest.main()
