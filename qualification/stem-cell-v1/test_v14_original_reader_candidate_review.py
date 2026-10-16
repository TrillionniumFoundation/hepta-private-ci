"""Private V14 candidate output structural audit; all answers are synthetic fixtures."""
import copy
from hashlib import sha256
import json
from pathlib import Path
import os
import stat
import subprocess
import sys
import tempfile
import unittest

import v14_original_reader_candidate_review as audit
import v14_original_reader_candidate_cpu as runner
import v14_reader_original_request_builder as original
from test_v14_original_reader_candidate_cpu import material_fixture
from v14_reader_sufficiency_gate import sha_obj


def fake_candidate_outputs():
    source, plan, private = material_fixture()
    attempts, records = [], []
    for case in plan['cases']:
        for arm in runner.ARMS:
            prompt = private['requests'][case['id']][arm]
            delivered = case['arms'][arm]['evidence_ids']
            ids = [17,2]
            token_sha = sha_obj([5,8,11,99])
            answer = 'synthetic [e1]' if 'e1' in delivered else 'unknown'
            used = ['e1'] if 'e1' in delivered else []
            attempts.append({
                'case_id':case['id'], 'arm':arm,
                'request_sha256':prompt['request_sha256'],
                'original_model_sha256':runner.MODEL_SHA,
                'original_input_token_ids_sha256':token_sha,
                'original_input_tokens':4,
                'physical_original_model_started':True,
                'production_authorized':False,
            })
            records.append({
                'case_id':case['id'], 'arm':arm,
                'request_sha256':prompt['request_sha256'],
                'input_token_ids_sha256':token_sha,
                'input_tokens':4,
                'original_generated_token_ids':ids,
                'output_tokens':len(ids),
                'original_raw_answer':answer,
                'answer_sha256':sha256(answer.encode()).hexdigest(),
                'cited_evidence_ids':used,
                'unregistered_citation_ids':[],
                'abstention_semantics_independently_verified':False,
                'cpu_ms':9,
                'wall_ms':8,
            })
    payload={
        'schema':runner.OUTPUT_SCHEMA,
        'source_sha256':sha_obj(source),
        'plan_sha256':sha_obj(plan),
        'private_prompt_packet_sha256':sha_obj(private),
        'original_model_weights_sha256':runner.MODEL_SHA,
        'original_model_tokenizer_sha256':runner.TOKEN_SHA,
        'original_model_config_sha256':runner.CONFIG_SHA,
        'original_runtime_sha256':runner.file_sha(runner.runtime_file()),
        'journal_sha256':'',
        'candidate_only':True,
        'reference_reader_executed':False,
        'independent_host_attestation_verified':False,
        'official_hf_operator_tokenizer_parity':False,
        'reader_source_claimed_original':True,
        'model_forward_calls':16,
        'model_calls_completed':8,
        'model_cpu_ms':80,
        'model_wall_ms':80,
        'private_raw_original_answers':records,
        'independent_semantic_correctness':None,
        'production_authorized':False,
        'decision':'HOLD_NO_GO',
    }
    return source,plan,private,payload,attempts


