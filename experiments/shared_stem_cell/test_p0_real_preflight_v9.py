"""Real-source pin/fail-open prevention and V7 CLI command validation.

All material fixtures are deliberately fake and local. Passing tests neither
loads Granite/mmBERT/Gemma/Laya nor authorizes model selection or FinalUse.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

from p0_pretrained_checkpoint_preflight_v9 import (
    ALLOW, CANDIDATES, Invalid, REQUIRED, SCHEMA, preflight, verify_snapshot)


class FakeSource:
    def __init__(self, directory: Path):
        self.root=directory
        self.calls=[]
        self.fail_for=set()
        self.bad_sha_for=set()
        self.missing_for=set()
        self.bad_revision_for=set()
        self.files={}
        for name,(repo,revision) in CANDIDATES.items():
            dest=directory/name
            dest.mkdir()
            for rel in REQUIRED:
                (dest/rel).write_bytes(f'FAKE {name}:{rel}'.encode())
            self.files[repo]=dest

    def info(self, *, repo_id, revision, files_metadata):
        self.calls.append(('info',repo_id,revision))
        if repo_id in self.fail_for:
            raise ConnectionError('fake source unavailable')
        assert files_metadata
        dest=self.files[repo_id]
        names=list(REQUIRED)
        children=[]
        for name in names:
            wanted=hashlib.sha256((dest/name).read_bytes()).hexdigest()
            if repo_id in self.bad_sha_for and name=='model.safetensors':
                wanted='0'*64
            children.append(SimpleNamespace(rfilename=name,lfs={'sha256':wanted}))
        return SimpleNamespace(sha=(revision if repo_id not in self.bad_revision_for else 'f'*40),
                               siblings=children)

    def download(self, *, repo_id, revision, allow_patterns):
        self.calls.append(('download',repo_id,revision))
        assert tuple(allow_patterns)==ALLOW
        return str(self.files[repo_id])


class IndependentCompactSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.source=FakeSource(self.folder)
        self.out=self.folder/'experiment'

    def run_preflight(self):
        return preflight(self.out,model_info=self.source.info,download=self.source.download)

    def test_real_pinned_source_admission_contract_both_sources(self):
        ret=self.run_preflight()
        self.assertEqual(ret['schema'],SCHEMA)
        self.assertTrue(ret['all_compact_source_preflight_completed'])
        self.assertEqual(set(ret['models']),set(CANDIDATES))
        self.assertTrue(all(x['status']=='source_materialized_not_model_qualified'
                            for x in ret['models'].values()))
        self.assertEqual(len([v for v in self.source.calls if v[0]=='download']),2)
        self.assertFalse(ret['whole_four_model_success'])
        self.assertFalse(ret['model_selected'])
        self.assertFalse(ret['original_checkpoint_publisher_independently_authenticated'])
        self.assertEqual(ret['authority'],'DENY_ALL')
        self.assertEqual(json.loads((self.out/'compact-preflight-v9.json').read_text()),ret)
        self.assertFalse(any(self.out.glob('*.failed.txt')))

    def test_failed_mmbert_does_not_cancel_valid_granite(self):
        self.source.fail_for.add(CANDIDATES['mmbert_small'][0])
        ret=self.run_preflight()
        self.assertEqual(ret['models']['granite_97m_r2']['status'],'source_materialized_not_model_qualified')
        self.assertEqual(ret['models']['mmbert_small']['status'],'unavailable')
        self.assertEqual(ret['models']['mmbert_small']['preflight_failure_class'],'ConnectionError')
        self.assertTrue((self.out/'mmbert_small.failed.txt').is_file())
        self.assertFalse((self.out/'granite_97m_r2.failed.txt').exists())
        self.assertEqual(len([v for v in self.source.calls if v[0]=='info']),2)
        self.assertFalse(ret['whole_four_model_success'])

    def test_failed_granite_does_not_cancel_valid_mmbert(self):
        self.source.fail_for.add(CANDIDATES['granite_97m_r2'][0])
        ret=self.run_preflight()
        self.assertEqual(ret['models']['mmbert_small']['status'],'source_materialized_not_model_qualified')
        self.assertEqual(ret['models']['granite_97m_r2']['status'],'unavailable')
        self.assertTrue((self.out/'granite_97m_r2.failed.txt').is_file())

    def test_both_real_source_download_errors_remain_unavailable(self):
        self.source.fail_for.update(x[0] for x in CANDIDATES.values())
        ret=self.run_preflight()
        self.assertFalse(ret['all_compact_source_preflight_completed'])
        self.assertEqual(sum(x['status']=='unavailable' for x in ret['models'].values()),2)
        self.assertTrue(all((self.out/f'{name}.failed.txt').exists() for name in CANDIDATES))

    def test_same_snapshot_wrong_publisher_lfs_bytes_is_rejected(self):
        self.source.bad_sha_for.add(CANDIDATES['mmbert_small'][0])
        ret=self.run_preflight()
        self.assertEqual(ret['models']['mmbert_small']['preflight_failure_class'],'Invalid')
        self.assertEqual(ret['models']['granite_97m_r2']['status'],'source_materialized_not_model_qualified')
        self.assertNotIn('full_pretrained_model_accepted',repr(ret))

    def test_wrong_upstream_revision_rejected_without_other_model_loss(self):
        self.source.bad_revision_for.add(CANDIDATES['granite_97m_r2'][0])
        ret=self.run_preflight()
        self.assertEqual(ret['models']['granite_97m_r2']['status'],'unavailable')
        self.assertEqual(ret['models']['mmbert_small']['status'],'source_materialized_not_model_qualified')

    def test_missing_tokenizer_is_not_a_valid_model(self):
        path=self.source.files[CANDIDATES['granite_97m_r2'][0]]/'tokenizer.json'
        path.unlink()
        ret=self.run_preflight()
        self.assertEqual(ret['models']['granite_97m_r2']['status'],'unavailable')

    def test_no_pickle_or_unsafe_remote_code_fallback(self):
        folder=self.source.files[CANDIDATES['mmbert_small'][0]]
        (folder/'unsafe.bin').write_bytes(b'fake native pickle')
        ret=self.run_preflight()
        self.assertEqual(ret['models']['mmbert_small']['status'],'unavailable')
        self.assertFalse(ret['model_selected'])

    def test_preexisting_failure_cannot_be_silently_overwritten(self):
        self.out.mkdir()
        (self.out/'granite_97m_r2.failed.txt').write_text('first real failure\n')
        with self.assertRaises(Invalid):
            self.run_preflight()
        self.assertEqual((self.out/'granite_97m_r2.failed.txt').read_text(),'first real failure\n')

    def test_staged_model_result_cannot_be_pretended_a_new_preflight(self):
        self.out.mkdir()
        (self.out/'mmbert_small.json').write_text('{"previous":"result"}')
        with self.assertRaises(Invalid):
            self.run_preflight()

    def test_symlinked_artifact_directory_cannot_write(self):
        other=self.folder/'external'
        other.mkdir()
        self.out.symlink_to(other,target_is_directory=True)
        with self.assertRaises(Invalid):
            self.run_preflight()

    def test_tampered_safe_file_stays_failure_even_if_repository_sha_matches(self):
        repo,revision=CANDIDATES['granite_97m_r2']
        model=self.source.files[repo]/'model.safetensors'
        original=model.read_bytes()
        old_sha=hashlib.sha256(original).hexdigest()
        def fixed_info(**kw):
            x=self.source.info(**kw)
            for child in x.siblings:
                if child.rfilename=='model.safetensors':child.lfs['sha256']=old_sha
            return x
        model.write_bytes(b'tampered')
        with self.assertRaises(Invalid):
            verify_snapshot(repo,revision,model_info=fixed_info,download=self.source.download)

    def test_preflight_error_does_not_expose_remote_error_message(self):
        original=self.source.info
        def bad_info(**kwargs):
            if kwargs['repo_id']==CANDIDATES['granite_97m_r2'][0]:
                raise ConnectionError('sensitive-repository-token-do-not-log')
            return original(**kwargs)
        ret=preflight(self.out,model_info=bad_info,download=self.source.download)
        self.assertEqual(ret['models']['granite_97m_r2']['status'],'unavailable')
        self.assertNotIn('sensitive-repository-token',
                         (self.out/'granite_97m_r2.failed.txt').read_text())


class OriginalPhysicalWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path=Path(__file__).resolve().parents[2]/'.github/workflows/hepta-p0-multirc-semantic-four.yml'
        cls.text=cls.path.read_text()
        cls.physical=cls.text.split('  physical-four-models:\n',1)[1].split('  partial-original-model-diagnostic:\n',1)[0]
        cls.matrix=cls.text.split('  physical-single-model:\n',1)[1].split('  physical-four-models:\n',1)[0]

    def test_v7_original_40_step_command_has_only_declared_flags(self):
        v7=self.text.split('  independent-original-head-training:\n',1)[1].split('  independent-human-score:\n',1)[0]
        step=v7.split('      - name: Refit two Heads per model from exact original human TRAIN labels and archived Q24 features\n',1)[1]
        # No accidental Python source files as unregistered positional arguments.
        self.assertIn('p0_independent_training_replay_v7.py \\\n            --fit ',step)
        self.assertNotIn('            experiments/shared_stem_cell/p0_partial_pretrained_diagnostic_v8.py \\\n',step)
        self.assertNotIn('            experiments/shared_stem_cell/test_p0_partial_pretrained_diagnostic_v8.py \\\n',step)
        names=re.findall(r'--([a-z0-9-]+)(?=\s)',step.split('; then',1)[0])
        self.assertEqual(set(names),{'fit','blind','granite-97m-r2',
                                     'mmbert-small','embeddinggemma-2-text','head-replay',
                                     'cold-replay','replay-root','output'})

    def test_v7_cli_rejects_historical_extra_files_but_accepts_repaired_argument_layout(self):
        # Execute the original parser, rather than trusting a documentation
        # string. No model is loaded: a nonexistent fit file stops afterward.
        script=Path(__file__).with_name('p0_independent_training_replay_v7.py')
        with tempfile.TemporaryDirectory() as tmp:
            missing=str(Path(tmp)/'missing.json')
            opts=[]
            for opt in ('fit','blind','granite-97m-r2','mmbert-small',
                        'embeddinggemma-2-text','head-replay','cold-replay',
                        'replay-root','output'):
                opts.extend((f'--{opt}',missing))
            fixed=subprocess.run([sys.executable,str(script),*opts],
                                 capture_output=True,text=True,timeout=15)
            self.assertNotEqual(fixed.returncode,0)
            self.assertNotIn('unrecognized arguments',fixed.stderr)
            self.assertIn('FileNotFoundError',fixed.stderr)
            old=subprocess.run([sys.executable,str(script),'accidental-v8.py',
                                'accidental-test-v8.py',*opts],
                               capture_output=True,text=True,timeout=15)
            self.assertNotEqual(old.returncode,0)
            self.assertIn('unrecognized arguments',old.stderr)

    def test_independent_model_preflight_failures_do_not_cancel_other_model(self):
        matrix=self.matrix
        self.assertIn('fail-fast: false',matrix)
        self.assertIn('model: [granite_97m_r2, mmbert_small, embeddinggemma_2_text, laya421_nochange]',matrix)
        self.assertIn('--model "$MODEL" --output-root "$ROOT"',matrix)
        self.assertIn('p0_pretrained_checkpoint_preflight_v9.py',matrix)
        self.assertIn('Gemma pinned checkpoint preparation failed',matrix)
        # Check the exact pinned package and runtime compatibility admitted by V13.
        self.assertIn("'laya==0.3.29'",matrix)
        self.assertNotIn("'laya==0.3.20'",matrix)
        self.assertIn("41a51775eae4bd624688f13425d71ce66aa0f6b9a49a922a775a92dc4a85c885",matrix)
        self.assertIn("sha256sum -c -",matrix)
        self.assertIn("m.version(\"laya\")==\"0.3.29\"",matrix)
        self.assertIn("\"revision\" in inspect.signature(laya.load).parameters",matrix)
        self.assertIn('if [ -s "$ROOT/$MODEL.failed.txt" ]; then',matrix)
        self.assertIn('attempt-{model}.json',matrix)
        self.assertIn('hepta-human-original-arm-${{ matrix.model }}-${{ github.run_id }}',matrix)
        self.assertIn('original pinned pretrained inference failed or timed out',matrix)

    def test_real_four_model_acceptance_remains_all_or_nothing(self):
        collector=self.physical
        self.assertIn('needs: [original-human-materials, physical-single-model]',collector)
        self.assertIn('merge-multiple: false',collector)
        self.assertNotIn('merge-multiple: true',collector)
        self.assertIn('p0_isolated_artifact_intake_v11.py',collector)
        self.assertIn('p0_parallel_model_collector_v10.py',collector)
        self.assertIn('original-arm-*-${{ github.run_id }}',collector)
        self.assertIn('if: always()',collector)
        scorer=self.text.split('  independent-human-score:\n',1)[1]
        self.assertNotIn('partial-original-model-diagnostic',scorer.split('    runs-on:',1)[0])
        self.assertIn('physical-four-models',scorer)
        self.assertIn('independent-original-head-training',scorer)
        self.assertIn('independent-cold-pretrained-encoder',scorer)
        self.assertIn('independent-pretrained-replay',scorer)

    def test_source_tests_include_new_source_preflight(self):
        source=self.text.split('  semantic-source-tests:\n',1)[1].split('  original-human-materials:\n',1)[0]
        self.assertIn('test_p0_real_preflight_v9.py',source)
        self.assertIn('p0_pretrained_checkpoint_preflight_v9.py',source)

    def test_four_model_producer_and_partial_diagnostic_retain_scoped_research_only_mode(self):
        self.assertIn('partial-original-model-diagnostic:',self.text)
        self.assertIn("always() && needs['original-human-materials'].result == 'success'",self.text)
        self.assertIn('test ! -e "$OUT/gemma-snapshot"',self.matrix)
        self.assertNotIn('owner-only-human-labels',self.matrix)
        self.assertNotIn('owner-only-human-labels',self.physical)
        self.assertNotIn('tool-dispatch',self.matrix)
        self.assertNotIn('tool-dispatch',self.physical)
        self.assertIn('held_test_labels_accessed',self.matrix)


if __name__=='__main__':
    unittest.main()
