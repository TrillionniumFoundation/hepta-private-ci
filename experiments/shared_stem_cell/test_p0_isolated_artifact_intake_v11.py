"""Original-only matrix-ingest source tests; all sample model data is SYNTHETIC."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from p0_multirc_semantic_material import Invalid, save
from p0_isolated_artifact_intake_v11 import (
    SCHEMA, isolated_intake, _inventory_arm)
from p0_parallel_model_collector_v10 import ATTEMPT_SCHEMA, original_four_census
from p0_partial_pretrained_diagnostic_v8 import MODELS

RUN='38683402065'


class IsolatedArtifactTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        r=Path(self.t.name)
        self.root=r/'attempts';self.root.mkdir()
        self.out=r/'joined';self.out.mkdir()
        (self.out/'fit.json').write_text('{"test":"training source"}\n')
        (self.out/'blind.json').write_text('{"test":"blind source"}\n')

    def folder(self,model):
        d=self.root/f'hepta-human-original-arm-{model}-{RUN}'
        d.mkdir()
        return d

    def attempt(self,folder,model,success):
        save(folder/f'attempt-{model}.json',{'schema':ATTEMPT_SCHEMA,
            'model':model,'outcome':'model_report_written' if success else 'failed_or_incomplete',
            'authority':'DENY_ALL','production_promotion_permitted':False,
            'held_test_labels_accessed':False})
        if success:
            (folder/f'{model}.json').write_text('{"synthetic":true}\n')
            if model!='laya421_nochange':
                r=folder/f'{model}.replay';r.mkdir()
                (r/'COMMITTED.json').write_text('{"synthetic":true}\n')
                (r/'features.safetensors').write_bytes(b'synthetic-replay-feature-fixture')
                (r/'heads.safetensors').write_bytes(b'synthetic-replay-head-fixture')
        else:
            (folder/f'{model}.failed.txt').write_text('source missing or model unavailable\n')
        return folder

    def collect(self):
        return isolated_intake(self.root,self.out,RUN)

    def test_missing_all_models_remains_explicit_zero_attestation(self):
        r=self.collect()
        self.assertEqual(r['schema'],SCHEMA)
        self.assertTrue(all(x['status']=='artifact_not_uploaded' for x in r['original_attempt_upload_statuses'].values()))
        self.assertFalse(r['entire_four_model_population_verified'])
        self.assertFalse(r['independently_confirmed_pretrained_execution'])
        self.assertFalse(r['production_promotion_permitted'])
        self.assertTrue((self.out/'artifact-intake-v11.json').is_file())
        self.assertEqual(len(r['intake_file_sha256']),0)

    def test_one_good_original_arm_preserves_original_file_and_completeness_denial(self):
        arm=self.attempt(self.folder('granite_97m_r2'),'granite_97m_r2',True)
        self.assertIn('granite_97m_r2.replay', {p.name for p in arm.iterdir()})
        r=self.collect()
        self.assertEqual(r['original_attempt_upload_statuses']['granite_97m_r2']['status'],'model_report_written')
        self.assertEqual(r['original_attempt_upload_statuses']['mmbert_small']['status'],'artifact_not_uploaded')
        self.assertEqual((self.out/'granite_97m_r2.replay/heads.safetensors').read_bytes(),b'synthetic-replay-head-fixture')
        self.assertNotIn('owner-only-human-labels.json',{p.name for p in self.out.iterdir()})
        self.assertEqual((self.out/'fit.json').read_text(),'{"test":"training source"}\n')

    def test_one_failure_not_a_zero_score_or_success(self):
        self.attempt(self.folder('mmbert_small'),'mmbert_small',False)
        r=self.collect()
        self.assertEqual(r['original_attempt_upload_statuses']['mmbert_small']['status'],'failed_or_incomplete')
        self.assertFalse((self.out/'mmbert_small.json').exists())
        self.assertEqual((self.out/'mmbert_small.failed.txt').read_text(),'source missing or model unavailable\n')

    def test_all_four_original_slots_kept_separate_without_merging_names(self):
        for model in MODELS:
            self.attempt(self.folder(model),model,True)
        r=self.collect()
        self.assertEqual(len(r['original_attempt_upload_statuses']),4)
        self.assertEqual(set(r['intake_file_sha256'])&{f'{m}.json' for m in MODELS},{f'{m}.json' for m in MODELS})
        self.assertFalse(r['entire_four_model_population_verified'])
        self.assertEqual(sum(x['status']=='model_report_written' for x in r['original_attempt_upload_statuses'].values()),4)

    def test_cross_model_attempt_receipt_name_rejected(self):
        folder=self.attempt(self.folder('granite_97m_r2'),'granite_97m_r2',True)
        p=folder/'attempt-granite_97m_r2.json';a=json.loads(p.read_text());a['model']='mmbert_small'
        p.write_text(json.dumps(a))
        with self.assertRaises(Invalid):self.collect()
        self.assertFalse((self.out/'artifact-intake-v11.json').exists())

    def test_duplicate_attempt_json_key_rejected(self):
        folder=self.attempt(self.folder('granite_97m_r2'),'granite_97m_r2',True)
        p=folder/'attempt-granite_97m_r2.json';p.write_text(p.read_text().replace('"authority":','"authority":"DENY_ALL","authority":'))
        with self.assertRaises(Invalid):self.collect()

    def test_other_arm_model_report_cannot_be_injected(self):
        folder=self.attempt(self.folder('granite_97m_r2'),'granite_97m_r2',True)
        (folder/'mmbert_small.json').write_text('wrong-runner fabricated report\n')
        with self.assertRaises(Invalid):self.collect()
        self.assertFalse((self.out/'mmbert_small.json').exists())

    def test_checkpoint_weights_cannot_be_uploaded_as_model_receipts(self):
        folder=self.attempt(self.folder('granite_97m_r2'),'granite_97m_r2',True)
        (folder/'model.safetensors').write_bytes(b'pretend-foundation-weights')
        with self.assertRaises(Invalid):self.collect()

    def test_replay_outside_three_registered_file_names_rejected(self):
        folder=self.attempt(self.folder('mmbert_small'),'mmbert_small',True)
        (folder/'mmbert_small.replay/test-labels.json').write_text('bad')
        with self.assertRaises(Invalid):self.collect()

    def test_symlinked_model_feature_rejected(self):
        folder=self.attempt(self.folder('mmbert_small'),'mmbert_small',True)
        f=folder/'mmbert_small.replay/features.safetensors';f.unlink();f.symlink_to('/etc/hosts')
        with self.assertRaises(Invalid):self.collect()

    def test_symlinked_runner_directory_rejected(self):
        external=Path(self.t.name)/'outside';external.mkdir()
        (self.root/f'hepta-human-original-arm-mmbert_small-{RUN}').symlink_to(external,target_is_directory=True)
        with self.assertRaises(Invalid):self.collect()

    def test_symlinked_collector_fit_rejected(self):
        (self.out/'fit.json').unlink();(self.out/'fit.json').symlink_to('/etc/hosts')
        with self.assertRaises(Invalid):self.collect()

    def test_model_failure_plus_success_report_rejected(self):
        folder=self.attempt(self.folder('granite_97m_r2'),'granite_97m_r2',False)
        (folder/'granite_97m_r2.json').write_text('{"forged":true}')
        with self.assertRaises(Invalid):self.collect()

    def test_native_laya_must_not_contain_trained_head_replay(self):
        folder=self.attempt(self.folder('laya421_nochange'),'laya421_nochange',True)
        (folder/'laya421_nochange.replay').mkdir()
        with self.assertRaises(Invalid):self.collect()

    def test_forged_source_identity_or_permissions_are_not_accepted(self):
        folder=self.attempt(self.folder('embeddinggemma_2_text'),'embeddinggemma_2_text',True)
        path=folder/'attempt-embeddinggemma_2_text.json';a=json.loads(path.read_text())
        a['production_promotion_permitted']=True;path.write_text(json.dumps(a))
        with self.assertRaises(Invalid):self.collect()

    def test_runtime_or_failure_slot_oversize_rejected(self):
        folder=self.attempt(self.folder('laya421_nochange'),'laya421_nochange',False)
        with (folder/'laya421_nochange.failed.txt').open('wb') as f:
            f.truncate(300_000)
        with self.assertRaises(Invalid):self.collect()

    def test_missing_and_swapped_run_identity_rejected(self):
        self.attempt(self.folder('mmbert_small'),'mmbert_small',True)
        with self.assertRaises(Invalid):isolated_intake(self.root,self.out,'00000000000000000000000000000000')
        wrong=self.root/f'hepta-human-original-arm-mmbert_small-{RUN}'
        wrong.rename(self.root/'hepta-human-original-arm-mmbert_small-12345')
        with self.assertRaises(Invalid):self.collect()

    def test_unregistered_extra_top_level_file_rejected(self):
        (self.root/'owner-only-human-labels.json').write_text('{"leak":true}')
        with self.assertRaises(Invalid):self.collect()

    def test_repeat_cannot_replace_original_intake_or_overwrite(self):
        self.attempt(self.folder('mmbert_small'),'mmbert_small',False)
        self.collect()
        with self.assertRaises(Invalid):self.collect()
        self.assertTrue((self.out/'artifact-intake-v11.json').exists())

    def test_copy_is_byte_equal_with_hash_manifest(self):
        folder=self.attempt(self.folder('mmbert_small'),'mmbert_small',True)
        original=(folder/'mmbert_small.replay/features.safetensors').read_bytes()
        r=self.collect()
        digest=r['intake_file_sha256']['mmbert_small.replay/features.safetensors']
        import hashlib
        self.assertEqual(hashlib.sha256(original).hexdigest(),digest)
        self.assertEqual((self.out/'mmbert_small.replay/features.safetensors').read_bytes(),original)

    def test_source_workflow_prohibits_flat_last_writer_wins_and_retains_four_gate(self):
        path=Path(__file__).resolve().parents[2]/'.github/workflows/hepta-p0-multirc-semantic-four.yml'
        s=path.read_text();collector=s.split('  physical-four-models:\n',1)[1].split('  partial-original-model-diagnostic:\n',1)[0]
        self.assertIn('merge-multiple: false',collector)
        self.assertNotIn('merge-multiple: true',collector)
        self.assertIn('p0_isolated_artifact_intake_v11.py',collector)
        self.assertIn('p0_parallel_model_collector_v10.py',collector)
        self.assertLess(collector.index('p0_isolated_artifact_intake_v11.py'),collector.index('p0_parallel_model_collector_v10.py'))
        self.assertIn('if: always()',collector)
        score=s.split('  independent-human-score:\n',1)[1].split('    runs-on:',1)[0]
        self.assertIn('physical-four-models',score)
        self.assertIn('independent-original-head-training',score)
        self.assertNotIn('partial-original-model-diagnostic',score)


class EndToEndIntakeThenOriginalCensus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_p0_parallel_model_collector_v10 import CollectorScientificDenials
        cls.original=CollectorScientificDenials
        cls.original.setUpClass()

    def setUp(self):
        self.raw=self.original(methodName='test_all_four_synthetic_source_arms_must_be_present_for_census_only')
        self.raw.setUp()
        self.addCleanup(self.raw.doCleanups)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.attempts=self.base/'arms';self.attempts.mkdir()
        self.out=self.base/'join';self.out.mkdir()
        save(self.out/'fit.json',self.original.fit)
        save(self.out/'blind.json',self.original.blind)

    def test_isolated_synthetic_archive_roundtrip_to_original_numeric_v8_and_four_census(self):
        for model in MODELS:
            self.raw.complete(model)
            folder=self.attempts/f'hepta-human-original-arm-{model}-{RUN}'
            folder.mkdir()
            for path in self.raw.root.iterdir():
                if (path.name.startswith(model) or path.name==f'attempt-{model}.json'):
                    if path.is_dir():shutil.copytree(path,folder/path.name)
                    else:shutil.copyfile(path,folder/path.name)
        result=isolated_intake(self.attempts,self.out,RUN)
        check=original_four_census(self.original.fit,self.original.blind,self.out)
        self.assertEqual(len(result['original_attempt_upload_statuses']),4)
        self.assertTrue(check['entire_four_model_population_present_and_v8_consistent'])
        self.assertEqual(check['authority'],'DENY_ALL')
        self.assertFalse(check['full_pretrained_model_execution_independently_authenticated'])


if __name__=='__main__':unittest.main()
