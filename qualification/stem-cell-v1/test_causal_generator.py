"""Local tensor/contract tests. The miniature learned LM is NOT pretrained."""
import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import torch
from torch import nn

from hf_causal_generator import DecodeLimits, LocalCausalProposer, checked_config, greedy_decode, public_messages
from hf_encoder_kernel import snapshot_digest
from system2_execution import PublicTask, Verification


class TokenizerFixture:
    chat_template = 'explicit fixture'
    eos_token_id = 2
    def __init__(self):
        self.length, self.masked = 1, False
        self.messages = []
    def apply_chat_template(self, messages, **kwargs):
        self.messages.append(copy.deepcopy(messages))
        return json.dumps(messages)
    def __call__(self, text, **kwargs):
        assert kwargs['truncation'] is False and kwargs['add_special_tokens'] is False
        ids = torch.ones(1, self.length, dtype=torch.long)
        mask = torch.ones_like(ids)
        if self.masked: mask[0, 0] = 0
        return dict(input_ids=ids, attention_mask=mask)
    def decode(self, ids, **kwargs):
        return ''.join({4:'a', 5:'b'}.get(i, '') for i in ids)


class TinyLearnedLM(nn.Module):
    def __init__(self):
        super().__init__()
        self.embedding, self.readout = nn.Embedding(8, 12), nn.Linear(12, 8)
        self.config = SimpleNamespace(vocab_size=8, eos_token_id=2, max_position_embeddings=128)
        self.inputs = []
    def forward(self, input_ids, attention_mask=None, use_cache=False, return_dict=True):
        if self.training is False:
            self.inputs.append(input_ids.tolist())
            assert use_cache is False
        return SimpleNamespace(logits=self.readout(self.embedding(input_ids)))


def learned_model():
    with torch.random.fork_rng():
        torch.manual_seed(114)
        model = TinyLearnedLM()
    optimizer = torch.optim.Adam(model.parameters(), lr=.03)
    x, y = torch.tensor([[1,4,5]]), torch.tensor([4,5,2])
    for _ in range(64):
        optimizer.zero_grad(set_to_none=True)
        loss = nn.functional.cross_entropy(model(x).logits.reshape(-1,8), y)
        loss.backward(); optimizer.step()
    return model.eval().requires_grad_(False)


class CausalGeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.trained = learned_model()
    def setUp(self):
        self.model = copy.deepcopy(self.trained)
        self.tokenizer = TokenizerFixture()
        self.limits = DecodeLimits(prompt_tokens=64, new_tokens=4)
        self.task = PublicTask('Describe the response.', 10, (('public evidence',9),))
    def test_actual_trained_logits_autoregress_to_multiple_tokens_and_eos(self):
        before = {k:v.clone() for k,v in self.model.state_dict().items()}
        text, receipt = greedy_decode(self.model, self.tokenizer, [{'role':'user','content':'x'}], self.limits)
        self.assertEqual(text, 'ab')
        self.assertEqual(receipt['generated_token_ids'], [4,5,2])
        self.assertEqual(self.model.inputs, [[[1]],[[1,4]],[[1,4,5]]])
        self.assertEqual(receipt['forward_prefix_lengths'], [1,2,3])
        for k,v in self.model.state_dict().items(): torch.testing.assert_close(v,before[k],rtol=0,atol=0)
    def test_repeat_calls_restart_state_not_kv_or_previous_output(self):
        a = greedy_decode(self.model,self.tokenizer,[],self.limits)
        b = greedy_decode(self.model,self.tokenizer,[],self.limits)
        self.assertEqual(a[0],b[0]); self.assertEqual(self.model.inputs[3],[[1]])
        self.assertFalse(b[1]['kv_cache_persisted'])
    def test_cap_is_explicit_not_falsely_eos_or_extra_model_calls(self):
        text,r = greedy_decode(self.model,self.tokenizer,[],replace(self.limits,new_tokens=1))
        self.assertEqual((text,r['status'],r['forward_calls']),('a','token_limit',1))
    def test_empty_eos_is_rejected_without_fabricated_answer(self):
        with torch.no_grad(): self.model.readout.weight.zero_(); self.model.readout.bias.zero_(); self.model.readout.bias[2]=100
        with self.assertRaisesRegex(ValueError,'empty'): greedy_decode(self.model,self.tokenizer,[],self.limits)
        self.assertEqual(len(self.model.inputs),1)
    def test_prompt_and_context_limits_reject_before_forward(self):
        for length, positions in ((65,128),(63,64)):
            self.tokenizer.length=length; self.model.config.max_position_embeddings=positions
            with self.assertRaises(ValueError): greedy_decode(self.model,self.tokenizer,[],self.limits)
        self.assertEqual(self.model.inputs,[])
    def test_padding_is_not_silently_reinterpreted(self):
        self.tokenizer.masked=True
        with self.assertRaises(ValueError): greedy_decode(self.model,self.tokenizer,[],self.limits)
        self.assertEqual(self.model.inputs,[])
    def test_nonfinite_logits_cannot_become_tokens(self):
        with torch.no_grad(): self.model.readout.bias.fill_(float('nan'))
        with self.assertRaisesRegex(ValueError,'logits'): greedy_decode(self.model,self.tokenizer,[],self.limits)
    def test_limits_reject_bool_negative_and_oversized(self):
        for changes in ({'new_tokens':True},{'prompt_tokens':0},{'new_tokens':129},{'output_bytes':-1}):
            with self.assertRaises(ValueError): replace(self.limits,**changes).validate()
    def test_public_task_and_revision_used_without_target_or_truncation(self):
        messages=public_messages(self.task,'previous answer','check the wording',self.limits)
        self.assertEqual(messages[1],{'role':'assistant','content':'previous answer'})
        self.assertIn('public evidence',messages[0]['content'])
        self.assertIn('check the wording',messages[2]['content'])
        with self.assertRaises(ValueError): public_messages(self.task,None,'feedback',self.limits)
        with self.assertRaises(ValueError): public_messages(self.task,None,None,replace(self.limits,input_bytes=1))
        with self.assertRaises(ValueError): public_messages(PublicTask('x',10,(('future',11),)),None,None,self.limits)
    def test_declared_output_byte_budget_enforced(self):
        with self.assertRaisesRegex(ValueError,'budget'): greedy_decode(self.model,self.tokenizer,[],replace(self.limits,output_bytes=1))
    def test_constructor_pins_before_loading_and_retains_shared_model(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td)/'model.json').write_text('{}')
            sha=snapshot_digest(td)
            with patch('hf_causal_generator.load_local_causal',return_value=(self.model,self.tokenizer,{})) as loader, \
                 patch('hf_causal_generator.verify_loaded_safetensors',return_value={}):
                with self.assertRaises(ValueError): LocalCausalProposer(td,expected_snapshot_sha256='a'*64)
                loader.assert_not_called()
                p=LocalCausalProposer(td,expected_snapshot_sha256=sha,limits=self.limits)
                self.assertEqual(p(self.task,None,None),'ab')
                self.assertEqual(p(self.task,'x','revise'),'ab')
                self.assertIs(p.model,self.model); self.assertEqual(loader.call_count,1)
                p.model.requires_grad_(True)
                with self.assertRaises(ValueError): p(self.task,None,None)
    def test_changed_snapshot_cannot_be_reverified(self):
        with tempfile.TemporaryDirectory() as td:
            f=Path(td)/'x';f.write_text('a')
            with patch('hf_causal_generator.load_local_causal',return_value=(self.model,self.tokenizer,{})), \
                 patch('hf_causal_generator.verify_loaded_safetensors',return_value={}):
                p=LocalCausalProposer(td,expected_snapshot_sha256=snapshot_digest(td))
                f.write_text('b')
                with self.assertRaises(ValueError):p.reverify()
    def test_unbounded_or_noncausal_config_cannot_start_load(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'config.json'
            for cfg in ({'model_type':'modernbert'}, {'model_type':'llama','architectures':['LlamaForCausalLM'], 'tie_word_embeddings':False}):
                p.write_text(json.dumps(cfg))
                with self.assertRaises(ValueError): checked_config(td)
    def test_actual_neural_callback_enters_existing_pair_collector(self):
        from test_paired_capture import setup_capture, Clock
        from paired_capture import PairCollector
        from paired_capture_export import read_pair
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'capture'; reg,_,_,_,_=setup_capture(root)
            seen=[]
            def propose(task,previous,feedback):
                seen.append((previous,feedback))
                return greedy_decode(self.model,self.tokenizer,public_messages(task,previous,feedback,self.limits),self.limits)[0]
            def verify(task,text):return Verification(text=='ab','format-only test check')
            # Observe retains unsupported neural ops; no false complete cost.
            # Existing fixture is strict V1; embedding is intentionally unknown,
            # so use a bound V2 Transformer profile through a new registration.
            from execution_meter import TRANSFORMER_POLICY_SCHEMA
            from transformer_work import PROFILE
            from paired_capture import freeze_capture,create_capture
            r=freeze_capture(reg['protocol'],expected_protocol_id=reg['protocol']['protocol_id'],
                boundaries=reg['boundaries'],meter_policy={**reg['meter_policy'],'schema':TRANSFORMER_POLICY_SCHEMA,
                'arithmetic_profile':PROFILE,'mode':'observe'},phase_caps=dict.fromkeys(reg['phase_caps'],10**9))
            newroot=Path(td)/'neural';create_capture(newroot,r)
            collector=PairCollector(newroot,expected_capture_id=r['capture_id'],callback_profile_sha256='b'*64,
                propose=propose,verify=verify)
            terminal=collector.run_pair('f000',clock=Clock())
            record,_=read_pair(newroot,r,0,terminal['terminal_id'])
            self.assertEqual(record['continue_candidate'],'ab')
            self.assertEqual(seen,[('0','recompute both terms')])
            self.assertEqual([e['kind'] for e in record['execution']['trace']],['propose','verify'])

class PublicCausalProbeTests(unittest.TestCase):
    def test_public_allowlist_cannot_download_an_unregistered_model(self):
        from public_encoder_probe import acquire_public
        with tempfile.TemporaryDirectory() as td, self.assertRaisesRegex(ValueError,'unregistered'):
            acquire_public(Path(td),model_id='unreviewed/remote-code')
    def test_source_lock_names_causal_checkpoint_without_changing_encoder_default(self):
        from public_encoder_probe import freeze_public_source, REQUIRED_FILES
        info=SimpleNamespace(sha='a'*40,siblings=[SimpleNamespace(rfilename=n,size=10) for n in REQUIRED_FILES])
        old=freeze_public_source(info)
        new=freeze_public_source(info,model_id='HuggingFaceTB/SmolLM2-135M-Instruct')
        self.assertEqual(old['schema'],'hepta.public-encoder-source-lock.v1')
        self.assertEqual(new['schema'],'hepta.public-causal-source-lock.v1')
        self.assertEqual(new['files'],old['files'])
    def test_full_local_learned_model_to_captured_endpoints_and_separate_scores(self):
        from public_causal_probe import probe
        model=learned_model(); tokenizer=TokenizerFixture()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); snapshot=root/'snapshot';snapshot.mkdir();(snapshot/'fixture').write_text('not pretrained')
            with patch('hf_causal_generator.load_local_causal',return_value=(model,tokenizer,{})), \
                 patch('hf_causal_generator.verify_loaded_safetensors',return_value={}):
                result=probe(snapshot,root)
            self.assertEqual(result['pair_statuses'],['completed']*4)
            self.assertEqual(result['revised_outputs'],['ab']*4)
            self.assertTrue(result['repeat_input_exact'])
            self.assertEqual([s['continue_utility'] for s in result['scores']],[0]*4)
            self.assertFalse(result['cost_matched_comparison_completed'])
            self.assertTrue((root/'paired-rows.json').is_file())
    def test_causal_cli_import_does_not_require_hf_or_download(self):
        import subprocess,sys
        result=subprocess.run([sys.executable,str(Path(__file__).with_name('public_causal_probe.py')),'--help'],
            capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':
    unittest.main()
