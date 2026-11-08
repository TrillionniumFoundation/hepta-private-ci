"""Local, pinned MLX forwards. No remote loading, sampled text or mock votes."""

import importlib.metadata
import json
import math
from pathlib import Path, PurePosixPath
import re

from .model_protocol import DECODER, LIMITS, MODELS, digest, file_sha, messages


def normalized_yes(log_yes, log_no):
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in (log_yes, log_no)):
        raise ValueError("nonfinite candidate log likelihood")
    difference = log_yes - log_no
    if difference >= 0:
        return 1 / (1 + math.exp(-difference))
    ratio = math.exp(difference)
    return ratio / (1 + ratio)


def pinned_assets(path, expected_sha):
    path = Path(path).resolve()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha) or file_sha(path) != expected_sha:
        raise ValueError("asset manifest binding mismatch")
    manifest = json.loads(path.read_text())
    if manifest.get("schema") != "hepta.verify1.model-preparation.v1" or manifest.get("status") != "READY" or type(manifest.get("models")) is not list or len(manifest["models"]) != 2:
        raise ValueError("model assets are not ready")
    selected = {}
    for key, expected in MODELS.items():
        matches = [item for item in manifest["models"] if item.get("repo_id") == expected["repo"]]
        if len(matches) != 1 or matches[0].get("revision") != expected["revision"]:
            raise ValueError("model revision binding mismatch")
        item = matches[0]
        root = Path(item["directory"]).resolve(strict=True)
        hashes, seen = {}, set()
        required = {"model.safetensors", "config.json", "tokenizer.json", "tokenizer_config.json"}
        allowed = required | {"generation_config.json", "special_tokens_map.json", "vocab.json", "merges.txt", "LICENSE", "README.md"}
        for entry in item["files"]:
            name = entry["filename"]
            relative = PurePosixPath(name)
            if name not in allowed or name in seen or relative.is_absolute() or ".." in relative.parts or str(relative) != name or "\\" in name:
                raise ValueError("noncanonical model asset path")
            seen.add(name)
            if entry.get("status") == "OPTIONAL_404" and name not in required and entry.get("http_status") == 404 and not (root / name).exists():
                continue
            if entry.get("status") != "VERIFIED":
                raise ValueError("unverified model asset")
            target = root.joinpath(*relative.parts).resolve(strict=True)
            if root not in target.parents or name in hashes or not target.is_file():
                raise ValueError("model asset escapes or duplicates its root")
            if type(entry["bytes"]) is not int or entry["bytes"] < 0 or target.stat().st_size != entry["bytes"]:
                raise ValueError("model asset size mismatch")
            actual = file_sha(target)
            if actual != entry["sha256"] or entry.get("expected_lfs_sha256") not in (None, actual):
                raise ValueError("model asset digest mismatch")
            hashes[name] = actual
        if not required <= set(hashes) or hashes.get("config.json") != expected["config_sha256"]:
            raise ValueError("missing pinned model config or weights")
        # mlx_lm must not discover unmanifested configuration or weights.
        visible = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and not any(part.startswith(".") for part in p.relative_to(root).parts)}
        if visible != set(hashes):
            raise ValueError("unmanifested model files")
        selected[key] = {"directory": str(root), "base_sha256": digest({"repo": expected["repo"], "revision": expected["revision"], "files": hashes}), "files": hashes, **expected}
    return selected


