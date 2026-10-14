"""Synthetic artifact ZIP adversarial tests; real model weights are not bundled."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

loc=Path(__file__).with_name('e1e2_public_receipt_audit.py')
spec=importlib.util.spec_from_file_location('public_receipt',loc)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
H='a'*64

def synthetic():
    cases=[]
    for i in range(128):
        cases.append({'case_id':f'id{i}','group_id':f'{i+1:064x}','joint_input_digest':H,
                      'label':i%2,'source_digest':f'{i+1:064x}','split':'new_holdout'})
    panel={'case_count':128,'cases':cases}
    arms=[]
    for k,name in enumerate(m.ARMS):
        rows=[]
        for case in cases:
            y=case['label'];p=(.1 if y==0 else .9) if k>=1 else (.9 if y==0 else .1)
            rows.append({'case_id':case['case_id'],'joint_input_digest':H,'source_digest':case['source_digest'],
                         'split':'new_holdout','prob_sports':p,'measured_serving_micros':100})
        arms.append({'arm_id':name,'production_promotion':'DENY_ALL','rows':rows})
    _,metrics=m._arm_rows(arms,{x['case_id']:x for x in cases})
    payload={'trainable_parameters':2018,'weights':['0x1.1p-2','0x1.0p-2']}
    bundle=m.canonical({'payload':payload,'payload_sha256':m.sha_bytes(m.canonical(payload))})
    receipt={'snapshot_file_sha256':m.sha_bytes(bundle),'snapshot_payload_sha256':m.sha_bytes(m.canonical(payload)),
             'trained_weights_exact_float64_reloaded':True,'frozen_weights_exact_float64_reloaded':True,
             'trainable_parameters':2018,'training_steps':40}
    replay={'production_promotion':'DENY_ALL','three_chronological_future_windows':False,
            'head_optimizer_steps_during_val2_evaluation':0,'snapshot_file_sha256':receipt['snapshot_file_sha256'],
            'snapshot_payload_sha256':receipt['snapshot_payload_sha256'],
            'arms':{a['arm_id']:{'rows':[dict((k,v) for k,v in r.items() if k!='measured_serving_micros') for r in a['rows']]}
                    for a in arms[:3]}}
    published={name:{'accuracy':v['accuracy'],'brier':v['brier'],'descriptive_ece_8bin':v['descriptive_ece_8bin'],
                     'allocated_serving_time_micros':v['reported_serving_micros']} for name,v in metrics.items()}
    sealed_report={name:{'accuracy':v['accuracy'],'brier':v['brier'],
                         'descriptive_ece_8_equal_width':v['descriptive_ece_8bin']} for name,v in metrics.items() if name!=m.ARMS[3]}
    a={
       'stem-agnews-new-source-panel.json':panel,
       'stem-gemma-fresh-arms.json':arms[:3],
       'stem-laya-fresh-arm.json':arms[3],
       'stem-cell-immutable-receipt.json':receipt,
       'stem-cell-immutable-bundle.json':m.strict_json(bundle),
       'stem-new-source-independent-review.json':{'new_window_is_chronologically_future':False,
          'equal_total_lifecycle_cost_proven':False,'model_forward_origin_independently_authenticated':False,'metrics':published}
    }
    b={'stem-sealed-val2-panel.json':panel,
       'stem-cell-immutable-receipt.json':receipt,
       'stem-cell-immutable-bundle.json':m.strict_json(bundle),
       'stem-sealed-val2-replay.json':replay,
       'stem-sealed-val2-independent-review.json':{'metrics':sealed_report}}
    return a,b

def zip_writes(path,files):
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for k,v in files.items():z.writestr(k,m.canonical(v))
    return m.sha_bytes(path.read_bytes())

class PublicRealReceiptTest(unittest.TestCase):
    def setup_study(self):
        tmp=tempfile.TemporaryDirectory()
        a,b=synthetic();p=Path(tmp.name)/'paired.zip';s=Path(tmp.name)/'sealed.zip'
        return tmp,a,b,p,s
    def run_case(self,modifier,expect_failure=True):
        tmp,a,b,p,s=self.setup_study()
        try:
            modifier(a,b)
            ah=zip_writes(p,a);sh=zip_writes(s,b)
            if expect_failure:
                with self.assertRaises(m.Invalid):m.audit(p,ah,s,sh)
            else:
                result=m.audit(p,ah,s,sh)
                self.assertEqual(result['paired_val2_case_count'],128)
                self.assertFalse(result['production_promotion_permitted'])
                self.assertTrue(result['paired_prediction_replay_exact'])
        finally:tmp.cleanup()
    def test_valid_toy_numeric_pair_not_authority(self):self.run_case(lambda a,b:None,False)
    def test_wrong_label_on_both_panels(self):
        def edit(a,b):
            a['stem-agnews-new-source-panel.json']['cases'][0]['label']=1
            b['stem-sealed-val2-panel.json']['cases'][0]['label']=1
        self.run_case(edit)
    def test_swapped_source_id(self):self.run_case(lambda a,b:a['stem-gemma-fresh-arms.json'][0]['rows'][0].update(source_digest=H))
    def test_missing_prediction(self):self.run_case(lambda a,b:a['stem-gemma-fresh-arms.json'][0]['rows'].pop())
    def test_changed_replay_probability(self):
        self.run_case(lambda a,b:b['stem-sealed-val2-replay.json']['arms']['gemma2_trained_head']['rows'][0].update(prob_sports=.222))
    def test_reloaded_weights_drift(self):self.run_case(lambda a,b:b['stem-cell-immutable-bundle.json'].update(payload={'altered':True}))
    def test_bad_head_ceiling(self):
        def edit(a,b):
            for d in (a,b):d['stem-cell-immutable-receipt.json']['trainable_parameters']=2049
        self.run_case(edit)
    def test_future_overclaim(self):self.run_case(lambda a,b:b['stem-sealed-val2-replay.json'].update(three_chronological_future_windows=True))
    def test_unauthorized_production(self):self.run_case(lambda a,b:a['stem-gemma-fresh-arms.json'][0].update(production_promotion='ALLOW'))
    def test_missing_laya_arm(self):self.run_case(lambda a,b:a.pop('stem-laya-fresh-arm.json'))
    def test_bad_zip_pin(self):
        tmp,a,b,p,s=self.setup_study()
        try:
            zip_writes(p,a);sh=zip_writes(s,b)
            with self.assertRaises(m.Invalid):m.audit(p,'b'*64,s,sh)
        finally:tmp.cleanup()
    def test_duplicate_json_fields(self):
        with self.assertRaises(m.Invalid):m.strict_json(b'{"a":1,"a":2}')
    def test_nonfinite_json(self):
        with self.assertRaises(m.Invalid):m.strict_json(b'{"a":NaN}')
    def test_zip_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'bad.zip'
            with zipfile.ZipFile(p,'w') as z:z.writestr('../escape.json',b'{}')
            with self.assertRaises(m.Invalid):m.CheckedZip(p,m.sha_bytes(p.read_bytes()))

if __name__=='__main__':unittest.main()
