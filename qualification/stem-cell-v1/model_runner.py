"""Offline, frozen-encoder Cell head training. Never writes outcome/authority.

Requires torch and transformers separately. All model inputs MUST be local,
content-pinned snapshots; no automatic network downloads or trust_remote_code.
"""

import argparse
import hashlib
import json
import math
import os
import platform
import random
import sys
import time
from pathlib import Path
from collections import OrderedDict

from study import load_jsonl, quantile, validate_dataset


MODEL_KEYS = {"mmbert_small", "mmbert_base", "modernbert_base", "jina_zh", "bge_small_zh"}
REPRESENTATIONS = {"joint", "sentence_cache", "landmarks", "cross_attention"}
HEADS = {"linear", "film", "rank8", "rank16", "mlp", "swiglu"}
BUDGETS = {2048, 16384, 65536, 262144}


def snapshot_digest(folder):
    """Hash relative names, lengths and file contents (including symlink targets)."""
    root = Path(folder).resolve()
    if not root.is_dir():
        raise ValueError("model snapshot must be a local directory")
    h = hashlib.sha256()
    files = sorted(p for p in root.rglob("*") if p.is_file())
    if not files:
        raise ValueError("empty model snapshot")
    for item in files:
        if not item.resolve().is_relative_to(root):
            raise ValueError("model snapshot contains escaping symlink")
        name = item.relative_to(root).as_posix().encode("utf-8")
        h.update(len(name).to_bytes(8, "big"))
        h.update(name)
        h.update(item.stat().st_size.to_bytes(8, "big"))
        with item.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                h.update(chunk)
    return h.hexdigest()


def select_shots(rows, per_class, seed):
    classes = sorted({r["label"] for r in rows})
    picked = []
    globally_used_groups = set()
    for label in classes:
        pool = [r for r in rows if r["label"] == label]
        pool.sort(key=lambda r: hashlib.sha256(f"{seed}:{r['source_group']}:{r['sample_id']}".encode()).hexdigest())
        groups = set()
        for row in pool:
            if row["source_group"] in globally_used_groups:
                continue
            groups.add(row["source_group"])
            globally_used_groups.add(row["source_group"])
            picked.append(row)
            if len(groups) >= per_class:
                break
        if len(groups) < per_class:
            raise ValueError(f"insufficient independent train groups for class {label}")
    return picked


