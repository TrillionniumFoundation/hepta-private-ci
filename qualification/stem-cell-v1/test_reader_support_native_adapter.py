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
