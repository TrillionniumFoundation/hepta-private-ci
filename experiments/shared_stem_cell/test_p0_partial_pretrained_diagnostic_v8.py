"""Adversarial tests of partial ORIGINAL physical reports, using SYNTHETIC features.

No hosted checkpoint was downloaded or human-held label opened in these tests.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from p0_multirc_semantic_material import Invalid, canonical, save
from p0_multirc_semantic_execute import fit_head
from p0_partial_pretrained_diagnostic_v8 import audit_partial, main, MODELS, SCHEMA
from p0_physical_replay_v5 import export_original_replay
from p0_question_only_head import fit_question_only
from test_p0_multirc_semantic import setup, mocked_report
from test_p0_question_only_matched import fake_vectors


class PartialProducerDiagnostic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _,_,cls.fit,cls.blind,_=setup()
        cls.templates={}
        for model,width in [('granite_97m_r2',384),('mmbert_small',384),('embeddinggemma_2_text',256)]:
            features=fake_vectors(cls.fit['cases']+cls.blind['cases'],width)
            weights={}
            head=fit_head(cls.fit['cases'],cls.blind['cases'],features,width,replay_heads=weights)
            prior=fit_question_only(cls.fit,cls.blind,features,width,head,replay_heads=weights)
            report=mocked_report(model,cls.fit,cls.blind)
            report['training']=head
            report['control']=head['controls']
            report['matched_question_only_control']=prior
            cls.templates[model]=(features,weights,report)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'original-producer'
        self.root.mkdir()

    def _complete(self,model='granite_97m_r2'):
        features,heads,report=self.templates[model]
        report=copy.deepcopy(report)
        save(self.root/f'{model}.json',report)
        export_original_replay(self.root/f'{model}.replay',self.fit,self.blind,report,model,features,heads)
        return report

    def _result(self):
        return audit_partial(self.fit,self.blind,self.root)

    def _save_invalid(self,obj,model='granite_97m_r2'):
        (self.root/f'{model}.json').write_bytes(canonical(obj)+b'\n')

    def test_missing_all_not_an_accepted_four_model_report(self):
        x=self._result()
        self.assertEqual(x['schema'],SCHEMA)
        self.assertEqual(x['original_model_reports_numeric_or_identity_consistent'],0)
        self.assertEqual(x['unavailable_model_count'],4)
        self.assertFalse(x['whole_four_model_success'])
        self.assertFalse(x['task_quality_or_stem_ranking_computed'])
        self.assertEqual({v['status'] for v in x['models'].values()},{'unavailable'})

    def test_genuine_synthetic_one_model_head_replay_preserves_three_missing(self):
        self._complete()
        x=self._result()
        self.assertFalse(x['invalid_source_or_report_present'])
        self.assertEqual(x['original_model_reports_numeric_or_identity_consistent'],1)
        self.assertEqual(x['unavailable_model_count'],3)
        good=x['models']['granite_97m_r2']
        self.assertEqual(good['status'],'original_head_numeric_replay_consistent')
        self.assertEqual(good['recomputed_held_predictions'],192)
        self.assertLess(good['max_probability_difference'],3e-5)
        self.assertFalse(good['encoder_source_cold_verified_by_this_job'])

    def test_two_valid_models_and_two_missing(self):
        self._complete('granite_97m_r2')
        self._complete('embeddinggemma_2_text')
        x=self._result()
        self.assertEqual(x['original_model_reports_numeric_or_identity_consistent'],2)
        self.assertEqual(x['unavailable_model_count'],2)
        self.assertFalse(x['whole_four_model_success'])

    def test_three_present_models_cannot_be_promoted_without_laya(self):
        for name in ('granite_97m_r2','mmbert_small','embeddinggemma_2_text'):
            self._complete(name)
        x=self._result()
        self.assertEqual(x['original_model_reports_numeric_or_identity_consistent'],3)
        self.assertFalse(x['whole_four_model_success'])
        self.assertFalse(x['independent_real_pretrained_weight_origin_verified'])

    def test_declared_failure_slot_is_unavailable_not_zero_quality(self):
        (self.root/'mmbert_small.failed.txt').write_text('intentional study failure\n')
        x=self._result()
        self.assertEqual(x['models']['mmbert_small']['status'],'unavailable')
        self.assertEqual(x['models']['mmbert_small']['reason'],'producer_declared_failed_model')
        self.assertNotIn('accuracy',x['models']['mmbert_small'])

    def test_report_without_checkpoint_is_invalid_not_missing(self):
        x=self.templates['granite_97m_r2'][2]
        save(self.root/'granite_97m_r2.json',x)
        result=self._result()
        self.assertEqual(result['models']['granite_97m_r2']['status'],'invalid')
        self.assertTrue(result['invalid_source_or_report_present'])

    def test_checkpoint_without_report_is_invalid_not_missing(self):
        self._complete()
        (self.root/'granite_97m_r2.json').unlink()
        self.assertEqual(self._result()['models']['granite_97m_r2']['status'],'invalid')

    def test_tampered_probabilities_even_self_rehashed_are_invalid(self):
        report=self._complete()
        report['control']['trained_head']['predictions'][0]['positive_probability']=.9999
        self._save_invalid(report)
        self.assertEqual(self._result()['models']['granite_97m_r2']['status'],'invalid')

    def test_forged_model_origin_or_authority_rejected(self):
        report=self._complete()
        report['physical_model_origin_independently_signed']=True
        self._save_invalid(report)
        self.assertTrue(self._result()['invalid_source_or_report_present'])

    def test_symlinked_report_is_invalid(self):
        self._complete()
        report=self.root/'granite_97m_r2.json'
        outside=self.root/'saved-original.json'
        report.rename(outside);report.symlink_to(outside.name)
        self.assertEqual(self._result()['models']['granite_97m_r2']['status'],'invalid')

    def test_symlinked_replay_directory_is_invalid(self):
        self._complete()
        replay=self.root/'granite_97m_r2.replay'
        outside=self.root/'saved-original.replay'
        replay.rename(outside);replay.symlink_to(outside.name,target_is_directory=True)
        self.assertTrue(self._result()['invalid_source_or_report_present'])

    def test_contradictory_failure_and_report_never_succeeds(self):
        self._complete()
        (self.root/'granite_97m_r2.failed.txt').write_text('unresolved terminal outcome\n')
        self.assertEqual(self._result()['models']['granite_97m_r2']['status'],'invalid')

    def test_symlinked_failure_slot_rejected(self):
        target=self.root/'original.txt';target.write_text('failed\n')
        (self.root/'mmbert_small.failed.txt').symlink_to(target.name)
        self.assertTrue(self._result()['invalid_source_or_report_present'])

    def test_laya_is_only_native_input_prediction_identity(self):
        report=mocked_report('laya421_nochange',self.fit,self.blind)
        save(self.root/'laya421_nochange.json',report)
        x=self._result()
        laya=x['models']['laya421_nochange']
        self.assertEqual(laya['status'],'laya_native_identity_only')
        self.assertFalse(laya['numeric_recomputed_from_laya_weights'])
        self.assertFalse(laya['actual_weight_source_independently_authenticated'])
        self.assertEqual(laya['native_frozen_prediction_count'],len(self.blind['cases']))

    def test_laya_learned_head_impersonation_rejected(self):
        report=mocked_report('laya421_nochange',self.fit,self.blind)
        report['training']={'parameter_count':770}
        save(self.root/'laya421_nochange.json',report)
        self.assertEqual(self._result()['models']['laya421_nochange']['status'],'invalid')

    def test_laya_replay_impersonation_rejected(self):
        report=mocked_report('laya421_nochange',self.fit,self.blind)
        save(self.root/'laya421_nochange.json',report)
        (self.root/'laya421_nochange.replay').mkdir()
        self.assertEqual(self._result()['models']['laya421_nochange']['status'],'invalid')

    def test_even_complete_four_report_never_grants_approval(self):
        for name in ('granite_97m_r2','mmbert_small','embeddinggemma_2_text'):
            self._complete(name)
        save(self.root/'laya421_nochange.json',mocked_report('laya421_nochange',self.fit,self.blind))
        out=self._result()
        self.assertEqual(out['original_model_reports_numeric_or_identity_consistent'],4)
        self.assertEqual(out['unavailable_model_count'],0)
        self.assertFalse(out['whole_four_model_success'])
        self.assertFalse(out['task_quality_or_stem_ranking_computed'])
        self.assertFalse(out['source_head_accepted_for_production'])
        self.assertFalse(out['production_promotion_permitted'])

    def test_fail_closed_cli_still_seals_failure_observation(self):
        self._complete()
        # Wrong model source metadata: fail once, but preserve diagnostic JSON.
        report=json.loads((self.root/'granite_97m_r2.json').read_text())
        report['model_revision']='invalid-revision'
        self._save_invalid(report)
        outfile=Path(self.tmp.name)/'diagnostic.json'
        args=['program','--fit',str(Path(self.tmp.name)/'fit.json'),
              '--blind',str(Path(self.tmp.name)/'blind.json'),
              '--artifacts-root',str(self.root),'--output',str(outfile)]
        save(Path(self.tmp.name)/'fit.json',self.fit)
        save(Path(self.tmp.name)/'blind.json',self.blind)
        with patch.object(sys,'argv',args):
            with self.assertRaises(SystemExit):main()
        result=json.loads(outfile.read_text())
        self.assertTrue(result['invalid_source_or_report_present'])
        self.assertEqual(result['models']['granite_97m_r2']['status'],'invalid')
        with patch.object(sys,'argv',args):
            with self.assertRaises(FileExistsError):main()

    def test_wrong_source_scope_even_self_consistent_receipt_rejected(self):
        report=self._complete()
        report['blind_material_sha256']='b'*64
        self._save_invalid(report)
        self.assertEqual(self._result()['models']['granite_97m_r2']['status'],'invalid')

    def test_missing_human_label_receipt_is_not_needed_for_partial_review(self):
        self._complete()
        names={k for k in self.root.iterdir() if k.name.endswith('.json')}
        self.assertNotIn(self.root/'owner-only-human-labels.json',names)
        self.assertFalse(self._result()['human_evaluation_labels_accessed'])

    def test_untrusted_partial_root_symlink_rejected(self):
        new=Path(self.tmp.name)/'alias'
        new.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(Invalid):audit_partial(self.fit,self.blind,new)


class WorkflowIsolationTests(unittest.TestCase):
    def test_partial_diagnosis_is_after_original_material_even_on_model_failure(self):
        text=(Path(__file__).resolve().parents[2]/'.github/workflows/hepta-p0-multirc-semantic-four.yml').read_text()
        selected=text.split('  partial-original-model-diagnostic:\n',1)[1].split('  independent-pretrained-replay:\n',1)[0]
        self.assertIn("needs: [original-human-materials, physical-four-models]",selected)
        self.assertIn("always() && needs['original-human-materials'].result == 'success'",selected)
        self.assertIn("name: hepta-human-four-original-predictions-${{ github.run_id }}",selected)
        self.assertNotIn('owner-only-human-labels',selected)
        self.assertNotIn('score',selected.split('name: Audit each original model')[0].lower())

    def test_partial_diagnostic_cannot_authorize_scientific_scoring(self):
        text=(Path(__file__).resolve().parents[2]/'.github/workflows/hepta-p0-multirc-semantic-four.yml').read_text()
        scorer=text.split('  independent-human-score:\n',1)[1]
        self.assertIn('needs: [original-human-materials, physical-four-models, independent-pretrained-replay, independent-cold-pretrained-encoder, independent-original-head-training]',scorer)
        self.assertNotIn('partial-original-model-diagnostic',scorer)


if __name__=='__main__':unittest.main()
