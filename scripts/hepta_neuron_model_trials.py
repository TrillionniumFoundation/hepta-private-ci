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
import subprocess
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
    return (isinstance(value, str) and len(value) == length and
            any(c != "0" for c in value) and all(c in "0123456789abcdef" for c in value))


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


def verify_checkout(expected_sha):
    result = subprocess.run(["git", "rev-parse", "HEAD"],
                            cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, check=False)
    require(result.returncode == 0 and result.stdout.strip() == expected_sha,
            "source checkout differs from frozen manifest")


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
                require(type(d) is int and 1 <= d <= 512 and type(w) is int and 5 <= w <= 256 and
                        is_sha(h.get("encoder_digest")),
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
    require(sha_tree(root) == model["artifact_tree_sha256"],
            "model artifact was mutated during execution")
    return nparams, model["weights_sha256"], observations, {"torch": torch.__version__,
        "sdk_tree_sha256": sdk_digest, "artifact_tree_sha256": model["artifact_tree_sha256"],
        "weights_file": str(weight), "native_context": native_context, "native_head_budget": native_head,
        "effective_context": max_len, "effective_head_budget": 192}


def make_head(torch, arm, d, out, hidden):
    nn = torch.nn
    if arm == "linear":
        return nn.Linear(d, out)
    if arm == "mlp":
        return nn.Sequential(nn.Linear(d, hidden["mlp"]), nn.GELU(), nn.Linear(hidden["mlp"], out))
    if arm == "swiglu":
        class SwiGLU(nn.Module):
            def __init__(self):
                super().__init__()
                self.gate = nn.Linear(d, hidden["swiglu"])
                self.value = nn.Linear(d, hidden["swiglu"])
                self.readout = nn.Linear(hidden["swiglu"], out)

            def forward(self, x):
                return self.readout(torch.nn.functional.silu(self.gate(x)) * self.value(x))
        return SwiGLU()
    raise InvalidTrial("unknown head")


def run_head(manifest, rows, arm, device, artifact_out):
    require(arm in ARMS["heads"] and manifest["family"] == "heads", "wrong head arm")
    import torch
    from safetensors.torch import save_file
    h = manifest["head"]
    d, w = h["input_dimension"], h["state_width"]
    expected, hidden = parameter_budget(d, w)
    require(manifest["parameter_cap"] == expected["linear"], "head cap must equal linear baseline")
    require(expected[arm] >= .99 * manifest["parameter_cap"], "candidate too small for matched budget")
    require(all(type(h.get(k)) is int and h[k] > 0 for k in ("seed", "epochs", "batch_size")),
            "training configuration is incomplete")
    require(type(h.get("learning_rate")) in (float, int) and 0 < h["learning_rate"] <= .1,
            "invalid learning rate")
    torch.manual_seed(h["seed"])
    torch.use_deterministic_algorithms(True)
    if device.startswith("cuda"):
        torch.cuda.manual_seed_all(h["seed"])
    network = make_head(torch, arm, d, 2 * w, hidden).to(device)
    nparams = sum(p.numel() for p in network.parameters())
    require(nparams == expected[arm] and nparams <= manifest["parameter_cap"], "parameter mismatch")
    train = [r for r in rows if r["split"] == "train"]
    x = torch.tensor([r["features_q24"] for r in train], dtype=torch.float32, device=device) / Q24
    y = torch.tensor([r["target_q24"] for r in train], dtype=torch.float32, device=device) / Q24
    opt = torch.optim.AdamW(network.parameters(), lr=h["learning_rate"], weight_decay=0.01)
    network.train()
    start_training = time.perf_counter()
    for epoch in range(h["epochs"]):
        generator = torch.Generator().manual_seed(h["seed"] + epoch)
        order = torch.randperm(len(train), generator=generator).tolist()
        for start in range(0, len(order), h["batch_size"]):
            ids = order[start:start + h["batch_size"]]
            opt.zero_grad(set_to_none=True)
            loss = torch.nn.functional.mse_loss(network(x[ids]), y[ids])
            require(bool(torch.isfinite(loss)), "nonfinite training loss")
            loss.backward()
            opt.step()
    if device.startswith("cuda"):
        torch.cuda.synchronize()
    training_seconds = time.perf_counter() - start_training
    network.eval()
    save_path = Path(artifact_out)
    require(save_path.is_absolute() and not save_path.exists() and save_path.suffix == ".safetensors",
            "new absolute safetensors path required")
    save_file({k: v.detach().cpu().contiguous() for k, v in network.state_dict().items()}, str(save_path))
    weight_sha = sha_file(save_path)
    observations = []
    with torch.no_grad():
        for row in rows:
            if row["split"] not in EVAL_SPLITS:
                continue
            start = time.perf_counter_ns()
            values = torch.tensor(row["features_q24"], dtype=torch.float32, device=device).unsqueeze(0) / Q24
            result = network(values).clamp(-8, 8)
            if device.startswith("cuda"):
                torch.cuda.synchronize()
            elapsed = (time.perf_counter_ns() - start) / 1e6
            pred = torch.round(result.cpu()[0] * Q24).to(torch.int64).tolist()
            observations.append({"id": row["id"], "split": row["split"],
                                 "prediction_q24": pred, "latency_ms": elapsed})
    return nparams, weight_sha, observations, {"torch": torch.__version__,
                                                "training_seconds": training_seconds,
                                                "optimizer": "AdamW", "weight_decay": .01,
                                                "head_profile_sha256": hashlib.sha256(
                                                    json.dumps(h, sort_keys=True).encode()).hexdigest()}


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(fraction * len(values)) - 1)]


