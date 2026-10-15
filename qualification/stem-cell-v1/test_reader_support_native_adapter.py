"""Exact first-generation frozen Reader to span-plan join, offline only."""
import copy
import unittest

from reader_support_causal import digest
from reader_support_native_adapter import ANNOTATION, build_plan, validate_original_material
from test_reader_support_causal import fixture


def panel_fixture():
    import hashlib
    import json
    old=fixture()
    header=dict(schema='hepta.multirc.two-question-material.v1',
        revision='4e14482c58d790d467ecfb29b6790e1917bf8756',repo='aps/super_glue',
        seed=7347,source_sha256_train='a'*64,source_sha256_validation='b'*64,
        train_passage_count=2,eval_passage_count=2,
        query_selection='first-two-ids-first-answer-per-question-no-label-choice',
        material_admission=dict(train={},validation={}),
        training_data_license_approved=False,pretraining_contamination_ruled_out=False)
    training=[dict(source_group=f'train-{i}',evidence=f'train evidence {i}',
        questions=[dict(task_id=f'train-{i}-{j}',question=f'train question {i}-{j}',
                        answer='yes',label=j%2) for j in range(2)]) for i in range(2)]
    evaluation=[dict(source_group=row['source_group'], evidence=row['evidence'],
        questions=[dict(task_id=f'task{2*i+j}',question=f'Is item {i} red? {j}',answer='yes')
                   for j in range(2)]) for i,row in enumerate(old['rows'])]
    original=dict(header=header,train=training,evaluation=evaluation)
    panel_id=hashlib.sha256(json.dumps(original,sort_keys=True,separators=(',', ':'),
                                         allow_nan=False).encode()).hexdigest()
    tr=dict(**header,split='train',panel_id=panel_id,rows=training)
    val=dict(**header,split='validation',panel_id=panel_id,rows=evaluation)
    selected=[dict(task_id=q['task_id'],source_group=g['source_group'])
              for g in evaluation for q in g['questions']]
    frozen=dict(schema='hepta.multirc.real-question-reader.v1',panel_id=panel_id,
        observation_id='d'*64,model_snapshot_sha256='b'*64,
        task_ids=[r['task_id'] for r in selected],source_groups=[r['source_group'] for r in selected],
        predictions=dict(conditioned=selected))
    annotations=dict(schema=ANNOTATION,panel_id=panel_id,original_observation_id='d'*64,
        labels_exposed=False,support_independently_verified=False,
        rows=[dict(task_id=q['task_id'],source_group=g['source_group'],
                   support_spans=old['rows'][i]['support_spans'],critical_span_index=0)
              for i,g in enumerate(evaluation) for q in g['questions']])
    annotations['annotation_id']=digest(annotations)
    return tr,val,frozen,annotations


def reseal(d):
    d['annotation_id']=digest({k:v for k,v in d.items() if k!='annotation_id'})


