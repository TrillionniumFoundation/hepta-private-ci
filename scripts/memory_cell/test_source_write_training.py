"""Real tiny-model optimizer equivalence, NOT pretrained task-quality evidence."""

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import unittest
from unittest.mock import patch

import torch
from peft import LoraConfig, get_peft_model, get_peft_model_state_dict
from transformers import Qwen2Config, Qwen2ForCausalLM

from experience_memory import ExperienceReader, render, source_examples
from grounded_protocol import completion_ids
from native import Question
from pretrained import frozen_digest
from test_experience_memory import source


class Tokenizer:
    eos_token_id = 31

    def apply_chat_template(self, messages, **kwargs):
        return [1, 2, 3]

    def encode(self, text, **kwargs):
        return [4 if text == "site_a" else 5]


def reader():
    value = object.__new__(ExperienceReader)
    with torch.random.fork_rng():
        torch.manual_seed(123)
        model = Qwen2ForCausalLM(
            Qwen2Config(
                vocab_size=32,
                hidden_size=16,
                intermediate_size=32,
                num_hidden_layers=1,
                num_attention_heads=2,
                num_key_value_heads=2,
                max_position_embeddings=128,
                attention_dropout=0.0,
            )
        )
        value.model = get_peft_model(
            model,
            LoraConfig(
                r=4,
                lora_alpha=8,
                lora_dropout=0.0,
                target_modules=["q_proj", "v_proj"],
                bias="none",
                task_type="CAUSAL_LM",
            ),
        )
    value.tokenizer = Tokenizer()
    value.base_digest = frozen_digest(value.model)
    value.trainable_parameters = sum(
        p.numel() for p in value.model.parameters() if p.requires_grad
    )
    value.roots, value.scopes = set(), set()
    value.scope, value.quarantined = "fixture", False
    return value


class SourceTrainingTests(unittest.TestCase):
    def setUp(self):
        self.reader = reader()
        self.sources = (
            source("a", "site_a", scope="a"),
            source("b", "site_b", scope="b"),
        )
        self.roots = {d.root for d in self.sources}

    def train(self):
        output = io.StringIO()
        with redirect_stdout(output), patch("experience_memory.STEPS", 4):
            receipt = self.reader.fit_sources(
                self.sources, revision=2, allowed_roots=self.roots, revoked=set()
            )
        return receipt, [json.loads(line) for line in output.getvalue().splitlines()]

    def test_actual_adapter_tensors_and_losses_match_legacy_loop(self):
        legacy = deepcopy(self.reader.model)
        examples, _ = source_examples(
            self.sources, revision=2, allowed_roots=self.roots, revoked=set()
        )
        prepared, groups = [], {}
        for item in examples:
            q = Question(**item["query"])
            prompt = render(self.reader.tokenizer, q, [], [])
            prepared.append(
                completion_ids(
                    self.reader.tokenizer, prompt, item["target"], maximum=2112
                )
            )
            groups.setdefault(q.scope, []).append(len(prepared) - 1)
        scopes = sorted(groups)
        params = [p for p in legacy.parameters() if p.requires_grad]
        optimizer = torch.optim.AdamW(params, lr=0.0002)
        losses = []
        legacy.train()
        for step in range(4):
            group = groups[scopes[step % len(scopes)]]
            ids, labels = prepared[group[(step // len(scopes)) % len(group)]]
            x = torch.tensor([ids], dtype=torch.long)
            optimizer.zero_grad(set_to_none=True)
            loss = legacy(
                input_ids=x,
                attention_mask=torch.ones_like(x),
                labels=torch.tensor([labels], dtype=torch.long),
                use_cache=False,
            ).loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0, error_if_nonfinite=True)
            optimizer.step()
            losses.append(float(loss.detach()))
        result, _ = self.train()
        actual = get_peft_model_state_dict(self.reader.model)
        expected = get_peft_model_state_dict(legacy)
        self.assertEqual(set(actual), set(expected))
        self.assertTrue(all(torch.equal(actual[k], expected[k]) for k in actual))
        self.assertEqual(result["losses"], losses)
        self.assertEqual(frozen_digest(self.reader.model), self.reader.base_digest)

    def test_progress_follows_actual_updates_not_planned_steps(self):
        result, log = self.train()
        self.assertEqual(
            [r["event"] for r in log], ["source-write-plan", "source-write-progress"]
        )
        progress = log[-1]
        self.assertEqual(progress["completed_steps"], result["steps"])
        self.assertEqual(progress["input_tokens"], result["input_tokens"])
        self.assertEqual(progress["supervised_tokens"], result["supervised_tokens"])
        self.assertEqual(progress["schedule_sha256"], result["schedule_sha256"])
        self.assertEqual(result["write_schedule"]["planned_steps"], 4)
        self.assertTrue(
            all(
                not p.requires_grad and p.grad is None
                for p in self.reader.model.parameters()
            )
        )

    def test_failed_forward_has_no_completed_progress_and_quarantines(self):
        output = io.StringIO()
        with (
            redirect_stdout(output),
            patch.object(
                self.reader.model,
                "forward",
                side_effect=RuntimeError("fixture failure"),
            ),
        ):
            with self.assertRaises(RuntimeError):
                self.reader.fit_sources(
                    self.sources, revision=2, allowed_roots=self.roots, revoked=set()
                )
        self.assertTrue(self.reader.quarantined)
        self.assertIsNone(self.reader.scope)
        self.assertEqual(self.reader.roots, set())
        log = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([r["event"] for r in log], ["source-write-plan"])
        self.assertTrue(
            all(
                not p.requires_grad and p.grad is None
                for p in self.reader.model.parameters()
            )
        )


if __name__ == "__main__":
    unittest.main()