class PartialOriginalOutputReview(unittest.TestCase):
    def setUp(self):
        self.source,self.plan,self.private,self.packet,self.attempts=fake_candidate_outputs()
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.journal=Path(self.tmp.name)/'starts.jsonl'
        with os.fdopen(os.open(self.journal,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),
                       'w',encoding='utf-8') as f:
            for item in self.attempts:
                f.write(json.dumps(item,sort_keys=True)+'\n')
        self.packet['journal_sha256']=audit.file_sha(self.journal)

    def review(self):
        return audit.review(self.source,self.plan,self.private,self.packet,
                            self.attempts,self.journal)

    def deny(self, mutate):
        mutate()
        with self.assertRaises((ValueError,KeyError,TypeError)):
            self.review()

    def test_source_only_fixture_is_never_called_physical_evidence(self):
        result=self.review()
        self.assertEqual(result['candidate_requests_claimed'],8)
        self.assertEqual(result['independently_recounted_model_forward_calls'],16)
        self.assertEqual(len(result['source_bound_answer_digests']),8)
        self.assertFalse(result['actual_model_inference_independently_replayed'])
        self.assertFalse(result['independent_host_attestation_verified'])
        self.assertFalse(result['reference_reader_executed'])
        self.assertFalse(result['production_authorized'])
        self.assertEqual(result['decision'],'HOLD_NO_GO')

    def test_original_source_mutation_rejected(self):
        self.deny(lambda:self.source['cases'][0]['sources'][0].update(text='injected'))

    def test_candidate_output_missing_rejected(self):
        self.deny(lambda:self.packet['private_raw_original_answers'].pop())

    def test_wrong_model_weight_digest_rejected(self):
        self.deny(lambda:self.packet.update(original_model_weights_sha256='f'*64))

    def test_wrong_tokenizer_digest_rejected(self):
        self.deny(lambda:self.packet.update(original_model_tokenizer_sha256='f'*64))

    def test_wrong_config_digest_rejected(self):
        self.deny(lambda:self.packet.update(original_model_config_sha256='f'*64))

    def test_wrong_runtime_digest_rejected(self):
        self.deny(lambda:self.packet.update(original_runtime_sha256='f'*64))

    def test_journal_digest_tamper_rejected(self):
        self.deny(lambda:self.packet.update(journal_sha256='f'*64))

    def test_changed_answer_bytes_rejected(self):
        self.deny(lambda:self.packet['private_raw_original_answers'][0].update(
            original_raw_answer='forged'))

    def test_fabricated_supported_citation_rejected(self):
        self.deny(lambda:self.packet['private_raw_original_answers'][0].update(
            cited_evidence_ids=['e1']))

    def test_missing_actual_citation_rejected(self):
        self.deny(lambda:self.packet['private_raw_original_answers'][2].update(
            cited_evidence_ids=[]))

    def test_eos_in_middle_denied(self):
        self.deny(lambda:self.packet['private_raw_original_answers'][0].update(
            original_generated_token_ids=[2,17],output_tokens=2))

    def test_model_forward_calls_conserved(self):
        self.deny(lambda:self.packet.update(model_forward_calls=300))

    def test_wrong_input_token_seal_denied(self):
        self.deny(lambda:self.packet['private_raw_original_answers'][0].update(
            input_token_ids_sha256='0'*64))

    def test_wrong_journal_sequence_rejected(self):
        self.deny(lambda:self.attempts[0].update(arm='lesion'))

    def test_faked_finaluse_denied(self):
        self.deny(lambda:self.packet.update(production_authorized=True))

    def test_faked_authentic_host_receipt_denied(self):
        self.deny(lambda:self.packet.update(independent_host_attestation_verified=True))

    def test_faked_reference_run_denied(self):
        self.deny(lambda:self.packet.update(reference_reader_executed=True))

    def test_cost_conservation_denied(self):
        self.deny(lambda:self.packet.update(model_cpu_ms=1))

    def test_reviewer_refuses_world_readable_private_journal(self):
        os.chmod(self.journal,0o644)
        with self.assertRaises(ValueError):
            audit.journal_rows(self.journal)

    def test_private_structural_review_cli_does_not_leak_answer(self):
        p=Path(self.tmp.name)
        files=[]
        for label,x in [('source',self.source),('plan',self.plan),
                        ('private-requests',self.private),('candidate-output',self.packet)]:
            path=p/(label+'.json')
            with os.fdopen(os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),
                           'w',encoding='utf-8') as f:
                json.dump(x,f)
            files.extend(('--'+label,str(path)))
        files.extend(('--journal',str(self.journal)))
        run=subprocess.run([sys.executable,str(Path(audit.__file__)),*files],
                           text=True,capture_output=True,check=True)
        self.assertEqual(json.loads(run.stdout)['decision'],'HOLD_NO_GO')
        self.assertNotIn('synthetic [e1]',run.stdout)


if __name__=='__main__':
    unittest.main()
