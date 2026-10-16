"""Source-only and failure-injection tests; fabricated tokenizer is NOT a Qwen forward."""
import copy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch

import source_first as v17
import v19_qwen_reference as qwen
import v19_qwen_material as material
import reference_preflight as gate


def fake_plan():
    entries = {}
    for i in range(30):
        for arm in qwen.ARMS:
            name = f'conv-26/q{i}|{arm}'
            base = f'Question {i}; reference evidence {arm}'
            # Exactly 24 same-input aliases, with 96 distinct messages.
            if i < 24 and arm == 'lesion':
                base = f'Question {i}; reference evidence none'
            messages = [{'role': 'system', 'content': 'source-only-fixture'},
                        {'role': 'user', 'content': base}]
            entries[name] = dict(messages=messages, message_sha256=v17.digest(messages), arm=arm)
    return dict(entries=entries, source_roots=list(v17.ROOTS), cases=[f'case{i}' for i in range(30)],
                v17_plan_sha256='fixture-v17', plan_sha256='fixture-v19')


class DeterministicTokenizer:
    def apply_chat_template(self, messages, **kwargs):
        d=sha256(v17.canon(messages)).digest()
        return [int.from_bytes(d[:8], 'big'), int.from_bytes(d[8:16], 'big')]


class PreflightTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.inputs = tuple(self.root / name for name in
                            ('public.json','owner.json','plan.json','annotation.json','requests.json'))
        for f in self.inputs: f.write_text('{}')
        self.model = self.root/'model'
        self.model.mkdir()
        self.spec = self.root/'model.json'
        self.spec.write_text('{}')
        self.reference = self.root/'reference.json'
        self.reference.write_text('{}')
        self.dst = self.root/'readiness.json'
        self.plan=fake_plan()
        self.validator=patch.object(qwen, 'validate', return_value=self.plan)
        self.material=patch.object(material, 'verify_snapshot', return_value='fixture-sha')
        self.mock_validate = self.validator.start(); self.material.start()
        self.addCleanup(self.validator.stop); self.addCleanup(self.material.stop)

    def run_gate(self, **overrides):
        return gate.admit(self.inputs, self.reference, self.model, self.spec, self.dst,
                          tokenizer=overrides.get('tokenizer', DeterministicTokenizer()))

    def test_complete_source_first_fixture_mechanism_only(self):
        result = self.run_gate()
        self.assertEqual((result['logical_model_requests'],result['unique_physical_input_ids']), (120,96))
        self.assertEqual(result['original_source_cases'],30)
        self.assertEqual(result['original_source_roots'],10)
        self.assertGreater(result['logical_input_tokens'],result['unique_input_tokens'])
        for key in ('original_qwen_forward_executed','production_authorized','independent_human_sufficiency_review'):
            self.assertIs(result[key],False)
        self.assertEqual(result['decision'],'HOLD_NO_GO')
        self.assertEqual(json.loads(self.dst.read_text()),result)
        self.assertEqual(self.dst.stat().st_mode & 0o777,0o600)

    def test_second_write_is_rejected_not_overwritten(self):
        self.run_gate()
        with self.assertRaises(ValueError): self.run_gate()

    def test_source_relabels_with_answers_denied(self):
        (self.root/'hidden.json').write_text('private')
        with self.assertRaisesRegex(ValueError,'answer labels'):
            self.run_gate()
        self.assertFalse(self.dst.exists())

    def test_symlinked_gold_even_when_dangling_denied(self):
        (self.root/'hidden.json').symlink_to(self.root/'not-there')
        with self.assertRaisesRegex(ValueError,'answer labels'):
            self.run_gate()

    def test_source_files_scattered_across_workspaces_denied(self):
        other=self.root/'other';other.mkdir(); out=other/'owner.json';out.write_text('{}')
        paths=(self.inputs[0],out,*self.inputs[2:])
        with self.assertRaisesRegex(ValueError,'one frozen source'):
            gate.admit(paths,self.reference,self.model,self.spec,self.dst,DeterministicTokenizer())

    def test_extra_duplicate_model_input_rejected(self):
        class Constant(DeterministicTokenizer):
            def apply_chat_template(self,messages,**kw):return [2,3]
        with self.assertRaisesRegex(ValueError,'collapsed'):
            self.run_gate(tokenizer=Constant())

    def test_unstable_tokenizer_denied_on_repeated_message(self):
        class Unstable(DeterministicTokenizer):
            def __init__(self):self.n=0
            def apply_chat_template(self,messages,**kwargs):
                self.n+=1
                return [self.n,42]
        with self.assertRaisesRegex(ValueError,'differently'):
            self.run_gate(tokenizer=Unstable())

    def test_context_limit_denied_without_silent_clipping(self):
        class TooLong(DeterministicTokenizer):
            def apply_chat_template(self,messages,**kwargs):return list(range(qwen.INPUT_CAP+1))
        with self.assertRaisesRegex(ValueError,'truncated'):
            self.run_gate(tokenizer=TooLong())

    def test_empty_or_noninteger_model_tokens_denied(self):
        for values in ([],[False],[1.5],['3'],[-1],None):
            class Bad(DeterministicTokenizer):
                def apply_chat_template(self,messages,**kwargs):return values
            with self.subTest(values=values),self.assertRaisesRegex(ValueError,'invalid'):
                self.run_gate(tokenizer=Bad())

    def test_missing_physical_source_rejected(self):
        self.plan=copy.deepcopy(self.plan)
        self.plan['entries'].pop(next(iter(self.plan['entries'])))
        self.mock_validate.return_value = self.plan
        with self.assertRaisesRegex(ValueError,'incomplete source-first'):
            self.run_gate()

    def test_relabelled_message_digest_denied(self):
        self.plan=copy.deepcopy(self.plan)
        self.plan['entries'][next(iter(self.plan['entries']))]['message_sha256']='0'*64
        self.mock_validate.return_value = self.plan
        with self.assertRaisesRegex(ValueError,'message'):
            self.run_gate()

    def test_model_sha_drift_between_preflight_steps_denied(self):
        with patch.object(material, 'verify_snapshot', side_effect=['sha1','sha2']):
            with self.assertRaisesRegex(ValueError,'drifted'):
                self.run_gate()

    def test_source_model_preflight_does_not_import_torch_or_transformers(self):
        import sys
        self.assertNotIn('transformers',sys.modules)
        self.assertNotIn('torch',sys.modules)
        self.run_gate()
        self.assertNotIn('transformers',sys.modules)
        self.assertNotIn('torch',sys.modules)

    def test_fail_closed_on_foreign_reference_arms(self):
        self.plan=copy.deepcopy(self.plan)
        self.plan['entries'][next(iter(self.plan['entries']))]['arm']='fake_model_fusion'
        self.mock_validate.return_value = self.plan
        with self.assertRaisesRegex(ValueError,'message'):
            self.run_gate()

    def physical_fixture(self):
        preflight = self.run_gate()
        token_groups = {}
        for rid, entry in sorted(self.plan['entries'].items()):
            ids = DeterministicTokenizer().apply_chat_template(entry['messages'])
            token_groups.setdefault(v17.digest(ids), []).append(rid)
        rows = {key: dict(logical_ids=sorted(ids), input_tokens=2)
                for key, ids in token_groups.items()}
        logical = {rid: key for key, ids in token_groups.items() for rid in ids}
        physical = dict(schema=qwen.SCHEMA+'.physical-private',
                plan_sha256=self.plan['plan_sha256'], model_spec_sha256='fixture-sha',
                actual_unique_qwen_requests=96, logical_arm_requests=120,
                requests_by_id=logical, physical_outputs=rows,
                authority='DENY_ALL',production_authorized=False,decision='HOLD_NO_GO')
        path=self.root/'model-physical.json'
        v17.write_once(path,physical)
        return preflight,physical,path

    def test_postseal_token_alias_accounting_conserved(self):
        original,phys,path=self.physical_fixture()
        result=gate.reconcile(self.dst,path)
        self.assertEqual(result['unique_tokens_paid_once'],192)
        self.assertEqual(result['logical_tokens_with_aliases'],240)
        self.assertEqual(result['decision'],'HOLD_NO_GO')
        self.assertFalse(result['original_Qwen_semantic_correctness_verified'])

    def test_postseal_resealed_cross_arm_alias_forgery_rejected(self):
        _,packet,path=self.physical_fixture()
        items=list(packet['requests_by_id'])
        packet['requests_by_id'][items[0]]=packet['requests_by_id'][items[1]]
        path.write_bytes(v17.canon(packet));path.chmod(0o600)
        with self.assertRaises(ValueError):gate.reconcile(self.dst,path)

    def test_postseal_changed_physical_token_cost_rejected(self):
        _,packet,path=self.physical_fixture()
        packet['physical_outputs'][next(iter(packet['physical_outputs']))]['input_tokens']+=1
        path.write_bytes(v17.canon(packet));path.chmod(0o600)
        with self.assertRaisesRegex(ValueError,'token accounting'):
            gate.reconcile(self.dst,path)

    def test_postseal_forged_model_identity_rejected(self):
        _,packet,path=self.physical_fixture()
        packet['model_spec_sha256']='foreign-model'
        path.write_bytes(v17.canon(packet));path.chmod(0o600)
        with self.assertRaisesRegex(ValueError,'detached'):
            gate.reconcile(self.dst,path)

    def test_postseal_no_wrong_admission_or_success_claims(self):
        _,packet,path=self.physical_fixture()
        packet['production_authorized']=True
        path.write_bytes(v17.canon(packet));path.chmod(0o600)
        with self.assertRaisesRegex(ValueError,'detached'):
            gate.reconcile(self.dst,path)

    def test_workflow_real_model_failure_order_and_no_gold_leak(self):
        workflow=Path(__file__).resolve().parents[2]/'.github/workflows/hepta-v19-original-qwen-reference.yml'
        text=workflow.read_text(encoding='utf-8')
        early='Fail-fast pinned Qwen3 material and full source-token admission BEFORE original 135M'
        original='Physically rerun frozen original 135M once on all unique requests'
        later='Physically run admitted Qwen3 0.6B on sealed source-first original inputs'
        after='Independently reconcile preflight aliases and physical tokens BEFORE opening gold'
        score='Fresh source re-open only AFTER BOTH original model seals'
        self.assertTrue(0<text.index(early)<text.index(original)<text.index(later)<text.index(after)<text.index(score))
        self.assertIn('reference_preflight.py',text)
        self.assertIn('test_reference_preflight.py',text)
        self.assertIn('test ! -e "$S/hidden.json"',text)
        self.assertIn('research/stem-v20-qwen-admission-20261016',text)
        self.assertIn('contents: read',text)
        self.assertNotIn('persist-credentials: true',text)

    def test_complete_frozen_qwen_census_is_not_model_success(self):
        val=self.run_gate()
        self.assertNotIn('"answer":',json.dumps(val))
        self.assertNotIn('messages',json.dumps(val))
        self.assertFalse(val['model_quality_or_ndu_gain_verified'])
        self.assertFalse(val['model_input_tokens_matched_to_135m'])


if __name__ == '__main__':
    import unittest
    unittest.main()
