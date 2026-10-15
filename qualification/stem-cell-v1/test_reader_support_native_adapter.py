"""Exact first-generation frozen Reader to span-plan join, offline only."""
import copy
import unittest

from reader_support_causal import digest
from reader_support_native_adapter import ANNOTATION, build_plan
from test_reader_support_causal import fixture


def panel_fixture():
    old=fixture()
    evaluation=dict(schema='hepta.multirc.two-question-material.v1',split='validation',
                    panel_id='a'*64,rows=[dict(source_group=row['source_group'],
                    evidence=row['evidence'],questions=[dict(task_id=row['task_id'],
                    question=row['question'],answer=row['answer'])]) for row in old['rows']])
    frozen=dict(schema='hepta.multirc.real-question-reader.v1',panel_id='a'*64,
        observation_id='d'*64,model_snapshot_sha256='b'*64,
        task_ids=['task0','task1'],source_groups=['group0','group1'],
        predictions=dict(conditioned=[dict(task_id=row['task_id'],source_group=row['source_group'])
                                      for row in old['rows']]))
    annotations=dict(schema=ANNOTATION,panel_id='a'*64,original_observation_id='d'*64,
        labels_exposed=False,support_independently_verified=False,
        rows=[dict(task_id=row['task_id'],source_group=row['source_group'],
                   support_spans=row['support_spans'],critical_span_index=0) for row in old['rows']])
    annotations['annotation_id']=digest(annotations)
    return evaluation,frozen,annotations


def reseal(d):
    d['annotation_id']=digest({k:v for k,v in d.items() if k!='annotation_id'})


class NativeAdapterPlanTests(unittest.TestCase):
    def test_original_predicted_task_and_exact_span_join(self):
        panel,model,annotation=panel_fixture()
        plan=build_plan(panel,model,annotation)
        self.assertEqual(plan['rows'][0]['support_spans'],annotation['rows'][0]['support_spans'])
        self.assertEqual(plan['model_sha256'],'b'*64)
        self.assertFalse(plan['support_independently_verified'])
        self.assertNotIn('label',plan['rows'][0])

    def test_annotation_never_admits_label(self):
        panel,model,annotation=panel_fixture()
        annotation['rows'][0]['label']=1
        reseal(annotation)
        with self.assertRaises(ValueError):build_plan(panel,model,annotation)

    def test_swapped_annotation_or_missing_case(self):
        panel,model,annotation=panel_fixture()
        annotation['rows']=list(reversed(annotation['rows']))
        reseal(annotation)
        with self.assertRaises(ValueError):build_plan(panel,model,annotation)
        annotation['rows'].pop()
        reseal(annotation)
        with self.assertRaises(ValueError):build_plan(panel,model,annotation)

    def test_changed_encoder_or_panel_is_not_silent(self):
        panel,model,annotation=panel_fixture()
        model['model_snapshot_sha256']='z'*64
        with self.assertRaises(ValueError):build_plan(panel,model,annotation)
        panel,model,annotation=panel_fixture()
        panel['panel_id']='c'*64
        with self.assertRaises(ValueError):build_plan(panel,model,annotation)

    def test_fake_review_and_unsealed_annotation_refused(self):
        panel,model,annotation=panel_fixture()
        annotation['support_independently_verified']=True
        reseal(annotation)
        with self.assertRaises(ValueError):build_plan(panel,model,annotation)
        panel,model,annotation=panel_fixture()
        annotation['rows'][0]['critical_span_index']=1
        with self.assertRaises(ValueError):build_plan(panel,model,annotation)

    def test_original_frozen_prediction_slot_drift(self):
        panel,model,annotation=panel_fixture()
        model['task_ids']=list(reversed(model['task_ids']))
        with self.assertRaises(ValueError):build_plan(panel,model,annotation)

    def test_external_annotation_cannot_invent_new_evidence(self):
        panel,model,annotation=panel_fixture()
        annotation['rows'][1]['support_spans']=[[0,999],[9,11]]
        reseal(annotation)
        with self.assertRaises(ValueError):build_plan(panel,model,annotation)

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
            panel,frozen,spans=panel_fixture()
            p=fixture()
            reader=ToyReader().eval()
            plain=run_blind(p,encoder=ToyEncoder(),question_encoder=ToyQuery(),
                            reader=reader,weight_sha256='c'*64)
            frozen['training']={'conditioned':{'weights_sha256':'c'*64}}
            frozen['predictions']['conditioned']=[dict(task_id=r['task_id'],
                source_group=r['source_group'],logits=r['observations']['ordinary_retrieval']['logits'],
                weights_sha256='c'*64) for r in plain['rows']]
            paths=dict(panel=root/'panel.json',spans=root/'spans.json',
                       owner=root/'owner-only-labels.json',legacy=root/'v1')
            paths['legacy'].mkdir()
            paths['panel'].write_text(json.dumps(panel))
            paths['spans'].write_text(json.dumps(spans))
            label=dict(schema='hepta.multirc.external-eval-labels.v1',panel_id='a'*64,
                       labels={'task0':1,'task1':0})
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
            invoke('prepare','--blind-eval-bundle',paths['panel'],*common,
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
            self.assertEqual(obs['physical_encoder_calls'],8)
            replay_dir=root/'replay'
            invoke('replay','--plan',plan_dir/'plan.json','--observations-dir',run_dir,
                   '--expected-observation-id',obs['observation_id'],*common,
                   '--snapshot',root/'model','--output',replay_dir)
            self.assertFalse(any('owner-only-labels' in x for x in opened))
            physical=json.loads((replay_dir/'replay.json').read_text())
            self.assertEqual(physical['physically_reexecuted_encoder_calls'],8)
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
            self.assertEqual(output['tasks'],2)
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
