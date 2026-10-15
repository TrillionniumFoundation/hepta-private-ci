"""Real Torch-on-SYNTHETIC features; isolated model attempts and all-four gate.

These are source/protocol tests, not actual Granite/mmBERT/Gemma/Laya execution.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from p0_multirc_semantic_material import Invalid, canonical, save
from p0_multirc_semantic_execute import fit_head
from p0_question_only_head import fit_question_only
from p0_physical_replay_v5 import export_original_replay
from p0_parallel_model_collector_v10 import (ATTEMPT_SCHEMA, SCHEMA,
    original_four_census, main)
from p0_pretrained_checkpoint_preflight_v9 import preflight, CANDIDATES, Invalid as PreflightInvalid
from test_p0_real_preflight_v9 import FakeSource
from test_p0_multirc_semantic import mocked_report, setup
from test_p0_question_only_matched import fake_vectors


class CollectorScientificDenials(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.train,cls.validation,cls.fit,cls.blind,cls.owner=setup()
        cls.templates={}
        for name,width in [('granite_97m_r2',384),('mmbert_small',384),('embeddinggemma_2_text',256)]:
            features=fake_vectors(cls.fit['cases']+cls.blind['cases'],width)
            heads={}
            evidence=fit_head(cls.fit['cases'],cls.blind['cases'],features,width,replay_heads=heads)
            prior=fit_question_only(cls.fit,cls.blind,features,width,evidence,replay_heads=heads)
            report=mocked_report(name,cls.fit,cls.blind)
            report['training']=evidence
            report['control']=evidence['controls']
            report['matched_question_only_control']=prior
            cls.templates[name]=(features,heads,report)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'combined'
        self.root.mkdir()

    def attempt(self,name,*,completed):
        save(self.root/f'attempt-{name}.json',{
            'schema':ATTEMPT_SCHEMA,'model':name,
            'outcome':'model_report_written' if completed else 'failed_or_incomplete',
            'production_promotion_permitted':False,'held_test_labels_accessed':False,
            'authority':'DENY_ALL'})

    def complete(self,model):
        if model=='laya421_nochange':
            report=mocked_report(model,self.fit,self.blind)
            save(self.root/f'{model}.json',report)
        else:
            f,h,r=self.templates[model]
            report=copy.deepcopy(r)
            save(self.root/f'{model}.json',report)
            export_original_replay(self.root/f'{model}.replay',self.fit,self.blind,
                                   report,model,f,h)
        self.attempt(model,completed=True)

    def fail(self,model):
        (self.root/f'{model}.failed.txt').write_text('physical-source-unavailable\n')
        self.attempt(model,completed=False)

    def audit(self):
        return original_four_census(self.fit,self.blind,self.root)

    def test_all_four_synthetic_source_arms_must_be_present_for_census_only(self):
        for model in ['granite_97m_r2','mmbert_small','embeddinggemma_2_text','laya421_nochange']:
            self.complete(model)
        result=self.audit()
        self.assertEqual(result['schema'],SCHEMA)
        self.assertTrue(result['entire_four_model_population_present_and_v8_consistent'])
        self.assertFalse(result['full_pretrained_model_execution_independently_authenticated'])
        self.assertFalse(result['production_promotion_permitted'])
        self.assertFalse(result['model_winner_selected'])
        self.assertFalse(result['new_quality_or_future_outcomes_proven'])
        self.assertEqual(result['missing_or_failed_model_count'],0)
        self.assertEqual(result['independent_v8_original_statuses']['laya421_nochange'],
                         'laya_native_identity_only')

    def test_one_failing_model_never_blocks_independent_others_or_passes_scientific_gate(self):
        self.complete('granite_97m_r2')
        self.fail('mmbert_small')
        self.complete('embeddinggemma_2_text')
        self.complete('laya421_nochange')
        x=self.audit()
        self.assertEqual(x['model_attempts']['mmbert_small']['status'],'failed_or_incomplete')
        self.assertEqual(x['independent_v8_original_statuses']['granite_97m_r2'],
                         'original_head_numeric_replay_consistent')
        self.assertEqual(x['missing_or_failed_model_count'],1)
        self.assertFalse(x['entire_four_model_population_present_and_v8_consistent'])

    def test_no_attempt_receipts_cannot_be_scored_even_with_original_four_reports(self):
        for model in ['granite_97m_r2','mmbert_small','embeddinggemma_2_text','laya421_nochange']:
            self.complete(model)
        (self.root/'attempt-granite_97m_r2.json').unlink()
        x=self.audit()
        self.assertEqual(x['model_attempts']['granite_97m_r2']['status'],'missing_attempt_receipt')
        self.assertFalse(x['entire_four_model_population_present_and_v8_consistent'])

    def test_zero_attempts_never_implies_four_model_success(self):
        x=self.audit()
        self.assertEqual(x['missing_or_failed_model_count'],4)
        self.assertFalse(x['entire_four_model_population_present_and_v8_consistent'])

    def test_stated_failure_without_real_failed_file_is_invalid(self):
        self.attempt('granite_97m_r2',completed=False)
        x=self.audit()
        self.assertEqual(x['model_attempts']['granite_97m_r2']['status'],'invalid_attempt_receipt')
        self.assertFalse(x['entire_four_model_population_present_and_v8_consistent'])

    def test_stated_success_without_pretrained_original_result_is_invalid(self):
        self.attempt('mmbert_small',completed=True)
        x=self.audit()
        self.assertEqual(x['model_attempts']['mmbert_small']['status'],'invalid_attempt_receipt')
        self.assertFalse(x['entire_four_model_population_present_and_v8_consistent'])

    def test_actual_report_missing_replay_cannot_pass(self):
        self.complete('granite_97m_r2')
        (self.root/'granite_97m_r2.replay/COMMITTED.json').unlink()
        x=self.audit()
        self.assertEqual(x['independent_v8_original_statuses']['granite_97m_r2'],'invalid')
        self.assertFalse(x['entire_four_model_population_present_and_v8_consistent'])

    def test_self_rehashed_forged_report_is_rejected_by_independent_v8(self):
        self.complete('granite_97m_r2')
        path=self.root/'granite_97m_r2.json'
        bad=json.loads(path.read_text())
        bad['control']['trained_head']['predictions'][0]['positive_probability']=.9999
        path.write_bytes(canonical(bad)+b'\n')
        self.assertEqual(self.audit()['independent_v8_original_statuses']['granite_97m_r2'],'invalid')

    def test_laya_cannot_impersonate_equal_trained_head(self):
        self.complete('laya421_nochange')
        path=self.root/'laya421_nochange.json'
        x=json.loads(path.read_text());x['training']={'optimizer':'SGD'}
        path.write_bytes(canonical(x)+b'\n')
        self.assertFalse(self.audit()['entire_four_model_population_present_and_v8_consistent'])

    def test_forged_attempt_authority_even_reshashed_does_not_pass(self):
        self.complete('mmbert_small')
        p=self.root/'attempt-mmbert_small.json'
        x=json.loads(p.read_text());x['production_promotion_permitted']=True
        p.write_bytes(canonical(x)+b'\n')
        self.assertEqual(self.audit()['model_attempts']['mmbert_small']['status'],'invalid_attempt_receipt')

    def test_cross_model_attempt_name_switch_cannot_pass(self):
        self.complete('granite_97m_r2')
        p=self.root/'attempt-granite_97m_r2.json'
        x=json.loads(p.read_text());x['model']='mmbert_small'
        p.write_bytes(canonical(x)+b'\n')
        self.assertFalse(self.audit()['entire_four_model_population_present_and_v8_consistent'])

    def test_owner_human_labels_must_not_enter_model_collector(self):
        (self.root/'owner-only-human-labels.json').write_text('{}\n')
        with self.assertRaises(Invalid):self.audit()

    def test_owner_label_symlink_cannot_bypass(self):
        (self.root/'owner-only-human-labels.json').symlink_to('missing.json')
        with self.assertRaises(Invalid):self.audit()

    def test_root_symlink_not_trusted(self):
        alias=Path(self.tmp.name)/'symlink'
        alias.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(Invalid):original_four_census(self.fit,self.blind,alias)

    def test_cli_writes_failed_census_once_even_if_not_all_models_exist(self):
        save(self.root/'fit.json',self.fit)
        save(self.root/'blind.json',self.blind)
        dest=self.root/'four-census-v10.json'
        args=['prog','--fit',str(self.root/'fit.json'),'--blind',str(self.root/'blind.json'),
              '--artifacts-root',str(self.root),'--output',str(dest)]
        with patch.object(sys,'argv',args):
            with self.assertRaises(SystemExit):main()
        z=json.loads(dest.read_text())
        self.assertFalse(z['entire_four_model_population_present_and_v8_consistent'])
        with patch.object(sys,'argv',args):
            with self.assertRaises(FileExistsError):main()

    def test_independent_scoring_requires_collector_success_not_partial_diagnostic(self):
        wf=(Path(__file__).resolve().parents[2]/'.github/workflows/hepta-p0-multirc-semantic-four.yml').read_text()
        score=wf.split('  independent-human-score:\n',1)[1]
        self.assertIn('physical-four-models',score.split('    runs-on:',1)[0])
        self.assertNotIn('partial-original-model-diagnostic',score.split('    runs-on:',1)[0])
        matrix=wf.split('  physical-single-model:\n',1)[1].split('  physical-four-models:\n',1)[0]
        self.assertNotIn('owner-only-human-labels',matrix)
        self.assertIn('if: always()',matrix)

    def test_cli_model_scoped_preflight_runs_only_one_requested_actual_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            source=FakeSource(root)
            a=preflight(root/'only-granite',model_info=source.info,
                        download=source.download,only_model='granite_97m_r2')
            self.assertEqual(set(a['models']),{'granite_97m_r2'})
            self.assertEqual(len(source.calls),2)
            self.assertEqual(a['models']['granite_97m_r2']['status'],
                             'source_materialized_not_model_qualified')
            self.assertFalse(a['whole_four_model_success'])
            self.assertFalse(a['all_compact_source_preflight_completed'])
            self.assertTrue(a['scoped_single_candidate'])
            self.assertEqual(a['requested_models'],['granite_97m_r2'])

    def test_cli_model_scoped_preflight_rejects_unknown_candidate(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(PreflightInvalid):
                preflight(Path(folder)/'root',model_info=lambda **k:None,
                          download=lambda **k:None,only_model='random_checkpoint')


if __name__=='__main__':unittest.main()
