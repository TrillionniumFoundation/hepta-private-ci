import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import torch

from public_encoder_probe import (ALLOWED_FILES, ProbeCoverageError, _measure_features,
                                   acquire_public, probe)
from test_transformer_work import transformer_policy
from test_transformer_work_v3 import expanded_policy


class ExpandedProbeTests(unittest.TestCase):
    def info(self, revision):
        return SimpleNamespace(sha=revision,siblings=[SimpleNamespace(rfilename=n,size=2) for n in ALLOWED_FILES])

    def test_requested_revision_is_frozen_before_transfer(self):
        revision='a'*40
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def info(repo,**kw):
                self.assertEqual(kw['revision'],revision)
                return self.info(revision)
            def download(repo,**kw):
                self.assertEqual(kw['revision'],revision)
                self.assertTrue((root/'source-lock.json').is_file())
                target=Path(kw['local_dir']);target.mkdir()
                for name in kw['allow_patterns']:(target/name).write_bytes(b'{}')
            api=SimpleNamespace(HfApi=lambda **kw:SimpleNamespace(model_info=info),snapshot_download=download)
            with patch.dict('sys.modules',{'huggingface_hub':api}):acquire_public(root,revision=revision)
            self.assertTrue((root/'downloaded-material.json').is_file())

    def test_changed_resolved_revision_refused_before_transfer(self):
        with tempfile.TemporaryDirectory() as tmp:
            download=unittest.mock.Mock()
            api=SimpleNamespace(HfApi=lambda **kw:SimpleNamespace(model_info=lambda *a,**k:self.info('b'*40)),
                                snapshot_download=download)
            with patch.dict('sys.modules',{'huggingface_hub':api}),self.assertRaisesRegex(ValueError,'different requested'):
                acquire_public(Path(tmp),revision='a'*40)
            download.assert_not_called()
            self.assertFalse((Path(tmp)/'source-lock.json').exists())

    def test_mutable_explicit_revision_refused_before_hub_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            for revision in ('latest','refs/main','',None):
                with self.subTest(revision=revision),self.assertRaises(ValueError):
                    acquire_public(Path(tmp),revision=revision)

    def test_actual_kernel_probe_has_same_features_and_strict_complete_count(self):
        def vectorize(torch_,model,tokenizer,row,device,**kw):
            left=torch.ones(2,3);right=torch.ones(3,4)
            return torch.ops.aten.matmul.default(left,right)[0],6
        # Actual tensor work, synthetic callback; stock-HF integration is separate.
        with patch('public_encoder_probe.vectorize_case',side_effect=vectorize):
            old,counts,a=_measure_features(torch,None,None,transformer_policy('observe'))
            new,lengths,b=_measure_features(torch,None,None,expanded_policy())
        self.assertEqual(counts,lengths)
        for x,y in zip(old,new):torch.testing.assert_close(x,y,rtol=0,atol=0)
        self.assertGreater(b['phase_flops']['inference'],0)
        self.assertEqual(b['unknown_operators'],{})

    def test_strict_failure_retains_cost_and_unknown_operator(self):
        def unsupported(*a,**kw):return torch.ones(3).acos(),3
        with patch('public_encoder_probe.vectorize_case',side_effect=unsupported):
            with self.assertRaises(ProbeCoverageError) as failure:
                _measure_features(torch,None,None,expanded_policy())
        record=failure.exception.observation
        self.assertIn('aten.acos.default',record['unknown_operators'])
        self.assertEqual(record['scopes'][0]['failed_calls'],1)
        self.assertIsNone(record['phase_flops']['inference'])

    def test_same_model_comparison_preserves_legacy_path_and_publishes_six_calls(self):
        # Loader/Tokenizer are substitutes, while all feature arithmetic executes.
        full=torch.nn.Module();full.head=torch.nn.Linear(2,2)
        encoder=SimpleNamespace(config=SimpleNamespace(hidden_size=4))
        def vectorize(torch_,model,tokenizer,row,device,**kw):
            scale=2. if row['state'].startswith('A ') else 1.
            return (torch.ones(2,3)*scale @ torch.ones(3,4))[0],6
        fake=SimpleNamespace(__version__='test-only',AutoTokenizer=SimpleNamespace(from_pretrained=lambda *a,**kw:object()))
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'config.json').write_text('{}')
            with patch.dict('sys.modules',{'transformers':fake}), \
                 patch('public_encoder_probe.load_complete_mlm',return_value=(full,encoder,{})), \
                 patch('public_encoder_probe.verify_loaded_safetensors'), \
                 patch('public_encoder_probe.vectorize_case',side_effect=vectorize):
                old=probe(tmp);new=probe(tmp,compare_arithmetic=True)
        self.assertEqual(old['schema'],'hepta.public-encoder-probe.v1')
        self.assertNotIn('arithmetic_comparison',old)
        self.assertEqual(new['inference_calls'],6)
        comparison=new['arithmetic_comparison']
        self.assertEqual(comparison['previous_feature_sha256'],comparison['current_feature_sha256'])
        self.assertFalse(comparison['full_system_cost_measured'])
        self.assertFalse(new['efficacy_established'])

    def test_capture_fit_binding_accepts_new_units_but_rejects_old_runtime_units(self):
        from test_paired_capture import setup_capture,Clock
        from test_paired_capture_export import observe
        from paired_capture import freeze_capture,create_capture,PairCollector
        from paired_capture_export import assemble_pairs,fit_collected
        from matrix_materials import file_sha256
        from empirical_continuation import FrozenPairedCritic
        from ndu_continuation import freeze_policy
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            original,_,_,propose,verify=setup_capture(root/'unused')
            p=original['protocol']
            registration=freeze_capture(p,expected_protocol_id=p['protocol_id'],boundaries=original['boundaries'],
                                         meter_policy=expanded_policy(),phase_caps=original['phase_caps'])
            create_capture(root/'actual',registration)
            collector=PairCollector(root/'actual',expected_capture_id=registration['capture_id'],
                callback_profile_sha256='b'*64,propose=propose,verify=verify)
            clock=Clock();seals=[collector.run_pair(r['pair_id'],clock=clock) for r in p['pairs']]
            observed=observe(root/'actual',registration,seals)
            _,rows,lineage=assemble_pairs(root/'actual',expected_capture_id=registration['capture_id'],
                observer_path=observed,expected_observer_sha256=file_sha256(observed))
            artifact,_=fit_collected(p,rows,lineage)
            critic=FrozenPairedCritic(artifact,expected_id=artifact['artifact_id'],
                callback_profile_sha256='b'*64,propose=propose,verify=verify)
            args=dict(objective_sha256=p['objective_sha256'],subject_id=p['subject_id'],
                critic_sha256=artifact['artifact_id'],critic_cutoff_ns=p['cutoff_ns'],expires_at_ns=p['expires_at_ns'],
                **p['coefficients'],minimum_margin=0.,max_estimate_age_ns=10**15,empirical_protocol_id=p['protocol_id'])
            execution=dict(max_rounds=2,max_calls=5,meter_policy=registration['meter_policy'],phase_caps=registration['phase_caps'])
            critic.validate_binding(freeze_policy(**args,execution=execution),propose,verify)
            wrong={**execution,'meter_policy':transformer_policy()}
            with self.assertRaisesRegex(ValueError,'arithmetic'):
                critic.validate_binding(freeze_policy(**args,execution=wrong),propose,verify)


if __name__=='__main__':unittest.main()
