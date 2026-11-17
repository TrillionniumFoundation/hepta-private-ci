"""Real tiny CPU switching test; private fixture install does not waive GPU gates."""

import copy
from pathlib import Path
import tempfile
import unittest
import weakref

from .. import causal_probe_v3 as probe, causal_train_v3 as numeric, data
from .onpolicy_train import attach_adapter, checked_parameter_hash
from .shared_pool_v4 import SharedAdapterPool, adapter_parameters


class SharedPoolTensorTests(unittest.TestCase):
    def test_actual_A_B_A_switch_has_stable_identity_and_one_base(self):
        import torch
        from tokenizers import Tokenizer, models, pre_tokenizers
        from transformers import GenerationConfig, PreTrainedTokenizerFast, Qwen2Config, Qwen2ForCausalLM

        torch.set_num_threads(1)
        torch.manual_seed(1729)
        config = Qwen2Config(vocab_size=32, hidden_size=32, intermediate_size=64,
                            num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=2,
                            max_position_embeddings=64, tie_word_embeddings=True,
                            bos_token_id=1, eos_token_id=2, pad_token_id=0)
        template = Qwen2ForCausalLM(config)
        initial = copy.deepcopy(template.state_dict())
        del template
        raw = Tokenizer(models.WordLevel({"t" + str(i): i for i in range(32)}, unk_token="t0"))
        raw.pre_tokenizer = pre_tokenizers.Whitespace()
        tokenizer = PreTrainedTokenizerFast(tokenizer_object=raw, pad_token="t0", bos_token="t1",
                                           eos_token="t2", chat_template=(
            "{% for message in messages %}{{ message['content'] }} {% endfor %}"))
        generation = GenerationConfig(do_sample=False, num_beams=1, max_new_tokens=2,
                                      bos_token_id=1, eos_token_id=2, pad_token_id=0)
        runtime = {"device": "cpu", "dtype": "float32", "max_input_tokens": 64,
                   "max_new_tokens": 2, "generation": generation.to_dict()}
        base_manifest = {"schema": "tiny.cpu.numerical.fixture.v1", "runtime": runtime,
                         "backend_versions": {}, "files": [], "engineering_only": True}
        with tempfile.TemporaryDirectory(prefix="hepta-shared-pool-cpu-") as tmp:
            root = Path(tmp)
            entries = {}
            for index, cell in enumerate(("A", "B", "C")):
                base = Qwen2ForCausalLM(config)
                base.load_state_dict(initial)
                base.requires_grad_(False)
                model = attach_adapter(base, {"schema": probe.SCHEMA}, root, trainable=True)
                parameters, _ = checked_parameter_hash(model, torch, None)
                optimizer = torch.optim.AdamW([p for _, p in parameters], lr=0.03)
                target = (7, 11, 13)[index]
                ids = torch.tensor([[3, 4, 5, target, target]])
                labels = torch.tensor([[-100, -100, -100, target, target]])
                for _ in range(32):
                    optimizer.zero_grad(set_to_none=True)
                    loss, selected = numeric.selected_token_loss(model, ids, torch.ones_like(ids), labels)
                    self.assertEqual(selected, 2)
                    loss.backward()
                    optimizer.step()
                after = numeric._parameter_hash(parameters, torch)
                directory = root / ("adapter-" + cell)
                model.save_pretrained(directory, safe_serialization=True)
                manifest = {"schema": "tiny.saved.adapter.fixture.v1", "runtime": runtime,
                            "backend_versions": {}, "adapter_directory": directory.name,
                            "engineering_only": True, "fixture_cell": cell}
                entries[cell] = {"manifest": manifest, "model_digest": data.digest(manifest),
                                 "adapter_label": "cell_" + str(index),
                                 "training": {"path": "fixture-" + cell, "sha256": "0" * 64,
                                              "bytes": 0, "parameter_after": after,
                                              "trainable_parameters": sum(p.numel() for _, p in parameters)}}
                del parameters, optimizer, model, base
            view = probe.Predictor.__new__(probe.Predictor)
            view.model = Qwen2ForCausalLM(config)
            view.model.load_state_dict(initial)
            view.model.requires_grad_(False)
            base_ref = weakref.ref(view.model)
            original_parameter_ids = {id(p) for p in view.model.parameters()}
            view.torch, view.tokenizer, view.device = torch, tokenizer, torch.device("cpu")
            view.generation, view.generation_digest = generation, data.digest(generation.to_dict())
            view.device_report, view.closed = {"device": "cpu", "engineering_only": True}, False
            pool = SharedAdapterPool.__new__(SharedAdapterPool)
            # Only the shared numerical implementation is exercised; production admission is separate.
            pool._install(view, entries, root, base_manifest)
            pool.initialization_cost = {"base_load_count": 1, "engineering_only": True}
            request = {"record_id": "tiny-cpu-switch", "task": {"input": "t3 t4 t5"}}
            outputs, logits = [], []
            for index, cell in enumerate(("A", "B", "A")):
                outputs.append(pool.generate(cell, request, root / ("call-" + str(index))))
                self.assertIs(pool._view.model.get_base_model(), base_ref())
                self.assertTrue(original_parameter_ids <= {id(p) for p in pool._view.model.parameters()})
                self.assertEqual(outputs[-1]["loaded_model_digest"], entries[cell]["model_digest"])
                self.assertEqual(outputs[-1]["active_adapter_sha256"], entries[cell]["training"]["parameter_after"])
                self.assertEqual(outputs[-1]["parameter_evidence_digest"],
                                 pool.parameter_evidence(cell)["parameter_evidence_digest"])
                self.assertLess(outputs[-1]["active_parameters"], outputs[-1]["resident_parameters"])
                self.assertFalse(any(p.requires_grad for p in pool._view.model.parameters()))
                with torch.inference_mode():
                    logits.append(pool._view.model(torch.tensor([[3, 4, 5]])).logits.clone())
            self.assertEqual(outputs[0]["output_token_ids"], outputs[2]["output_token_ids"])
            self.assertTrue(torch.equal(logits[0], logits[2]))
            self.assertFalse(torch.equal(logits[0], logits[1]))
            self.assertNotEqual(outputs[0]["active_adapter_sha256"], outputs[1]["active_adapter_sha256"])
            self.assertEqual(pool.snapshot()["inventory"]["base_load_count"], 1)
            with torch.no_grad():
                adapter_parameters(pool._view.model, "cell_0")[0][1].add_(0.01)
            with self.assertRaisesRegex(ValueError, "actual training after hash"):
                pool.generate("A", request, root / "wrong-hash")
            self.assertTrue((root / "wrong-hash" / "POOL_FAILED.json").is_file())
            self.assertFalse((root / "wrong-hash" / "POOL_RAW_OUTPUT.json").exists())
            pool.close()
            self.assertIsNone(view.model)
            self.assertIsNone(base_ref())
            with self.assertRaisesRegex(ValueError, "pool is closed"):
                pool.generate("A", request, root / "closed")


if __name__ == "__main__":
    unittest.main()
