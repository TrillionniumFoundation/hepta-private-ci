"""Tiny synthetic MultiRC-like source-owner fixture; no authentic publisher rows."""
from __future__ import annotations

import copy
import hashlib
import unittest

import gate
import matched_head
import original_multirc_p2 as m
import physical_feature_bank as bank


def fake_original_material():
    fit=[];blind=[]
    for split,n in m.COUNTS.items():
        for pid in range(n):
            paragraph=(f'Original published research passage {split} {pid}. '
                       'The evidence describes one inventory of shipments, signed forms, '
                       'and several facts with source-specific timestamps. '*2)
            sid=hashlib.sha256(paragraph.encode()).hexdigest()
            group=hashlib.sha256(' '.join(paragraph.split()).casefold().encode()).hexdigest()
            for q in range(2):
                question=f'Did the original shipment evidence document {pid} say item {q} arrived?'
                for a in range(2):
                    candidate=f'Candidate {a} for question {q} in passage {pid}'
                    orig_prompt=('Is the proposed answer supported by the original passage? '
                                  'Question: '+m.json.dumps(question,ensure_ascii=False)+
                                  ' Candidate answer: '+m.json.dumps(candidate,ensure_ascii=False))
                    qid=hashlib.sha256(f'{sid}:{q}'.encode()).hexdigest()[:32]
                    aid=hashlib.sha256(f'{split}:{pid}:{q}:{a}:answer'.encode()).hexdigest()[:32]
                    for condition in ('original','no_evidence'):
                        case=hashlib.sha256(f'{split}:{pid}:{q}:{a}:{condition}'.encode()).hexdigest()[:32]
                        view={'state':paragraph if condition=='original' else '(no passage evidence available)',
                              'question':orig_prompt,'options':bank.OPTIONS.copy()}
                        row={'case_id':case,'source_id':sid,'source_group':group,
                             'split':split,'question_id':qid,'answer_id':aid,
                             'condition':condition,'candidate_text':candidate,
                             'original_question_text':question,'joint_input':view,
                             'view_sha256':gate.digest(view)}
                        if split!='test':
                            row['label']=(q+a)%2 if condition=='original' else None
                            fit.append(row)
                        else:blind.append(row)
    base={'schema':m.SCHEMA,'repo':m.DATA_REPO,'revision':m.DATA_REVISION,
          'train_sha256':'a'*64,'validation_sha256':'b'*64,
          'selection_rule':m.SOURCE_SELECTION,'source_passages_by_split':m.COUNTS,
          'training_license_independently_approved':False,
          'contamination_ruled_out':False,'temporal_future_windows_verified':False,
          'authority':'DENY_ALL','production_promotion_permitted':False}
    ident=gate.digest({'base':base,'fit':fit,'blind':blind})
    meta=dict(base,panel_id=ident)
    return {'metadata':meta,'cases':fit},{'metadata':meta,'cases':blind}


class MultiRcOriginalBridgeTests(unittest.TestCase):
    def test_96_original_cases_and_no_blind_labels(self):
        fit,blind=fake_original_material()
        panel,views,fitlabels=m.build_source_owner(fit,blind)
        self.assertEqual(len(panel['cases']),96)
        self.assertEqual(len(views['cases']),96)
        self.assertEqual([x['split'] for x in panel['cases']].count('fit'),48)
        self.assertEqual([x['split'] for x in panel['cases']].count('cal'),16)
        self.assertEqual([x['split'] for x in panel['cases']].count('test'),32)
        self.assertEqual(len(fitlabels['targets']),48)
        self.assertEqual(len({x['group_id'] for x in panel['cases']}),24)
        self.assertFalse(any('label' in x or 'target' in x or 'gold' in x for x in views['cases']))
        bank.manifest_views(panel,views)
        matched_head.validate_fit(panel,fitlabels)

    def test_labels_change_with_frozen_source_yields_provenance_denial(self):
        fit,blind=fake_original_material()
        fit['cases'][0]['label']^=1
        with self.assertRaises(gate.Denied):m.build_source_owner(fit,blind)

    def test_refuse_forged_original_heldout_label(self):
        fit,blind=fake_original_material();blind['cases'][0]['label']=1
        with self.assertRaises(gate.Denied):m.build_source_owner(fit,blind)

    def test_refuse_generated_no_evidence_human_label(self):
        fit,blind=fake_original_material()
        fake=next(x for x in fit['cases'] if x['condition']=='no_evidence')
        fake['label']=0
        with self.assertRaises(gate.Denied):m.build_source_owner(fit,blind)

    def test_refuse_missing_pair(self):
        fit,blind=fake_original_material()
        blind['cases']=[x for x in blind['cases'] if not (x['condition']=='no_evidence' and x['case_id']==blind['cases'][1]['case_id'])]
        with self.assertRaises(gate.Denied):m.build_source_owner(fit,blind)

    def test_refuse_same_source_in_two_splits(self):
        fit,blind=fake_original_material()
        orig=next(x for x in fit['cases'] if x['condition']=='original')
        first=next(x for x in blind['cases'] if x['condition']=='original')
        first['source_group']=orig['source_group']
        with self.assertRaises(gate.Denied):m.build_source_owner(fit,blind)

    def test_source_question_tamper_self_hash_resign_still_rejected(self):
        fit,blind=fake_original_material()
        q=fit['cases'][0];q['joint_input']['question']='totally unrelated rewritten prompt'
        q['view_sha256']=gate.digest(q['joint_input'])
        fit['metadata']['panel_id']=blind['metadata']['panel_id']=gate.digest({
            'base':{k:v for k,v in fit['metadata'].items() if k!='panel_id'},
            'fit':fit['cases'],'blind':blind['cases']})
        with self.assertRaises(gate.Denied):m.build_source_owner(fit,blind)

    def test_unknown_extra_source_column_denied(self):
        fit,blind=fake_original_material()
        fit['cases'][0]['private_comment']='exfiltrate'
        with self.assertRaises(gate.Denied):m.build_source_owner(fit,blind)

    def test_source_revision_mutation_denied(self):
        fit,blind=fake_original_material()
        fit['metadata']['revision']=blind['metadata']['revision']='0'*40
        with self.assertRaises(gate.Denied):m.build_source_owner(fit,blind)

    def test_no_cherry_pick_of_labels_into_question_order(self):
        fit,blind=fake_original_material()
        p1,v1,l1=m.build_source_owner(fit,blind)
        changed=copy.deepcopy(fit)
        for row in changed['cases']:
            if row['condition']=='original': row['label']=1-row['label']
        changed['metadata']['panel_id']=blind['metadata']['panel_id']=gate.digest({
            'base':{k:v for k,v in changed['metadata'].items() if k!='panel_id'},
            'fit':changed['cases'],'blind':blind['cases']})
        p2,v2,l2=m.build_source_owner(changed,blind)
        self.assertEqual([x['case_id'] for x in p1['cases']],[x['case_id'] for x in p2['cases']])
        self.assertNotEqual(l1['targets'],l2['targets'])
        self.assertNotEqual(gate.digest(p1),gate.digest(p2)) # external original panel identity changed
        self.assertFalse(p1['production_promotion_permitted'])

if __name__=='__main__':unittest.main()
