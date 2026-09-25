"""Local Laya backend for the existing Neuron feature worker port.

The four Q24 inputs are owner-approved retrieval summary features, not text
hashes or authority. Outputs predict marginal retrieval benefit; they neither
select a tool nor certify evidence sufficiency. No network model is contacted.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import resource
import shutil
import sys
import tempfile
import time
from typing import Any

Q24 = 1 << 24
BASE_SHA256 = "9d628fd971b700382ac6f65920a86f149777b2e748e0c955fb3b19695aa8f204"
ASSET_SHA256 = {
    "rl_agent_config.json": "25061739243b617ad88d1219ba6f8a9c86c5881ca28df024fa2d9b3b2fcc30c6",
    "encoder/config.json": "83f6916d13ef0f556ac461f28308dc2bffa7ebeadee8ec9e2db5812020ea5bb4",
    "tokenizer/tokenizer.json": "609d8f4c067cd3950f88594c5a802616cea245823836ef5848ee4fc40aab5b6f",
    "tokenizer/tokenizer_config.json": "6c6b2d8e3c84ce0e671c129cd6b374b235d6f9863042a5836358d00a89bbb5a1",
}
PROFILE = {
    "schema": "hepta.laya.retrieval-continuation.v1",
    "features": ["support_coverage", "contradiction", "uncertainty", "remaining_budget"],
    "units": "Q24 fraction in [0,1]",
    "prediction_labels": ["no_material_benefit", "material_benefit"],
    "question": "Would another retrieval step materially improve the available evidence? Predict benefit only; do not authorize an action.",
    "maximum_tokens": 512,
    "tokenizer_adapter": "private-copy-compatible-config-v1",
    "probability_semantics": "model_prediction_not_behavior_propensity",
}


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def strict_json(raw: bytes | str) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value = dict(pairs)
        if len(value) != len(pairs):
            raise ValueError("duplicate JSON field")
        return value
    def reject_constant(value: str) -> None:
        raise ValueError("non-finite JSON constant: " + value)
    return json.loads(raw, object_pairs_hook=unique, parse_constant=reject_constant)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def bounded_features(features: Any) -> list[int]:
    if not isinstance(features, list) or len(features) != 4:
        raise ValueError("this profile requires four retrieval features")
    if any(type(v) is not int or not 0 <= v <= Q24 for v in features):
        raise ValueError("retrieval features must be bounded Q24 fractions")
    return features


def state_for(features: Any) -> str:
    values = bounded_features(features)
    return canonical(dict(zip(PROFILE["features"], (v / Q24 for v in values), strict=True))).decode()


def peak_bytes() -> int:
    # Linux ru_maxrss is KiB. This conservative process high-water mark includes
    # the encoder, tokenizer, Python runtime and all previous transient peaks.
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


class LayaCell:
    def __init__(self, model: Path, expected_base: str, candidate: Path | None = None):
        import torch
        import laya
        from safetensors.torch import load_file

        if sys.platform != "linux" or not model.is_absolute() or not model.is_dir():
            raise ValueError("this bounded CPU profile requires an absolute local Linux model directory")
        if expected_base != BASE_SHA256 or file_digest(model / "model.safetensors") != expected_base:
            raise ValueError("base model bytes do not match this selected profile")
        for name, expected in ASSET_SHA256.items():
            if file_digest(model / name) != expected:
                raise ValueError("model configuration changed before allocation: " + name)
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ.pop("LAYA_CPU_AMP", None)
        torch.set_num_threads(4)
        self.torch = torch
        self.base_digest = expected_base
        self.temperature = 1.0
        self.scratch = tempfile.TemporaryDirectory(prefix="hepta-laya-loader-")
        local = Path(self.scratch.name)
        # Laya normalizes old tokenizer metadata. Never let that mutate the
        # selected artifact or a shared HuggingFace snapshot.
        for name in ("tokenizer", "encoder"):
            shutil.copytree(model / name, local / name)
        shutil.copyfile(model / "rl_agent_config.json", local / "rl_agent_config.json")
        (local / "model.safetensors").symlink_to(model / "model.safetensors")
        with contextlib.redirect_stdout(sys.stderr):
            self.agent = laya.Agent(str(local), device="cpu", fast=False, compile=False)
        if self.agent.device.type != "cpu":
            raise ValueError("runtime device does not match the selected CPU profile")
        if file_digest(model / "model.safetensors") != expected_base:
            raise ValueError("base model changed while loading")
        self.model = self.agent.model.float().eval()
        self.temperature = float(self.model.temperature[0])
        if not math.isfinite(self.temperature) or not 0.05 <= self.temperature <= 20:
            raise ValueError("the pinned base calibration is outside this profile")
        for parameter in self.model.parameters():
            parameter.requires_grad_(False)
        self.base_assets_digest = digest(canonical({
            str(p.relative_to(local)): file_digest(p)
            for directory in (local / "tokenizer", local / "encoder")
            for p in sorted(directory.rglob("*")) if p.is_file()
        }) + (local / "rl_agent_config.json").read_bytes())
        head_digest = expected_base
        if candidate is not None:
            if not candidate.is_absolute() or not candidate.is_dir():
                raise ValueError("candidate must be an absolute staged artifact directory")
            meta_bytes = (candidate / "candidate.json").read_bytes()
            if len(meta_bytes) > 8192:
                raise ValueError("candidate metadata exceeds its bound")
            meta = strict_json(meta_bytes)
            if meta.get("schema") != "hepta.laya.scorer-candidate.v1" or meta.get("base_sha256") != expected_base:
                raise ValueError("candidate belongs to a different base or schema")
            if meta.get("base_assets_sha256") != self.base_assets_digest:
                raise ValueError("candidate encoder/tokenizer configuration changed")
            if meta.get("preprocessor_sha256") != digest(canonical(PROFILE)):
                raise ValueError("candidate feature contract changed")
            head_file = candidate / "scorer.safetensors"
            if head_file.stat().st_size > 16 * 1024 * 1024 or file_digest(head_file) != meta.get("scorer_sha256"):
                raise ValueError("candidate scorer bytes changed")
            temperature = meta.get("temperature")
            if type(temperature) not in (float, int) or not math.isfinite(temperature) or not 0.05 <= temperature <= 20:
                raise ValueError("candidate calibration is invalid")
            self.model.scorer.load_state_dict(load_file(str(head_file)), strict=True)
            self.temperature = float(temperature)
            head_digest = digest(meta_bytes + bytes.fromhex(meta["scorer_sha256"]))
        self.encoder_digest = expected_base
        self.head_digest = head_digest
        token_files = {p.name: file_digest(p) for p in sorted((local / "tokenizer").iterdir()) if p.is_file()}
        package = Path(laya.__file__).parent
        runtime = {
            "backend_sha256": file_digest(Path(__file__).resolve()),
            "base_assets_sha256": self.base_assets_digest,
            "laya": importlib.metadata.version("laya"),
            "laya_sources": {p.name: file_digest(p) for p in sorted(package.glob("*.py"))},
            "torch": torch.__version__,
            "python": sys.version,
            "numerical_packages": {name: importlib.metadata.version(name) for name in ("numpy", "tokenizers", "safetensors", "huggingface-hub")},
            "transformers": importlib.metadata.version("transformers"),
        }
        cpu = next((line.strip() for line in Path("/proc/cpuinfo").read_text().splitlines() if line.startswith("model name")), platform.machine())
        self.manifest = {
            "model_id": "laya.retrieval-continuation-v1",
            "weights_digest": digest(b"hepta.laya.effective.v1\0" + bytes.fromhex(expected_base) + bytes.fromhex(head_digest)),
            "tokenizer_digest": digest(canonical(token_files)),
            "preprocessor_digest": digest(canonical(PROFILE)),
            "quantization_digest": digest(b"cpu-float32-eager-v1"),
            "runtime_digest": digest(canonical(runtime)),
            "device_digest": digest(canonical({"device": "cpu", "cpu": cpu, "threads": 4, "machine": platform.machine()})),
            "maximum_tokens": 512,
        }
        self.manifest["model_digest"] = digest(canonical(self.manifest))

    def tensors(self, features: Any) -> dict[str, Any]:
        from laya.common import build_sequence
        q = {"t": "choice", "ins": PROFILE["question"], "crit": {
            "no_material_benefit": "Another retrieval step is unlikely to materially improve evidence.",
            "material_benefit": "Another retrieval step is likely to materially improve evidence.",
        }}
        # Build a larger reference too: a silent sequence truncation is not an
        # accepted source transformation in this frozen feature profile.
        full, markers = build_sequence(self.agent.tok, state_for(features), q, max_len=4096, head_max_len=192)
        ids, bounded_markers = build_sequence(self.agent.tok, state_for(features), q, max_len=512, head_max_len=192)
        if ids != full or markers != bounded_markers or len(markers) != 2:
            raise ValueError("the selected tokenizer would truncate a feature request")
        torch = self.torch
        return {
            "input_ids": torch.tensor([ids], dtype=torch.long),
            "attention_mask": torch.ones((1, len(ids)), dtype=torch.long),
            "marker_pos": torch.tensor([markers], dtype=torch.long),
            "marker_mask": torch.ones((1, 2), dtype=torch.bool),
            "qtype": torch.tensor([0], dtype=torch.long),
        }

    def logits(self, features: Any):
        with self.torch.inference_mode():
            return self.model(**self.tensors(features))[0].float()

    def predict(self, features: Any) -> list[int]:
        probabilities = self.torch.softmax(self.logits(features) / self.temperature, dim=-1)[0].tolist()
        if any(not math.isfinite(v) or not 0 <= v <= 1 for v in probabilities):
            raise ValueError("model returned invalid prediction probabilities")
        first = round(probabilities[0] * Q24)
        return [first, Q24 - first]


def emit(value: Any) -> None:
    sys.stdout.write(canonical(value).decode() + "\n")
    sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--base-sha256", required=True)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--inspect", action="store_true")
    args = parser.parse_args()
    cell = LayaCell(args.model, args.base_sha256, args.candidate)
    emit({"manifest": cell.manifest, "encoder_digest": cell.encoder_digest,
          "head_digest": cell.head_digest, "memory_bytes": peak_bytes()})
    if args.inspect:
        return
    while True:
        raw = sys.stdin.buffer.readline(16385)
        if not raw:
            return
        if len(raw) > 16384 or not raw.endswith(b"\n"):
            raise ValueError("worker request exceeds the bounded transport frame")
        request = strict_json(raw)
        if not isinstance(request, dict) or set(request) != {"request_id", "features_q24"}:
            raise ValueError("unknown or missing worker input fields")
        if not isinstance(request["request_id"], str) or not 1 <= len(request["request_id"]) <= 256:
            raise ValueError("invalid worker request identity")
        started = time.perf_counter_ns()
        prediction = cell.predict(request["features_q24"])
        emit({"request_id": request["request_id"], "prediction_q24": prediction,
              "memory_bytes": peak_bytes(), "latency_micros": max(1, (time.perf_counter_ns() - started) // 1000)})


if __name__ == "__main__":
    main()
