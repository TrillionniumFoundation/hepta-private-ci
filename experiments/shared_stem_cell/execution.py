"""Actual local execution for the existing six-experiment research suite.

No implicit downloads, synthetic fallback, model selection or product authority.
The producer seals predictions before the separate evaluator sees held-out labels.
Missing energy/FLOP counters remain None; tensor bytes are not process RSS.
"""
from __future__ import annotations

import argparse
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import platform
import time

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F


from experiments.shared_stem_cell.wire import InputError, canonical, decode, sha, write_once


def integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise InputError(f"invalid {name}")
    return value


def bound_file(path: Path, expected: str, maximum=16 * 1024 * 1024) -> bytes:
    if (not isinstance(expected, str) or len(expected) != 64
            or any(c not in "0123456789abcdef" for c in expected)):
        raise InputError("invalid external SHA256")
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise InputError("missing, linked or oversized source")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum or sha(raw) != expected:
        raise InputError("source digest/size drift")
    return raw


def tensor_digest(value: torch.Tensor) -> str:
    value = value.detach().cpu().contiguous()
    return sha(canonical([str(value.dtype), list(value.shape)])
               + value.reshape(-1).view(torch.uint8).numpy().tobytes())


def parameters(model: nn.Module):
    state = model.state_dict()
    return {"sha256": sha(canonical({k: tensor_digest(v) for k, v in sorted(state.items())})),
            "parameters": sum(p.numel() for p in model.parameters()),
            "parameter_bytes": sum(p.numel() * p.element_size() for p in model.parameters())}


@contextmanager
def measured():
    """Current-process timings only; no invented energy or backend FLOP values."""
    result = {"energy_joules": None, "active_flops": None,
              "rss_start_bytes": None, "rss_end_bytes": None,
              "peak_rss_bytes": None, "gpu_peak_bytes": None}
    try:
        import psutil
        process = psutil.Process(os.getpid())
        result["rss_start_bytes"] = process.memory_info().rss
    except (ImportError, OSError):
        process = None
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    try:
        yield result
    finally:
        result["wall_ns"] = time.perf_counter_ns() - wall
        result["process_cpu_ns"] = time.process_time_ns() - cpu
        if process is not None:
            try:
                result["rss_end_bytes"] = process.memory_info().rss
            except OSError:
                pass


@dataclass(frozen=True)
class Case:
    case_id: str
    group: str
    split: str
    observed_at: int | None
    cell: int
    scope: str
    text: str

    @property
    def input_digest(self):
        return sha(canonical([self.scope, self.text]))


def dataset(path: Path, expected: str, classes: int, cells: int, temporal: bool):
    """Independent groups and content across folds; no invented future time."""
    integer(classes, 2, 256, "classes")
    integer(cells, 1, 4096, "cells")
    raw = bound_file(path, expected)
    cases, labels, groups, texts, times = [], {}, {}, {}, {}
    for line in raw.splitlines():
        if not line.strip():
            raise InputError("blank physical dataset row")
        row = decode(line)
        if not isinstance(row, dict) or set(row) != {
            "case_id", "group", "split", "observed_at", "cell", "scope", "text", "label"
        }:
            raise InputError("unexpected dataset fields")
        for key in ("case_id", "group", "scope", "text"):
            if not isinstance(row[key], str) or not 1 <= len(row[key].encode()) <= 65536:
                raise InputError(f"invalid {key}")
        split = row["split"]
        if split not in {"train", "extra_train", "calibration", "holdout", "retention"}:
            raise InputError("unknown split")
        integer(row["cell"], 0, cells - 1, "cell")
        integer(row["label"], 0, classes - 1, "label")
        case = Case(**{k: v for k, v in row.items() if k != "label"})
        if case.case_id in labels:
            raise InputError("duplicate case")
        # Content equality is checked across scopes too, not just cache namespaces.
        content_key = sha(case.text.encode())
        for registry, key in ((groups, case.group), (texts, content_key)):
            if key in registry and registry[key] != split:
                raise InputError("cross-fold group/content leakage")
            registry[key] = split
        if case.observed_at is not None:
            integer(case.observed_at, 0, 2**63 - 1, "observed_at")
            times.setdefault(split, []).append(case.observed_at)
        elif temporal:
            raise InputError("temporal study needs observed timestamps")
        cases.append(case)
        labels[case.case_id] = row["label"]
    if not 4 <= len(cases) <= 16384:
        raise InputError("bounded dataset cardinality required")
    if not {"train", "calibration", "holdout"} <= {x.split for x in cases}:
        raise InputError("train/calibration/holdout are required")
    if temporal:
        train = times["train"] + times.get("extra_train", [])
        if not max(train) < min(times["calibration"]) <= max(times["calibration"]) < min(times["holdout"]):
            raise InputError("invalid chronological boundaries")
    return tuple(cases), labels


