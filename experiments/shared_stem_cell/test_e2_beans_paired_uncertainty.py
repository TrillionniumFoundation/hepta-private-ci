"""Mechanism tests with invented labels; never a pretrained-model outcome."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from e2_beans_paired_uncertainty import (
    ARMS, CLASSES, PREFIX, AuditFailure, audit, canonical, exact_mcnemar,
    read_pinned, sha, wilson)


def example():
    manifest={'schema':PREFIX+'.source-plan','natural_images':True,
              'dataset_repo':'AI-Lab-Makerere/beans','test_cases':24,
              'phase_time_is_not_original_timestamp':True,
              'authority':'DENY_ALL','production_accepted':False,
              'file_sha256s':{'future_images.jsonl':'a'*64}}
    source=[];labels=[];pred=[]
    for i in range(24):
        cls=CLASSES[i//8];base=CLASSES[((i//8)+1)%3]
        image=sha(('image-'+str(i)).encode())
        source_digest=sha(('case-'+str(i)).encode())
        core={'case_id':f'c{i}','group_id':f'g{i}', 'scope':'research', 'observed_at':100+i}
        source.append({**core,'split':'future','condition':'vision_required',
                       'image_path':f'img{i}.jpg','image_sha256':image,
                       'question':'Which disease?', 'source_sha256':source_digest})
        labels.append({**core,'source_sha256':source_digest,
                       'source_input_sha256':image,'class_label':cls})
        pred.append({**core,'source_input_sha256':image,'predicted_labels':{
            'fitted':cls,
            'rotated_target_control':base,
            'unaligned_identity':base,
            'vision_prototype':cls if i%3!=0 else base}})
    predictions={'schema':PREFIX+'.class-predictions','natural_images':True,
                 'arms':list(ARMS),'future_labels_seen':False,'stem_selected':False,
                 'production_accepted':False,'authority':'DENY_ALL','rows':pred}
    accuracy={};per_class={};paired={}
    for a in ARMS:
        count=sum(row['predicted_labels'][a]==labels[i]['class_label'] for i,row in enumerate(pred))
        accuracy[a]={'correct':count,'total':24}
        per_class[a]={c:{'correct':sum(row['predicted_labels'][a]==labels[i]['class_label']
                                     for i,row in enumerate(pred) if labels[i]['class_label']==c),
                         'total':8} for c in CLASSES}
    for a in ARMS:
        if a=='vision_prototype':continue
        acc={'rescued':0,'harmed':0,'both_correct':0,'both_wrong':0}
        for i,row in enumerate(pred):
            truth=labels[i]['class_label']
            this=row['predicted_labels'][a]==truth
            base=row['predicted_labels']['vision_prototype']==truth
            key=('rescued' if this and not base else 'harmed' if base and not this
                 else 'both_correct' if this else 'both_wrong')
            acc[key]+=1
        paired[a]=acc
    report={'schema':PREFIX+'.independent-class-readout','total_cases':24,
            'chronological_future_test':False,'independent_ground_truth_owner':False,
            'model_selection_permitted':False,'production_accepted':False,
            'authority':'DENY_ALL','accuracy':accuracy,'per_class':per_class,
            'paired_vs_frozen_vision_prototype':paired}
    return manifest,source,labels,predictions,report


class PairedUncertaintyTests(unittest.TestCase):
    def setUp(self):
        self.m,self.s,self.t,self.p,self.o=copy.deepcopy(example())
    def run_audit(self):return audit(self.m,self.s,self.t,self.p,self.o)
    def test_full_panel_reports_no_qualification(self):
        r=self.run_audit()
        self.assertEqual(r['cases'],24)
        self.assertEqual(r['accuracy']['fitted']['correct'],24)
        self.assertEqual(r['paired_vs_frozen_vision_prototype']['fitted']['rescued'],8)
        self.assertFalse(r['model_selected'])
        self.assertFalse(r['production_accepted'])
        self.assertEqual(r['authority'],'DENY_ALL')
        self.assertFalse(r['three_chronological_future_windows'])
        self.assertEqual(r['source_class_counts'],{c:8 for c in CLASSES})
    def test_exact_two_sided_discordance(self):
        self.assertAlmostEqual(exact_mcnemar(8,0),0.0078125)
        self.assertEqual(exact_mcnemar(2,2),1)
        self.assertEqual(exact_mcnemar(0,0),1)
        self.assertAlmostEqual(exact_mcnemar(1,8),0.0390625)
    def test_wilson_boundary(self):
        lo,hi=wilson(24,24)
        self.assertGreater(lo,0.8)
        self.assertLessEqual(hi,1)
        lo,hi=wilson(0,24)
        self.assertEqual(lo,0)
        self.assertLess(hi,0.2)
    def test_changed_labels_rejected(self):
        self.t[0]['class_label']=CLASSES[1]
        with self.assertRaises(AuditFailure):self.run_audit()
    def test_missing_arm_rejected(self):
        self.p['rows'][0]['predicted_labels'].pop('vision_prototype')
        with self.assertRaises(AuditFailure):self.run_audit()
    def test_predicted_target_leak_rejected(self):
        self.p['rows'][0]['class_label']=CLASSES[0]
        with self.assertRaises(AuditFailure):self.run_audit()
    def test_wrong_source_digest_rejected(self):
        self.t[0]['source_input_sha256']='b'*64
        with self.assertRaises(AuditFailure):self.run_audit()
    def test_duplicate_prediction_rejected(self):
        self.p['rows'][1]['case_id']=self.p['rows'][0]['case_id']
        with self.assertRaises(AuditFailure):self.run_audit()
    def test_fake_prospective_window_rejected(self):
        self.o['chronological_future_test']=True
        with self.assertRaises(AuditFailure):self.run_audit()
    def test_forged_original_score_rejected(self):
        self.o['accuracy']['fitted']['correct']=23
        with self.assertRaises(AuditFailure):self.run_audit()
    def test_false_promotion_rejected(self):
        self.p['production_accepted']=True
        with self.assertRaises(AuditFailure):self.run_audit()
    def test_changed_source_plan_rejected(self):
        self.m['phase_time_is_not_original_timestamp']=False
        with self.assertRaises(AuditFailure):self.run_audit()
    def test_noncanonical_json_and_duplicate_keys_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'x.json';blob=b'{"a":1,"a":2}\n';p.write_bytes(blob)
            with self.assertRaises(AuditFailure):read_pinned(p,sha(blob))
            blob=b'{"a":1}';p.write_bytes(blob)
            with self.assertRaises(AuditFailure):read_pinned(p,sha(blob))
    def test_leaked_future_group_rejected(self):
        self.t[0]['group_id']='group-leak'
        with self.assertRaises(AuditFailure):self.run_audit()
    def test_modified_image_case_rejected(self):
        self.s[0]['image_sha256']='c'*64
        with self.assertRaises(AuditFailure):self.run_audit()
    def test_vision_reference_can_outperform_bridge(self):
        for i,row in enumerate(self.p['rows']):
            row['predicted_labels']['fitted']=CLASSES[(i//8+1)%3]
        with self.assertRaises(AuditFailure):self.run_audit()

if __name__=='__main__':unittest.main()