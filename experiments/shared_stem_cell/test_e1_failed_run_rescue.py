"""Synthetic fault injection for actual failed-Action archival numeric review."""
import io,copy,json,tempfile,unittest
from unittest.mock import patch
from zipfile import ZipFile,ZIP_DEFLATED
import e1_failed_run_rescue as a


def fixture():
    cases=[]
    for split,n in (('train',128),('calibration',32),('test',64)):
        for i in range(n):
            text=split+'-source-'+str(i)
            joint={'state':text,'question':'Which category does the news report describe?',
                   'options':['world','sports']}
            src=a.sha(text.encode())
            cases.append({'case_id':src[:24],'source_digest':src,'group_id':src,'split':split,
                          'label':i%2,'joint_input':joint,'joint_input_digest':a.sha(a.canonical(joint))})
    panel={'cases':cases,'case_count':224,'production_promotion':'DENY_ALL',
           'cross_sectional_not_future':True}
    preds={}
    for name in ('frozen_head','learned_head'):
        rows=[]
        for c in cases:
            if c['split']=='train':continue
            p=.5 if name=='frozen_head' else (.9 if c['label']==1 else .1)
            rows.append({'case_id':c['case_id'],'split':c['split'],
                         'joint_input_digest':c['joint_input_digest'],'positive_probability':p})
        preds[name]={'head_sha256':('b' if name=='frozen_head' else 'c')*64,
                     'calibration_temperature':1.0,'predictions':rows}
    g={'schema':'hepta.e1-english-public-pretrained-head.v1','model':'granite_97m_r2',
       'model_revision':a.REVISION,'feature_width':384,'public_panel_sha256':a.sha(a.canonical(panel)),
       'authority':'DENY_ALL','production_promotion_permitted':False,'english_only':True,
       'public_dataset_is_chronological_future':False,'actual_pretrained_local_weight_execution_claimed':True,
       'model_origin_independently_authenticated':False,
       'tokens_per_case':{x['case_id']:12 for x in cases},
       'features_q24_identity':{x['case_id']:'f'*64 for x in cases},
       'physical_observations':{'load_ms':2,'encode_ms_by_case':{x['case_id']:1 for x in cases}},
       'fitting':{'steps':40,'seed':20261014,'learning_rate':.15,'head_parameter_count':770,
                  'training_test_labels_accessed':False,'train_time_ms':100,'controls':preds}}
    return {'panel.json':a.canonical(panel),'granite_97m_r2.json':a.canonical(g),
            'granite_97m_r2.e2.json':a.canonical({'authority':'DENY_ALL','production_promotion_permitted':False}),
            'mmbert_small.json':a.canonical({'model':'mmbert_small','production_promotion_permitted':False}),
            'mmbert_small.e2.json':a.canonical({'authority':'DENY_ALL'}),
            'embeddinggemma_2_text.failed.txt':b'embeddinggemma_2_text failed source-based real CPU trial\n'}

def zipped(files):
    b=io.BytesIO()
    with ZipFile(b,'w',ZIP_DEFLATED) as z:
        for key,val in files.items():z.writestr(key,val)
    return b.getvalue()

def fake_e2(panel,e1,sha_e1,e2):
    assert sha_e1==a.sha(a.canonical(e1))
    return {'authority':'DENY_ALL','production_promotion_permitted':False,'e2_receipt_reviewed':True}

class Tests(unittest.TestCase):
    def run_case(self,change=None,accept=False):
        files=fixture()
        if change:change(files)
        blob=zipped(files)
        with patch.object(a,'PANEL_SHA',a.sha(files['panel.json'])):
            if accept:
                report=a.audit(blob,a.sha(blob),e2_review=fake_e2)
                self.assertEqual(report['holdout_cases'],64)
                self.assertEqual(report['granite_recomputed_accuracy_brier']['learned_head']['test']['correct'],64)
                self.assertEqual(report['granite_recomputed_accuracy_brier']['frozen_head']['test']['correct'],32)
                self.assertFalse(report['three_model_pairwise_scientific_comparison_complete'])
                self.assertFalse(report['production_promotion_permitted'])
                return
            with self.assertRaises((a.Invalid,ValueError,KeyError,TypeError)):
                a.audit(blob,a.sha(blob),e2_review=fake_e2)
    def edit(self,files,path,fn):
        data=a.parse(files[path]);fn(data);files[path]=a.canonical(data)
    def test_bound_archive_readout_synthetic(self):self.run_case(accept=True)
    def test_approved_real_archive_digest_is_enforced(self):
        blob=zipped(fixture())
        with self.assertRaises(a.Invalid):a.audit(blob,e2_review=fake_e2)
    def test_missing_granite_head(self):self.run_case(lambda f:f.pop('granite_97m_r2.json'))
    def test_duplicate_zip_member(self):
        f=fixture();blob=io.BytesIO()
        with ZipFile(blob,'w') as z:
            for k,v in f.items():z.writestr(k,v)
            z.writestr('panel.json',b'{}')
        with self.assertRaises(a.Invalid):a.audit(blob.getvalue(),a.sha(blob.getvalue()),e2_review=fake_e2)
    def test_swapped_prediction_case(self):self.run_case(lambda f:self.edit(f,'granite_97m_r2.json',lambda x:x['fitting']['controls']['learned_head']['predictions'][0].update(case_id='alien')))
    def test_modified_original_probability(self):self.run_case(lambda f:self.edit(f,'granite_97m_r2.json',lambda x:x['fitting']['controls']['learned_head']['predictions'][0].update(positive_probability=3.2)))
    def test_unsealed_source_panel(self):self.run_case(lambda f:self.edit(f,'panel.json',lambda x:x.update(production_promotion='ALLOWED')))
    def test_incomplete_encoder_tokens(self):self.run_case(lambda f:self.edit(f,'granite_97m_r2.json',lambda x:x['tokens_per_case'].pop(next(iter(x['tokens_per_case'])))))
    def test_forged_train_budget(self):self.run_case(lambda f:self.edit(f,'granite_97m_r2.json',lambda x:x['fitting'].update(steps=41)))
    def test_original_mmbert_cannot_promote(self):self.run_case(lambda f:self.edit(f,'mmbert_small.json',lambda x:x.update(production_promotion_permitted=True)))
    def test_gemma_must_be_declared_failed(self):self.run_case(lambda f:f.__setitem__('embeddinggemma_2_text.failed.txt',b'succeeded'))
    def test_missing_e2_review(self):self.run_case(lambda f:f.pop('granite_97m_r2.e2.json'))
    def test_original_raw_prediction_bound_to_input(self):self.run_case(lambda f:self.edit(f,'granite_97m_r2.json',lambda x:x['fitting']['controls']['frozen_head']['predictions'][0].update(joint_input_digest='f'*64)))
    def test_e2_independent_reviewer_may_not_promote(self):
        f=fixture();blob=zipped(f)
        with patch.object(a,'PANEL_SHA',a.sha(f['panel.json'])):
            with self.assertRaises(a.Invalid):a.audit(blob,a.sha(blob),e2_review=lambda *_:{'authority':'DENY_ALL','production_promotion_permitted':True})

if __name__=='__main__':unittest.main()
