#!/usr/bin/env python3
"""Fail-closed, independent evaluation of real Neuron Cell model observations.

No model is downloaded or executed here. Predictions are raw observed artifacts
from approved model drivers; qualification and promotion are separate authorities.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import subprocess
import tempfile
from collections import defaultdict

from trace_evidence import TraceEvidenceError, audit_trace

SCHEMA = "hepta.neuron-model-bakeoff.v1"
ARMS = ("laya-english", "laya-typed", "laya-multilingual", "arctic-head", "harrier-head")
SPLITS = ("train", "calibration", "test", "future")
SCALES = (64, 256, 1024, 4096)
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
EVENT_OWNERS = {
    "artifact_cas": "artifact.registry",
    "signed_load": "inference.worker",
    "generation_cutover": "supervisor",
    "stale_generation_reject": "inference.control",
    "fault_reopen": "neuron.runtime",
    "rollback": "artifact.registry",
}


class EvidenceError(ValueError):
    pass


def require(ok: bool, why: str) -> None:
    if not ok:
        raise EvidenceError(why)


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(type(value) is dict, f"{path}: object required")
    return value


def artifact(root: Path, ref: dict) -> Path:
    require(type(ref) is dict, "artifact reference must be object")
    name, digest = ref.get("path"), ref.get("sha256")
    require(type(name) is str and bool(name) and type(digest) is str and HEX64.fullmatch(digest) is not None,
            "artifact requires relative path and full SHA256")
    rel = Path(name)
    require(not rel.is_absolute() and ".." not in rel.parts, "artifact path traversal")
    base, target = root.resolve(), (root / rel).resolve()
    require(target.is_relative_to(base) and target.is_file(), "artifact is missing or escapes root")
    require(sha_file(target) == digest, f"artifact SHA256 mismatch: {name}")
    return target


def records(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            obj = json.loads(line)
            require(type(obj) is dict, f"{path}:{line_no}: object required")
            out.append(obj)
    require(bool(out), f"{path}: empty observations")
    return out


def candidate_registry() -> dict[str, dict]:
    """Read the committed candidate source pins; a manifest cannot silently substitute a model."""
    path = Path(__file__).resolve().parent / "CANDIDATES.json"
    config = load_json(path)
    require(config.get("schema") == "hepta.neuron-bakeoff.candidate-source-pins.v1",
            "registered source-pin schema mismatch")
    models = config.get("models")
    require(type(models) is list and len(models) == len(ARMS), "fixed model roster required")
    pins = {}
    for model in models:
        require(type(model) is dict and model.get("arm") in ARMS and model["arm"] not in pins,
                "duplicate/unregistered candidate in pinned roster")
        require(type(model.get("revision")) is str and HEX40.fullmatch(model["revision"]) is not None,
                "pinned model revision must be SHA40")
        require(all(type(model.get(k)) is str for k in ("repository", "subfolder", "license")),
                "pinned source identity incomplete")
        pins[model["arm"]] = model
    require(set(pins) == set(ARMS), "incomplete fixed model roster")
    return pins


def validate_dataset(data: list[dict]) -> dict:
    ids, split_groups = set(), defaultdict(set)
    seen_splits = set()
    for row in data:
        cid, group, split = row.get("case_id"), row.get("group_id"), row.get("split")
        require(type(cid) is str and cid and cid not in ids, "duplicate/invalid case_id")
        require(type(group) is str and group, "group_id required")
        require(split in SPLITS, "invalid dataset split")
        labels = row.get("labels")
        require(type(labels) is list and 2 <= len(labels) <= 256 and
                all(type(x) is str and x for x in labels) and len(set(labels)) == len(labels),
                "invalid label vocabulary")
        require(row.get("label") in labels, "truth label not in vocabulary")
        require(type(row.get("language")) is str and bool(row["language"]), "missing language")
        require(type(row.get("task_family")) is str and bool(row["task_family"]), "missing task_family")
        require(type(row.get("ood")) is bool, "explicit ood boolean required")
        ids.add(cid)
        split_groups[split].add(group)
        seen_splits.add(split)
    require(seen_splits == set(SPLITS), "train/calibration/test/future all required")
    for i, left in enumerate(SPLITS):
        for right in SPLITS[i + 1:]:
            require(not (split_groups[left] & split_groups[right]), "data leakage: group shared across splits")
    return {row["case_id"]: row for row in data}


def valid_number(value: object, lo: float = 0.0) -> bool:
    return type(value) in (float, int) and math.isfinite(value) and value >= lo


def validate_predictions(predictions: list[dict], cases: dict, arm: str) -> dict:
    expected = {cid for cid, row in cases.items() if row["split"] in ("test", "future")}
    obs = {}
    for row in predictions:
        cid = row.get("case_id")
        require(type(cid) is str and cid in expected and cid not in obs,
                f"{arm}: missing/duplicate/extra case")
        vocab = cases[cid]["labels"]
        probs = row.get("probabilities")
        require(type(probs) is dict and set(probs) == set(vocab), f"{arm}/{cid}: mismatched probability keys")
        require(all(valid_number(p) and p <= 1.0 for p in probs.values()) and
                abs(sum(probs.values()) - 1.0) <= 1e-4,
                f"{arm}/{cid}: probabilities must be finite, normalized and within [0,1]")
        require(type(row.get("abstained")) is bool, f"{arm}/{cid}: abstention must be explicit")
        require(valid_number(row.get("latency_ms")) and row["latency_ms"] > 0,
                f"{arm}/{cid}: observed latency required")
        require(type(row.get("rss_bytes")) is int and row["rss_bytes"] > 0,
                f"{arm}/{cid}: actual RSS required")
        gpu = row.get("gpu_peak_bytes")
        require(gpu is None or (type(gpu) is int and gpu >= 0), "invalid GPU measurement")
        require(type(row.get("host_id")) is str and row["host_id"], "host identity required")
        require(type(row.get("device")) is str and row["device"], "device required")
        require(type(row.get("model_weights_sha256")) is str and HEX64.fullmatch(row["model_weights_sha256"]),
                "actual weights digest required")
        obs[cid] = row
    require(set(obs) == expected, f"{arm}: incomplete paired evaluation observations")
    return obs


def percentile(nums: list[float], level: float) -> float:
    require(bool(nums), "empty percentile")
    nums = sorted(nums)
    point = (len(nums) - 1) * level / 100
    low = math.floor(point)
    high = math.ceil(point)
    return nums[low] + (nums[high] - nums[low]) * (point - low)


def score(rows: list[tuple[dict, dict]]) -> dict:
    require(bool(rows), "empty evaluation slice")
    accepted = 0
    correct = 0
    brier = 0.0
    bins = [[0.0, 0.0, 0] for _ in range(15)]
    ood = 0
    false_accept = 0
    per_language = defaultdict(lambda: [0, 0])
    per_family = defaultdict(lambda: [0, 0])
    latencies, rss, gpu = [], [], []
    for truth, pred in rows:
        probs = pred["probabilities"]
        decision = max(truth["labels"], key=lambda c: probs[c])
        confidence = probs[decision]
        ok = not pred["abstained"] and decision == truth["label"]
        correct += int(ok)
        accepted += int(not pred["abstained"])
        brier += sum((probs[c] - (1.0 if c == truth["label"] else 0.0)) ** 2 for c in truth["labels"])
        bin_idx = min(14, int(confidence * 15))
        bins[bin_idx][0] += confidence
        bins[bin_idx][1] += int(decision == truth["label"])
        bins[bin_idx][2] += 1
        if truth["ood"]:
            ood += 1
            false_accept += int(not pred["abstained"])
        for agg, key in ((per_language, truth["language"]), (per_family, truth["task_family"])):
            agg[key][0] += int(ok)
            agg[key][1] += 1
        latencies.append(float(pred["latency_ms"]))
        rss.append(pred["rss_bytes"])
        if pred["gpu_peak_bytes"] is not None:
            gpu.append(pred["gpu_peak_bytes"])
    n = len(rows)
    ece = sum((count / n) * abs(total_conf / count - total_correct / count)
              for total_conf, total_correct, count in bins if count)
    return {
        "count": n, "accuracy_with_abstentions": correct / n,
        "coverage": accepted / n,
        "selective_accuracy": correct / accepted if accepted else None,
        "multiclass_brier": brier / n,
        "ece_15_bins": ece,
        "ood_false_accept_rate": false_accept / ood if ood else None,
        "ood_count": ood,
        "by_language_accuracy": {k: a / c for k, (a, c) in sorted(per_language.items())},
        "by_family_accuracy": {k: a / c for k, (a, c) in sorted(per_family.items())},
        "p50_ms": percentile(latencies, 50), "p95_ms": percentile(latencies, 95),
        "p99_ms": percentile(latencies, 99), "peak_rss_bytes": max(rss),
        "peak_gpu_bytes": max(gpu) if len(gpu) == n else None,
    }


def paired_ci(cases: dict, baseline: dict, candidate: dict, split: str,
              repetitions: int = 500) -> dict:
    groups = defaultdict(list)
    for cid, row in cases.items():
        if row["split"] == split:
            groups[row["group_id"]].append(cid)
    keys = sorted(groups)
    require(len(keys) >= 2, f"{split}: at least two independent groups required")
    rng = random.Random(0)

    def gain(ids: list[str]) -> float:
        def accuracy(obs: dict) -> float:
            return sum(int(not obs[c]["abstained"] and
                           max(cases[c]["labels"], key=lambda a: obs[c]["probabilities"][a]) == cases[c]["label"])
                       for c in ids) / len(ids)
        return accuracy(candidate) - accuracy(baseline)

    all_ids = [cid for k in keys for cid in groups[k]]
    samples = []
    for _ in range(repetitions):
        chosen = [rng.choice(keys) for _ in keys]
        samples.append(gain([cid for k in chosen for cid in groups[k]]))
    return {"point": gain(all_ids), "ci95": [percentile(samples, 2.5), percentile(samples, 97.5)],
            "groups": len(keys), "method": "paired-group-bootstrap-seed0-500"}


def verify_workload(root: Path, manifest: dict, weights_by_arm: dict[str, str]) -> list[dict]:
    rows = records(artifact(root, manifest["workload"]))
    seen = set()
    for row in rows:
        arm = row.get("arm")
        require(arm in ARMS, "workload arm missing or invalid")
        scale, active = row.get("logical_cells"), row.get("active_cells")
        require(type(scale) is int and scale in SCALES and (arm, scale) not in seen,
                "missing/duplicate/invalid logical cell scale")
        require(type(active) is int and 1 <= active <= scale, "active concurrency required")
        require(type(row.get("requests")) is int and row["requests"] > 0, "observed requests required")
        for field in ("throughput_per_sec", "p95_ms", "p99_ms", "load_ms", "peak_rss_bytes"):
            require(valid_number(row.get(field)), f"actual {field} required")
        require(row["p99_ms"] >= row["p95_ms"] > 0 and row["peak_rss_bytes"] > 0,
                "invalid workload measurement")
        require(type(row.get("host_id")) is str and row["host_id"], "host identity required")
        require(row.get("execution_kind") == "observed-real-model", "synthetic workload cannot qualify")
        require(row.get("model_weights_sha256") == weights_by_arm[arm],
                "workload model digest differs from evaluated predictions")
        require(type(row.get("trace")) is dict, "raw request trace reference required")
        try:
            row["recomputed_from_raw_trace"] = audit_trace(row, records(artifact(root, row["trace"])))
        except TraceEvidenceError as exc:
            raise EvidenceError(str(exc)) from exc
        seen.add((arm, scale))
    require(seen == {(arm, scale) for arm in ARMS for scale in SCALES},
            "not all 5 models x 64/256/1024/4096 scales are measured")
    return sorted(rows, key=lambda row: (row["arm"], row["logical_cells"]))


def verify_lifecycle(root: Path, manifest: dict, trusted_key: Path | None) -> dict:
    receipt = load_json(artifact(root, manifest["lifecycle"]))
    require(receipt.get("schema") == "hepta.neuron-bakeoff.lifecycle.v1", "wrong lifecycle schema")
    events = receipt.get("events")
    require(type(events) is list and len(events) == len(EVENT_OWNERS), "incomplete lifecycle events")
    mapping = {}
    for event in events:
        require(type(event) is dict, "invalid lifecycle event")
        name = event.get("name")
        require(name in EVENT_OWNERS and name not in mapping, "duplicate/unexpected lifecycle event")
        require(event.get("owner") == EVENT_OWNERS[name] and event.get("status") == "observed_success",
                "lifecycle owner mismatch or not observed")
        require(type(event.get("operation_id")) is str and event["operation_id"], "operation identity required")
        require(type(event.get("generation")) is int and event["generation"] > 0, "generation required")
        require(type(event.get("receipt_sha256")) is str and HEX64.fullmatch(event["receipt_sha256"]),
                "actual operation receipt digest required")
        artifact(root, {"path": event.get("receipt_path"), "sha256": event["receipt_sha256"]})
        mapping[name] = event
    require(set(mapping) == set(EVENT_OWNERS), "missing lifecycle event")
    require([event["name"] for event in events] == list(EVENT_OWNERS),
            "lifecycle event order must preserve artifact/load/cutover/reject/reopen/rollback")
    target_gen = mapping["generation_cutover"]["generation"]
    for key in ("artifact_cas", "signed_load", "fault_reopen", "rollback"):
        require(mapping[key]["generation"] == target_gen, "generation drift")
    require(mapping["stale_generation_reject"]["generation"] < target_gen,
            "stale generation rejection must reference previous generation")
    require(trusted_key is not None and trusted_key.is_file(), "independent trusted public key required")
    sig = receipt.get("signature_base64")
    require(type(sig) is str and sig, "detached signature required")
    signed = {k: v for k, v in receipt.items() if k != "signature_base64"}
    try:
        signature = base64.b64decode(sig, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise EvidenceError("invalid signature encoding") from exc
    with tempfile.TemporaryDirectory() as temp:
        message, sig_file = Path(temp) / "message", Path(temp) / "sig"
        message.write_bytes(canonical(signed))
        sig_file.write_bytes(signature)
        completed = subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin",
                                    "-inkey", str(trusted_key.resolve()), "-rawin", "-in", str(message),
                                    "-sigfile", str(sig_file)], capture_output=True, check=False)
    require(completed.returncode == 0, "independent lifecycle signature invalid")
    return {"independent_signature_verified": True, "public_key_sha256": sha_file(trusted_key),
            "generation": target_gen, "verified_event_names": sorted(mapping)}


def evaluate(root: Path, manifest: dict, trusted_key: Path | None = None) -> dict:
    require(manifest.get("schema") == SCHEMA, "wrong manifest schema")
    require(type(manifest.get("source_commit")) is str and HEX40.fullmatch(manifest["source_commit"]),
            "exact source SHA required")
    dataset = validate_dataset(records(artifact(root, manifest["dataset"])))
    pinned_sources = candidate_registry()
    model_specs = manifest.get("models")
    require(type(model_specs) is list and len(model_specs) == len(ARMS), "all five candidate arms required")
    predictions = {}
    trainer = []
    training_sha = sha_bytes(canonical([dataset[cid] for cid in sorted(dataset) if dataset[cid]["split"] == "train"]))
    for spec in model_specs:
        require(type(spec) is dict and spec.get("arm") in ARMS, "unknown model arm")
        arm = spec["arm"]
        require(arm not in predictions, "duplicate model arm")
        require(type(spec.get("revision")) is str and HEX40.fullmatch(spec["revision"]),
                f"{arm}: pinned revision required")
        pin = pinned_sources[arm]
        require(all(spec.get(k) == pin[k] for k in ("repository", "subfolder", "revision", "license")),
                f"{arm}: model source revision, subfolder or license differs from committed pins")
        for field in ("weights", "tokenizer", "runtime", "calibration"):
            artifact(root, spec[field])
        require(type(spec.get("license")) is str and spec["license"], "license review required")
        actual = validate_predictions(records(artifact(root, spec["predictions"])), dataset, arm)
        weight_digest = spec["weights"]["sha256"]
        require(all(o["model_weights_sha256"] == weight_digest for o in actual.values()),
                f"{arm}: observed weights do not match artifact")
        require(all(o.get("calibration_sha256") == spec["calibration"]["sha256"] for o in actual.values()),
                f"{arm}: observed calibration does not match selected artifact")
        if arm in ("arctic-head", "harrier-head"):
            head_path = artifact(root, spec["head_weights"])
            training_report = load_json(artifact(root, spec["training_report"]))
            require(all(o.get("head_sha256") == spec["head_weights"]["sha256"] for o in actual.values()),
                    f"{arm}: observed head does not match artifact")
            require(training_report.get("head_sha256") == sha_file(head_path) and
                    training_report.get("encoder_weights_sha256") == weight_digest,
                    f"{arm}: trained head lineage mismatch")
            h = spec.get("head_training")
            require(type(h) is dict and all(k in h for k in
                    ("steps", "examples_seen", "batch_size", "seed", "target_dim", "optimizer_sha256", "training_dataset_sha256")),
                    "head_training provenance required")
            require(all(type(h[k]) is int and h[k] > 0 for k in ("steps", "examples_seen", "batch_size", "target_dim")),
                    "positive training budgets required")
            require(type(h["seed"]) is int, "head_training seed required")
            require(all(type(h[k]) is str and HEX64.fullmatch(h[k]) for k in
                        ("optimizer_sha256", "training_dataset_sha256")), "training SHA256 required")
            require(h["training_dataset_sha256"] == training_sha,
                    "head trained on unregistered dataset or contaminated split")
            require(all(training_report.get(k) == h[k] for k in h),
                    f"{arm}: training report contradicts declared budget")
            trainer.append(h)
        predictions[arm] = actual
    require(set(predictions) == set(ARMS), "candidate roster incomplete")
    require(trainer[0] == trainer[1], "Arctic/Harrier heads were not trained with identical budgets")
    out = {"schema": "hepta.neuron-model-bakeoff.report.v1", "source_commit": manifest["source_commit"],
           "dataset_sha256": manifest["dataset"]["sha256"], "models": {}, "paired_accuracy_vs_english": {},
           "workload": verify_workload(root, manifest, {s["arm"]: s["weights"]["sha256"] for s in model_specs}),
           "lifecycle": verify_lifecycle(root, manifest, trusted_key),
           "qualification": "evaluation_evidence_only_not_release_or_promotion",
           "independent_acceptance": False, "all_blockers_closed": False,
           "production_activation_allowed": False}
    for split in ("test", "future"):
        for arm in ARMS:
            rows = [(row, predictions[arm][cid]) for cid, row in dataset.items() if row["split"] == split]
            out["models"].setdefault(arm, {})[split] = score(rows)
            if arm != "laya-english":
                out["paired_accuracy_vs_english"].setdefault(arm, {})[split] = paired_ci(
                    dataset, predictions["laya-english"], predictions[arm], split)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path, help="local evidence root; no downloads")
    parser.add_argument("--manifest", required=True, type=Path, help="manifest inside root")
    parser.add_argument("--trusted-lifecycle-key", type=Path, required=True,
                        help="public key independently provisioned OUTSIDE candidate manifest")
    parser.add_argument("--output", type=Path, help="optional output report JSON")
    args = parser.parse_args()
    try:
        root = args.root.resolve()
        manifest_path = args.manifest.resolve()
        require(manifest_path.is_relative_to(root), "manifest outside evidence root")
        report = evaluate(root, load_json(manifest_path), args.trusted_lifecycle_key)
    except (EvidenceError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"BLOCKED: {exc}\n")
    rendered = json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
