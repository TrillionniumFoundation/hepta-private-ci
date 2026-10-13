"""Actual PEFT counter regression on tiny random Llama fixtures, not efficacy."""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import torch
from peft import LoraConfig, get_peft_model

import five_causal_experiments as c
from five_causal_native import count_forwards
import five_reader_response_learning as l
import test_five_reader_response as fixtures


class TrainingCounterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_peft_training_bypasses_outer_hook_but_reaches_decoder(self):
        backend = fixtures.NativeAdapterTests().backend()
        model = get_peft_model(backend.loaded, LoraConfig(r=4, lora_alpha=8,
            target_modules=["q_proj", "v_proj"], bias="none", task_type="CAUSAL_LM"))
        batch, _ = l.compile_supervision(backend.tokenizer, fixtures.examples()[0],
            input_cap=8, response_cap=64, position_cap=128)
        decoder = l.training_forward_owner(model)
        with count_forwards(model.get_base_model()) as outer, count_forwards(decoder) as actual:
            loss = model(**batch, use_cache=False).loss
            loss.backward()
        self.assertEqual(outer["model_calls"], 0)
        self.assertEqual(actual["model_calls"], 1)
        self.assertTrue(bool(torch.isfinite(loss)))

    def test_two_epochs_count_actual_dispatches_and_per_step_journal(self):
        backend = fixtures.NativeAdapterTests().backend()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/"candidate"
            receipt = l.fit_response_adapter(backend, fixtures.examples(), output, epochs=2)
            self.assertEqual(receipt["optimizer_steps"], 8)
            self.assertEqual(receipt["training_forwards"], 8)
            self.assertEqual(receipt["training_forward_counter"], l.FORWARD_COUNTER)
            self.assertEqual(receipt["counter_owner_class"], "LlamaModel")
            rows = [json.loads(line)["record"] for line in (output/"optimizer-journal.jsonl").read_text().splitlines()]
            done = [r for r in rows if r["event"] == "optimizer_finished"]
            self.assertEqual(len(done), 8)
            self.assertEqual([r["observed_decoder_forwards"] for r in done], [1]*8)
            self.assertFalse(receipt["production_accepted"])

    def test_failed_decoder_keeps_measured_attempt_and_removes_hook(self):
        backend = fixtures.NativeAdapterTests().backend()
        decoder = backend.loaded.base_model
        before = len(decoder._forward_pre_hooks)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/"candidate"
            with patch.object(decoder, "forward", side_effect=RuntimeError("fixture decoder failure")):
                with self.assertRaisesRegex(RuntimeError, "fixture decoder failure"):
                    l.fit_response_adapter(backend, fixtures.examples(), output, epochs=1)
            rows = [json.loads(line)["record"] for line in (output/"optimizer-journal.jsonl").read_text().splitlines()]
            failed = [r for r in rows if r["event"] == "optimizer_failed_or_unknown"]
            self.assertEqual(len(failed), 1)
            self.assertEqual(failed[0]["observed_decoder_forwards"], 1)
            self.assertFalse(failed[0]["retry_permitted"])
            self.assertFalse((output/"training-receipt.json").exists())
            self.assertEqual(len(decoder._forward_pre_hooks), before)

    def test_missing_or_self_decoder_owner_is_rejected(self):
        class SelfDecoder(torch.nn.Module):
            @property
            def base_model(self):
                return self
        for bad in (SimpleNamespace(),
                    SimpleNamespace(get_base_model=lambda: torch.nn.Linear(2, 2)),
                    SimpleNamespace(get_base_model=lambda: SelfDecoder())):
            with self.assertRaises(c.Invalid):
                l.training_forward_owner(bad)


if __name__ == "__main__":
    unittest.main()
