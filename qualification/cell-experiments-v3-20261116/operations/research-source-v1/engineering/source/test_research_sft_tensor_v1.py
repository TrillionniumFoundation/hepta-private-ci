"""Actual CPU tensor/LoRA engineering, separate from every real research task.

Random tiny Qwen2 configuration only. No pretrained weights, tokenizer, generation,
CUDA execution, authored reference call or real research fit occurs here.
"""
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch
import peft
from transformers import Qwen2Config, Qwen2ForCausalLM
import research_sft_contract_v1 as contract
import research_sft_train_v1 as train
from cell_experiments import causal_probe_v3 as probe
from cell_experiments import causal_train_v3 as original

io = contract.helpers().io


class ResearchTensorTests(unittest.TestCase):
    def test_actual_cpu_loop_masks_gradients_optimizer_and_research_adapter_roundtrip(self):
        self.assertEqual(os.environ.get("CUDA_VISIBLE_DEVICES"), "")
        self.assertFalse(torch.cuda.is_available())
        torch.set_num_threads(2)
        torch.manual_seed(contract.TRAINING["seed"])
        directory = Path(os.environ["RESEARCH_ENGINEERING_OUTPUT"]) / "actual-tensor-fixture"
        directory.mkdir(parents=True, exist_ok=False)
        config = Qwen2Config(
            vocab_size=32, hidden_size=8, intermediate_size=16, num_hidden_layers=1,
            num_attention_heads=2, num_key_value_heads=2, max_position_embeddings=2048,
            pad_token_id=0, bos_token_id=1, eos_token_id=2, attention_dropout=0.0,
            tie_word_embeddings=False)
        config._attn_implementation = "eager"
        base = Qwen2ForCausalLM(config)
        base_state = copy.deepcopy(base.state_dict())
        model = peft.get_peft_model(base, peft.LoraConfig(
            r=4, lora_alpha=8, lora_dropout=0.0, target_modules=["q_proj", "v_proj"],
            task_type="CAUSAL_LM", bias="none"))
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        model.enable_input_require_grads()
        model.train()
        parameters = [(name, value) for name, value in model.named_parameters() if value.requires_grad]
        self.assertTrue(parameters)
        self.assertTrue(all("lora_" in name and value.device.type == "cpu" for name, value in parameters))
        self.assertIs(train.selected_token_loss, original.selected_token_loss)
        self.assertIs(train._parameter_hash, original._parameter_hash)
        before = train._parameter_hash(parameters, torch)
        ids = torch.tensor([[1, 4, 5, 6, 7, 8]])
        labels = torch.tensor([[-100, -100, -100, -100, 7, 8]])
        mask = torch.ones_like(ids)
        loss, selected = train.selected_token_loss(model, ids, mask, labels)
        logits = model(input_ids=ids, attention_mask=mask, use_cache=False).logits
        expected = torch.nn.functional.cross_entropy(logits[0, [3, 4]].float(), labels[0, [4, 5]])
        self.assertEqual(selected, 2)
        torch.testing.assert_close(loss, expected)
        invalid = mask.clone()
        invalid[0, -1] = 0
        with self.assertRaisesRegex(ValueError, "unmasked"):
            train.selected_token_loss(model, ids, invalid, labels)
        del logits, loss, expected
        records, encoded = [], []
        for group in range(6):
            records.append({"task_id": "synthetic-cpu-task-" + str(group)})
            turns = []
            for turn in range(2):
                tokens = [1, 3 + group, 11 + turn, 6, 7, 8] + ([9] if turn else [])
                turns.append({"record_id": "synthetic-cpu-record-" + str(group),
                              "input_ids": tokens, "labels": [-100] * (len(tokens) - 2) + tokens[-2:]})
            encoded.append(turns)
        settings = copy.deepcopy(contract.TRAINING)
        optimizer = torch.optim.AdamW(
            [value for _, value in parameters], lr=settings["learning_rate"],
            betas=tuple(settings["optimizer_betas"]), eps=settings["optimizer_eps"],
            weight_decay=settings["weight_decay"])
        losses, consumed, supervised, counts = train.fit_steps(
            torch, model, 0, encoded, records, settings, optimizer, parameters,
            torch.device("cpu"), directory)
        after = train._parameter_hash(parameters, torch)
        steps = [json.loads(line) for line in (directory / "STEPS.jsonl").read_text().splitlines()]
        self.assertEqual(len(losses), 64)
        self.assertEqual(len(steps), 64)
        self.assertEqual([sum(row) for row in counts], [11, 11, 11, 11, 10, 10])
        self.assertEqual(supervised, 128)
        self.assertEqual(consumed, sum(row["input_tokens"] for row in steps))
        self.assertEqual(sum(row["padded_positions"] for row in steps), 64 * 1536)
        self.assertEqual([row["step"] for row in steps], list(range(1, 65)))
        self.assertTrue(all(row["turn"] == ((row["step"] - 1) // 6) % 2 for row in steps))
        self.assertTrue(all(torch.isfinite(torch.tensor(losses))))
        self.assertNotEqual(before, after)
        self.assertTrue(all(int(state["step"]) == 64 for state in optimizer.state.values()))
        adapter = directory / "adapter"
        model.save_pretrained(adapter, safe_serialization=True)
        with (directory / "optimizer.pt").open("xb") as stream:
            torch.save(optimizer.state_dict(), stream)
        model.eval()
        with torch.inference_mode():
            trained_logits = model(input_ids=ids, attention_mask=mask, use_cache=False).logits.clone()
        parent = {"schema": probe.SCHEMA, "family": probe.FAMILY, "model_id": probe.MODEL_ID,
                  "runtime": {"device": "cpu", "dtype": "float32", "engineering_fixture": True},
                  "backend_versions": probe._versions()}
        manifest = {
            "schema": contract.MODEL_SCHEMA, "profile": contract.PROFILE,
            "admission_policy": contract.ADMISSION, "family": contract.FAMILY,
            "model_id": probe.MODEL_ID, "base_manifest": parent,
            "parent_model_digest": io.digest(parent), "runtime": parent["runtime"],
            "backend_versions": parent["backend_versions"], "peft_version": peft.__version__,
            "adapter_directory": adapter.relative_to(io.WORKSPACE_ROOT).as_posix(),
            "adapter_files": probe._inventory(adapter), "research_source_inventory": contract.sources(),
            "fixture_actor": "random tiny CPU engineering only", **contract.SCOPE}
        # Only the base-loading boundary is a fixture. The new adapter validator,
        # new Predictor orchestration, PEFT disk loader and actual tensor math run.
        def tiny_parent_init(instance, manifest_arg, root_arg):
            self.assertEqual(manifest_arg, parent)
            self.assertEqual(root_arg, io.WORKSPACE_ROOT)
            instance.model = Qwen2ForCausalLM(config)
            instance.model.load_state_dict(base_state, strict=True)
            instance.torch = torch
            instance.device = torch.device("cpu")
            instance.device_report = {"engineering_only": True, "device": "cpu"}
            instance.tokenizer = None
            instance.manifest = copy.deepcopy(parent)
            instance.model_digest = io.digest(parent)
            instance.closed = False
        with patch.object(probe, "verify_model", return_value=io.digest(parent)), \
                patch.object(probe.Predictor, "__init__", tiny_parent_init):
            loaded = train.load_predictor(manifest, io.WORKSPACE_ROOT)
        self.assertEqual(loaded.model_digest, io.digest(manifest))
        self.assertFalse(loaded.model.training)
        self.assertTrue(all(not value.requires_grad and value.device.type == "cpu"
                            for value in loaded.model.parameters()))
        with torch.inference_mode():
            restored = loaded.model(input_ids=ids, attention_mask=mask, use_cache=False).logits
        torch.testing.assert_close(restored, trained_logits, rtol=0, atol=0)
        loaded.close()
        self.assertFalse(torch.cuda.is_initialized())
        io.write_new(directory / "NUMERIC_RESULT.json", {
            "status": "CPU_ENGINEERING_COMPLETE", "steps": 64,
            "supervised_tokens": supervised, "input_tokens": consumed,
            "padded_positions": 64 * 1536, "record_turn_updates": counts,
            "parameter_before": before, "parameter_after": after,
            "parameter_change": before != after, "adapter_roundtrip_exact_logits": True,
            "actual_original_selected_loss_matches_dense_cross_entropy": True,
            "new_production_fit_steps_exercised": True, "new_adapter_loader_exercised": True,
            "base_loader_boundary": "explicit random tiny CPU fixture",
            "real_research_fits": 0, "real_model_generations": 0, "authored_verifier_calls": 0,
            "pretrained_model_loaded": False, "tokenizer_loaded": False, "gpu_used": False,
            "torch_version": torch.__version__, "peft_version": peft.__version__,
            "adapter_files": probe._inventory(adapter),
            "optimizer_sha256": io.file_hash(directory / "optimizer.pt"),
            **contract.SCOPE})