def verify_snapshot(root: Path, manifest: dict):
    """Verify an operator-staged, ordinary-file snapshot, including tokenizer."""
    if root.is_symlink() or not root.is_dir():
        raise InputError("snapshot must be a real local directory")
    revision = manifest.get("revision", "")
    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
        raise InputError("model revision must be immutable")
    files = manifest.get("files")
    if not isinstance(files, dict) or not 1 <= len(files) <= 256:
        raise InputError("bounded snapshot inventory required")
    total = 0
    for name, digest in sorted(files.items()):
        part = Path(name)
        if part.is_absolute() or ".." in part.parts or not part.parts:
            raise InputError("invalid snapshot path")
        target = root / part
        if any(p.is_symlink() for p in [target, *target.parents] if p != root.parent):
            raise InputError("linked snapshot path")
        if not target.is_file():
            raise InputError("missing snapshot member")
        size = target.stat().st_size
        total += size
        if total > 4 * 1024**3:
            raise InputError("snapshot exceeds 4 GiB")
        h = hashlib.sha256()
        with target.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024**2), b""):
                h.update(chunk)
        if h.hexdigest() != digest:
            raise InputError("snapshot content drift")
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if actual != set(files):
        raise InputError("undeclared snapshot member")
    if not any(name.endswith(".safetensors") for name in files):
        raise InputError("safetensors weights required")
    return sha(canonical(manifest))


def verify_materialized(loaded, info, root, manifest):
    """Check every saved tensor and exact storage aliases; shared by frozen towers."""
    from safetensors import safe_open
    fields = ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs")
    if not isinstance(info, dict) or any(k not in info or info[k] for k in fields):
        raise InputError("incomplete model load")
    state = loaded.state_dict()
    # Stock CLIP's position_ids may be present in publisher checkpoints but
    # registered as non-persistent buffers by newer Transformers runtimes.
    # Reconcile ONLY those two known generated buffers, and verify their full
    # original integer contents against both the loaded buffer and arange.
    # Unknown/dropped parameters remain hard failures; this is not a blanket
    # load-info waiver or a suppression of checkpoint inventory validation.
    clip_position_buffers = {}
    if getattr(getattr(loaded, "config", None), "model_type", None) == "clip":
        exact_keys = frozenset({
            "text_model.embeddings.position_ids",
            "vision_model.embeddings.position_ids",
        })
        clip_position_buffers = {
            key: value for key, value in loaded.named_buffers()
            if key in exact_keys and key not in state
        }
    covered, aliases = set(), set()
    def alias(value):
        return (value.data_ptr(), tuple(value.shape), tuple(value.stride()), str(value.dtype))
    for name in manifest["files"]:
        if not name.endswith(".safetensors"):
            continue
        with safe_open(str(root / name), framework="pt", device="cpu") as saved:
            for key in saved.keys():
                tensor = saved.get_tensor(key)
                if key in covered:
                    raise InputError("snapshot tensor inventory mismatch")
                if key in state:
                    if tensor.shape != state[key].shape:
                        raise InputError("snapshot tensor inventory mismatch")
                    if not bool(torch.isfinite(tensor).all()) or not torch.equal(tensor.to(state[key].dtype), state[key]):
                        raise InputError("snapshot tensor materialization mismatch")
                    aliases.add(alias(state[key]))
                elif key in clip_position_buffers:
                    buffer = clip_position_buffers[key]
                    if (tensor.ndim != 2 or tensor.shape[0] != 1
                            or buffer.shape != tensor.shape
                            or buffer.dtype != torch.int64 or tensor.dtype != torch.int64
                            or not torch.equal(tensor, buffer)
                            or not torch.equal(tensor, torch.arange(tensor.shape[1], dtype=torch.int64).unsqueeze(0))):
                        raise InputError("CLIP position buffer materialization mismatch")
                else:
                    raise InputError("snapshot tensor inventory mismatch")
                covered.add(key)
    if any(k not in covered and alias(v) not in aliases for k, v in state.items()):
        raise InputError("unverified loaded tensor")
    return {"verified_tensor_keys": len(covered), "state_keys": len(state),
            "loaded_tensor_bytes": sum(v.numel() * v.element_size() for v in state.values()),
            "storage_aliases_validated": True}


