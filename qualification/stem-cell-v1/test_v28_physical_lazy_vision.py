"""Pure contract tests: fake feature drivers NEVER substantiate physical pretrained execution."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import v28_physical_lazy_vision as p


def make_rows():
    cases=[]
    for i in range(64):
        cases.append({'id':f'{i+1:064x}','group':f'{i+2000:064x}',
                      'image':f'{i+3000:064x}', 'split':'test'})
    return cases,cases[:21]


def plan():
    rows=[]
    for i in range(64):
        trig=i<21
        text=0
        image=1 if i<19 else 0
        rows.append({'id':f'{i+1:064x}','group':f'{i+2000:064x}',
                     'trigger_vision':trig,'selected_class':image if trig else text,
                     'text_class':text,'image_class':image})
    return {'schema':'hepta.stem.v27.scienceqa-conditional-replay.v1.prelabel-plan',
            'archived_prediction_sha256':p.PRED_SHA,'source_sha256':p.STEM_SOURCE,
            'threshold':0.005,'policy':'text_margin_lt_threshold_else_text',
            'rows':rows,'prelabel_only':True,'physical_conditional_forwards':False,
            'training_updates':0,'production_authorized':False}


class MockTensor(list):
    def tolist(self):return list(self)


class MockBatch(list):
    @property
    def shape(self):return (len(self),384)


class FakeVision:
    """Deterministic synthetic features and an observable fake batch counter."""
    def __init__(self):self.calls=0
    def encode(self, raw):
        self.calls+=1
        vectors=[]
        for item in raw:
            offset=int.from_bytes(hashlib.sha256(item).digest()[:2],'big')/65535
            vectors.append([float(offset)]*384)
        return MockBatch([MockTensor(row) for row in vectors])


class Contracts(unittest.TestCase):
    def test_original_route_shape_and_selection(self):
        x=p.validate_plan(plan())
        self.assertEqual(len(x),64)
        self.assertEqual(sum(a['trigger_vision'] for a in x),21)
        self.assertEqual(sum(a['selected_class']!=a['text_class'] for a in x),19)

    def test_source_alignment_preserves_actual_route_order(self):
        all_rows, chosen=make_rows()
        extra=[{'id':f'{i+100:064x}','group':f'{i+2400:064x}',
                'image':f'{i+3500:064x}', 'split':'train'} for i in range(128)]
        rows=all_rows+extra
        result=p.align_source(plan()['rows'],rows,
            {'source_sha256':p.STEM_SOURCE,'private_test_labels_sha256':None,
             'production_accepted':False})
        self.assertEqual([r['id'] for r in result[0]], [r['id'] for r in all_rows])
        self.assertEqual([r['id'] for r in result[1]], [r['id'] for r in chosen])

    def test_full_and_lazy_real_execution_contract_with_fake_driver(self):
        full,lazy=make_rows()
        driver=FakeVision()
        touched=[]
        def grab(path,digest):
            touched.append(path.name)
            self.assertEqual(path.name,digest)
            return ('pixels:'+digest).encode()
        def run(rows):
            return p.execute_arm(driver,rows,Path('/nonexistent'),read_bytes=grab)
        receipts,difference=p.compare_arms(full,lazy,run)
        self.assertEqual([r['items'] for r in receipts],[64,21,21,64])
        self.assertEqual([r['batches'] for r in receipts],[8,3,3,8])
        self.assertEqual(driver.calls,22)
        self.assertLess(difference,1e-6)
        self.assertEqual(len(touched),170) # 64+21+21+64, only selected 21 in lazy runs
        self.assertEqual(touched[64:85], [q['image'] for q in lazy])
        self.assertEqual(touched[85:106], [q['image'] for q in lazy])

    def test_changed_gate_class_rejected(self):
        t=plan();t['rows'][0]['selected_class']=2
        with self.assertRaises(p.Reject):p.validate_plan(t)

    def test_boolean_class_rejected(self):
        t=plan();t['rows'][0]['selected_class']=True
        with self.assertRaises(p.Reject):p.validate_plan(t)

    def test_missing_original_case_rejected(self):
        t=plan();t['rows'].pop()
        with self.assertRaises(p.Reject):p.validate_plan(t)

    def test_duplicate_route_case_rejected(self):
        t=plan();t['rows'][1]['id']=t['rows'][0]['id']
        with self.assertRaises(p.Reject):p.validate_plan(t)

    def test_fake_visual_grant_rejected(self):
        t=plan();t['production_authorized']=True
        with self.assertRaises(p.Reject):p.validate_plan(t)

    def test_fabricated_physical_prior_call_rejected(self):
        t=plan();t['physical_conditional_forwards']=True
        with self.assertRaises(p.Reject):p.validate_plan(t)

    def test_mutated_model_source_rejected(self):
        rows=make_rows()[0]
        with self.assertRaises(p.Reject):
            p.align_source(plan()['rows'],rows+[dict(rows[0])]*128,
                {'source_sha256':'0'*64,'private_test_labels_sha256':None,
                'production_accepted':False})

    def test_test_label_digest_leak_rejected(self):
        rows=make_rows()[0]
        with self.assertRaises(p.Reject):
            p.align_source(plan()['rows'],rows+[{'split':'train'}]*128,
                 {'source_sha256':p.STEM_SOURCE,'private_test_labels_sha256':'c'*64,
                  'production_accepted':False})

    def test_fake_backend_call_count_rejected(self):
        class Cheat(FakeVision):
            def encode(self,raw):
                answer=super().encode(raw)
                self.calls-=1
                return answer
        with self.assertRaises(p.Reject):
            p.execute_arm(Cheat(),make_rows()[1],Path('/'),read_bytes=lambda q,d:b'x')

    def test_missing_selected_output_rejected(self):
        all_rows,chosen=make_rows()
        def bad(rows):
            obs={'items':len(rows),'batches':8 if len(rows)==64 else 3,
                 'cpu_ns':1,'wall_ns':1}
            return obs, {q['id']:(0.1,)*384 for q in rows[:-1]}
        with self.assertRaises(p.Reject):p.compare_arms(all_rows,chosen,bad)

    def test_numeric_drift_rejected(self):
        all_rows,chosen=make_rows();count=0
        def bad(rows):
            nonlocal count
            count+=1
            return ({'items':len(rows),'batches':8 if len(rows)==64 else 3,
                     'cpu_ns':1,'wall_ns':1},
                    {q['id']:(float(count),)*384 for q in rows})
        with self.assertRaises(p.Reject):p.compare_arms(all_rows,chosen,bad)

    def test_invalid_truthy_boolean_resource_rejected(self):
        full,lazy=make_rows()
        def fake(rows):
            return ({'items':len(rows),'batches':8 if len(rows)==64 else 3,
                     'cpu_ns':True,'wall_ns':1},
                    {q['id']:(0.1,)*384 for q in rows})
        with self.assertRaises(p.Reject):p.compare_arms(full,lazy,fake)

    def test_wrong_checkpoint_revision_rejected(self):
        manifest={'revision':'0'*40,'files':{'model.safetensors':'a'*64}}
        with self.assertRaises(p.Reject):p.model_identity_safe(manifest,'a'*64)

    def test_valid_checkpoint_identity_only_when_equal(self):
        manifest={'revision':p.DINO_REVISION,
                  'files':{'model.safetensors':'a'*64,'config.json':'b'*64}}
        identity=p.sha(p.canonical(manifest))
        self.assertEqual(p.model_identity_safe(manifest,identity),identity)
        with self.assertRaises(p.Reject):p.model_identity_safe(manifest,'0'*64)

    def test_json_duplicates_and_nonfinite_rejected(self):
        for raw in (b'{"a":1,"a":2}',b'{"x":NaN}',b'{"x":Infinity}'):
            with self.subTest(raw=raw),self.assertRaises(p.Reject):p.strict_json(raw)

    def test_safe_write_refuses_overwrite_and_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            path=root/'out.json'
            p.safe_write(path,{'authority':'DENY_ALL'})
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            with self.assertRaises(FileExistsError):p.safe_write(path,{'authority':'DENY_ALL'})
            symlink=root/'other.json';symlink.symlink_to(path)
            with self.assertRaises(p.Reject):p.safe_write(symlink,{})

    def test_hosted_workflow_has_target_isolation_and_true_pretrained_gate(self):
        path=(Path(__file__).resolve().parents[2]/'.github'/'workflows'/
              'hepta-stem-v28-physical-lazy-vision.yml')
        workflow=path.read_text()
        for text in ('original-physical-lazy-vision:',
                     "github.event_name == 'push'",
                     'e3_scienceqa_stage.py 7fa6adc26a76dfcc644c748259a4a8ca8d04f99e',
                     'e3_source_target_partition.py 904347ca0a4a49c28dedea6cac1b9bb6d1142fe4',
                     'e3_granite_dino_real.py b99c99d8e13a4d1899a0597d7733753fb3ce092a',
                     '--predictor-source-only',
                     "doc['private_test_labels_sha256'] is None",
                     'test ! -e "$RUNNER_TEMP/original-e3.zip"',
                     'c8f3f3d03ef9bdc9722d1197aaa807d901a4d5cda2e6c40d20f8ddcf7d2b8ad2',
                     'actual_pretrained_vision_forward'):
            self.assertIn(text,workflow)
        self.assertNotIn('HELD_SHA:',workflow)
        self.assertNotIn('|| true',workflow)
        self.assertLess(workflow.index('v27_conditional_vision_replay.py seal'),
                        workflow.index('--predictor-source-only'))
        self.assertLess(workflow.index('--predictor-source-only'),
                        workflow.index('python qualification/stem-cell-v1/v28_physical_lazy_vision.py'))

    def test_frozen_plan_sha_is_observed_original_archive(self):
        # The real original byte-pinned archive was inspected to derive this
        # immutable plan SHA; neither TEST labels nor live model outputs enter.
        self.assertEqual(p.PLAN_SHA,'c8f3f3d03ef9bdc9722d1197aaa807d901a4d5cda2e6c40d20f8ddcf7d2b8ad2')


if __name__=='__main__':unittest.main()
