"""Offline frozen AG News pilot mechanics; synthetic fixtures, NOT efficacy."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

import torch

from public_stem_agnews_pilot_v20 import (
    CANDIDATES, DATA_FILES, DATA_REVISION, N_CLASSES, SEED, STEPS, WIDTH,
    PilotError, canon, checked_plan, evaluate, head_train, jsonl,
    make_plan, output_dir, profile_binding, read_rows, select_balanced,
    sha, strict_json, to_cohorts,
)


def fixture():
    train=[{'text':f'Actual-news-like train category={cls} document {i}: example',
            'label':cls} for cls in range(4) for i in range(50)]
    test=[{'text':f'Actual-news-like test category={cls} document {i}: example',
           'label':cls} for cls in range(4) for i in range(30)]
    files={name:{'sha256':spec[1],'bytes':spec[2]} for name,spec in DATA_FILES.items()}
    a,b,c=to_cohorts(train,test)
    return a,b,c,checked_plan(make_plan(a,b,c,files))


def mock_results(plan,targets):
    rows=[{'case_id':row['case_id'],
           'probabilities':[0.8 if x==row['label'] else 0.2/3 for x in range(4)]}
          for row in targets]
    noise=[{'case_id':row['case_id'],
            'probabilities':[0.25]*4} for row in targets]
    return {name:{
        'schema':'hepta.stem-real-heldout-head-arm.v20',
        'candidate':name,'train_sha256':plan['train_sha256'],
        'heldout_source_sha256':plan['heldout_source_sha256'],
        'plan_sha256':sha(canon(plan)),'seed':SEED,'steps':STEPS,
        'holdout_targets_seen_by_producer':False,
        'deployed_no_change_verified':False,
        'production_accepted':False,'authority':'DENY_ALL',
        'predictions':copy.deepcopy(rows),
        'shuffled_predictions':copy.deepcopy(noise),
        'execution':{'trained_head_parameters':123},
        'head_parameters':123,
        'model_profile_sha256':sha(name.encode()),
        'model_snapshot_sha256':sha(('snapshot:'+name).encode())}
        for name in CANDIDATES}


class RealPublicDatasetProtocolTests(unittest.TestCase):
    def test_exact_research_source_and_disjoint_equal_budgets(self):
        train,sources,targets,plan=fixture()
        self.assertEqual((len(train),len(sources),len(targets)),(128,64,64))
        self.assertEqual([x['case_id'] for x in sources],
                         [x['case_id'] for x in targets])
        self.assertTrue(all('label' not in row for row in sources))
        self.assertEqual([sum(x['label']==j for x in train) for j in range(4)],[32]*4)
        self.assertEqual([sum(x['label']==j for x in targets) for j in range(4)],[16]*4)
        self.assertTrue({x['text'] for x in train}.isdisjoint(
                        {x['text'] for x in sources}))
        self.assertFalse(plan['independent_no_change_verified'])
        self.assertFalse(plan['dataset_temporal_future'])

    def test_repeatable_census_and_duplicate_rejection(self):
        train=[{'text':f'train {c}-{j}','label':c} for c in range(4) for j in range(40)]
        sampled,used=select_balanced(train,phase='train',per_class=32)
        self.assertEqual(sampled,select_balanced(list(reversed(train)),phase='train',per_class=32)[0])
        self.assertEqual(len(used),128)
        with self.assertRaisesRegex(PilotError,'too few'):
            select_balanced([{'text':'dup','label':0}]*500,phase='train',per_class=32)

    def test_unknown_dataset_revision_and_budget_cannot_change(self):
        *_,p=fixture()
        for field,value in [('revision','f'*40),('steps',65),('classes',5),
                            ('independent_no_change_verified',True),('production_accepted',True),
                            ('dataset_temporal_future',True),('candidates',['mmbert-small'])]:
            with self.subTest(field=field),self.assertRaises(PilotError):
                checked_plan({**p,field:value})
        bad=copy.deepcopy(p)
        bad['original_files']['train']['sha256']='0'*64
        with self.assertRaisesRegex(PilotError,'original dataset'):
            checked_plan(bad)

    def test_frozen_train_and_test_target_bytes_must_match(self):
        train,sources,targets,p=fixture()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            output_dir(root/'sample',{'plan.json':canon(p),'train.jsonl':jsonl(train),
                                      'heldout-source.jsonl':jsonl(sources),
                                      'heldout-targets.jsonl':jsonl(targets)})
            s=root/'sample'
            self.assertEqual(strict_json(s/'plan.json'),p)
            got=read_rows(s/'heldout-source.jsonl',p['heldout_source_sha256'],limit=64,
                          fields={'case_id','text'})
            self.assertEqual(got,sources)
            (s/'heldout-source.jsonl').write_bytes(jsonl(targets))
            with self.assertRaisesRegex(PilotError,'digest drift'):
                read_rows(s/'heldout-source.jsonl',p['heldout_source_sha256'],limit=64,
                          fields={'case_id','text'})
            with self.assertRaisesRegex(PilotError,'new output directory'):
                output_dir(s,{'retry.json':b'{}'})

    def test_source_train_gate_never_receives_future_labels(self):
        train,sources,targets,p=fixture()
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/'target.jsonl'; f.write_bytes(jsonl(targets))
            with self.assertRaisesRegex(PilotError,'unexpected label'):
                read_rows(f,p['heldout_targets_sha256'],limit=64,
                          fields={'case_id','text'})

    def test_equal_head_budget_reproducible_without_encoder_gradient(self):
        torch.set_num_threads(1)
        features=torch.linspace(-1,1,128*WIDTH).reshape(128,WIDTH).clone().float()
        labels=[i%4 for i in range(128)]
        m,loss=head_train(features,labels,seed=SEED,shuffle_labels=False)
        copy_model,copy_loss=head_train(features,labels,seed=SEED,shuffle_labels=False)
        negative,_=head_train(features,labels,seed=SEED,shuffle_labels=True)
        self.assertEqual(m.parameter_count(),negative.parameter_count())
        self.assertEqual(m.parameter_count(),copy_model.parameter_count())
        self.assertEqual(loss,copy_loss)
        for key,a in m.state_dict().items():
            self.assertTrue(torch.equal(a,copy_model.state_dict()[key]))

    def test_independent_evaluator_never_declares_deployed_no_change_or_winner(self):
        _train,_source,target,plan=fixture()
        result=evaluate(plan,target,mock_results(plan,target))
        self.assertIsNone(result['winner'])
        self.assertFalse(result['deployed_no_change_baseline_observed'])
        self.assertFalse(result['time_sealed_independent_future_utility'])
        self.assertEqual(result['authority'],'DENY_ALL')
        self.assertEqual(result['candidate_reports']['mmbert-small']['trained_head']['accuracy'],1)
        self.assertEqual(result['uniform_reference_not_no_change']['accuracy'],0.25)

    def test_missing_arm_cohort_or_any_label_lookahead_rejected(self):
        _train,_source,target,plan=fixture()
        result=mock_results(plan,target)
        for n,change in [('no_arm',None),('drift',('heldout_source_sha256','0'*64)),
                         ('lookahead',('holdout_targets_seen_by_producer',True)),
                         ('authority',('production_accepted',True)),
                         ('budget',('seed',SEED+1))]:
            x=copy.deepcopy(result)
            if change is None:x.pop('mmbert-small')
            else:x['mmbert-small'][change[0]]=change[1]
            with self.subTest(n=n),self.assertRaises(PilotError):evaluate(plan,target,x)
        x=mock_results(plan,target)
        x['granite-97m-r2']['predictions'][0]['case_id']='corrupted'
        with self.assertRaisesRegex(PilotError,'census'):evaluate(plan,target,x)
        changed=copy.deepcopy(target)
        changed[0]['label']=(changed[0]['label']+1)%4
        with self.assertRaisesRegex(PilotError,'precommitment'):
            evaluate(plan,changed,mock_results(plan,target))

    def test_output_cannot_overwrite_existing_research_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            output_dir(root/'new',{'file.json':canon({'a':1})})
            with self.assertRaisesRegex(PilotError,'new output directory'):
                output_dir(root/'new',{'file.json':canon({'a':2})})


if __name__=='__main__':unittest.main()