class LocalEncoder:
    """Stock HF encoder/MLM only. A Laya Decision Head is NOT silently dropped."""
    simulated = False
    permitted_kinds = {"encoder", "masked_lm"}

    def __init__(self, root: Path, manifest: dict, maximum_tokens=512):
        self.root, self.manifest = root, manifest
        self.identity = verify_snapshot(root, manifest)
        self.maximum_tokens = integer(maximum_tokens, 8, 8192, "token ceiling")
        from transformers import AutoModel, AutoModelForCausalLM, AutoModelForMaskedLM, AutoTokenizer
        kind = manifest.get("kind")
        factories = {"encoder": AutoModel, "masked_lm": AutoModelForMaskedLM, "causal_lm": AutoModelForCausalLM}
        if kind not in self.permitted_kinds:
            raise InputError("unsupported model kind; no Laya/generator reinterpretation")
        self.tokenizer = AutoTokenizer.from_pretrained(
            root, local_files_only=True, trust_remote_code=False)
        loaded, info = factories[kind].from_pretrained(
            root, local_files_only=True, trust_remote_code=False, use_safetensors=True,
            output_loading_info=True, attn_implementation="eager")
        self.loaded = loaded.cpu().float().eval()
        self.loaded.requires_grad_(False)
        self.materialization = verify_materialized(self.loaded, info, root, manifest)
        verify_snapshot(root, manifest)
        self.model = self.loaded.base_model
        self.forward_calls = 0

    @torch.no_grad()
    def encode(self, texts: list[str]):
        if not 1 <= len(texts) <= 32:
            raise InputError("batch cardinality")
        encoded = self.tokenizer(texts, padding=True, truncation=False, return_tensors="pt")
        length = encoded["input_ids"].shape[1]
        if length > self.maximum_tokens or length * len(texts) > 32768:
            raise InputError("token budget; no silent truncation")
        value = self.model(**encoded).last_hidden_state
        mask = encoded["attention_mask"].unsqueeze(-1).to(value.dtype)
        pooled = (value * mask).sum(1) / mask.sum(1).clamp_min(1)
        self.forward_calls += 1
        return pooled.detach().cpu().float().contiguous()

    def close(self):
        verify_snapshot(self.root, self.manifest)