def metrics(rows, observations, family):
    by_id = {r["id"]: r for r in rows if r["split"] in EVAL_SPLITS}
    require(len(observations) == len(by_id) and len({x["id"] for x in observations}) == len(by_id),
            "missing or duplicate prediction")
    summary = {}
    for split in EVAL_SPLITS:
        batch = []
        for item in observations:
            require(item["id"] in by_id and item["split"] == by_id[item["id"]]["split"],
                    "prediction identity/split drift")
            if item["split"] == split:
                batch.append((by_id[item["id"]], item))
        require(bool(batch), "missing evaluation window")
        latencies = [b["latency_ms"] for _, b in batch]
        require(all(type(t) in (int, float) and math.isfinite(t) and t >= 0 for t in latencies),
                "invalid latency sample")
        result = {"count": len(batch), "p50_ms": percentile(latencies, .5),
                  "p95_ms": percentile(latencies, .95), "p99_ms": percentile(latencies, .99)}
        if family != "heads":
            bs, correct, bins, accepted, ood_count = [], [], [[] for _ in range(10)], 0, 0
            for source, pred in batch:
                keys = list(source["question"]["criteria"])
                p = pred["probabilities"]
                require(isinstance(p, list) and len(p) == len(keys) and
                        all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in p)
                        and abs(sum(p) - 1) <= .001, "invalid probabilities")
                p = [v / sum(p) for v in p]
                label = keys.index(source["gold"])
                bs.append(sum((v - (i == label)) ** 2 for i, v in enumerate(p)))
                choice = max(range(len(p)), key=p.__getitem__)
                win = int(choice == label)
                correct.append(win)
                confidence = max(p)
                bins[min(9, int(confidence * 10))].append((confidence, win))
                if source["is_ood"]:
                    ood_count += 1
                    accepted += int(confidence >= .8)
            cohort_scores = {}
            for field in ("language", "domain"):
                labels = sorted({source[field] for source, _ in batch})
                cohort_scores[field] = {
                    label: {
                        "count": sum(source[field] == label for source, _ in batch),
                        "accuracy": statistics.mean(int(max(range(len(pred["probabilities"])),
                               key=pred["probabilities"].__getitem__) ==
                               list(source["question"]["criteria"]).index(source["gold"]))
                               for source, pred in batch if source[field] == label),
                    } for label in labels
                }
            result.update({"cohorts": cohort_scores,
                           "accuracy": statistics.mean(correct), "brier_multiclass": statistics.mean(bs),
                           "ece10": sum(len(b) * abs(statistics.mean(x for x, _ in b) -
                                                      statistics.mean(y for _, y in b)) for b in bins if b) / len(batch),
                           "ood_samples": ood_count,
                           "ood_false_accept_at_0_8": accepted / ood_count if ood_count else None})
        else:
            squares, absolute = [], []
            for source, pred in batch:
                p = pred["prediction_q24"]
                require(isinstance(p, list) and len(p) == len(source["target_q24"]) and
                        all(type(v) is int and abs(v) <= 8 * Q24 for v in p), "invalid q24 output")
                for a, b in zip(p, source["target_q24"]):
                    delta = (a - b) / Q24
                    squares.append(delta * delta)
                    absolute.append(abs(delta))
            result.update({"mse": statistics.mean(squares), "mae": statistics.mean(absolute)})
        summary[split] = result
    return summary


