"""Adversarial receipt/material and real child-budget tests; no fabricated efficacy."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import llm_runtime_pilot as runtime


class RuntimePilotTests(unittest.TestCase):
    def setUp(self):
        self.plan = runtime.experiment_plan({'test_fixture': 'not-model-material'})
        self.contract = 'c'*64
        self.artifact = 'a'*64

    def predictions(self):
        c = runtime.contract_module()
        values = []
        for row in self.plan['tasks']:
            if row['partition'] == 'training':
                continue
            request = dict(schema='pon-causal-decoder-request-v1', contract=self.contract,
                           input_ids=[[1, 5]], attention_mask=[[True, True]], generation_tokens=8)
            rid = c.H('causal-decoder-request-v1', c.canonical(request)).hex()
            # This is an attack-checking record fixture, never inference evidence.
            response = dict(schema='pon-causal-decoder-reported-response-v1', contract=self.contract,
                            request=rid, generated_token_ids=[[6]*8], decoded_outputs=['fixture'])
            values.append(dict(task=row['id'], snapshot=self.plan['snapshot'], numeric_dtype='float32',
                role='candidate', artifact=self.artifact, actual_device='cpu', request=request,
                request_id=rid, response=response, generated_tokens=8,
                output_sha256=hashlib.sha256(b'fixture').hexdigest()))
        return values

    def verify(self, rows):
        return runtime.verify_predictions(rows, self.plan, 'candidate', self.artifact, self.contract)

    def test_mandatory_controls_and_all_false_scope(self):
        runtime.validate_plan(self.plan)
        for name in runtime.QUALIFICATIONS:
            changed = copy.deepcopy(self.plan); changed[name] = True
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'QUALIFICATION_SCOPE'):
                runtime.validate_plan(changed)
        changed = copy.deepcopy(self.plan); changed['participants'].remove('budget-matched-full-tune')
        with self.assertRaisesRegex(ValueError, 'REQUIRED_CONTROLS'):
            runtime.validate_plan(changed)

    def test_frozen_family_rejects_false_runtime_or_missing_strong_control(self):
        family=runtime.verify_family(runtime.read_json(runtime.FAMILY_PATH))
        for mutate in [lambda f:f.update(public_network_ready=True),
                       lambda f:f['required_controls'].remove('budget-matched-full-tune'),
                       lambda f:f['evaluation']['current_fixture'].update(independent=True),
                       lambda f:f['evaluation'].update(nonpositive_gain_reward=True),
                       lambda f:f['material_pins']['files']['tokenizer.json'].update(sha256='a'*64)]:
            changed=copy.deepcopy(family);mutate(changed)
            with self.assertRaises(ValueError):runtime.verify_family(changed)

    def test_native_artifact_domain_is_not_plain_sha_and_hashes_actual_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'artifact.safetensors';path.write_bytes(b'explicit test fixture not model')
            domain=runtime.native_artifact_digest(path)
            self.assertEqual(domain,runtime.contract_module().H('artifact',path.read_bytes()).hex())
            self.assertNotEqual(domain,runtime.file_sha(path))
            path.write_bytes(path.read_bytes()+b'changed')
            self.assertNotEqual(domain,runtime.native_artifact_digest(path))

    def test_budget_boolean_and_unbounded_generation_reject(self):
        for change in [('threads', True), ('generation_tokens', 17), ('training_steps', True)]:
            changed = copy.deepcopy(self.plan); changed[change[0]] = change[1]
            with self.subTest(change=change), self.assertRaises(ValueError):
                runtime.validate_plan(changed)

    def test_duplicate_json_receipt_cannot_rewrite_success_or_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'receipt.json'
            path.write_text('{"outcome":"failed","outcome":"success"}')
            with self.assertRaisesRegex(ValueError,'DUPLICATE_JSON'):runtime.read_json(path)
        for key, value in [('wall_seconds',1801),('rss_bytes',16*1024**3+1),('wall_seconds',True)]:
            changed = copy.deepcopy(self.plan); changed['training_budget'][key] = value
            with self.subTest(key=key,value=value), self.assertRaisesRegex(ValueError,'BUDGET_LIMIT'):
                runtime.validate_plan(changed)

    def test_prompt_target_and_task_identity_tamper_reject(self):
        for key, value in [('prompt','substituted prompt'),('expected_output','substituted answer'),
                           ('id','b'*64),('partition','unknown')]:
            changed = copy.deepcopy(self.plan); changed['tasks'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): runtime.validate_plan(changed)
        changed = copy.deepcopy(self.plan); changed['tasks'].append(copy.deepcopy(changed['tasks'][0]))
        with self.assertRaisesRegex(ValueError, 'TASK_ALIAS'): runtime.validate_plan(changed)

    def test_artifact_role_snapshot_swaps_and_cpu_fallback_reject(self):
        rows = self.predictions(); self.assertEqual(len(self.verify(rows)),8)
        for key,value in [('artifact','b'*64),('role','current-backbone'),('snapshot','d'*64),
                          ('numeric_dtype','float16')]:
            changed=copy.deepcopy(rows);changed[0][key]=value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError,'PREDICTION_CONTEXT'):self.verify(changed)
        changed=copy.deepcopy(rows);changed[0]['actual_device']='cuda'
        with self.assertRaisesRegex(ValueError,'SILENT_DEVICE_FALLBACK'):self.verify(changed)

    def test_missing_duplicate_response_and_output_tamper_reject(self):
        rows=self.predictions()
        for changed in (rows[:-1], rows[:-1]+[rows[0]]):
            with self.assertRaisesRegex(ValueError,'PREDICTION_SET'):self.verify(changed)
        changed=copy.deepcopy(rows);changed[0]['response']['request']='f'*64
        with self.assertRaisesRegex(ValueError,'RESPONSE_REQUEST'):self.verify(changed)
        changed=copy.deepcopy(rows);changed[0]['request']['input_ids'][0][0]=2
        with self.assertRaisesRegex(ValueError,'RESPONSE_REQUEST'):self.verify(changed)
        changed=copy.deepcopy(rows);changed[0]['response']['generated_token_ids'][0].pop()
        with self.assertRaisesRegex(ValueError,'FIXED_COUNT'):self.verify(changed)
        changed=copy.deepcopy(rows);changed[0]['response']['decoded_outputs'][0]='changed'
        with self.assertRaisesRegex(ValueError,'OUTPUT_HASH'):self.verify(changed)

    def material_fixture(self, directory):
        config = dict(model_type='llama',num_hidden_layers=30,hidden_size=576,intermediate_size=1536,
            num_attention_heads=9,num_key_value_heads=3,vocab_size=49152,max_position_embeddings=8192,
            tie_word_embeddings=True,attention_bias=False,mlp_bias=False,torch_dtype='bfloat16',
            rope_theta=100000,rms_norm_eps=1e-5,hidden_act='silu',attention_dropout=0.0,rope_scaling=None)
        blobs = {name:b'explicit non-model attack fixture' for name in runtime.PUBLIC_FILES}
        blobs['config.json']=json.dumps(config).encode()
        files={}
        for name, blob in blobs.items():
            (directory/name).write_bytes(blob)
            files[name]=dict(size=len(blob),sha256=hashlib.sha256(blob).hexdigest(),revision=runtime.REVISION)
        manifest=dict(model=runtime.MODEL,revision=runtime.REVISION,files=files)
        (directory/'material-manifest.json').write_text(json.dumps(manifest))
        return manifest,{name:(item['size'],item['sha256']) for name,item in files.items()}

    def test_material_corruption_self_rehashed_tokenizer_and_symlink_reject(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);manifest, public=self.material_fixture(directory)
            with patch.object(runtime,'PUBLIC_FILES',public),patch.object(runtime,'WEIGHT_SHA',public['model.safetensors'][1]):
                runtime.verify_materials(directory)
                target=directory/'tokenizer.json';original=target.read_bytes();target.write_bytes(b'forged tokenizer')
                with self.assertRaisesRegex(ValueError,'MATERIAL_HASH'):runtime.verify_materials(directory)
                changed=copy.deepcopy(manifest);changed['files']['tokenizer.json'].update(size=target.stat().st_size,sha256=runtime.file_sha(target))
                (directory/'material-manifest.json').write_text(json.dumps(changed))
                with self.assertRaisesRegex(ValueError,'PUBLIC_FILE_ROOT'):runtime.verify_materials(directory)
                (directory/'material-manifest.json').write_text(json.dumps(manifest))
                target.write_bytes(original);renamed=directory/'external';target.rename(renamed);target.symlink_to(renamed)
                with self.assertRaisesRegex(ValueError,'MATERIAL_HASH'):runtime.verify_materials(directory)

    def test_real_timeout_child_is_preserved_and_never_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)/'timeout'
            result=runtime.supervise([sys.executable,'-c','import time;print("started",flush=True);time.sleep(5)'],
                                      directory,dict(wall_seconds=0.1,rss_bytes=128*1024**2))
            self.assertEqual(result['outcome'],'failed');self.assertEqual(result['stop_reason'],'wall-budget-exceeded')
            self.assertIn('started',(directory/'process.log').read_text())
            self.assertTrue((directory/'supervisor.json').is_file())

    def test_explicit_profiles_cannot_fall_through_to_default_exit_reconciliation(self):
        for profile in runtime.EXIT_PROFILES[1:]:
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as temporary, \
                    patch.object(runtime, 'current_rss', return_value=None), \
                    patch.object(runtime, 'reconcile_unobserved_exit', side_effect=AssertionError('explicit fallback')), \
                    patch.object(runtime, 'owned_rss_diagnostic', side_effect=AssertionError('default diagnostic')):
                result = runtime.supervise([sys.executable, '-c', 'import time;time.sleep(1)'],
                    Path(temporary)/'run', dict(wall_seconds=2, rss_bytes=128*1024**2),
                    exit_observation=runtime.exit_observation_profile(profile))
            self.assertEqual(result['outcome'], 'failed')
            self.assertEqual(result['rss_observation_gaps'], [])
            self.assertEqual(result['terminal_reconciliation_profile'], 'explicit-'+profile)

    def test_real_memory_budget_child_and_successful_child_have_distinct_results(self):
        if not Path('/proc').is_dir():self.skipTest('Linux RSS owner required')
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            result=runtime.supervise([sys.executable,'-c','import time;x=bytearray(100*1024**2);time.sleep(5)'],
                directory/'memory',dict(wall_seconds=2,rss_bytes=32*1024**2))
            self.assertEqual(result['outcome'],'failed');self.assertEqual(result['stop_reason'],'rss-budget-exceeded')
            self.assertGreater(result['sampled_peak_rss_bytes'],32*1024**2)
            success=runtime.supervise([sys.executable,'-c','print("done")'],directory/'success',
                                      dict(wall_seconds=2,rss_bytes=128*1024**2))
            self.assertEqual(success['outcome'],'success');self.assertIsNone(success['stop_reason'])
            self.assertGreaterEqual(success['child_cpu_ns'],0)


from test_llm_runtime_rss_owner import RssIdentityTests, RssSupervisionTests
from test_llm_runtime_exit_observation import ExitObservationTests
from test_llm_runtime_exit_subset_observation import TerminalSubsetTests
from test_llm_runtime_exit_worker_observation import WorkerPidfdTests
from test_llm_runtime_exit_worker_wait4 import WorkerWait4Tests
from test_llm_runtime_exit_worker_frontier import WorkerFrontierTests
from test_llm_runtime_kernel_owned import KernelOwnedTests
from test_llm_runtime_kernel_close import KernelCloseTests, KernelAbiTests
from test_llm_runtime_kernel_aggregate import AggregateTests
from test_llm_runtime_kernel_counters import CounterTests
from test_llm_runtime_kernel_diagnostic import TerminalDiagnosticTests
from test_llm_runtime_evidence_pipe import EvidencePipeOwnershipTests
from test_llm_runtime_evidence_frames import EvidenceFrameTests, EvidenceWriterTests
from test_llm_runtime_evidence_transport import EvidenceTransportTests
from test_llm_runtime_decode import DecodeRoutingTests, ActualDecoderTensorTests
from test_llm_runtime_artifact_loading import ArtifactChildTests, RecipeBindingTests
from test_llm_runtime_artifact_loading_torch import ActualArtifactTensorTests
from test_llm_base_material import BaseMaterialTests
from test_llm_base_material_torch import ActualBaseMaterialTests
from test_llm_base_source_closure import BaseMaterialSourceClosureTests
from test_llm_runtime_assessment import CostAssessmentTests, TrainingReceiptAssessmentTests
from test_llm_runtime_trial_ledger import TrialLedgerTests, PilotRunAdmissionTests
from test_llm_runtime_trial_review import TrialLedgerReviewTests
from test_llm_runtime_trial_replay import TrialLedgerReplayTests


if __name__=='__main__':unittest.main()