class LocalTextGenerator(LocalEncoder):
    """Real, pinned pretrained text generation; no target-bearing generation API."""
    permitted_kinds = {"causal_lm"}

    @torch.no_grad()
    def generate(self, prompts, maximum_new_tokens=64, *, add_special_tokens=True):
        integer(maximum_new_tokens, 1, 256, "generation ceiling")
        if type(add_special_tokens) is not bool:
            raise InputError("explicit special-token policy required")
        if not isinstance(prompts, list) or not 1 <= len(prompts) <= 64:
            raise InputError("bounded generation batch")
        # Validate EVERY prompt before spending the first decoder call.
        prepared = []
        for prompt in prompts:
            if not isinstance(prompt, str) or not 1 <= len(prompt.encode()) <= 65536:
                raise InputError("bounded nonempty generation prompt")
            encoded = self.tokenizer(prompt, truncation=False, return_tensors="pt",
                                     add_special_tokens=add_special_tokens)
            tokens = encoded.get("input_ids")
            if (not isinstance(tokens, torch.Tensor) or tokens.dtype != torch.long
                    or tokens.device.type != "cpu" or tokens.ndim != 2 or tokens.shape[0] != 1
                    or not 1 <= tokens.shape[1] <= self.maximum_tokens):
                raise InputError("generation input exceeds ceiling/shape; no truncation")
            context = getattr(self.loaded.config, "max_position_embeddings", None)
            if context is not None and (type(context) is not int or tokens.shape[1] + maximum_new_tokens > context):
                raise InputError("generation continuation exceeds model context")
            prepared.append(encoded)
        rows = []
        for prompt, encoded in zip(prompts, prepared):
            with measured() as timing:
                output = self.loaded.generate(**encoded, do_sample=False,
                    max_new_tokens=maximum_new_tokens,
                    pad_token_id=self.tokenizer.eos_token_id)
            prefix = encoded["input_ids"].shape[1]
            if (not isinstance(output, torch.Tensor) or output.dtype != torch.long
                    or output.ndim != 2 or output.shape[0] != 1
                    or not prefix <= output.shape[1] <= prefix + maximum_new_tokens):
                raise InputError("generated token shape/budget mismatch")
            if not torch.equal(output[:, :prefix], encoded["input_ids"]):
                raise InputError("causal output prefix mismatch")
            tokens = output[0, prefix:]
            rows.append({"input_sha256": sha(prompt.encode()),
                "input_token_sha256": tensor_digest(encoded["input_ids"]),
                "output_token_sha256": tensor_digest(tokens), "generated_tokens": len(tokens),
                "input_tokens": prefix, "input_special_tokens_added": add_special_tokens,
                "text": self.tokenizer.decode(tokens, skip_special_tokens=True), **timing})
        self.close()
        return {"modality": "text", "model_digest": self.identity, "outputs": rows,
                "semantic_quality": None, "multimodal_generation_completed": False,
                "production_accepted": False}


def encode_cases(backend, cases, *, batch_size=8, cache_bytes=0):
    """Transactional finite output checks; cache hits retain their own tensors."""
    integer(batch_size, 1, 32, "batch size")
    integer(cache_bytes, 0, 512 * 1024**2, "cache bytes")
    cache, size, results = OrderedDict(), 0, []
    calls = hits = 0
    with measured() as measurement:
        for start in range(0, len(cases), batch_size):
            group = cases[start:start + batch_size]
            scopes = {case.scope for case in group}
            if len(scopes) != 1:
                raise InputError("cross-scope physical batch")
            keys = [(backend.identity, case.input_digest) for case in group]
            selected, missing, texts = {}, [], []
            for key, case in zip(keys, group):
                if cache_bytes and key in cache:
                    selected[key] = cache[key]  # borrow before any eviction
                    cache.move_to_end(key)
                    hits += 1
                elif not cache_bytes or key not in missing:
                    missing.append(key)
                    texts.append(case.text)
                else:
                    hits += 1
            if missing:
                value = backend.encode(texts)
                calls += 1
                if (not isinstance(value, torch.Tensor) or value.ndim != 2
                        or value.shape[0] != len(missing) or not 1 <= value.shape[1] <= 8192
                        or value.device.type != "cpu" or value.dtype != torch.float32
                        or not bool(torch.isfinite(value).all())):
                    raise InputError("invalid physical encoder output")
                if cache_bytes:
                    # Clone rows: retaining a view would pin an uncharged whole batch.
                    fresh = [(k, v.clone().contiguous()) for k, v in zip(missing, value)]
                    for key, item in fresh:
                        selected[key] = item
                        charge = item.numel() * item.element_size()
                        if charge > cache_bytes:
                            continue
                        while cache and size + charge > cache_bytes:
                            _, old = cache.popitem(last=False)
                            size -= old.numel() * old.element_size()
                        cache[key] = item
                        size += charge
                else:
                    results.extend(v.clone() for v in value)
            if cache_bytes:
                results.extend(selected[key] for key in keys)
    return torch.stack(results), {**measurement, "encoder_forward_calls": calls,
        "cache_reuses": hits, "cache_retained_tensor_bytes": size,
        "retained_result_tensor_bytes": sum(v.numel() * v.element_size() for v in results),
        "cache_object_overhead_measured": False, "requests": len(cases),
        "simulated_encoder": bool(backend.simulated), "model_digest": backend.identity}


