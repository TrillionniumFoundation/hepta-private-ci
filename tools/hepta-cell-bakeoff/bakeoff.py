#!/usr/bin/env python3
"""Offline, non-authorizing Hepta DecisionCell model comparison.

Scores only submitted observations. Never loads a model, mints provenance,
certifies signatures, or promotes an artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path

SCHEMA = "hepta.cell.bakeoff.v1"
MODEL_NAMES = ("laya-english", "laya-typed", "laya-multilingual", "arctic-305m", "harrier-270m")
SPLITS = ("train", "calibration", "future_1", "future_2")
SCALES = (64, 256, 1024, 4096)
TEMPERATURES = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 5.0)
HEX = set("0123456789abcdef")


class EvidenceError(ValueError):
    pass


def require(cond: bool, reason: str) -> None:
    if not cond:
        raise EvidenceError(reason)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda: f.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def is_hex(value: object, size: int = 64) -> bool:
    return isinstance(value, str) and len(value) == size and set(value) <= HEX and any(c != "0" for c in value)


def jsonl(path: Path) -> list[dict]:
    require(path.is_file(), f"missing {path}")
    require(path.stat().st_size <= 512 * 1024 * 1024, f"oversize {path}")
    rows = []
    with path.open(encoding="utf-8") as source:
        for idx, line in enumerate(source, 1):
            require(len(line) <= 65536, f"oversize line {idx} in {path}")
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EvidenceError(f"malformed {path}:{idx}: {exc}") from exc
            require(isinstance(row, dict), f"non-object {path}:{idx}")
            rows.append(row)
    require(bool(rows), f"empty {path}")
    return rows


def load_plan(path: Path) -> dict:
    plan = json.loads(path.read_text(encoding="utf-8"))
    require(plan.get("schema") == SCHEMA, "unsupported plan schema")
    require(is_hex(plan.get("source_head"), 40), "source head must be exact 40-hex SHA")
    require(is_hex(plan.get("dataset_sha256")), "dataset must be pinned by SHA-256")
    require(plan.get("baseline") == "laya-english", "baseline must be laya-english")
    require(isinstance(plan.get("threshold"), (int, float)) and 0.5 <= plan["threshold"] < 1, "threshold must be preregistered")
    models = plan.get("models")
    require(isinstance(models, list) and {m.get("name") for m in models} == set(MODEL_NAMES)
            and len(models) == len(MODEL_NAMES), "must declare exactly five model candidates")
    for model in models:
        require(model.get("kind") in ("typed", "encoder-head"), "unsupported model kind")
        require(isinstance(model.get("repo"), str) and "/" in model["repo"], "missing model repository")
        require(is_hex(model.get("revision"), 40), f"unpinned revision: {model['name']}")
        for field in ("weights_sha256", "tokenizer_sha256", "runtime_sha256", "head_sha256"):
            require(is_hex(model.get(field)), f"missing {field}: {model['name']}")
        require(model.get("license_review") == "approved", f"license not approved: {model['name']}")
        require(isinstance(model.get("parameters"), int) and 1 <= model["parameters"] <= 421000000,
                f"parameter budget exceeded: {model['name']}")
    head_arms = [m for m in models if m["kind"] == "encoder-head"]
    require({m["name"] for m in head_arms} == {"arctic-305m", "harrier-270m"}, "encoder head arms mismatch")
    budgets = {(m.get("head_steps"), m.get("head_seed"), m.get("head_optimizer"), m.get("head_lr"), m.get("train_data_sha256"))
               for m in head_arms}
    require(len(budgets) == 1 and next(iter(budgets))[0] is not None, "encoder heads require equal training budget")
    require(isinstance(plan.get("registered_before_utc"), str) and plan["registered_before_utc"],
            "missing preregistration timestamp")
    return plan


def validate_data(rows: list[dict]) -> dict[str, dict]:
    by_id: dict[str, dict] = {}
    split_groups: dict[str, set[str]] = defaultdict(set)
    times: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        uid = r.get("id")
        require(isinstance(uid, str) and 0 < len(uid) <= 128 and uid not in by_id, "invalid/duplicate sample id")
        require(r.get("split") in SPLITS, f"invalid split for {uid}")
        require(isinstance(r.get("source_group"), str) and r["source_group"], "missing source group")
        opts = r.get("options")
        require(isinstance(opts, list) and 2 <= len(opts) <= 32 and len(set(opts)) == len(opts)
                and all(isinstance(o, str) and o for o in opts), "invalid options")
        require(r.get("label") in opts, "invalid gold label")
        require(isinstance(r.get("timestamp"), int) and r["timestamp"] > 0, "missing source time")
        require(isinstance(r.get("language"), str) and r["language"], "missing language")
        require(isinstance(r.get("task_family"), str) and r["task_family"], "missing task family")
        require(type(r.get("ood")) is bool, "missing OOD label")
        split_groups[r["split"]].add(r["source_group"])
        times[r["split"]].append(r["timestamp"])
        by_id[uid] = r
    require(all(split_groups[k] for k in SPLITS), "all train/calibration/future splits must exist")
    for i, a in enumerate(SPLITS):
        for b in SPLITS[i+1:]:
            require(split_groups[a].isdisjoint(split_groups[b]), f"source leakage between {a}/{b}")
    require(max(times["train"]) < min(times["future_1"]), "future_1 not held out by time")
    require(max(times["future_1"]) < min(times["future_2"]), "future_2 not held out by time")
    require(max(times["calibration"]) < min(times["future_1"]), "calibration leakage into future")
    return by_id


def validate_predictions(rows: list[dict], data: dict[str, dict], plan: dict) -> dict[str, dict[str, dict]]:
    expected = {s for s, r in data.items() if r["split"] != "train"}
    result: dict[str, dict[str, dict]] = defaultdict(dict)
    model_pins = {m["name"]: m for m in plan["models"]}
    for r in rows:
        model, uid = r.get("model"), r.get("id")
        require(model in model_pins and uid in expected, "unknown model/sample or leaked train prediction")
        require(uid not in result[model], f"duplicate prediction: {model}/{uid}")
        pin = model_pins[model]
        require(r.get("revision") == pin["revision"] and r.get("weights_sha256") == pin["weights_sha256"],
                f"model identity mismatch: {model}")
        probs = r.get("probabilities")
        opts = data[uid]["options"]
        require(isinstance(probs, dict) and set(probs) == set(opts), f"option mismatch: {model}/{uid}")
        require(all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in probs.values())
                and abs(sum(probs.values()) - 1) <= 0.001, f"invalid probability: {model}/{uid}")
        require(type(r.get("abstain")) is bool, "missing explicit abstention")
        require(type(r.get("latency_ms")) in (float, int) and math.isfinite(r["latency_ms"])
                and r["latency_ms"] >= 0, "invalid latency")
        require(r.get("origin") == "live-model-observation", "non-live origin cannot enter evaluation")
        result[model][uid] = r
    require(set(result) == set(model_pins), "missing model observations")
    for model, entries in result.items():
        require(set(entries) == expected, f"missing observations: {model}")
    return result


def tempered(probs: dict[str, float], t: float) -> dict[str, float]:
    logits = {k: math.log(max(float(v), 1e-12)) / t for k, v in probs.items()}
    peak = max(logits.values())
    exp = {k: math.exp(v - peak) for k, v in logits.items()}
    denom = sum(exp.values())
    return {k: v / denom for k, v in exp.items()}


def temperature(ids: list[str], data: dict, predictions: dict) -> float:
    def nll(t):
        return sum(-math.log(max(tempered(predictions[uid]["probabilities"], t)[data[uid]["label"]], 1e-12))
                   for uid in ids) / len(ids)
    return min(TEMPERATURES, key=lambda t: (nll(t), abs(t - 1)))


def score(ids: list[str], data: dict, predictions: dict, t: float, threshold: float) -> dict:
    require(bool(ids), "empty evaluation cohort")
    correct, brier, losses, accepted, ood_count, ood_accepted = 0, [], [], 0, 0, 0
    bins: list[list[tuple[float, int]]] = [[] for _ in range(10)]
    class_tp = defaultdict(int)
    class_fp = defaultdict(int)
    class_fn = defaultdict(int)
    latency = []
    for uid in ids:
        d, p = data[uid], predictions[uid]
        ps = tempered(p["probabilities"], t)
        chosen = max(d["options"], key=lambda o: ps[o])
        conf = ps[chosen]
        hit = int(chosen == d["label"])
        correct += hit
        class_tp[d["label"]] += hit
        if not hit:
            class_fp[chosen] += 1
            class_fn[d["label"]] += 1
        brier.append(sum((ps[o] - int(o == d["label"])) ** 2 for o in d["options"]))
        losses.append(-math.log(max(ps[d["label"]], 1e-12)))
        bins[min(9, int(conf * 10))].append((conf, hit))
        accepts = not p["abstain"] and conf >= threshold
        accepted += int(accepts)
        if d["ood"]:
            ood_count += 1
            ood_accepted += int(accepts)
        latency.append(p["latency_ms"])
    ece = sum(len(b) / len(ids) * abs(statistics.mean(x[0] for x in b) - statistics.mean(x[1] for x in b))
              for b in bins if b)
    classes = set(class_tp) | set(class_fp) | set(class_fn)
    macro_f1 = statistics.mean((2 * class_tp[c] / (2 * class_tp[c] + class_fp[c] + class_fn[c]))
                               if (2 * class_tp[c] + class_fp[c] + class_fn[c]) else 0 for c in classes)
    latency.sort()
    p95 = latency[max(0, math.ceil(0.95 * len(latency)) - 1)]
    p99 = latency[max(0, math.ceil(0.99 * len(latency)) - 1)]
    return {"n": len(ids), "independent_source_groups": len({data[i]["source_group"] for i in ids}),
            "accuracy": correct / len(ids), "macro_f1": macro_f1, "brier": statistics.mean(brier),
            "nll": statistics.mean(losses), "ece_10": ece, "acceptance": accepted / len(ids),
            "ood_n": ood_count, "ood_false_acceptance": ood_accepted / ood_count if ood_count else None,
            "p95_latency_ms": p95, "p99_latency_ms": p99}


def paired_interval(ids: list[str], data: dict, base: dict, challenger: dict,
                    base_t: float, challenge_t: float, *, seed: int = 229, draws: int = 1000) -> tuple[float, float]:
    groups: dict[str, list[str]] = defaultdict(list)
    for uid in ids:
        groups[data[uid]["source_group"]].append(uid)
    units = list(groups.values())
    def hits(predictions, temp):
        result = {}
        for uid in ids:
            ps = tempered(predictions[uid]["probabilities"], temp)
            result[uid] = int(max(ps, key=ps.get) == data[uid]["label"])
        return result
    base_hits = hits(base, base_t)
    challenge_hits = hits(challenger, challenge_t)
    unit_totals = [(sum(challenge_hits[i] - base_hits[i] for i in group), len(group)) for group in units]
    rng = random.Random(seed)
    differences = []
    for _ in range(draws):
        chosen = [unit_totals[rng.randrange(len(units))] for _ in units]
        differences.append(sum(x for x, _ in chosen) / sum(n for _, n in chosen))
    differences.sort()
    return differences[int(0.025 * (draws-1))], differences[int(0.975 * (draws-1))]


def check_resources(rows: list[dict], models: list[dict]) -> tuple[dict, list[str]]:
    by_model: dict[str, dict] = defaultdict(dict)
    blockers = []
    required = ("active_cells", "cpu_rss_peak_bytes", "gpu_peak_bytes", "throughput_per_sec",
                "p95_latency_ms", "p99_latency_ms", "load_latency_ms", "host_id", "driver_receipt")
    for row in rows:
        model, scale = row.get("model"), row.get("logical_cells")
        require(model in {m["name"] for m in models} and scale in SCALES, "invalid resource model/scale")
        require(scale not in by_model[model], "duplicate resource model/scale")
        for field in required:
            require(field in row and row[field] is not None, f"missing measured {field}")
        require(type(row["active_cells"]) is int and 0 < row["active_cells"] <= scale, "invalid active cells")
        for field in required[:0] + required[1:7]:
            require(type(row[field]) in (int, float) and math.isfinite(row[field]) and row[field] >= 0,
                    f"invalid resource {field}")
        require(row["p99_latency_ms"] >= row["p95_latency_ms"], "latency quantile inversion")
        require(row.get("origin") == "observed-target-host", "resources must be target-host observations")
        by_model[model][scale] = row
    for model in models:
        if set(by_model[model["name"]]) != set(SCALES):
            blockers.append(f"resource-missing-scales:{model['name']}")
    return by_model, blockers


def evaluate(plan: dict, data_path: Path, predictions_path: Path,
             resource_path: Path | None = None, lifecycle_path: Path | None = None) -> dict:
    require(digest(data_path) == plan["dataset_sha256"], "dataset digest mismatch")
    data = validate_data(jsonl(data_path))
    raw = validate_predictions(jsonl(predictions_path), data, plan)
    calibration_ids = [i for i, row in data.items() if row["split"] == "calibration"]
    ts = {m: temperature(calibration_ids, data, ps) for m, ps in raw.items()}
    scores = {}
    for model, ps in raw.items():
        scores[model] = {window: score([i for i, r in data.items() if r["split"] == window],
                                        data, ps, ts[model], plan["threshold"])
                         for window in ("future_1", "future_2")}
    comparisons = {}
    blockers = []
    baseline = plan["baseline"]
    for model in raw:
        if model == baseline:
            continue
        comparisons[model] = {}
        for window in ("future_1", "future_2"):
            ids = [i for i, r in data.items() if r["split"] == window]
            ci = paired_interval(ids, data, raw[baseline], raw[model], ts[baseline], ts[model])
            comparisons[model][window] = {"paired_accuracy_gain_ci95": list(ci)}
            if len({data[i]["source_group"] for i in ids}) < 400:
                blockers.append(f"insufficient-independent-groups:{window}")
            ood_groups = {data[i]["source_group"] for i in ids if data[i]["ood"]}
            if len(ood_groups) < 400:
                blockers.append(f"insufficient-independent-ood-groups:{window}")
            # Non-compensable old-task retention and cross-language/organ floors.
            subgroups = {(data[i]["task_family"], data[i]["language"]) for i in ids}
            for task, lang in subgroups:
                sub_ids = [i for i in ids if data[i]["task_family"] == task and data[i]["language"] == lang]
                label = f"{task}/{lang}"
                if len({data[i]["source_group"] for i in sub_ids}) < 40:
                    blockers.append(f"subgroup-support-insufficient:{window}:{label}")
                    continue
                accuracy_new = score(sub_ids, data, raw[model], ts[model], plan["threshold"])["accuracy"]
                accuracy_base = score(sub_ids, data, raw[baseline], ts[baseline], plan["threshold"])["accuracy"]
                if accuracy_base - accuracy_new > 0.02:
                    blockers.append(f"negative-transfer:{model}:{window}:{label}")
            if ci[0] <= 0:
                blockers.append(f"nonpositive-paired-gain:{model}:{window}")
            m = scores[model][window]
            if m["ood_false_acceptance"] is None or m["ood_false_acceptance"] > 0.005:
                blockers.append(f"ood-floor-not-proved:{model}:{window}")
    resource_summary = None
    if resource_path is not None:
        resource_summary, resource_blockers = check_resources(jsonl(resource_path), plan["models"])
        blockers.extend(resource_blockers)
    else:
        blockers.append("no-observed-64-256-1024-4096-cell-resource-evidence")
    if lifecycle_path is None:
        blockers.append("missing-external-cas-fence-rollback-restart-attestation")
    else:
        events = jsonl(lifecycle_path)
        required = {"artifact-cas", "generation-fence", "signed-final-use", "rollback", "restart-recovery", "old-generation-rejected"}
        for model in MODEL_NAMES:
            observed = {r.get("event") for r in events if r.get("model") == model}
            if not required.issubset(observed):
                blockers.append(f"lifecycle-events-unproven:{model}")
        # A JSON declaration is not cryptographic verification of an independent issuer.
        blockers.append("external-signature-trust-root-and-live-receipt-verification-required")
    blockers.append("independent-host-and-dataset-provenance-not-authenticated")
    return {"schema": SCHEMA, "authority": "research-only-no-model-selection-or-release",
            "source_head": plan["source_head"], "dataset_sha256": plan["dataset_sha256"],
            "predictions_sha256": digest(predictions_path), "temperature_fit_calibration_only": ts,
            "scores": scores, "paired_comparisons": comparisons,
            "resource_coverage": ({k: sorted(v) for k, v in resource_summary.items()} if resource_summary is not None else None),
            "blockers": sorted(set(blockers)), "production_qualified": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--resources", type=Path)
    parser.add_argument("--lifecycle", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fail-on-blockers", action="store_true")
    args = parser.parse_args()
    try:
        report = evaluate(load_plan(args.plan), args.dataset, args.predictions, args.resources, args.lifecycle)
        args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"report": str(args.out), "production_qualified": False,
                          "blocker_count": len(report["blockers"])}, sort_keys=True))
        return 2 if args.fail_on_blockers and report["blockers"] else 0
    except (EvidenceError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"CELL-BAKEOFF INVALID: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
