"""Official tiny random HF/PEFT tests; not pretrained capability evidence."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import torch
from transformers import LlamaConfig, LlamaForCausalLM
from types import SimpleNamespace
import five_causal_experiments as c
import five_reader_response_learning as learning
import five_reader_evidence_pairs as pairs
import question_evidence_relevance as rel
from test_question_evidence_relevance import examples


class Tokens:
    chat_template = "fixture-relevance-v1"
    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        prefix = [1]+[4+(ord(x)%92) for x in messages[1]["content"]]+[3]
        if add_generation_prompt: return prefix
        return prefix+[4+(ord(x)%92) for x in messages[-1]["content"]]+[2]


def backend():
    torch.manual_seed(91)
    model = LlamaForCausalLM(LlamaConfig(vocab_size=128, hidden_size=16, intermediate_size=32,
        num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=2, max_position_embeddings=2048,
        bos_token_id=1, eos_token_id=2, pad_token_id=0, attention_dropout=0))
    model.eval().requires_grad_(False)
    return SimpleNamespace(loaded=model, tokenizer=Tokens(), close=lambda:None)


class NativeTests(unittest.TestCase):
    def setUp(self): torch.set_num_threads(1)

    def test_three_profiles_optimize_once_per_original_pair_and_reload(self):
        for profile in rel.PROFILES:
            with self.subTest(profile=profile), TemporaryDirectory() as d:
                obj=backend(); before=learning.state_digest(obj.loaded.state_dict())
                receipt=learning.fit_response_adapter(obj,examples(),Path(d)/"fit",epochs=1,
                    loss_profile=pairs.MARGIN,relevance_profile=profile)
                self.assertEqual(receipt["optimizer_steps"],4)
                self.assertEqual(receipt["training_forwards"],32)
                self.assertEqual(before,receipt["base_tensor_sha256"])
                self.assertTrue(receipt["base_unchanged"] and receipt["checkpoint_reload_equal"])
                self.assertTrue(all(not p.requires_grad for p in obj.loaded.parameters()))

    def test_actual_eight_forwards_and_joint_gradient(self):
        obj=backend(); obj.loaded.requires_grad_(True)
        batch,_=rel.prepare(obj.tokenizer,examples(),position_cap=2048,profile=rel.ALIGNED)[0]
        with learning.count_forwards(obj.loaded.base_model) as n:
            loss,diag=rel.backward(obj.loaded,batch)
        self.assertEqual(n["model_calls"],8)
        self.assertTrue(torch.isfinite(loss))
        self.assertEqual(len(diag["extra_log_scores"]),4)
        observed={k:p.grad.clone() for k,p in obj.loaded.named_parameters() if p.grad is not None}
        obj.loaded.zero_grad(set_to_none=True)
        scalars=[pairs.sequence_score(obj.loaded,b) for b,_ in batch["original"]["variants"]]
        extra=[pairs.sequence_score(obj.loaded,b) for b,_ in batch["extra"]]
        reference=sum(pairs.part_loss(scalars[g],scalars[b],pairs.MARGIN) for g,b in ((0,1),(3,2)))
        reference+=sum(pairs.part_loss(extra[g],extra[b],pairs.MARGIN) for g,b in rel.directions(rel.ALIGNED))
        reference.backward()
        torch.testing.assert_close(loss,reference.detach())
        for k,p in obj.loaded.named_parameters():
            if k in observed: torch.testing.assert_close(observed[k],p.grad,atol=1e-5,rtol=1e-4)

    def test_unavailable_extra_keeps_original_training(self):
        with TemporaryDirectory() as d:
            obj=backend()
            receipt=learning.fit_response_adapter(obj,examples()[:2],Path(d)/"fit",epochs=1,
                loss_profile=pairs.MARGIN,relevance_profile=rel.ALIGNED)
            self.assertEqual(receipt["optimizer_steps"],1)
            self.assertEqual(receipt["training_forwards"],4)
            self.assertEqual(receipt["loss_objective"]["available_extra_pairs"],0)

    def test_unknown_or_projection_profile_rejected_before_wrap(self):
        for kwargs in ({"relevance_profile":"unknown"}, {"relevance_profile":rel.ALIGNED,"projection_profile":"assistant-logits-v1"}):
            with TemporaryDirectory() as d:
                obj=backend(); out=Path(d)/"fit"
                with self.assertRaises(c.Invalid):
                    learning.fit_response_adapter(obj,examples(),out,loss_profile=pairs.MARGIN,**kwargs)
                self.assertFalse(out.exists()); self.assertFalse(hasattr(obj.loaded,"peft_config"))

    def test_tokens_include_complete_response_and_same_source(self):
        obj=backend(); data=examples(); before=deepcopy(data)
        for profile in rel.PROFILES:
            batches=rel.prepare(obj.tokenizer,data,position_cap=2048,profile=profile)
            for batch,meta in batches:
                self.assertEqual(meta["expected_decoder_forwards"],8)
                for b,m in batch["extra"]:
                    self.assertTrue(bool((b["labels"][:,:m["prefix_tokens"]]==-100).all()))
                    self.assertEqual(int(b["input_ids"][0,-1]),2)
        self.assertEqual(data,before)

    def test_metadata_only_question_swap_rejected(self):
        class Bad(Tokens):
            def apply_chat_template(self,messages,**kwargs):
                messages=deepcopy(messages); messages[1]["content"]="same"
                return super().apply_chat_template(messages,**kwargs)
        with self.assertRaises(c.Invalid): rel.prepare(Bad(),examples(),position_cap=2048,profile=rel.ALIGNED)

    def test_extra_failure_records_actual_work_and_no_update(self):
        with TemporaryDirectory() as d:
            obj=backend(); original=pairs.sequence_score; count=[0]
            def fail(*args,**kw):
                count[0]+=1
                if count[0]==6: raise RuntimeError("fixture extra failed")
                return original(*args,**kw)
            with patch.object(pairs,"sequence_score",side_effect=fail), self.assertRaises(RuntimeError):
                learning.fit_response_adapter(obj,examples(),Path(d)/"fit",epochs=1,
                    loss_profile=pairs.MARGIN,relevance_profile=rel.ALIGNED)
            journal=(Path(d)/"fit/optimizer-journal.jsonl").read_text()
            self.assertIn('"observed_decoder_forwards":5',journal)
            self.assertNotIn('"event":"optimizer_finished"',journal)


if __name__=="__main__": unittest.main()