class Head(nn.Module):
    """Actual parameterized Heads; low_rank is post-Encoder, not backbone LoRA."""
    def __init__(self, width, classes, kind="linear", rank=8):
        super().__init__()
        integer(width, 1, 8192, "width")
        integer(classes, 2, 256, "classes")
        integer(rank, 1, min(256, width), "rank")
        self.kind = kind
        self.base = nn.Linear(width, classes)
        if kind in {"gated", "low_rank"}:
            self.down = nn.Linear(width, rank)
            self.up = nn.Linear(rank, classes, bias=False)
            if kind == "gated":
                self.gate = nn.Linear(width, classes)
        elif kind == "sparse_expert":
            self.experts = nn.ModuleList([nn.Linear(width, classes) for _ in range(2)])
            self.router = nn.Linear(width, 2)
        elif kind != "linear":
            raise InputError("unknown Head kind")

    def forward(self, x):
        output = self.base(x)
        if self.kind in {"gated", "low_rank"}:
            residual = self.up(torch.tanh(self.down(x)))
            if self.kind == "gated":
                residual = residual * torch.sigmoid(self.gate(x))
            return output + residual
        if self.kind == "sparse_expert":
            probabilities = self.router(x).softmax(-1)
            if self.training:
                return output + sum(probabilities[:, i:i+1] * e(x) for i, e in enumerate(self.experts))
            chosen = probabilities.argmax(-1)
            for i, expert in enumerate(self.experts):
                mask = chosen == i
                if bool(mask.any()):
                    output[mask] += expert(x[mask])
        return output


def fit(initial: nn.Module, x, y, *, steps=40, seed=17, batch=16):
    from copy import deepcopy
    integer(steps, 1, 10000, "steps")
    integer(batch, 1, 256, "training batch")
    if x.ndim != 2 or len(x) != len(y) or not len(x) or y.dtype != torch.long:
        raise InputError("training shape")
    if not bool(torch.isfinite(x).all()):
        raise InputError("nonfinite training input")
    original = parameters(initial)["sha256"]
    model = deepcopy(initial).train()
    rng = torch.Generator().manual_seed(seed)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.01, weight_decay=0.0)
    with measured() as metrics:
        for _ in range(steps):
            ids = torch.randint(len(x), (min(batch, len(x)),), generator=rng)
            optimizer.zero_grad(set_to_none=True)
            loss = F.cross_entropy(model(x[ids].detach()), y[ids])
            if not bool(torch.isfinite(loss)):
                raise InputError("nonfinite training loss")
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0, error_if_nonfinite=True)
            optimizer.step()
    if parameters(initial)["sha256"] != original:
        raise InputError("initial/frozen control mutated")
    return model.eval(), {**metrics, **parameters(model), "steps": steps,
                          "examples_processed": steps * min(batch, len(x))}


