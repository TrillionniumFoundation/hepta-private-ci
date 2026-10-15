"""Synthetic E1 three-way parity fault-injection; no pretrained model execution."""
import copy
import importlib.util
from pathlib import Path
import unittest
import sys
sys.path.insert(0,str(Path(__file__).parent))
from e1e5_confirmatory_review import OBS_SCHEMA,E1_PROFILES,SPLITS
RESOURCE_FIELDS = ("load_ms","encode_ms","bridge_fit_ms","head_train_ms","cache_ms","migration_ms","recompute_ms","serving_ms","evaluation_ms","checkpoint_ms","peak_rss_bytes","cpu_ms","gpu_ms","energy_joules","throughput_per_sec","p95_ms","p99_ms")
import e1_three_stem_consistency as m
H='a'*64

def fixture():
    cases=[]
    for i,part in enumerate(SPLITS):
        for j,(language,family) in enumerate((('zh','chinese_semantics'),('en','english_semantics'),('code','code_diagnostics'))):
            k=len(cases)
            cases.append({'case_id':f'c{k}','source_group':f'g{k}','input_sha256':f'{k+1:064x}',
                'scope':'s','split':part,'modality':'code' if language=='code' else 'text','observed_at':i+1+j/10,
                'reader_condition':'sufficient','reader_correct':True,'answer_label':k%2,
                'language':language,'task_family':family})
    resources={k:1 for k in RESOURCE_FIELDS}
    record={'schema':m.SCHEMA,'authority':'DENY_ALL','production_promotion_permitted':False,
       'plan_sha256':H,'dataset_sha256':H,'no_change_producer_sha256':H,'scope':'s','candidates':[]}
    for j,model in enumerate(m.CANDIDATES):
        arms=[]
        for armname in ('no_change','frozen_head','learned_head'):
            preds=[{'case_id':c['case_id'],'input_sha256':c['input_sha256'],'prelabel_sealed':True,
               'positive_probability':.75 if c['answer_label'] else .25} for c in cases]
            arms.append({'name':armname,'model_sha256':H if armname=='no_change' else f'{j+2:064x}',
                'head_sha256':H,'reader_invocations':0,'actual_model_forward':True,
                'resources':resources.copy(),'predictions':preds})
        study={'schema':OBS_SCHEMA,'stage':'E1','encoder_candidate':model,
            'feature_width':E1_PROFILES[model][0], 'pooling_profile':E1_PROFILES[model][1],
            'upstream_revision':'b'*40,'tokenizer_sha256':H,'source_tree_sha256':H,
            'dataset_sha256':H,'plan_sha256':H,'evaluator_sha256':H,'scope':'s',
            'authority':'DENY_ALL','production_promotion_permitted':False,'cases':copy.deepcopy(cases),'arms':arms}
        training={'seed':7,'steps':40,'batch_size':4,'learning_rate':.01,'head_kind':'linear',
                'head_ceiling':2048,'trainable_head_parameters':512,'optimizer':'adamw',
                'train_case_sha256':H,'minibatch_sha256':H}
        record['candidates'].append({'model':model,'run_sha256':f'{j+10:064x}',
               'study':study,'training':training,'tokens':{c['case_id']:12 for c in cases}})
    return record

