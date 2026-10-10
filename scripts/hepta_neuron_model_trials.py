#!/usr/bin/env python3
"""Offline, shadow-only Hepta Neuron model comparison. Never selects an artifact."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import statistics
import sys
import time
from pathlib import Path

SCHEMA = "hepta.neuron.model-trial.v1"
SPLITS = ("train", "calibration", "holdout", "future_1", "future_2")
EVAL_SPLITS = SPLITS[2:]
ARMS = {
    "decisions": ("laya", "typed"),
    "multilingual": ("laya", "multilingual"),
    "heads": ("linear", "mlp", "swiglu"),
}
MODEL_IDS = {
    "laya": "convaiinnovations/laya",
    "typed": "convaiinnovations/laya-typed-decisions",
    "multilingual": "convaiinnovations/laya-multilingual",
}
Q24 = 1 << 24


class InvalidTrial(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise InvalidTrial(message)


def is_sha(value, length=64):
    return isinstance(value, str) and len(value) == length and all(c in "0123456789abcdef" for c in value)


def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha_tree(root, only_python=False):
    """Bind tokenizer, config, head and encoder files; reject escaping links."""
    root = Path(root).resolve(strict=True)
    h = hashlib.sha256()
    paths = sorted(x for x in root.rglob("*") if x.is_file() and
                   (not only_python or x.suffix == ".py"))
    require(bool(paths), "empty model/SDK artifact")
    for path in paths:
        require(not path.is_symlink() and path.resolve().is_relative_to(root), "symlink in artifact")
        name = path.relative_to(root).as_posix().encode("utf-8")
        h.update(len(name).to_bytes(4, "big") + name)
        h.update(bytes.fromhex(sha_file(path)))
    return h.hexdigest()


def write_new(path, data):
    payload = (json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode()
    with open(path, "xb") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_inputs(manifest_file, dataset_file):
    manifest = read_json(manifest_file)
    require(manifest.get("schema") == SCHEMA and manifest.get("family") in ARMS, "invalid manifest")
    require(is_sha(manifest.get("source_sha"), 40), "source SHA must be a pinned Git commit")
    require(is_sha(manifest.get("dataset_sha256")), "dataset SHA missing")
    require(sha_file(dataset_file) == manifest["dataset_sha256"], "dataset changed after freezing")
    require(is_sha(manifest.get("host_profile_digest")), "host profile missing")
    require(type(manifest.get("parameter_cap")) is int and manifest["parameter_cap"] > 0, "parameter cap missing")
    rows = []
    ids, source_splits = set(), {}
    with open(dataset_file, encoding="utf-8") as f:
        for raw in f:
            if not raw.strip():
                continue
            row = json.loads(raw)
            require(isinstance(row, dict), "invalid row")
            cid, split, group = row.get("id"), row.get("split"), row.get("source_group")
            require(isinstance(cid, str) and cid and cid not in ids, "duplicate or empty case id")
            require(split in SPLITS and isinstance(group, str) and group, "missing split/source group")
            require(group not in source_splits or source_splits[group] == split,
                    "source group leaked between splits")
            source_splits[group] = split
            ids.add(cid)
            require(type(row.get("observed_at_ms")) is int and row["observed_at_ms"] > 0,
                    "missing event observation timestamp")
            if manifest["family"] == "heads":
                h = manifest.get("head", {})
                d, w = h.get("input_dimension"), h.get("state_width")
                require(type(d) is int and 1 <= d <= 512 and type(w) is int and 5 <= w <= 256,
                        "invalid head dimensions")
                for field, size in (("features_q24", d), ("target_q24", 2 * w)):
                    values = row.get(field)
                    require(isinstance(values, list) and len(values) == size and
                            all(type(v) is int and abs(v) <= 8 * Q24 for v in values),
                            f"invalid {field} for {cid}")
            else:
                q = row.get("question", {})
                require(isinstance(row.get("state"), (str, dict, list)) and
                        isinstance(q, dict) and q.get("type") == "choice" and
                        isinstance(q.get("instructions"), str) and
                        isinstance(q.get("criteria"), dict) and
                        2 <= len(q["criteria"]) <= 20 and
                        all(isinstance(v, str) for v in q["criteria"].values()) and
                        row.get("gold") in q["criteria"], "invalid choice task")
                require(isinstance(row.get("language"), str) and row["language"] and
                        isinstance(row.get("domain"), str) and row["domain"] and
                        type(row.get("is_ood")) is bool, "missing cohort/OOD facts")
            rows.append(row)
    require(bool(rows) and all(any(r["split"] == s for r in rows) for s in SPLITS),
            "train/calibration/holdout/two future windows are required")
    if manifest["family"] == "multilingual":
        require(all({"en", "zh", "cross"} <= {r["language"] for r in rows if r["split"] == split}
                    for split in EVAL_SPLITS), "each window needs English, Chinese and cross-lingual tasks")
    if manifest["family"] != "heads":
        require(all(any(r["is_ood"] for r in rows if r["split"] == split) for split in EVAL_SPLITS),
                "each evaluation window needs real held-out OOD cases")
    # A future window must be observed after the earlier window, not merely relabeled.
    maxima = {s: max(r["observed_at_ms"] for r in rows if r["split"] == s) for s in SPLITS}
    minima = {s: min(r["observed_at_ms"] for r in rows if r["split"] == s) for s in SPLITS}
    require(all(maxima[a] < minima[b] for a, b in zip(SPLITS, SPLITS[1:])),
            "time windows overlap or are out of order")
    return manifest, rows


def parameter_budget(d, w):
    out = 2 * w
    cap = d * out + out
    mlp_h = (cap - out) // (d + out + 1)
    swiglu_h = (cap - out) // (2 * d + out + 2)
    require(mlp_h > 0 and swiglu_h > 0, "dimensions too small for matched heads")
    return {"linear": cap, "mlp": mlp_h * (d + out + 1) + out,
            "swiglu": swiglu_h * (2 * d + out + 2) + out}, {"mlp": mlp_h, "swiglu": swiglu_h}


def peak_rss_bytes():
    try:
        with open("/proc/self/status", encoding="ascii") as f:
            for line in f:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return None


def hardware():
    return {"system": platform.platform(), "python": sys.version.split()[0],
            "pid": os.getpid(), "monotonic_clock": "perf_counter_ns"}


def run_laya(manifest, rows, arm, artifact_dir, weights_file, device, sdk_digest):
    require(arm in MODEL_IDS and arm in ARMS[manifest["family"]], "wrong Laya arm")
    model = manifest.get("models", {}).get(arm, {})
    require(model.get("model_id") == MODEL_IDS[arm] and is_sha(model.get("revision"), 40),
            "unpinned model identity/revision")
    require(is_sha(model.get("weights_sha256")) and is_sha(model.get("artifact_tree_sha256"))
            and is_sha(sdk_digest), "weight/artifact/SDK pin absent")
    root = Path(artifact_dir).resolve(strict=True)
    weight = (root / weights_file).resolve(strict=True)
    require(weight.is_relative_to(root) and weight.is_file() and weight.name.endswith(".safetensors"),
            "weights must be contained safetensors")
    require(sha_file(weight) == model["weights_sha256"], "model weight bytes mismatch")
    require(sha_tree(root) == model["artifact_tree_sha256"], "model artifact tree mismatch")
    require((root / "encoder" / "config.json").is_file() and (root / "tokenizer").is_dir(),
            "complete offline encoder/tokenizer must be present")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import laya  # optional: physically installed on the target host
    import torch
    require(sha_tree(Path(laya.__file__).parent, only_python=True) == sdk_digest,
            "Laya installed SDK tree does not match pin")
    agent = laya.load(str(root), device=device)
    nparams = sum(p.numel() for p in agent.model.parameters())
    require(nparams <= manifest["parameter_cap"], "actual model exceeds size cap")
    require(str(agent.device) == device, "unexpected physical model device")
    # Shared text, option ordering and max_len; different tokenizers still reported separately.
    max_len = manifest.get("max_len")
    require(type(max_len) is int and max_len == 512, "must use common 512-token cap")
    require(type(agent.cfg.get("max_len")) is int and agent.cfg["max_len"] >= max_len,
            "model cannot support common context cap")
    native_context = agent.cfg["max_len"]
    agent.cfg["max_len"] = max_len
    native_head = agent.cfg.get("head_max_len", 192)
    require(type(native_head) is int and native_head >= 192, "incompatible option budget")
    agent.cfg["head_max_len"] = 192
    observations = []
    for row in rows:
        if row["split"] not in EVAL_SPLITS:
            continue
        start = time.perf_counter_ns()
        result = agent.predict(row["state"], {"q": row["question"]})
        if str(agent.device) != device:
            raise InvalidTrial("model silently moved device during execution")
        elapsed = (time.perf_counter_ns() - start) / 1e6
        probs = result["answers"]["q"]["probabilities"]
        keys = list(row["question"]["criteria"])
        require(list(probs) == keys, "candidate order was altered")
        p = [probs[k] for k in keys]
        require(all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in p)
                and abs(sum(p) - 1) <= 0.001, "invalid probability distribution")
        observations.append({"id": row["id"], "split": row["split"],
                             "probabilities": p, "latency_ms": elapsed,
                             "input_tokens": result["usage"]["input_tokens"]})
    return nparams, model["weights_sha256"], observations, {"torch": torch.__version__,
        "sdk_tree_sha256": sdk_digest, "artifact_tree_sha256": model["artifact_tree_sha256"],
        "weights_file": str(weight), "native_context": native_context, "native_head_budget": native_head,
        "effective_context": max_len, "effective_head_budget": 192}