def head_trial(x, cases, train_labels, *, classes, kind, steps, seed,
               artifact_dir=None, artifact_binding=None):
    """Returns unlabeled predictions. No held-out target mapping is accepted."""
    if artifact_dir is not None:
        from experiments.shared_stem_cell.head_artifacts import _binding, _path
        if not isinstance(artifact_binding, dict):
            raise InputError("explicit artifact feature binding required")
        _binding({**artifact_binding, "logical_cell": "preflight",
                  "training_lineage_sha256": sha(b"preflight-only")})
        if any(c.scope != artifact_binding["scope"] for c in cases):
            raise InputError("Head export scope mismatch before training")
        if _path(artifact_dir).exists():
            raise InputError("Head trial export directory must be new")
    outputs, costs = [], []
    for cell in sorted({case.cell for case in cases}):
        train_ids = [i for i, c in enumerate(cases) if c.cell == cell and c.split == "train"]
        test_ids = [i for i, c in enumerate(cases) if c.cell == cell and c.split in {"holdout", "retention"}]
        if not train_ids or not test_ids:
            raise InputError("each active Cell needs train and held-out cases")
        torch.manual_seed(seed + cell)
        initial = Head(x.shape[1], classes, kind, min(8, x.shape[1])).eval()
        y = torch.tensor([train_labels[cases[i].case_id] for i in train_ids], dtype=torch.long)
        trained, cost = fit(initial, x[train_ids], y, steps=steps, seed=seed)
        artifacts = None
        if artifact_dir is not None:
            from experiments.shared_stem_cell.head_artifacts import export_head, load_head
            if not isinstance(artifact_binding, dict):
                raise InputError("explicit artifact feature binding required")
            scopes = {c.scope for c in cases if c.cell == cell}
            if len(scopes) != 1 or artifact_binding.get("scope") not in scopes:
                raise InputError("Head export scope mismatch")
            lineage = {"seed": seed, "steps": steps, "kind": kind,
                       "train": [[cases[i].case_id, cases[i].input_digest,
                                  train_labels[cases[i].case_id]] for i in train_ids]}
            binding = {**artifact_binding, "logical_cell": str(cell),
                       "training_lineage_sha256": sha(canonical(lineage))}
            artifacts = {}
            with measured() as artifact_cost:
                for role, candidate in (("frozen", initial), ("learned", trained)):
                    destination = Path(artifact_dir) / f"cell-{cell}" / role
                    receipt = export_head(destination, candidate, binding)
                    restored = load_head(destination, receipt["manifest_sha256"], binding)
                    with torch.no_grad():
                        expected, actual = candidate(x[test_ids]), restored(x[test_ids])
                    if not torch.equal(expected, actual):
                        raise InputError("reopened Head prediction parity failed")
                    artifacts[role] = {**receipt, "relative_path": f"cell-{cell}/{role}",
                                       "binding": binding, "reload_logits_exact": True}
            artifacts["export_and_reload_cost"] = artifact_cost
        costs.append({"cell": cell, **cost, "frozen": parameters(initial),
                      "offline_head_artifacts": artifacts})
        with torch.no_grad():
            before = initial(x[test_ids]).softmax(-1).tolist()
            after = trained(x[test_ids]).softmax(-1).tolist()
        for i, frozen, learned in zip(test_ids, before, after):
            outputs.append({"case_id": cases[i].case_id, "group": cases[i].group,
                "split": cases[i].split, "cell": cell, "input_digest": cases[i].input_digest,
                "arm": kind, "frozen_probabilities": frozen, "probabilities": learned})
    return outputs, costs


def evaluate_sealed(path: Path, expected: str, labels, cases, expected_arms=None):
    payload = decode(bound_file(path, expected, 64 * 1024**2))
    rows = payload["predictions"]
    if not isinstance(rows, list) or not rows:
        raise InputError("nonempty predictions required")
    if expected_arms is not None and {row["arm"] for row in rows} != set(expected_arms):
        raise InputError("missing complete arm")
    available = {c.case_id: c for c in cases if c.split in {"holdout", "retention"}}
    result, seen = {}, set()
    for row in rows:
        case = available.get(row["case_id"])
        key = (row["arm"], row["case_id"])
        if case is None or key in seen or row["input_digest"] != case.input_digest:
            raise InputError("prediction identity/coverage drift")
        seen.add(key)
        for name in ("probabilities", "frozen_probabilities"):
            p = row[name]
            if not isinstance(p, list) or len(p) < 2 or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in p) or abs(sum(p) - 1) > 1e-5:
                raise InputError("invalid probability distribution")
        p, q, y = row["probabilities"], row["frozen_probabilities"], labels[case.case_id]
        if len(p) != len(q) or y >= len(p):
            raise InputError("class dimension drift")
        values = result.setdefault((row["arm"], case.split), [])
        values.append((int(np.argmax(p) == y), int(np.argmax(q) == y),
                       sum((v - int(i == y))**2 for i, v in enumerate(p))))
    for arm in {row["arm"] for row in rows}:
        if {case_id for a, case_id in seen if a == arm} != set(available):
            raise InputError("incomplete arm; failures may not be filtered")
    return [{"arm": arm, "split": split, "cases": len(values),
             "accuracy": float(np.mean([v[0] for v in values])),
             "same_init_frozen_accuracy": float(np.mean([v[1] for v in values])),
             "brier": float(np.mean([v[2] for v in values])),
             "independent_evaluation": False}
            for (arm, split), values in sorted(result.items())]


