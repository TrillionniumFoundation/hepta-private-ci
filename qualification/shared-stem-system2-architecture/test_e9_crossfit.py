"""Fail-closed E9 policy-learning and source/heldout barrier tests."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

from e7_archive import ARMS, PHYSICAL_SHA, HISTORICAL_SHA
from e7_route_seal import routing_prob
from e9_crossfit import (prelabel, source_labels_train_only, fit_fold, evaluate,
                         validate_prelabel, fold_mapping, parse_train,
                         probability_and_cost, load, write_once, SCHEMA)
from e9_independent_review import review

PHYSICAL=os.environ.get('HEPTA_E9_PHYSICAL')
HISTORICAL=os.environ.get('HEPTA_E9_HISTORICAL')


def synthetic():
    rows=[]
    for i in range(128):
        case=f'case{i:03}'
        p,q=.2,.9
        rows.append({'case_id':case, 'group_id':f'{i+1:064x}',
                     'joint_input_digest':f'{i+900:064x}', 'fold':0,
                     'granite_prob':p,'mmbert_prob':q,
                     'granite_encoder_forward_ns':50,'mmbert_encoder_forward_ns':100,
                     'granite_head_ns':5,'mmbert_head_ns':10,
                     'routing':{a:dict(probability=routing_prob(a,p,q)[0],
                                        secondary_used=routing_prob(a,p,q)[1]) for a in ARMS}})
    folds=fold_mapping(rows)
    for r in rows:r['fold']=folds[r['group_id']]
    return {'schema':SCHEMA,'authority':'DENY_ALL','physical_archive_sha256':PHYSICAL_SHA,
            'labels_seen_during_prelabel':False,'actual_new_encoder_forwards':0,
            'registered_arms':list(ARMS),'production_accepted':False,'rows':rows}


def training(data, fold, label=1, digest='f'*64):
    return {'schema':'hepta.e9.train-only-fold-v1','authority':'DENY_ALL',
            'fold':fold,'prelabel_sha256':digest,
            'historical_archive_sha256':HISTORICAL_SHA,
            'holdout_labels_included':False,
            'rows':[{'case_id':r['case_id'],'group_id':r['group_id'],'label':label}
                    for r in data['rows'] if r['fold'] != fold]}


class E9Contract(unittest.TestCase):
    def setUp(self):
        self.base=synthetic()

    def test_all_128_group_assignments_exact_and_deterministic(self):
        self.assertEqual(len(validate_prelabel(self.base)),128)
        self.assertEqual({i:sum(r['fold']==i for r in self.base['rows']) for i in range(4)},
                         {0:32,1:32,2:32,3:32})
        self.assertEqual(fold_mapping(self.base['rows']),fold_mapping(list(reversed(self.base['rows']))))

    def test_bad_source_identity_rejected(self):
        for key, val in [('group_id','A'*64),('joint_input_digest','unknown'),('fold',True),
                         ('case_id','case000')]:
            b=copy.deepcopy(self.base)
            b['rows'][1][key]=val
            with self.subTest(key=key),self.assertRaises(ValueError):
                validate_prelabel(b)

    def test_label_bearing_extra_prelabel_field_rejected(self):
        d=copy.deepcopy(self.base);d['labels']={'case000':1}
        with self.assertRaises(ValueError):validate_prelabel(d)

    def test_wrong_route_probability_or_flag_rejected(self):
        for change in ('probability','secondary_used'):
            b=copy.deepcopy(self.base)
            b['rows'][1]['routing']['gate_conf_090'][change]=None
            with self.subTest(change=change),self.assertRaises(ValueError):
                validate_prelabel(b)

    def test_train_only_completeness_and_fold_leak(self):
        t=training(self.base,0)
        self.assertEqual(len(parse_train(self.base,'f'*64,0,t)[1]),96)
        candidate=copy.deepcopy(t)
        r=next(r for r in self.base['rows'] if r['fold']==0)
        candidate['rows'][0]['case_id']=r['case_id']
        candidate['rows'][0]['group_id']=r['group_id']
        with self.assertRaises(ValueError):parse_train(self.base,'f'*64,0,candidate)

    def test_missing_or_extra_train_label_rejected(self):
        for mode in ('drop','append','unknown','bool','incorrect_sha'):
            t=training(self.base,0)
            if mode=='drop':t['rows'].pop()
            if mode=='append':t['rows'].append(t['rows'][0])
            if mode=='unknown':t['unknown_heldout_truth']=1
            if mode=='bool':t['rows'][0]['label']=True
            if mode=='incorrect_sha':t['prelabel_sha256']='a'*64
            with self.subTest(mode=mode),self.assertRaises(ValueError):
                parse_train(self.base,'f'*64,0,t)

    def test_training_can_select_non_granite_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d)
            ps=write_once(base/'p.json',self.base)
            ts=write_once(base/'train.json',training(self.base,1,digest=ps))
            receipt=fit_fold(base/'p.json',ps,base/'train.json',ts,1,base/'fit.json')
            self.assertEqual(receipt['selected_arm'],'mmbert_only')
            selected,_=load(base/'fit.json')
            self.assertFalse(selected['holdout_labels_seen'])
            self.assertEqual(selected['train_scores']['mmbert_only']['correct'],96)

    def test_probability_compute_not_free_and_nonselected(self):
        row=self.base['rows'][0]
        self.assertEqual(probability_and_cost(row,'granite_only'),(.2,55,0))
        self.assertEqual(probability_and_cost(row,'mmbert_only'),(.9,110,0))
        self.assertEqual(probability_and_cost(row,'gate_conf_090'),(.9,165,1))

    def test_immutable_outputs_and_digest_guard(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'seal.json';sha=write_once(p,self.base)
            self.assertEqual(load(p,sha)[1],sha)
            with self.assertRaises(FileExistsError):write_once(p,self.base)
            with self.assertRaises(ValueError):load(p,'0'*64)

    def test_unregistered_extra_arm_rejected(self):
        d=copy.deepcopy(self.base);d['rows'][0]['routing']['posthoc_gate']={'probability':1,'secondary_used':True}
        with self.assertRaises(ValueError):validate_prelabel(d)

    def test_no_false_future_or_production_claim(self):
        d=copy.deepcopy(self.base);d['production_accepted']=True
        with self.assertRaises(ValueError):validate_prelabel(d)
        d=copy.deepcopy(self.base);d['labels_seen_during_prelabel']=True
        with self.assertRaises(ValueError):validate_prelabel(d)

    @unittest.skipUnless(PHYSICAL and HISTORICAL, 'both original immutable ZIPs required')
    def test_actual_original_two_ZIP_complete_crossfit_and_second_algorithm(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'pre.json'
            phase=prelabel(PHYSICAL,p)
            self.assertEqual(phase['case_count'],128)
            train=source_labels_train_only(HISTORICAL,p,phase['prelabel_sha256'],str(root/'train'))
            choices=[]
            for fold in range(4):
                f=root/f'fit{fold}.json';choices.append(f)
                candidate=fit_fold(p,phase['prelabel_sha256'],root/f'train-fold{fold}.json',
                       train[str(root/f'train-fold{fold}.json')],fold,f)
                self.assertEqual(candidate['selected_arm'],'granite_only')
            result=evaluate(p,phase['prelabel_sha256'],choices,HISTORICAL,root/'out.json')
            self.assertEqual(result['result']['trained_route']['correct'],122)
            self.assertEqual(result['result']['trained_route']['hypothetical_extra_mmbert_calls'],0)
            self.assertFalse(result['result']['production_accepted'])
            independence=review(HISTORICAL,PHYSICAL,p,root/'out.json',choices,root/'audit.json')
            self.assertEqual(independence['crossfit_correct'],122)
            self.assertFalse(independence['online_system2_gain_certified'])
            # Independent reviewer MUST reject a tampered scored answer.
            forged=json.loads((root/'out.json').read_text())
            forged['trained_route']['correct']=123
            (root/'forged-score.json').write_text(json.dumps(forged))
            with self.assertRaises(ValueError):
                review(HISTORICAL,PHYSICAL,p,root/'forged-score.json',choices,
                       root/'forged-review.json')
            # A changed arm cannot be laundered into a 'train-chosen' action.
            forged_fit=json.loads(choices[0].read_text())
            forged_fit['selected_arm']='gate_conf_098'
            (root/'forged-fit.json').write_text(json.dumps(forged_fit))
            fake_folds=[root/'forged-fit.json',*choices[1:]]
            with self.assertRaises(ValueError):
                evaluate(p,phase['prelabel_sha256'],fake_folds,HISTORICAL,
                         root/'forged-primary.json')
            with self.assertRaises(ValueError):
                review(HISTORICAL,PHYSICAL,p,root/'out.json',fake_folds,
                       root/'forged-review2.json')

    @unittest.skipUnless(PHYSICAL and HISTORICAL, 'both original immutable ZIPs required')
    def test_wrong_model_provenance_and_source_drift_fail(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            with self.assertRaises(ValueError):
                prelabel(HISTORICAL,root/'not-physical.json')
            p = root/'prelabel.json'
            pre = prelabel(PHYSICAL,p)
            with self.assertRaises(ValueError):
                source_labels_train_only(PHYSICAL,p,pre['prelabel_sha256'],str(root/'bad'))


if __name__=='__main__':unittest.main()
