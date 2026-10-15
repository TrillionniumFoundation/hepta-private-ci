"""Synthetic/run-contract cases; does NOT execute original pretrained weights."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from p0_multirc_semantic_material import Invalid, save
from p0_parallel_model_collector_v10 import ATTEMPT_SCHEMA
from p0_partial_pretrained_diagnostic_v8 import MODELS
from p0_runner_stage_diag_v12 import (
    SCHEMA,AUDIT_SCHEMA,STEPS,create_stage,verify_stage,audit_stage_root)

RUN='38684561669'
SHA='2c1661ae0cf71e871c81482ca73ff67806621278'


def steps(model,failed=None):
    ret={k:'success' for k in STEPS}
    ret['compact_checkout']='skipped' if model=='laya421_nochange' else 'success'
    ret['gemma_checkout']='success' if model=='embeddinggemma_2_text' else 'skipped'
    if failed:
        ret[failed]='failure'
        for k in STEPS[STEPS.index(failed)+1:]:
            if k not in ('gemma_checkout',):ret[k]='skipped'
    return ret


class StageContract(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root=Path(self.t.name)
        self.root.joinpath('arms').mkdir()

    def arm(self,model,success=True):
        folder=self.root/'arms'/f'hepta-human-original-arm-{model}-{RUN}'
        folder.mkdir()
        save(folder/f'attempt-{model}.json',{
            'schema':ATTEMPT_SCHEMA,'model':model,
            'outcome':'model_report_written' if success else 'failed_or_incomplete',
            'authority':'DENY_ALL','production_promotion_permitted':False,
            'held_test_labels_accessed':False})
        if success:
            (folder/f'{model}.json').write_text('{"synthetic":true}\n')
            if model!='laya421_nochange':
                (folder/f'{model}.replay').mkdir()
        else:
            (folder/f'{model}.failed.txt').write_text('original candidate failed\n')
        return folder

    def publish(self,model,success=True,steps_override=None):
        folder=self.arm(model,success)
        record=create_stage(folder,model,RUN,SHA,steps_override or steps(model))
        return folder,record

    def test_four_original_success_receipts_never_authorize(self):
        for model in MODELS:
            folder,record=self.publish(model)
            self.assertEqual(record['schema'],SCHEMA)
            self.assertIsNone(record['first_non_success_required_stage'])
            self.assertFalse(record['all_four_model_qualification'])
            self.assertFalse(record['human_held_labels_read'])
            self.assertEqual(verify_stage(folder,model,RUN,SHA),record)
        a=audit_stage_root(self.root/'arms',RUN,SHA)
        self.assertEqual(a['schema'],AUDIT_SCHEMA)
        self.assertFalse(a['all_four_scientifically_accepted'])
        self.assertEqual({v['status'] for v in a['original_stage_census'].values()},{'model_report_written'})

    def test_missing_runner_artifacts_are_not_successes(self):
        self.publish('granite_97m_r2')
        a=audit_stage_root(self.root/'arms',RUN,SHA)
        self.assertEqual(a['original_stage_census']['mmbert_small']['status'],'artifact_not_uploaded')

    def test_failed_source_checkout_keeps_first_causal_stage(self):
        fault=steps('mmbert_small')
        fault.update({'compact_checkout':'failure','source_lock':'skipped','runtime':'skipped',
                      'source_preflight':'skipped','original_attempt':'skipped'})
        folder,report=self.publish('mmbert_small',success=False,steps_override=fault)
        self.assertEqual(report['first_non_success_required_stage'],'compact_checkout')
        self.assertEqual(verify_stage(folder,'mmbert_small',RUN,SHA),report)

    def test_failed_original_inference_without_exception_leak(self):
        folder,report=self.publish('laya421_nochange',success=False)
        self.assertEqual(report['first_non_success_required_stage'],'caught_inside_successful_step')
        self.assertNotIn('original candidate failed',json.dumps(report))
        self.assertFalse(report['production_promotion_permitted'])
        self.assertEqual(verify_stage(folder,'laya421_nochange',RUN,SHA),report)

    def test_wrong_source_head_rejected_even_with_consistent_self_receipt(self):
        self.publish('granite_97m_r2')
        with self.assertRaises(Invalid):audit_stage_root(self.root/'arms',RUN,'e'*40)

    def test_wrong_github_run_rejected(self):
        folder,_=self.publish('granite_97m_r2')
        with self.assertRaises(Invalid):verify_stage(folder,'granite_97m_r2','12',SHA)

    def test_duplicate_json_key_is_rejected(self):
        folder,_=self.publish('granite_97m_r2')
        p=folder/'granite_97m_r2.stage-v12.json'
        p.write_text(p.read_text().replace('"authority":','"authority":"DENY_ALL","authority":'))
        with self.assertRaises(Invalid):verify_stage(folder,'granite_97m_r2',RUN,SHA)

    def test_model_swap_rejected(self):
        folder,_=self.publish('granite_97m_r2')
        p=folder/'granite_97m_r2.stage-v12.json'
        r=json.loads(p.read_text());r['model']='mmbert_small';p.write_text(json.dumps(r))
        with self.assertRaises(Invalid):verify_stage(folder,'granite_97m_r2',RUN,SHA)

    def test_success_cannot_hide_failed_actual_checkout(self):
        f=self.arm('granite_97m_r2')
        outcome=steps('granite_97m_r2');outcome['compact_checkout']='failure'
        with self.assertRaises(Invalid):create_stage(f,'granite_97m_r2',RUN,SHA,outcome)
        self.assertFalse((f/'granite_97m_r2.stage-v12.json').exists())

    def test_suppressed_failure_slot_cannot_masquerade_as_success(self):
        folder,_=self.publish('mmbert_small',False)
        (folder/'mmbert_small.failed.txt').unlink()
        with self.assertRaises(Invalid):verify_stage(folder,'mmbert_small',RUN,SHA)

    def test_forced_production_authority_rejected(self):
        folder,_=self.publish('mmbert_small')
        p=folder/'mmbert_small.stage-v12.json'
        o=json.loads(p.read_text());o['production_promotion_permitted']=True;p.write_text(json.dumps(o))
        with self.assertRaises(Invalid):verify_stage(folder,'mmbert_small',RUN,SHA)

    def test_no_held_test_label_claim_allowed(self):
        folder,_=self.publish('embeddinggemma_2_text')
        p=folder/'embeddinggemma_2_text.stage-v12.json'
        o=json.loads(p.read_text());o['human_held_labels_read']=True;p.write_text(json.dumps(o))
        with self.assertRaises(Invalid):verify_stage(folder,'embeddinggemma_2_text',RUN,SHA)

    def test_laya_must_skip_compact_and_gemma_source(self):
        f=self.arm('laya421_nochange')
        x=steps('laya421_nochange');x['compact_checkout']='success'
        with self.assertRaises(Invalid):create_stage(f,'laya421_nochange',RUN,SHA,x)

    def test_gemma_must_have_reviewed_checkout(self):
        f=self.arm('embeddinggemma_2_text')
        x=steps('embeddinggemma_2_text');x['gemma_checkout']='skipped'
        with self.assertRaises(Invalid):create_stage(f,'embeddinggemma_2_text',RUN,SHA,x)

    def test_missing_and_symlinked_stage_attestation_rejected(self):
        folder,_=self.publish('granite_97m_r2')
        p=folder/'granite_97m_r2.stage-v12.json';p.unlink()
        with self.assertRaises(Invalid):verify_stage(folder,'granite_97m_r2',RUN,SHA)
        p.symlink_to('/etc/hosts')
        with self.assertRaises(Invalid):verify_stage(folder,'granite_97m_r2',RUN,SHA)

    def test_unregistered_model_directory_rejected(self):
        folder,_=self.publish('granite_97m_r2')
        (self.root/'arms'/'forged-model').mkdir()
        with self.assertRaises(Invalid):audit_stage_root(self.root/'arms',RUN,SHA)

    def test_unknown_step_values_and_partial_shape_rejected(self):
        f=self.arm('granite_97m_r2')
        x=steps('granite_97m_r2');x['runtime']='green'
        with self.assertRaises(Invalid):create_stage(f,'granite_97m_r2',RUN,SHA,x)
        x=steps('granite_97m_r2');x.pop('runtime')
        with self.assertRaises(Invalid):create_stage(f,'granite_97m_r2',RUN,SHA,x)

    def test_cli_workflow_isolated_stage_and_no_scientific_bypass(self):
        wf=(Path(__file__).resolve().parents[2]/'.github/workflows/hepta-p0-multirc-semantic-four.yml').read_text()
        self.assertIn('p0_runner_stage_diag_v12.py',wf)
        self.assertIn('source-sha',wf)
        self.assertIn('stage-v12.json',Path(__file__).with_name('p0_isolated_artifact_intake_v11.py').read_text())
        self.assertIn('independent-original-head-training',wf)
        self.assertIn('independent-cold-pretrained-encoder',wf)
        self.assertIn('independent-pretrained-replay',wf)
        self.assertIn('if: ${{ always() && needs[',wf)


if __name__=='__main__':unittest.main()