class MLXBackend:
    def __init__(self, journal, manifest, manifest_sha):
        self.journal = journal
        with journal.operation("asset_verification", {"manifest_sha256": manifest_sha}) as receipt:
            self.identities = pinned_assets(manifest, manifest_sha)
            receipt["identities"] = self.identities
            journal.write("asset_preparation_manifest.json", json.loads(Path(manifest).read_text()))
        import mlx.core as mx
        import mlx_lm
        from mlx_lm import load
        self.mx = mx
        self.models = {}
        dependencies = {name: importlib.metadata.version(name) for name in ("mlx", "mlx-lm", "transformers", "tokenizers", "safetensors", "numpy")}
        if dependencies["mlx"] != "0.31.1" or dependencies["mlx-lm"] != "0.31.2":
            raise ValueError("unreviewed MLX runtime version")
        expected_sources = {"utils.py": "3a53fbd0cd5dc7d5f5dbc093b903a7573b6f05ead14e61b4958162b7c585bcc2", "models/qwen3.py": "2284df96ecb669109b281df4534470b18f285aa9a5e41735ad682f601f93c639", "models/llama.py": "8b46ac7f11c7134c1d83f12ec6e05b3d64a30f18aa7468798437b2e413f80cdb"}
        installed_sources = {name: file_sha(Path(mlx_lm.__file__).parent / name) for name in expected_sources}
        if installed_sources != expected_sources:
            raise ValueError("reviewed native MLX-LM source changed")
        device = {"default_device": str(mx.default_device())}
        metal = getattr(mx, "metal", None)
        info_function = getattr(mx, "device_info", None) or getattr(metal, "device_info", None)
        if callable(info_function):
            try:
                device["info"] = json.loads(json.dumps(info_function(), default=str))
            except Exception as error:
                device["info_error"] = {"type": type(error).__name__, "message": str(error)}
        available = getattr(metal, "is_available", None)
        if callable(available):
            device["metal_available"] = bool(available())
        journal.write("runtime_identity.json", {"dependencies": dependencies, "device": device, "mlx_lm_sources": installed_sources, "asset_manifest_sha256": manifest_sha, "models": self.identities})
        for key, identity in self.identities.items():
            with journal.operation("model_load", {"model": key, "base_sha256": identity["base_sha256"]}) as receipt:
                model, tokenizer = load(identity["directory"], tokenizer_config={"local_files_only": True, "trust_remote_code": False})
                model.eval()
                mx.eval(model.parameters())
                mx.synchronize()
                self.models[key] = (model, tokenizer)
                receipt["model_type"] = model.model_type

    def _prepare(self, key, role, view, context, kind):
        self.journal.consume(assessments=1)
        model, tokenizer = self.models[key]
        request = messages(view, role)
        prompt = tokenizer.apply_chat_template(request, tokenize=False, add_generation_prompt=True, enable_thinking=False)
        tokens = tokenizer.encode(prompt, add_special_tokens=False)
        if not tokens or len(tokens) > LIMITS["prompt_tokens"]:
            raise ValueError("prompt token limit")
        return model, tokenizer, tokens, {"inference_kind": kind, "model": key, "role": role, "context": context,
            "base_sha256": self.identities[key]["base_sha256"], "adapter_sha256": None,
            "view": view, "evidence_sha256": digest(view), "prompt": prompt, "prompt_sha256": digest(prompt),
            "prompt_token_ids": tokens, "prompt_tokens": len(tokens), "decoder": DECODER,
            "calibrated": False, "interpretation": "normalized candidate score, not a certified error probability"}

    def _forward(self, model, tokens, hidden=False):
        self.journal.consume(forward_passes=1, input_tokens=len(tokens))
        inputs = self.mx.array([tokens])
        output = model.model(inputs)[:, -1, :] if hidden else model(inputs)
        self.mx.eval(output)
        self.mx.synchronize()
        return output

    def score(self, key, role, view, context):
        with self.journal.operation("model_score", context) as receipt:
            model, tokenizer, tokens, detail = self._prepare(key, role, view, context, "yes_no_likelihood")
            receipt.update(detail)
            candidates = [tokenizer.encode(label, add_special_tokens=False) for label in DECODER["candidates"]]
            if any(not ids or len(ids) > 8 for ids in candidates) or candidates[0] == candidates[1]:
                raise ValueError("invalid candidate tokenization")
            if any(a == b[:len(a)] for a, b in ((candidates[0], candidates[1]), (candidates[1], candidates[0]))):
                raise ValueError("candidate token sequences must be prefix-free")
            mx = self.mx
            logs = []
            if all(len(ids) == 1 for ids in candidates):
                last = self._forward(model, tokens)[0, -1].astype(mx.float32)
                normalizer = mx.logsumexp(last)
                values = mx.stack([last[ids[0]] - normalizer for ids in candidates])
                mx.eval(values)
                mx.synchronize()
                logs = values.tolist()
            else:
                for ids in candidates:
                    logits = self._forward(model, tokens + ids[:-1])[0, len(tokens) - 1:].astype(mx.float32)
                    values = mx.stack([logits[i, token] - mx.logsumexp(logits[i]) for i, token in enumerate(ids)])
                    total = mx.sum(values)
                    mx.eval(total)
                    mx.synchronize()
                    logs.append(total.item())
            receipt.update(candidate_token_ids=candidates, candidate_log_likelihoods=logs, score=normalized_yes(*logs))
            return {"score": receipt["score"], "operation_id": receipt["operation_id"], "base_sha256": receipt["base_sha256"], "adapter_sha256": None, "prompt_sha256": receipt["prompt_sha256"], "evidence_sha256": receipt["evidence_sha256"]}

    def features(self, view, context):
        with self.journal.operation("model_features", context) as receipt:
            model, _, tokens, detail = self._prepare("qwen", "neutral", view, context, "frozen_final_hidden")
            receipt.update(detail)
            values = self._forward(model, tokens, hidden=True).astype(self.mx.float32)
            self.mx.eval(values)
            self.mx.synchronize()
            vector = values[0].tolist()
            if not vector or any(not math.isfinite(value) for value in vector):
                raise ValueError("invalid model hidden state")
            receipt.update(feature_sha256=digest(vector), feature_dimension=len(vector))
            return {"values": vector, "operation_id": receipt["operation_id"], "base_sha256": receipt["base_sha256"], "prompt_sha256": receipt["prompt_sha256"], "evidence_sha256": receipt["evidence_sha256"]}
