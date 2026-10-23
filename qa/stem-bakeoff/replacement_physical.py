"""Pinned five-arm CPU shadow execution, never a model qualification receipt.

Real Laya arms execute their COMPLETE typed policy. Arctic/Harrier execute
frozen encoders and learn equally budgeted TASK-ONLY linear heads. Historical
UCI data is not an independent prospective or multilingual acceptance set.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time

from prepare_news_cohorts import load_cohorts, sha
from replacement_gate import EXPECTED, SPLITS, score_rows, validate_registry
from replacement_laya_view import guard_laya_originals, load_laya_cpu_isolated

LAYA_SOURCE_REVISION = "c7527708f9f5220c669d8aa385077cd28d04708a"
CATEGORIES = ("business", "entertainment", "medicine and health", "science and technology")
POOLING = {"arctic_305m": "cls", "harrier_270m": "last_token"}
TRAIN_STEPS = 200
TRAIN_SEED = 7
TRAIN_RATE = 0.05
TEMPERATURES = (0.5, 1.0, 2.0, 4.0)


def file_sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("model artifact must be an ordinary file, not a symlink")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def verify_checkpoint(name: str, spec: dict, snapshot: Path) -> dict:
    """Hash the actual model bytes, not a Hub manifest or claimed digest."""
    if name not in EXPECTED or not snapshot.is_dir() or snapshot.is_symlink():
        raise ValueError("unregistered arm or invalid local snapshot")
    weights = snapshot / spec["weight_file"]
    if not weights.exists() or weights.stat().st_size == 0 or file_sha256(weights) != spec["weight_sha256"]:
        raise ValueError("physical checkpoint weight bytes differ from pinned SHA256")
    # No root config.json on the publisher's pinned typed-decisions revision.
    # Laya requires a complete typed-policy artifact, not a generic HF
    # AutoModel root config; Encoder-only arms have a different schema.
    if name.startswith("laya_"):
        required = ("rl_agent_config.json", "encoder/config.json", "tokenizer/tokenizer.json")
    else:
        required = ("config.json", "tokenizer.json")
    for rel in required:
        item = snapshot / rel
        if item.is_symlink() or not item.is_file() or not item.stat().st_size:
            raise ValueError(f"physical checkpoint missing regular {rel}")
    return {"repository": spec["repository"], "revision": spec["revision"],
            "loaded_weight_sha256": file_sha256(weights),
            "weight_bytes": weights.stat().st_size,
            "component_sha256": {rel: file_sha256(snapshot / rel) for rel in required}}


def verify_laya_source(root: Path) -> None:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("pinned Laya source checkout required")
    got = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                         capture_output=True, text=True, timeout=15, check=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
                           capture_output=True, text=True, timeout=15, check=True).stdout.strip()
    if got != LAYA_SOURCE_REVISION or dirty:
        raise ValueError("Laya source revision or worktree does not match immutable source pin")
    for name in ("laya/__init__.py", "laya/common.py", "laya/agent.py"):
        if not (root / name).is_file():
            raise ValueError(f"pinned Laya package missing {name}")


def choose_rows(cohorts: dict, per_split: int) -> dict:
    if type(per_split) is not int or (per_split != 0 and
                                     (per_split < 8 or per_split > 128 or per_split % 4)):
        raise ValueError("sample must be full or 8..128 rows per cohort, divisible by four")
    out = {}
    for name in SPLITS:
        src = cohorts[name]
        if per_split == 0:
            out[name] = src
        else:
            quota = per_split // 4
            groups = [[row for row in src if row["label"] == k][:quota] for k in range(4)]
            if any(len(x) != quota for x in groups):
                raise ValueError(f"insufficient independent {name} examples")
            out[name] = sorted((row for part in groups for row in part),
                               key=lambda r: (r["timestamp_ms"], r["source_id"]))
    return out


def configure_arctic_cpu(config) -> dict:
    """Disable pinned GTE xFormers/unpadding on the CPU-only shadow host.

    Do not silently change a new publisher config: this override is a
    separately measured compatibility profile, not the original performance
    profile or a production-qualified equivalent.
    """
    flags = {}
    for key in ("use_memory_efficient_attention", "unpad_inputs"):
        raw = getattr(config, key, None)
        if raw not in (True, False, "true", "false") or type(raw) not in (str, bool):
            raise ValueError(f"unexpected pinned Arctic {key} profile")
        flags[key] = raw
        setattr(config, key, False)
    if any(getattr(config, key) is not False for key in flags):
        raise ValueError("Arctic CPU attention override did not apply")
    return flags


def tensor_digest(module) -> str:
    import torch
    d = hashlib.sha256()
    for key, value in sorted(module.state_dict().items()):
        t = value.detach().cpu().contiguous()
        d.update(json.dumps([key, list(t.shape), str(t.dtype)], separators=(",", ":")).encode())
        d.update(memoryview(t.view(torch.uint8).numpy()))
    return d.hexdigest()


def train_task_head(train_features, train_labels, calib_features, calib_labels):
    """Exactly the same task-head family, initialization and update budget."""
    import torch
    import torch.nn.functional as F
    torch.manual_seed(TRAIN_SEED)
    width = train_features.shape[1]
    head = torch.nn.Linear(width, 4).to(dtype=torch.float32)
    initial = tensor_digest(head)
    opt = torch.optim.AdamW(head.parameters(), lr=TRAIN_RATE, weight_decay=0.0)
    for _ in range(TRAIN_STEPS):
        opt.zero_grad(set_to_none=True)
        loss = F.cross_entropy(head(train_features), train_labels)
        if not torch.isfinite(loss):
            raise ValueError("nonfinite real Head training loss")
        loss.backward()
        opt.step()
    head.eval()
    for param in head.parameters():
        param.requires_grad_(False)
    with torch.no_grad():
        logits = head(calib_features)
        losses = [float(F.cross_entropy(logits / temp, calib_labels)) for temp in TEMPERATURES]
        temperature = TEMPERATURES[min(range(len(TEMPERATURES)), key=lambda i: (losses[i], i))]
    return head, temperature, {"head_initial_sha256": initial,
                               "head_trained_sha256": tensor_digest(head),
                               "head_parameters": sum(p.numel() for p in head.parameters()),
                               "optimizer": "AdamW", "seed": TRAIN_SEED, "steps": TRAIN_STEPS,
                               "learning_rate": TRAIN_RATE, "calibration_temperature": temperature,
                               "calibration_nll_grid": dict(zip(map(str, TEMPERATURES), losses))}


def _rss_bytes() -> int | None:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def run(name: str, registry: dict, snapshot: Path, cohorts_dir: Path, archive: Path,
        laya_source: Path | None, per_split: int) -> dict:
    import torch
    import torch.nn.functional as F
    if validate_registry(registry):
        raise ValueError("invalid exact model registry")
    if name not in EXPECTED:
        raise ValueError("unknown candidate")
    torch.set_num_threads(2)
    spec = registry["models"][name]
    physical = verify_checkpoint(name, spec, snapshot)
    manifest, all_rows = load_cohorts(cohorts_dir, archive=archive)
    rows = choose_rows(all_rows, per_split)
    dataset = sha(json.dumps({k: [(r["source_id"], r["source_row_sha256"], r["label"])
                                  for r in v] for k, v in rows.items()},
                             sort_keys=True, separators=(",", ":")).encode())
    observed = {key: [] for key in SPLITS}
    latency = []
    loaded_at = time.perf_counter()
    before_rss = _rss_bytes()
    training = None
    arctic_cpu_flags = None
    laya_tokenizer_compat = None
    counters = [0]
    if name.startswith("laya_"):
        if laya_source is None:
            raise ValueError("pinned Laya source is mandatory for full-policy execution")
        verify_laya_source(laya_source)
        sys.path.insert(0, str(laya_source))
        from laya.agent import Agent
        with guard_laya_originals(snapshot):
            agent, laya_tokenizer_compat = load_laya_cpu_isolated(snapshot, Agent)
            if laya_tokenizer_compat["original_weight_sha256"] != physical["loaded_weight_sha256"]:
                raise ValueError("Laya original-weight view identity differs from publisher pin")
            if agent.device.type != "cpu":
                raise ValueError("unapproved Laya execution device fallback")
            handle = agent.model.register_forward_hook(lambda *_: counters.__setitem__(0, counters[0] + 1))
            load_ms = (time.perf_counter() - loaded_at) * 1000
            try:
                for split in SPLITS:
                    for row in rows[split]:
                        start = time.perf_counter()
                        result = agent.system_one(row["text"], {"category": {
                            "type": "choice", "instructions": "Classify this news headline by subject.",
                            "criteria": dict.fromkeys(CATEGORIES)}})
                        latency.append((time.perf_counter() - start) * 1000)
                        choice = result["answers"]["category"]
                        p = [choice["probabilities"][label] for label in CATEGORIES]
                        total = sum(p)
                        if not all(math.isfinite(v) and 0 <= v <= 1 for v in p) or total <= 0:
                            raise ValueError("invalid real Laya typed policy distribution")
                        observed[split].append([v / total for v in p])
            finally:
                handle.remove()
            if counters[0] != sum(map(len, rows.values())):
                raise ValueError("expected exactly one complete typed DecisionModel forward per example")
            loaded_parameters = sum(p.numel() for p in agent.model.parameters())
            kind = "full_policy"
    else:
        from transformers import AutoConfig, AutoModel, AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(snapshot, local_files_only=True, trust_remote_code=False)
        model_kwargs = {"local_files_only": True, "trust_remote_code": False,
                        "output_loading_info": True, "dtype": torch.float32}
        if name == "arctic_305m":
            # This pinned public GTE checkpoint ships custom modeling/config code.
            # Execute only in the unprivileged, no-secret research worker. Code audit
            # and native-runtime conformance remain separate production blockers.
            model_kwargs["trust_remote_code"] = True
            model_kwargs["add_pooling_layer"] = False
            cpu_config = AutoConfig.from_pretrained(
                snapshot, local_files_only=True, trust_remote_code=True)
            arctic_cpu_flags = configure_arctic_cpu(cpu_config)
            model_kwargs["config"] = cpu_config
        encoder, loading_info = AutoModel.from_pretrained(snapshot, **model_kwargs)
        if name == "arctic_305m" and (
                encoder.config.use_memory_efficient_attention is not False
                or encoder.config.unpad_inputs is not False):
            raise ValueError("pinned Arctic CPU model re-enabled unsupported attention profile")
        if loading_info.get("missing_keys") or loading_info.get("mismatched_keys"):
            raise ValueError("real frozen Encoder has missing or mismatched checkpoint tensors")
        encoder.requires_grad_(False).eval()
        handle = encoder.register_forward_hook(lambda *_: counters.__setitem__(0, counters[0] + 1))
        load_ms = (time.perf_counter() - loaded_at) * 1000
        raw_features = {}
        try:
            with torch.no_grad():
                for split in SPLITS:
                    vectors = []
                    for row in rows[split]:
                        inputs = tokenizer(row["text"], truncation=True, max_length=192,
                                           return_tensors="pt")
                        if not 0 < inputs["input_ids"].shape[1] <= 192:
                            raise ValueError("invalid bounded tokenizer output")
                        start = time.perf_counter()
                        result = encoder(**inputs)
                        latency.append((time.perf_counter() - start) * 1000)
                        tokens = result.last_hidden_state
                        pooled = tokens[:, 0] if POOLING[name] == "cls" else tokens[:, -1]
                        vec = F.normalize(pooled.float(), dim=-1)[0].cpu()
                        if not torch.isfinite(vec).all():
                            raise ValueError("nonfinite real embedding")
                        vectors.append(vec)
                    raw_features[split] = torch.stack(vectors)
        finally:
            handle.remove()
        if counters[0] != sum(map(len, rows.values())):
            raise ValueError("expected one actual frozen Encoder forward per example")
        labels = {k: torch.tensor([r["label"] for r in v], dtype=torch.long) for k, v in rows.items()}
        head, temperature, training = train_task_head(
            raw_features["train"], labels["train"], raw_features["calibration"], labels["calibration"])
        with torch.no_grad():
            for split in SPLITS:
                observed[split] = F.softmax(head(raw_features[split]) / temperature, dim=-1).tolist()
        loaded_parameters = sum(p.numel() for p in encoder.parameters())
        kind = "encoder_plus_new_task_head"
    expected_count = sum(map(len, rows.values()))
    scored = {}
    for split in SPLITS:
        batch = [dict(source_id=r["source_id"], source_group_id=r["source_group_id"],
                      label=r["label"], probabilities=list(map(float, prob)),
                      is_ood=split == "ood", language="en")
                 for r, prob in zip(rows[split], observed[split], strict=True)]
        scored[split] = {"metrics": score_rows(batch), "rows": batch}
    if len(latency) != expected_count:
        raise ValueError("lost real per-row inference samples")
    result = {"schema": "hepta.neuron.replacement-physical-shadow.v1", "candidate": name,
              "checkpoint": physical, "loaded_parameter_count": loaded_parameters,
              "execution_kind": kind, "observed_forward_calls": counters[0],
              "source_archive_sha256": manifest["source_archive_sha256"],
              "frozen_selected_rows_sha256": dataset, "per_split_limit": per_split,
              "scores": scored, "head_training": training,
              "performance": {"device": "cpu", "host": platform.platform(),
                              "runtime": torch.__version__, "arctic_cpu_override": arctic_cpu_flags,
                              "laya_tokenizer_compat": laya_tokenizer_compat,
                              "rss_after_bytes": _rss_bytes(),
                              "rss_before_bytes": before_rss,
                              "load_ms": load_ms, "original_forward_latency_ms": latency,
                              "forward_count": len(latency),
                              "forward_latency_p50_ms": statistics.median(latency),
                              "raw_forward_throughput_per_second":
                                  len(latency) / max(sum(latency) / 1000, 1e-9)},
              "limits": {"historical_2014_dataset": True, "multilingual_quality_measured": False,
                         "retrieval_quality_measured": False, "prospective_holdout": False,
                         "target_device_qualified": False, "full_policy_retrained_equal_budget": False,
                         "independent_observer_attested": False},
              "mode": "SHADOW_ONLY", "authority": "DENY_ALL",
              "production_activation_allowed": False}
    if verify_checkpoint(name, spec, snapshot) != physical:
        raise ValueError("checkpoint weight/config/tokenizer bytes drifted during experiment")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", choices=EXPECTED, required=True)
    parser.add_argument("--registry", default=str(Path(__file__).with_name("replacement_models.json")))
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--cohorts", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--laya-source", type=Path)
    parser.add_argument("--rows-per-split", type=int, default=8)
    parser.add_argument("--operator-accepted-terms", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.operator_accepted_terms:
        parser.error("independent operator must accept the exact upstream model terms")
    result = run(args.candidate, json.loads(Path(args.registry).read_text()), args.snapshot,
                 args.cohorts, args.archive, args.laya_source, args.rows_per_split)
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(result, out, sort_keys=True, indent=2, allow_nan=False)
        out.write("\n")
    print(json.dumps({"candidate": args.candidate,
                      "forward_calls": result["observed_forward_calls"],
                      "raw_output": str(args.output), "production_activation_allowed": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