def run(manifest_path: Path, output: Path):
    """Real offline model path; absence/errors never fall back to synthetic curves."""
    manifest_raw = manifest_path.read_bytes()
    config = decode(manifest_raw)
    if config.get("schema") != "hepta.shared-stem-execution.v1":
        raise InputError("execution manifest schema")
    output.mkdir(parents=True, exist_ok=False)
    write_once(output / "plan.json", config)
    root = manifest_path.parent
    started_wall, started_cpu = time.perf_counter_ns(), time.process_time_ns()
    try:
        if any(type(config.get(flag, False)) is not bool for flag in ("temporal", "measure_head_batch")):
            raise InputError("temporal and measure_head_batch must be Boolean declarations")
        cases, labels = dataset(root / config["dataset"]["path"], config["dataset"]["sha256"],
            config["classes"], config["cells"], config.get("temporal", False))
        train_labels = {c.case_id: labels[c.case_id] for c in cases if c.split == "train"}
        # Scope partitions are explicit and checked before loading any weights.
        if len({case.scope for case in cases}) != 1:
            raise InputError("one scope per physical study; partition before invocation")
        with measured() as model_load:
            backend = LocalEncoder(root / config["model"]["path"], config["model"],
                                   config.get("maximum_tokens", 512))
        with measured() as whole:
            x, encoding = encode_cases(backend, cases, batch_size=config.get("batch_size", 8))
            sharing = []
            if config.get("measure_sharing", False):
                sample = tuple(c for c in cases if c.split == "holdout")[:8]
                for repeat in (1, 4):
                    workload = sample * repeat
                    reference = None
                    profiles = [("singleton_no_cache", 1, 0), ("batch_no_cache", 8, 0),
                                ("batch_cache", 8, 64 * 1024**2)]
                    if repeat == 4:
                        profiles.reverse()
                    for name, batch, capacity in profiles:
                        features, costs = encode_cases(backend, workload, batch_size=batch, cache_bytes=capacity)
                        if reference is not None and not torch.allclose(reference, features, rtol=1e-5, atol=1e-5):
                            raise InputError("batch/cache numerical parity failed")
                        reference = features
                        sharing.append({"arm": name, "repeat": repeat, **costs,
                            "cold_cache": True, "model_load_shared": True,
                            "independent_questions": len(sample), "not_end_to_end_cell_latency": True})
            rows, training = [], {}
            for kind in ("linear", "gated", "low_rank", "sparse_expert"):
                predictions, costs = head_trial(x, cases, train_labels, classes=config["classes"],
                    kind=kind, steps=config.get("steps", 40), seed=config.get("seed", 17),
                    artifact_dir=output / "heads" / kind,
                    artifact_binding={"scope": cases[0].scope, "stem_sha256": backend.identity,
                        "dataset_sha256": config["dataset"]["sha256"],
                        "generation": integer(config.get("candidate_generation", 1), 1, 2**64 - 1, "candidate generation"),
                        "feature_profile_sha256": sha(canonical({"width": x.shape[1],
                            "representation": "masked_mean_float32", "model": backend.identity,
                            "maximum_tokens": config.get("maximum_tokens", 512)}))})
                rows.extend(predictions)
                training[kind] = costs
            head_batch = {}
            if config.get("measure_head_batch", False):
                from experiments.shared_stem_cell.head_batch import compare_exported_heads
                head_batch = compare_exported_heads(output / "heads", training, x, cases)
            controls = {}
            if config.get("run_controls", False):
                from experiments.shared_stem_cell.controls import split_trial, recurrent_trial
                ids = {split: [i for i, c in enumerate(cases) if c.split == split]
                       for split in ("train", "calibration", "holdout", "extra_train")}
                target = lambda split: torch.tensor([labels[cases[i].case_id] for i in ids[split]], dtype=torch.long)
                routed = torch.cat([x, torch.tensor([[c.cell % 2] for c in cases], dtype=torch.float32)], 1)
                extra = (routed[ids["extra_train"]], target("extra_train")) if ids["extra_train"] else None
                controls["split"] = split_trial(routed[ids["train"]], target("train"), routed[ids["holdout"]],
                    classes=config["classes"], steps=config.get("steps", 40), seed=config.get("seed", 17), extra=extra)
                controls["system2"] = recurrent_trial(x[ids["train"]].unsqueeze(1), target("train"),
                    x[ids["calibration"]].unsqueeze(1), target("calibration"), x[ids["holdout"]].unsqueeze(1),
                    classes=config["classes"], steps=config.get("steps", 40), seed=config.get("seed", 17))
                controls["system2"]["input_semantics"] = "iterative_refinement_of_one_pooled_observation_not_multihop"
                controls["holdout_case_ids"] = [cases[i].case_id for i in ids["holdout"]]
            generation = None
            if "generator" in config:
                generator = LocalTextGenerator(root / config["generator"]["path"], config["generator"],
                                               config.get("maximum_tokens", 512))
                prompts = [c.text for c in cases if c.split == "holdout"][:16]
                generation = generator.generate(prompts)
            backend.close()
            # Recheck persistent input drift before publishing; not OS attestation.
            bound_file(root / config["dataset"]["path"], config["dataset"]["sha256"])
            if manifest_path.read_bytes() != manifest_raw:
                raise InputError("manifest changed during execution")
            seal = write_once(output / "predictions.json", {"predictions": rows})
            controls_seal = write_once(output / "controls.json", controls)
            generation_seal = write_once(output / "generation.json", generation)
            head_batch_seal = write_once(output / "head-batch.json", head_batch)
        scores = evaluate_sealed(output / "predictions.json", seal, labels, cases,
            expected_arms=("linear", "gated", "low_rank", "sparse_expert"))
        from experiments.shared_stem_cell.control_evaluation import evaluate_controls
        control_scores = evaluate_controls(output / "controls.json", controls_seal,
                                           labels, cases, classes=config["classes"])
        report = {"schema": "hepta.shared-stem-executed.v1", "mode": "local_pretrained",
            "control_scores": control_scores,
            "manifest_sha256": sha(manifest_raw), "predictions_sha256": seal,
            "source_sha256": sha(Path(__file__).read_bytes()), "encoding": encoding,
            "training": training, "whole_execution": whole, "scores": scores,
            "model_load": model_load, "sharing": sharing,
            "head_batch_sha256": head_batch_seal, "head_batch_executed": bool(head_batch),
            "controls_sha256": controls_seal, "generation_sha256": generation_seal,
            "multimodal_towers_executed": False, "controls_executed": bool(controls),
            "runtime": {"python": platform.python_version(), "torch": torch.__version__},
            "production_accepted": False, "independent_evaluation": False,
            "laya_comparison_completed": False, "six_experiments_completed": False}
        write_once(output / "report.json", report)
        return report
    except Exception as error:
        write_once(output / "failure.json", {"status": "failed", "exception": type(error).__name__,
            "message": str(error), "production_accepted": False,
            "elapsed_wall_ns": time.perf_counter_ns() - started_wall,
            "elapsed_process_cpu_ns": time.process_time_ns() - started_cpu})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    run(arguments.manifest, arguments.output)