class NativeAdapterPlanTests(unittest.TestCase):
    def test_v1_original_panel_digest_reconstructed_from_actual_source_bytes(self):
        train,panel,model,annotation=panel_fixture()
        self.assertEqual(validate_original_material(train,panel,model['panel_id']),
                         model['panel_id'])
        self.assertEqual(build_plan(train,panel,model,annotation)['panel_sha256'],
                         model['panel_id'])

    def test_changed_original_passage_with_stale_panel_identity_fails(self):
        # Previously accepted in #2115: same claimed panel_id, new source text.
        train,panel,model,annotation=panel_fixture()
        panel['rows'][0]['evidence']=panel['rows'][0]['evidence'].replace('RED','BLU')
        with self.assertRaisesRegex(ValueError,'bytes do not match'):
            build_plan(train,panel,model,annotation)

    def test_question_and_answer_swaps_rejected_independently_of_labels(self):
        for field in ('question','answer','task_id'):
            train,panel,model,annotation=panel_fixture()
            panel['rows'][0]['questions'][0][field] += '!' if field != 'task_id' else 'z'
            with self.subTest(field=field),self.assertRaises(ValueError):
                build_plan(train,panel,model,annotation)

    def test_train_source_and_train_label_changes_rejected(self):
        train,panel,model,annotation=panel_fixture()
        train['rows'][0]['questions'][0]['label']=1-train['rows'][0]['questions'][0]['label']
        with self.assertRaises(ValueError):build_plan(train,panel,model,annotation)
        train,panel,model,annotation=panel_fixture()
        train['rows'][0]['evidence']='new train data without new panel id'
        with self.assertRaises(ValueError):build_plan(train,panel,model,annotation)

    def test_eval_labels_are_forbidden_even_if_bundle_is_rehashed(self):
        train,panel,model,annotation=panel_fixture()
        panel['rows'][0]['questions'][0]['label']=1
        with self.assertRaises(ValueError):build_plan(train,panel,model,annotation)

    def test_original_panel_pair_is_mandatory(self):
        train,panel,model,annotation=panel_fixture()
        with self.assertRaises(ValueError):build_plan(None,panel,model,annotation)
        with self.assertRaises(ValueError):build_plan(panel,panel,model,annotation)
        with self.assertRaises(ValueError):build_plan(train,None,model,annotation)

    def test_changed_claimed_admission_and_source_revision_rejected(self):
        for field,change in (('seed',0),('source_sha256_train','f'*64),
                             ('material_admission',{'train':{},'validation':{'fake':1}}),
                             ('revision','different-public-snapshot')):
            train,panel,model,annotation=panel_fixture()
            train[field]=change; panel[field]=change
            with self.subTest(field=field),self.assertRaises(ValueError):
                build_plan(train,panel,model,annotation)

    def test_unicode_original_v1_json_digest_convention(self):
        import hashlib,json
        train,panel,model,annotation=panel_fixture()
        # Rebuild with valid non-ASCII original V1 passage on its exact panel ID.
        panel['rows'][0]['evidence'] += ' 中文'
        header={k:train[k] for k in train if k not in ('split','rows','panel_id')}
        material=dict(header=header,train=train['rows'],evaluation=panel['rows'])
        bound=hashlib.sha256(json.dumps(material,sort_keys=True,separators=(',', ':'),
                                       allow_nan=False).encode()).hexdigest()
        train['panel_id']=panel['panel_id']=model['panel_id']=annotation['panel_id']=bound
        annotation['annotation_id']=digest({k:v for k,v in annotation.items() if k!='annotation_id'})
        self.assertEqual(validate_original_material(train,panel,bound),bound)
        self.assertEqual(build_plan(train,panel,model,annotation)['panel_sha256'],bound)

    def test_original_predicted_task_and_exact_span_join(self):
        train,panel,model,annotation=panel_fixture()
        plan=build_plan(train,panel,model,annotation)
        self.assertEqual(plan['rows'][0]['support_spans'],annotation['rows'][0]['support_spans'])
        self.assertEqual(plan['model_sha256'],'b'*64)
        self.assertFalse(plan['support_independently_verified'])
        self.assertNotIn('label',plan['rows'][0])

    def test_annotation_never_admits_label(self):
        train,panel,model,annotation=panel_fixture()
        annotation['rows'][0]['label']=1
        reseal(annotation)
        with self.assertRaises(ValueError):build_plan(train,panel,model,annotation)

    def test_swapped_annotation_or_missing_case(self):
        train,panel,model,annotation=panel_fixture()
        annotation['rows']=list(reversed(annotation['rows']))
        reseal(annotation)
        with self.assertRaises(ValueError):build_plan(train,panel,model,annotation)
        annotation['rows'].pop()
        reseal(annotation)
        with self.assertRaises(ValueError):build_plan(train,panel,model,annotation)

    def test_changed_encoder_or_panel_is_not_silent(self):
        train,panel,model,annotation=panel_fixture()
        model['model_snapshot_sha256']='z'*64
        with self.assertRaises(ValueError):build_plan(train,panel,model,annotation)
        train,panel,model,annotation=panel_fixture()
        panel['panel_id']='c'*64
        with self.assertRaises(ValueError):build_plan(train,panel,model,annotation)

    def test_fake_review_and_unsealed_annotation_refused(self):
        train,panel,model,annotation=panel_fixture()
        annotation['support_independently_verified']=True
        reseal(annotation)
        with self.assertRaises(ValueError):build_plan(train,panel,model,annotation)
        train,panel,model,annotation=panel_fixture()
        annotation['rows'][0]['critical_span_index']=1
        with self.assertRaises(ValueError):build_plan(train,panel,model,annotation)

    def test_original_frozen_prediction_slot_drift(self):
        train,panel,model,annotation=panel_fixture()
        model['task_ids']=list(reversed(model['task_ids']))
        with self.assertRaises(ValueError):build_plan(train,panel,model,annotation)

    def test_external_annotation_cannot_invent_new_evidence(self):
        train,panel,model,annotation=panel_fixture()
        annotation['rows'][1]['support_spans']=[[0,999],[9,11]]
        reseal(annotation)
        with self.assertRaises(ValueError):build_plan(train,panel,model,annotation)