class Tests(unittest.TestCase):
 def deny(self,modify):
    x=fixture();modify(x)
    with self.assertRaises((ValueError,KeyError,TypeError)):
        m.review(x)
 def test_synthetic_mechanism_never_promotes(self):
    ans=m.review(fixture());self.assertEqual(ans['matched_source_cases'],21)
    self.assertFalse(ans['stem_winner_selected']);self.assertFalse(ans['model_weight_origin_and_physical_execution_verified'])
 def test_missing_stem(self):self.deny(lambda x:x['candidates'].pop())
 def test_duplicate_stem(self):self.deny(lambda x:x['candidates'][2].update(model='mmbert_small'))
 def test_train_budget_drift(self):self.deny(lambda x:x['candidates'][1]['training'].update(steps=41))
 def test_train_minibatch_drift(self):self.deny(lambda x:x['candidates'][1]['training'].update(minibatch_sha256='b'*64))
 def test_wrong_source_case(self):self.deny(lambda x:x['candidates'][1]['study']['cases'][0].update(input_sha256='f'*64))
 def test_changed_source_group(self):self.deny(lambda x:x['candidates'][1]['study']['cases'][0].update(source_group='wrong'))
 def test_changed_label(self):self.deny(lambda x:x['candidates'][1]['study']['cases'][0].update(answer_label=1))
 def test_swapped_no_change_probabilities(self):
    self.deny(lambda x:x['candidates'][1]['study']['arms'][0]['predictions'][0].update(positive_probability=.3))
 def test_changed_no_change_weight(self):self.deny(lambda x:x['candidates'][1]['study']['arms'][0].update(head_sha256='f'*64))
 def test_wrong_model_identity(self):self.deny(lambda x:x['candidates'][1]['study']['arms'][1].update(model_sha256='f'*64))
 def test_no_encoder_duplication(self):self.deny(lambda x:[a.update(model_sha256=f'{2:064x}') for a in x['candidates'][1]['study']['arms'][1:]])
 def test_bad_feature_width(self):self.deny(lambda x:x['candidates'][2]['study'].update(feature_width=384))
 def test_wrong_pooling(self):self.deny(lambda x:x['candidates'][0]['study'].update(pooling_profile='mean_l2'))
 def test_missing_code_family(self):self.deny(lambda x:x['candidates'][0]['study']['cases'][2].pop('task_family'))
 def test_language_drift(self):self.deny(lambda x:x['candidates'][0]['study']['cases'][0].update(language='en'))
 def test_missing_family_in_future(self):self.deny(lambda x:x['candidates'][0]['study']['cases'][11].update(language='zh',task_family='chinese_semantics'))
 def test_tokens_incomplete(self):self.deny(lambda x:x['candidates'][0]['tokens'].pop('c1'))
 def test_tokens_truncated(self):self.deny(lambda x:x['candidates'][0]['tokens'].update(c1=513))
 def test_head_ceiling(self):self.deny(lambda x:x['candidates'][0]['training'].update(trainable_head_parameters=3000))
 def test_bad_authority(self):self.deny(lambda x:x.update(production_promotion_permitted=True))
 def test_reused_run(self):self.deny(lambda x:x['candidates'][0].update(run_sha256=x['candidates'][1]['run_sha256']))


def core_fixture():
    """Separate 97M/140M/149M pre-registration, using synthetic data only."""
    panel=fixture()
    panel['schema']=m.CORE_SCHEMA
    modern=panel['candidates'][2]
    modern['model']='modernbert_base'
    modern['study']['encoder_candidate']='modernbert_base'
    modern['study']['feature_width']=768
    modern['study']['pooling_profile']='mean_l2'
    for item in panel['candidates']:
        item['study']['upstream_revision']=m.CORE_REVISIONS[item['model']]
    return panel

class CoreStemTests(unittest.TestCase):
    def deny(self, mutate):
        panel=core_fixture()
        mutate(panel)
        with self.assertRaises((ValueError,KeyError,TypeError)):
            m.review(panel)

    def test_core_triad_is_distinct_from_historical_gemma_study(self):
        output=m.review(core_fixture())
        self.assertEqual(output['schema'],m.CORE_OUT_SCHEMA)
        self.assertEqual(set(output['models']),set(m.CORE_CANDIDATES))
        self.assertEqual(output['models']['modernbert_base']['feature_width'],768)
        self.assertTrue(output['matched_training_ceiling_and_schedule'])
        self.assertFalse(output['production_no_change_source_independently_authenticated'])
        self.assertFalse(output['independent_reader_and_future_outcome_authority'])
        self.assertFalse(output['stem_winner_selected'])
        self.assertFalse(output['production_promotion_permitted'])
        self.assertEqual(output['authority'],'DENY_ALL')

    def test_cannot_replace_149m_with_embeddinggemma(self):
        def mutate(panel):
            panel['candidates'][2]['model']='embeddinggemma_2_text'
            panel['candidates'][2]['study']['encoder_candidate']='embeddinggemma_2_text'
            panel['candidates'][2]['study']['feature_width']=256
            panel['candidates'][2]['study']['pooling_profile']='matryoshka_256_l2'
        self.deny(mutate)

    def test_unpinned_modernbert_revision(self):
        self.deny(lambda x:x['candidates'][2]['study'].update(upstream_revision='b'*40))

    def test_modernbert_width_drift(self):
        self.deny(lambda x:x['candidates'][2]['study'].update(feature_width=384))

    def test_modernbert_pooling_drift(self):
        self.deny(lambda x:x['candidates'][2]['study'].update(pooling_profile='cls_l2'))

    def test_cross_candidate_labels_cannot_change(self):
        self.deny(lambda x:x['candidates'][2]['study']['cases'][0].update(answer_label=1))

    def test_cross_candidate_future_group_cannot_change(self):
        self.deny(lambda x:x['candidates'][2]['study']['cases'][-1].update(source_group='g9'))

    def test_head_training_schedule_must_be_matched(self):
        self.deny(lambda x:x['candidates'][2]['training'].update(steps=41))

    def test_no_change_predictions_must_be_identical(self):
        self.deny(lambda x:x['candidates'][2]['study']['arms'][0]['predictions'][0].update(positive_probability=.5))

    def test_gemma_schema_cannot_claim_modernbert(self):
        x=core_fixture();x['schema']=m.SCHEMA
        with self.assertRaises(ValueError):m.review(x)

if __name__=='__main__':unittest.main()
