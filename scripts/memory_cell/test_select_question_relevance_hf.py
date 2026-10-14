"""Required official tiny-model checks; random fixture weights, no task efficacy."""
import hashlib
import unittest

import torch
from transformers import LlamaConfig, LlamaForCausalLM

import five_causal_experiments as c
from five_causal_native import count_forwards
from five_reader_evidence_pairs import sequence_score
import select_question_relevance as q
import test_select_question_relevance as pure


class Tokenizer:
    def apply_chat_template(self, messages, tokenize=True, add_generation_prompt=False):
        # A deterministic fixture tokenizer, NOT the pretrained Reader tokenizer.
        prefix = [1] + [5 + x % 200 for x in hashlib.sha256(messages[1]["content"].encode()).digest()[:16]] + [3]
        if messages[-1]["role"] == "assistant":
            return prefix + [5 + x % 200 for x in hashlib.sha256(messages[-1]["content"].encode()).digest()[:8]] + [2]
        return prefix


class OfficialTests(unittest.TestCase):
    def unit(self):
        p, cases, _ = pure.fixture()
        return q.build_plan(p, cases)["units"][0]

    def test_four_real_frozen_scores_and_full_vocabulary_shapes(self):
        variants = q.compile_unit(Tokenizer(), self.unit(), position_cap=256)
        torch.manual_seed(17)
        model = LlamaForCausalLM(LlamaConfig(vocab_size=256, hidden_size=16, intermediate_size=32,
            num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=2,
            max_position_embeddings=256, bos_token_id=1, eos_token_id=2, pad_token_id=0)).eval().requires_grad_(False)
        saved = {n: p.clone() for n, p in model.state_dict().items()}
        shapes = []
        handle = model.lm_head.register_forward_hook(lambda module, args, output: shapes.append(tuple(output.shape)))
        try:
            with count_forwards(model.base_model) as counts, torch.no_grad():
                scores = [float(sequence_score(model, batch)) for batch, _ in variants]
        finally:
            handle.remove()
        self.assertEqual(counts["model_calls"], 4)
        self.assertEqual(shapes, [(1, batch["input_ids"].shape[1], 256) for batch, _ in variants])
        result = q.preference(scores)
        self.assertIsNone(result["semantic_accuracy"])
        self.assertTrue(all(torch.equal(saved[n], p) for n, p in model.state_dict().items()))

    def test_tokenizer_collapsing_question_inputs_fails_before_scoring(self):
        class Collapsed(Tokenizer):
            def apply_chat_template(self, messages, **kwargs):
                changed = [dict(m) for m in messages]
                changed[1]["content"] = "same fixture input"
                return super().apply_chat_template(changed, **kwargs)
        with self.assertRaises(c.Invalid): q.compile_unit(Collapsed(), self.unit(), position_cap=256)

    def test_overlong_selected_input_fails_without_shorter_donor(self):
        class Long(Tokenizer):
            def apply_chat_template(self, messages, **kwargs):
                return [4] * 800 + super().apply_chat_template(messages, **kwargs)
        with self.assertRaises(c.Invalid): q.compile_unit(Long(), self.unit(), position_cap=2048)

    def test_successful_blank_output_remains_observed_but_not_selective(self):
        for text in ("", "  \n\t"):
            row = q.behavior({"status": "succeeded", "answer": text},
                             {"status": "succeeded", "answer": q.REFUSAL})
            self.assertTrue(row["jointly_observed"])
            self.assertFalse(row["weak_selective_behavior"])
            self.assertIsNone(row["semantic_accuracy"])


if __name__ == "__main__":
    unittest.main()