if __name__=='__main__':unittest.main()


class FourStageNativeCLITest(unittest.TestCase):
    """Real Torch numerical forwards and create-only files; fake V1 owner adapters.

    This is an integration CONTRACT test, not an actual public HF model load.
    """

    def test_cli_prepare_run_replay_score_delays_labels_and_denies_authority(self):
        import hashlib
        import json
        import sys
        import tempfile
        import types
        from pathlib import Path
        from unittest.mock import patch
        from reader_support_native_adapter import main
        from reader_support_causal import run_blind, PLAN
        from test_reader_support_causal import ToyEncoder, ToyQuery, ToyReader, fixture

        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            train,panel,frozen,spans=panel_fixture()
            p=fixture()
            # Four original V1 tasks: two questions on each of two source groups.
            sources={r['source_group']:r for r in p['rows']}
            p['rows']=[dict(sources[g['source_group']], task_id=q['task_id'],
                            question=q['question'],answer=q['answer'])
                       for g in panel['rows'] for q in g['questions']]
            p['plan_id']=digest({k:v for k,v in p.items() if k!='plan_id'})
            reader=ToyReader().eval()
            plain=run_blind(p,encoder=ToyEncoder(),question_encoder=ToyQuery(),
                            reader=reader,weight_sha256='c'*64)
            frozen['training']={'conditioned':{'weights_sha256':'c'*64}}
            frozen['predictions']['conditioned']=[dict(task_id=r['task_id'],
                source_group=r['source_group'],logits=r['observations']['ordinary_retrieval']['logits'],
                weights_sha256='c'*64) for r in plain['rows']]
            paths=dict(train=root/'train.json',panel=root/'panel.json',spans=root/'spans.json',
                       owner=root/'owner-only-labels.json',legacy=root/'v1')
            paths['legacy'].mkdir()
            paths['train'].write_text(json.dumps(train))
            paths['panel'].write_text(json.dumps(panel))
            paths['spans'].write_text(json.dumps(spans))
            label=dict(schema='hepta.multirc.external-eval-labels.v1',panel_id=panel['panel_id'],
                       labels={k:(i%2) for i,k in enumerate(frozen['task_ids'])})
            paths['owner'].write_text(json.dumps(label))
            opened=[]; verified=[]
            def strict_json(path):
                opened.append(str(path))
                return json.loads(Path(path).read_text())
            def file_sha256(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
            def write_json_exclusive(path, content):
                with open(path,'x',encoding='utf-8') as f:json.dump(content,f,sort_keys=True)
            def check_seal(path,seal):
                if Path(path)!=paths['legacy'] or seal!='s'*64:
                    raise ValueError('unknown original V1 seal')
                return frozen
            def safe_encoder(path):
                return ToyEncoder(),ToyQuery(),lambda:verified.append('snapshot'),'b'*64,None,None
            def load_conditioned_bank(path,observation):
                if observation is not frozen:raise ValueError('not original V1 frozen Reader')
                return reader
            library={
                'matrix_materials':dict(file_sha256=file_sha256,strict_json=strict_json),
                'matrix_runtime':dict(write_json_exclusive=write_json_exclusive),
                'multirc_reader_study':dict(check_seal=check_seal,safe_encoder=safe_encoder),
                'multirc_evidence_stress':dict(load_conditioned_bank=load_conditioned_bank)
            }
            modules={name:types.ModuleType(name) for name in library}
            for name, funcs in library.items():
                for key, fn in funcs.items():setattr(modules[name],key,fn)
            def invoke(*args):
                with patch.dict(sys.modules,modules),patch.object(sys,'argv',
                      ['reader_support_native_adapter.py',*map(str,args)]):
                    main()
            common=['--run-dir',paths['legacy'],'--expected-v1-seal-id','s'*64]
            plan_dir=root/'plan'
            invoke('prepare','--train-bundle',paths['train'],
                   '--blind-eval-bundle',paths['panel'],*common,
                   '--external-spans',paths['spans'],'--output',plan_dir)
            self.assertTrue((plan_dir/'COMMITTED.json').exists())
            self.assertFalse(any('owner-only-labels' in x for x in opened))
            actual_plan=json.loads((plan_dir/'plan.json').read_text())
            self.assertEqual(actual_plan['schema'],PLAN)
            run_dir=root/'run'
            invoke('run','--plan',plan_dir/'plan.json',*common,
                   '--snapshot',root/'model','--output',run_dir)
            self.assertFalse(any('owner-only-labels' in x for x in opened))
            obs=json.loads((run_dir/'observations.json').read_text())
            self.assertTrue(obs['original_prediction_replay_verified'])
            self.assertEqual(obs['physical_encoder_calls'],16)
            replay_dir=root/'replay'
            invoke('replay','--plan',plan_dir/'plan.json','--observations-dir',run_dir,
                   '--expected-observation-id',obs['observation_id'],*common,
                   '--snapshot',root/'model','--output',replay_dir)
            self.assertFalse(any('owner-only-labels' in x for x in opened))
            physical=json.loads((replay_dir/'replay.json').read_text())
            self.assertEqual(physical['physically_reexecuted_encoder_calls'],16)
            self.assertEqual(len(verified),2)
            score=root/'scored'
            invoke('score','--plan',plan_dir/'plan.json','--observations-dir',run_dir,
                   '--expected-observation-id',obs['observation_id'],*common,
                   '--replay-dir',replay_dir,'--expected-replay-id',physical['replay_id'],
                   '--owner-labels',paths['owner'],
                   '--expected-owner-label-file-sha256',file_sha256(paths['owner']),
                   '--output',score)
            self.assertTrue(any('owner-only-labels' in x for x in opened))
            output=json.loads((score/'scores.json').read_text())
            self.assertEqual(output['tasks'],4)
            self.assertTrue(output['physical_second_pass_reexecution_structurally_verified'])
            self.assertEqual(output['authority'],'DENY_ALL')
            self.assertNotIn('premise_removed',output['original_label_descriptive_accuracy'])
            self.assertFalse(output['independent_model_origin_signatures_verified'])
            self.assertFalse(output['support_candidate_semantic_sufficiency_independently_verified'])

            # The score stage cannot reuse a replay from a different physical run.
            bad_score=root/'bad-score'
            with self.assertRaises(ValueError):
                invoke('score','--plan',plan_dir/'plan.json','--observations-dir',run_dir,
                       '--expected-observation-id',obs['observation_id'],*common,
                       '--replay-dir',replay_dir,'--expected-replay-id','e'*64,
                       '--owner-labels',paths['owner'],
                       '--expected-owner-label-file-sha256',file_sha256(paths['owner']),
                       '--output',bad_score)
            self.assertTrue((bad_score/'FAILED.json').exists())
            self.assertFalse((bad_score/'COMMITTED.json').exists())
