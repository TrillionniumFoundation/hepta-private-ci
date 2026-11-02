"""Explicit publisher-card architecture with strict sealed local safetensors."""

from importlib import metadata
import importlib
import json
from pathlib import Path

import numpy as np
from .contracts import FILES, MODEL, REVISION, VERSIONS, WEIGHT_SHA, metadata_contract, sha


def bounded(wave):
    wave = np.asarray(wave)
    if wave.ndim != 1 or len(wave) < 16000:
        raise ValueError("A complete accepted one-second source prefix is required")
    prefix = np.array(wave[:16000], dtype=np.float32, copy=True)
    if not np.isfinite(prefix).all():
        raise ValueError("Accepted waveform contains nonfinite values")
    return prefix


def canonical_weights(state, expected):
    converted, mapping = {}, []
    prefix = "wav2vec2.encoder.pos_conv_embed.conv."
    aliases = {prefix + "weight_g": prefix + "parametrizations.weight.original0",
               prefix + "weight_v": prefix + "parametrizations.weight.original1"}
    for key, value in state.items():
        target = aliases.get(key, key) if key not in expected else key
        if target in converted:
            raise ValueError("Ambiguous old/new positional weight-normalization keys")
        converted[target] = value
        if target != key:
            mapping.append({"from": key, "to": target})
    missing, extra = sorted(set(expected) - set(converted)), sorted(set(converted) - set(expected))
    shapes = [{"key": key, "actual": list(converted[key].shape), "expected": list(expected[key].shape)}
              for key in set(expected) & set(converted) if converted[key].shape != expected[key].shape]
    if missing or extra or shapes:
        raise ValueError(json.dumps({"missing_keys": missing, "unexpected_keys": extra, "shape_mismatches": shapes}))
    return converted, mapping


class EmotionEncoder:
    def __init__(self, directory):
        directory = Path(directory)
        self.seal = json.loads((directory / "ASSET_SEAL.json").read_text())
        if self.seal["model"] != MODEL or self.seal["revision"] != REVISION:
            raise ValueError("Wrong immutable model identity")
        for name in FILES:
            record = self.seal["files"][name]
            if (directory / name).stat().st_size != record["bytes"] or sha(directory / name) != record["sha256"]:
                raise ValueError("Actual local asset differs from pre-inference seal: " + name)
        if self.seal["files"]["model.safetensors"]["sha256"] != WEIGHT_SHA:
            raise ValueError("Wrong published safetensors identity")
        metadata_contract(directory)
        for name, version in VERSIONS.items():
            if metadata.version(name) != version:
                raise ValueError("Pinned scientific runtime differs: " + name)
        import torch
        from safetensors.torch import load_file
        from transformers import Wav2Vec2Config, Wav2Vec2FeatureExtractor, Wav2Vec2Model
        torch.set_num_threads(1)
        modules = ("torch", "numpy", "safetensors.torch",
                   "transformers.models.wav2vec2.modeling_wav2vec2",
                   "transformers.models.wav2vec2.feature_extraction_wav2vec2")
        self.runtime_source_sha256 = {str(Path(importlib.import_module(name).__file__).resolve()):
                                     sha(importlib.import_module(name).__file__) for name in modules}

        class Regression(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.dense = torch.nn.Linear(1024, 1024)
                self.dropout = torch.nn.Dropout(.1)
                self.out_proj = torch.nn.Linear(1024, 3)

            def forward(self, pooled):
                transformed = torch.tanh(self.dense(self.dropout(pooled)))
                return self.out_proj(self.dropout(transformed))

        class PublisherArchitecture(torch.nn.Module):
            def __init__(self, config):
                super().__init__()
                self.wav2vec2 = Wav2Vec2Model(config)
                self.classifier = Regression()

        config = Wav2Vec2Config.from_dict(json.loads((directory / "config.json").read_text()))
        if config.num_labels != 3 or config.final_dropout != .1:
            raise ValueError("Publisher-card regression dimensions differ")
        config._attn_implementation = "eager"
        self.model = PublisherArchitecture(config)
        raw = load_file(str(directory / "model.safetensors"), device="cpu")
        state, self.key_mapping = canonical_weights(raw, self.model.state_dict())
        if not all(t.dtype == torch.float32 and bool(torch.isfinite(t).all()) for t in state.values()):
            raise ValueError("Expected finite FP32 published state")
        result = self.model.load_state_dict(state, strict=True)
        if result.missing_keys or result.unexpected_keys:
            raise ValueError("Strict full pretrained state load failed")
        self.model.eval().requires_grad_(False)
        self.processor = Wav2Vec2FeatureExtractor.from_pretrained(str(directory), local_files_only=True)
        self.torch, self.tensor_count = torch, len(state)

    def infer(self, wave):
        prefix = bounded(wave)
        processed = self.processor(prefix, sampling_rate=16000, padding=False,
                                   return_attention_mask=True, return_tensors="pt")
        if tuple(processed.input_values.shape) != (1, 16000) or not bool((processed.attention_mask == 1).all()):
            raise ValueError("Unexpected accepted-window processor contract")
        with self.torch.inference_mode():
            hidden = self.model.wav2vec2(processed.input_values).last_hidden_state
            pooled = hidden.mean(dim=1)
            regression = self.model.classifier(pooled)
        result = {"normalized": processed.input_values[0].numpy().copy(), "hidden": hidden[0].numpy().copy(),
                  "pooled": pooled[0].numpy().copy(), "regression": regression[0].numpy().copy()}
        if result["hidden"].shape != (49, 1024) or result["pooled"].shape != (1024,) or result["regression"].shape != (3,):
            raise ValueError("Official mean-pooled hidden/regression output dimensions differ")
        if not all(np.isfinite(item).all() for item in result.values()):
            raise ValueError("Nonfinite pretrained forward")
        return result