def compare(manifest, rows, packets, baseline_sha):
    family = manifest["family"]
    require(set(packets) == set(ARMS[family]) and is_sha(baseline_sha), "complete arms/frozen baseline required")
    baseline_arm = ARMS[family][0]
    require(sha_file(packets[baseline_arm]) == baseline_sha, "no-change baseline receipt changed")
    receipts = {arm: read_json(file) for arm, file in packets.items()}
    ids = {r["id"] for r in rows if r["split"] in EVAL_SPLITS}
    results = {}
    for arm, receipt in receipts.items():
        require(receipt.get("schema") == SCHEMA and receipt.get("family") == family and
                receipt.get("arm") == arm and receipt.get("source_sha") == manifest["source_sha"] and
                receipt.get("dataset_sha256") == manifest["dataset_sha256"] and
                receipt.get("host_profile_digest") == manifest["host_profile_digest"],
                "model/dataset/host identity drift")
        if family != "heads":
            model = manifest.get("models", {}).get(arm, {})
            require(receipt.get("model_id") == MODEL_IDS[arm] == model.get("model_id") and
                    receipt.get("model_revision") == model.get("revision") and
                    receipt.get("weights_sha256") == model.get("weights_sha256") and
                    receipt.get("runtime", {}).get("artifact_tree_sha256") == model.get("artifact_tree_sha256"),
                    "model identity, bytes or revision drift")
        if family == "heads":
            expected_profile = hashlib.sha256(json.dumps(manifest["head"], sort_keys=True).encode()).hexdigest()
            require(receipt.get("runtime", {}).get("head_profile_sha256") == expected_profile,
                    "head encoder/training profile drift")
        require(type(receipt.get("parameters")) is int and 0 < receipt["parameters"] <= manifest["parameter_cap"],
                "model violates parameter cap")
        seen = receipt.get("observations")
        require(isinstance(seen, list) and {x.get("id") for x in seen} == ids,
                "different attempted cases across models")
        results[arm] = metrics(rows, seen, family)
    require(len({receipts[a].get("device") for a in ARMS[family]}) == 1,
            "arms used different compute devices")
    if family == "heads":
        params = [receipts[a]["parameters"] for a in ARMS[family]]
        require(min(params) >= .99 * max(params), "head arms not within 1% parameter budget")
    if family == "decisions":
        require(abs(receipts["laya"]["parameters"] - receipts["typed"]["parameters"]) <=
                .01 * receipts["laya"]["parameters"], "421M comparison has unmatched parameters")
    transitions = {}
    for candidate in ARMS[family][1:]:
        transitions[candidate] = {}
        base = {x["id"]: x for x in receipts[baseline_arm]["observations"]}
        new = {x["id"]: x for x in receipts[candidate]["observations"]}
        for split in EVAL_SPLITS:
            harmed, eligible = 0, 0
            for case in (r for r in rows if r["split"] == split):
                old, fresh = base[case["id"]], new[case["id"]]
                if family == "heads":
                    def error(p):
                        return sum((a - b) ** 2 for a, b in zip(p, case["target_q24"]))
                    eligible += 1
                    harmed += int(error(fresh["prediction_q24"]) > error(old["prediction_q24"]))
                else:
                    options = list(case["question"]["criteria"])
                    if options[max(range(len(options)), key=lambda i: old["probabilities"][i])] == case["gold"]:
                        eligible += 1
                        harmed += int(options[max(range(len(options)), key=lambda i: fresh["probabilities"][i])] != case["gold"])
            transitions[candidate][split] = {"negative_transfer_rate": harmed / eligible if eligible else None,
                                             "at_risk_cases": eligible}
    return {"schema": SCHEMA, "family": family, "diagnostic_comparison": True,
            "results": results, "negative_transfer": transitions,
            "baseline_sha256": baseline_sha,
            "production_evidence_verified": False, "ndu_selection_authorized": False,
            "promotion_authorized": False,
            "blockers": ["independent evaluator/holdout signature absent",
                         "NDU utility and future-window retention not independently attested",
                         "actual target-host deployment/canary and recovery not attested"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("run", "compare"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--arm", choices=tuple({v for arms in ARMS.values() for v in arms}))
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--weights-file", type=Path, default=Path("model.safetensors"))
    parser.add_argument("--sdk-sha256")
    parser.add_argument("--checkpoint-out", type=Path)
    parser.add_argument("--receipt", action="append", default=[], help="arm=absolute-file-path")
    parser.add_argument("--baseline-sha256")
    args = parser.parse_args()
    try:
        manifest, rows = load_inputs(args.manifest, args.dataset)
        verify_checkout(manifest["source_sha"])
        if args.mode == "compare":
            require(args.baseline_sha256 is not None, "baseline sha required")
            pairs = [a.split("=", 1) for a in args.receipt]
            require(all(len(p) == 2 for p in pairs), "expected arm=path")
            data = compare(manifest, rows, {arm: path for arm, path in pairs}, args.baseline_sha256)
        else:
            require(args.arm in ARMS[manifest["family"]], "invalid arm for family")
            started_wall = time.perf_counter()
            started_cpu = time.process_time()
            if manifest["family"] == "heads":
                require(args.checkpoint_out is not None, "head checkpoint-out required")
                parameters, weights, observations, runtime = run_head(
                    manifest, rows, args.arm, args.device, args.checkpoint_out)
            else:
                require(args.artifact_dir is not None and args.sdk_sha256 is not None,
                        "pinned local model and SDK required")
                parameters, weights, observations, runtime = run_laya(
                    manifest, rows, args.arm, args.artifact_dir,
                    args.weights_file, args.device, args.sdk_sha256)
            data = {"schema": SCHEMA, "family": manifest["family"], "arm": args.arm,
                    "model_id": manifest.get("models", {}).get(args.arm, {}).get("model_id"),
                    "model_revision": manifest.get("models", {}).get(args.arm, {}).get("revision"),
                    "device": args.device,
                    "source_sha": manifest["source_sha"], "dataset_sha256": manifest["dataset_sha256"],
                    "host_profile_digest": manifest["host_profile_digest"],
                    "parameters": parameters, "weights_sha256": weights,
                    "runtime": runtime, "hardware": hardware(), "observations": observations,
                    "end_to_end_wall_seconds": time.perf_counter() - started_wall,
                    "cpu_seconds": time.process_time() - started_cpu,
                    "peak_rss_bytes": peak_rss_bytes(),
                    "steady_state_throughput_per_s": len(observations) * 1000 /
                        sum(obs["latency_ms"] for obs in observations)
                        if sum(obs["latency_ms"] for obs in observations) > 0 else None,
                    "production_evidence_verified": False, "promotion_authorized": False}
        write_new(args.output, data)
    except (InvalidTrial, KeyError, TypeError, ValueError, OSError) as error:
        parser.exit(2, f"blocked: {error}\n")


if __name__ == "__main__":
    main()