def build_head(torch, input_dim, classes, kind, budget):
    from torch import nn

    class FiLM(nn.Module):
        def __init__(self):
            super().__init__()
            self.gamma = nn.Parameter(torch.ones(input_dim))
            self.beta = nn.Parameter(torch.zeros(input_dim))
            self.readout = nn.Linear(input_dim, classes)

        def forward(self, x):
            return self.readout(x * self.gamma + self.beta)

    class SwiGLU(nn.Module):
        def __init__(self, width):
            super().__init__()
            self.gate = nn.Linear(input_dim, width)
            self.value = nn.Linear(input_dim, width)
            self.readout = nn.Linear(width, classes)

        def forward(self, x):
            return self.readout(torch.nn.functional.silu(self.gate(x)) * self.value(x))

    if kind == "linear":
        head = nn.Linear(input_dim, classes)
    elif kind == "film":
        head = FiLM()
    elif kind in ("rank8", "rank16"):
        rank = int(kind.removeprefix("rank"))
        head = nn.Sequential(nn.Linear(input_dim, rank, bias=False), nn.Linear(rank, classes))
    elif kind == "mlp":
        width = max(1, (budget - classes) // (input_dim + classes + 1))
        head = nn.Sequential(nn.Linear(input_dim, width), nn.GELU(), nn.Linear(width, classes))
    elif kind == "swiglu":
        width = max(1, (budget - classes) // (2 * (input_dim + 1) + classes + 1))
        head = SwiGLU(width)
    else:
        raise ValueError("unregistered head architecture")
    count = sum(p.numel() for p in head.parameters())
    if count > budget:
        raise ValueError(f"head {kind} requires {count} params > budget {budget}; unsupported arm")
    return head, count


class FrozenEncoder:
    def __init__(self, folder, device, max_length, allow_custom_code=False,
                 max_cache_bytes=128 * 1024 * 1024):
        import torch
        from transformers import AutoModel, AutoTokenizer

        self.torch = torch
        self.device = device
        self.max_length = max_length
        self.tokenizer = AutoTokenizer.from_pretrained(
            folder, local_files_only=True, trust_remote_code=allow_custom_code)
        self.model = AutoModel.from_pretrained(
            folder, local_files_only=True, trust_remote_code=allow_custom_code).to(device).eval()
        for param in self.model.parameters():
            param.requires_grad_(False)
        self.cache = OrderedDict()
        self.cache_bytes = 0
        self.cache_limit_bytes = max_cache_bytes
        self.cache_evictions = 0
        self.cache_hits = 0
        self.encoder_invocations = 0
        self.truncations = 0

    def encode(self, text, scope):
        key = (scope, text, self.max_length)
        if key in self.cache:
            self.cache_hits += 1
            self.cache.move_to_end(key)
            return self.cache[key], True
        tokenized = self.tokenizer(text, return_tensors="pt", truncation=False)
        length = int(tokenized["attention_mask"].sum())
        if length > self.max_length:
            self.truncations += 1
            tokenized = self.tokenizer(text, return_tensors="pt", truncation=True,
                                       max_length=self.max_length)
        args = {k: v.to(self.device) for k, v in tokenized.items()}
        if self.device.startswith("cuda"):
            self.torch.cuda.synchronize()
        with self.torch.inference_mode():
            output = self.model(**args)
            states = output.last_hidden_state[0, :int(args["attention_mask"].sum())]
            states = states.float().cpu()
        if self.device.startswith("cuda"):
            self.torch.cuda.synchronize()
        self.encoder_invocations += 1
        size = states.numel() * states.element_size()
        if size <= self.cache_limit_bytes:
            while self.cache_bytes + size > self.cache_limit_bytes:
                _, evicted = self.cache.popitem(last=False)
                self.cache_bytes -= evicted.numel() * evicted.element_size()
                self.cache_evictions += 1
            self.cache[key] = states
            self.cache_bytes += size
        return states, False


def mean(states):
    return states.mean(dim=0)


def landmarks(states, k):
    import torch
    if states.shape[0] <= k:
        return states
    # Contiguous segment means preserve positional coverage at bounded memory.
    return torch.stack([states[int(i * states.shape[0] / k):int((i + 1) * states.shape[0] / k)].mean(0)
                        for i in range(k)])


def features_for_row(encoder, row, kind, k=8):
    import torch
    scope = row["scope"]
    if not isinstance(scope, str) or not scope:
        raise ValueError("scope required to isolate reused features")
    question = row["question"] + "\nOptions:\n" + "\n".join(f"{i}: {x}" for i, x in enumerate(row["options"]))
    if kind == "joint":
        hidden, cached = encoder.encode(row["state"] + "\nQuestion:\n" + question, scope)
        return mean(hidden), cached
    state, cached_s = encoder.encode(row["state"], scope)
    query, cached_q = encoder.encode(question, scope)
    q = mean(query)
    if kind == "sentence_cache":
        return torch.cat((mean(state), q)), cached_s and cached_q
    keys = landmarks(state, k)
    if kind == "landmarks":
        return torch.cat((keys.mean(0), keys.max(dim=0).values, q)), cached_s and cached_q
    if kind == "cross_attention":
        score = (q @ keys.T) / math.sqrt(q.numel())
        attended = torch.softmax(score, dim=0) @ keys
        return torch.cat((q, attended)), cached_s and cached_q
    raise ValueError("unknown representation")


def train_head(torch, head, x, y, *, steps, seed):
    torch.manual_seed(seed)
    head.train()
    optimizer = torch.optim.AdamW(head.parameters(), lr=1e-3, weight_decay=0.01)
    gen = torch.Generator().manual_seed(seed)
    for _ in range(steps):
        idx = torch.randint(x.size(0), (min(32, x.size(0)),), generator=gen)
        logits = head(x[idx])
        loss = torch.nn.functional.cross_entropy(logits, y[idx])
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
    head.eval()


def temperature_from_calibration(torch, logits, labels):
    candidates = (0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0)
    scores = [torch.nn.functional.cross_entropy(logits / t, labels).item() for t in candidates]
    return candidates[min(range(len(scores)), key=scores.__getitem__)]


def main():
    parser = argparse.ArgumentParser(description="Frozen local HF model and per-Cell head experiment")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--snapshot", required=True, help="LOCAL vetted model directory; no model hub fetch")
    parser.add_argument("--expected-snapshot-digest", required=True)
    parser.add_argument("--model-key", required=True, choices=sorted(MODEL_KEYS))
    parser.add_argument("--representation", required=True, choices=sorted(REPRESENTATIONS))
    parser.add_argument("--head", required=True, choices=sorted(HEADS))
    parser.add_argument("--budget", type=int, required=True, choices=sorted(BUDGETS))
    parser.add_argument("--shots-per-class", type=int, required=True)
    parser.add_argument("--seed", type=int, default=7347)
    parser.add_argument("--train-steps", type=int, default=100)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--allow-audited-custom-code", action="store_true")
    parser.add_argument("--export-q24", action="store_true",
                        help="export calibration-checked unsigned Q24 affine Head candidate")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.train_steps <= 0 or args.shots_per_class < 0:
        parser.error("invalid train steps or shot count")
    if args.allow_audited_custom_code and args.model_key != "jina_zh":
        parser.error("custom code exception is reserved for separately audited Jina snapshot")
    destinations = [Path(args.output), Path(args.output + ".run.json")]
    if args.export_q24:
        destinations.append(Path(args.output + ".q24.json"))
    if any(target.exists() for target in destinations):
        raise FileExistsError("append-only experiment output exists; refusing overwrite")
    require_digest = lambda d: len(d) == 64 and all(c in "0123456789abcdef" for c in d)
    if not require_digest(args.expected_snapshot_digest):
        parser.error("expected snapshot digest must be sha256 hex")
    verified = snapshot_digest(args.snapshot)
    if verified != args.expected_snapshot_digest:
        raise ValueError("snapshot digest mismatch; refusing unpinned model")
    import torch

    torch.manual_seed(args.seed)
    random.seed(args.seed)
    torch.set_num_threads(max(1, min(8, os.cpu_count() or 1)))
    torch.use_deterministic_algorithms(True)
    protocol = json.loads(Path(__file__).with_name("protocol.json").read_text(encoding="utf-8"))
    dataset_bytes = Path(args.dataset).read_bytes()
    dataset_digest = hashlib.sha256(dataset_bytes).hexdigest()
    ds = validate_dataset(list(load_jsonl(args.dataset)))
    rows = list(ds.values())
    classes = sorted({row["label"] for row in rows})
    if classes != list(range(len(classes))) or len(classes) < 2:
        raise ValueError("labels must be contiguous, fixed-width multiclass targets")
    if any(len(row["options"]) != len(classes) for row in rows):
        raise ValueError("all tasks must share output schema / class count")
    trains = [r for r in rows if r["split"] == "train"]
    cals = [r for r in rows if r["split"] == "calibration"]
    evaluated = [r for r in rows if r["split"] in {"held_out", "future_1", "future_2", "ood"}]
    if not cals or not evaluated:
        raise ValueError("independent calibration and evaluation splits required")
    selected = select_shots(trains, args.shots_per_class, args.seed) if args.shots_per_class else []
    if not selected:
        raise ValueError("zero-shot untrained Head cannot produce a trained-Cell claim; use no-change baseline")
    cpu_start = time.process_time()
    encoder = FrozenEncoder(args.snapshot, args.device,
                            protocol["model_candidates"][args.model_key]["max_tokens"],
                            allow_custom_code=args.allow_audited_custom_code,
                            max_cache_bytes=protocol["experiment_2"]["frozen_encoder_cache_max_bytes"])
    sample_features = {}
    sample_meta = {}
    feature_start = time.perf_counter()
    for row in selected + cals + evaluated:
        before = time.perf_counter_ns()
        vec, cached = features_for_row(encoder, row, args.representation,
                                       protocol["experiment_2"]["landmarks"])
        duration_ms = (time.perf_counter_ns() - before) / 1e6
        sample_features[row["sample_id"]] = vec
        sample_meta[row["sample_id"]] = {"latency_ms": duration_ms,
                                          "latency_path": "cache_hit_head" if cached else "cold_encoder"}
    feature_seconds = time.perf_counter() - feature_start
    first = selected[0]["sample_id"]
    head, count = build_head(torch, sample_features[first].numel(), len(classes), args.head, args.budget)
    x = torch.stack([sample_features[r["sample_id"]] for r in selected])
    y = torch.tensor([r["label"] for r in selected])
    start = time.perf_counter()
    train_head(torch, head, x, y, steps=args.train_steps, seed=args.seed)
    training_seconds = time.perf_counter() - start
    with torch.inference_mode():
        cal_logits = head(torch.stack([sample_features[r["sample_id"]] for r in cals]))
        cal_labels = torch.tensor([r["label"] for r in cals])
        temperature = temperature_from_calibration(torch, cal_logits, cal_labels)
        cal_conf = torch.softmax(cal_logits / temperature, -1).max(-1).values.tolist()
        threshold = quantile(cal_conf, 1 - protocol["experiment_2"]["calibration_in_domain_coverage"])
    arm = f"{args.model_key}:{args.representation}:{args.head}:{args.budget}:{args.shots_per_class}"
    q24_candidate = None
    if args.export_q24:
        from native_bridge import build_q24_head_candidate
        q24_candidate = build_q24_head_candidate(
            torch, head, args.head, verified,
            [sample_features[r["sample_id"]] for r in cals],
            max_abs_error=protocol["experiment_2"]["native_cpu_bridge"]["max_calibration_abs_logit_error"],
        )
        if q24_candidate["native_stored_coefficients"] > args.budget:
            raise ValueError("Q24 deployed tensor profile exceeds per-Cell parameter budget")
    import transformers
    source_digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    protocol_digest = hashlib.sha256(Path(__file__).with_name("protocol.json").read_bytes()).hexdigest()
    runtime_identity = {"arm": arm, "dataset_digest": dataset_digest,
                        "model_digest": verified, "train_steps": args.train_steps,
                        "seed": args.seed, "device": args.device,
                        "model_runner_source_sha256": source_digest,
                        "protocol_sha256": protocol_digest,
                        "python": platform.python_version(), "torch": torch.__version__,
                        "transformers": getattr(transformers, "__version__", "unreported")}
    run_digest = hashlib.sha256(json.dumps(runtime_identity, sort_keys=True).encode()).hexdigest()
    emitted = []
    with torch.inference_mode():
        for row in evaluated:
            sid = row["sample_id"]
            start = time.perf_counter_ns()
            proba = torch.softmax(head(sample_features[sid].unsqueeze(0)) / temperature, -1)[0]
            head_ms = (time.perf_counter_ns() - start) / 1e6
            info = sample_meta[sid]
            emitted.append({"arm": arm, "sample_id": sid, "label": row["label"],
                            "probabilities": proba.tolist(), "ood_threshold": threshold,
                            "model_digest": verified, "dataset_digest": dataset_digest,
                            "runtime_digest": run_digest, "latency_path": info["latency_path"],
                            "latency_ms": info["latency_ms"] + head_ms,
                            "head_parameters": count, "training_seconds": training_seconds,
                            "encoder_forward_calls": encoder.encoder_invocations,
                            "cache_hits": encoder.cache_hits,
                            "cache_evictions": encoder.cache_evictions,
                            "truncations": encoder.truncations,
                            "source_scope": row["scope"], "backend_kind": "offline_hf_shadow"})
    with Path(args.output).open("x", encoding="utf-8") as handle:
        for row in emitted:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    prediction_digest = hashlib.sha256(Path(args.output).read_bytes()).hexdigest()
    try:
        import psutil
        rss_after = psutil.Process().memory_info().rss
    except ImportError:
        rss_after = None
    try:
        import resource
        # POSIX ru_maxrss is a process-lifetime high water mark: KiB on
        # Linux, bytes on macOS; it is NOT a per-arm incremental peak.
        ru_maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        process_lifetime_peak_rss_bytes = (ru_maxrss * 1024 if sys.platform.startswith("linux")
                                           else ru_maxrss if sys.platform == "darwin" else None)
    except ImportError:
        process_lifetime_peak_rss_bytes = None
    process_cpu_seconds = time.process_time() - cpu_start
    result_manifest = {"schema": "hepta.stem-cell-hf-run-manifest.v1",
                       "shadow_only": True, "production_authorized": False,
                       **runtime_identity, "run_digest": run_digest,
                       "predictions_sha256": prediction_digest, "training_examples": len(selected),
                       "calibration_examples": len(cals), "evaluation_examples": len(evaluated),
                       "head_parameters": count,
                       "encoder_parameters": sum(p.numel() for p in encoder.model.parameters()),
                       "feature_seconds": feature_seconds, "training_seconds": training_seconds,
                       "encoder_forward_calls": encoder.encoder_invocations,
                       "cache_hits": encoder.cache_hits,
                       "cache_evictions": encoder.cache_evictions,
                       "cache_bytes_after": encoder.cache_bytes,
                       "cache_bytes_limit": encoder.cache_limit_bytes,
                       "truncations": encoder.truncations,
                       "process_rss_after_bytes": rss_after,
                       "process_lifetime_peak_rss_bytes": process_lifetime_peak_rss_bytes,
                       "cpu_process_seconds": process_cpu_seconds,
                       "cpu_measurement_scope": "whole_process_since_first_encoder_load_not_hardware_total",
                       "cuda_peak_allocated_bytes": (torch.cuda.max_memory_allocated() if args.device.startswith("cuda") else None),
                       "measurement_warning": "HF standalone no native Hepta batch or independent NDU outcome receipt"}
    if q24_candidate is not None:
        from native_bridge import write_q24_head_candidate
        q24_candidate.update({"arm": arm, "dataset_digest": dataset_digest,
                              "source_run_digest": run_digest,
                              "calibration_source": "calibration_fold_only"})
        q24_digest = write_q24_head_candidate(args.output + ".q24.json", q24_candidate)
        result_manifest["native_q24_shadow_artifact_sha256"] = q24_digest
        result_manifest["native_q24_width"] = q24_candidate["input_width"]
        result_manifest["native_q24_stored_coefficients"] = q24_candidate["native_stored_coefficients"]
    with Path(args.output + ".run.json").open("x", encoding="utf-8") as manifest_handle:
        manifest_handle.write(json.dumps(result_manifest, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"arm": arm, "rows": len(emitted), "head_parameters": count,
                      "encoder_forward_calls": encoder.encoder_invocations,
                      "cache_hits": encoder.cache_hits, "cache_evictions": encoder.cache_evictions,
                      "truncations": encoder.truncations,
                      "training_seconds": training_seconds, "model_digest": verified,
                      "production_authorized": False}, sort_keys=True))


if __name__ == "__main__":
    main()
