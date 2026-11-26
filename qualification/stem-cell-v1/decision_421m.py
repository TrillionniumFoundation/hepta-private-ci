#!/usr/bin/env python3
"""Four-way 395-435M decision comparison, reusing the Hepta Stem L1 dataset.

This is a shadow-only, OFFLINE evaluator for externally executed real models.
It never downloads weights, runs unknown Laya code, trains an HF model, signs
outcomes, or grants a production authority. It refuses incomplete comparisons.
A checkpoint arm is NOT automatically zero-shot: Laya Typed may already have
seen similar tasks during upstream fine-tuning.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random

from model_runner import snapshot_digest
from study import (MAX_EVIDENCE_ROW_BYTES, parse_finite_evidence_float,
                   quantile, reject_nonstandard_evidence_number,
                   validate_dataset)

SOURCES = {
    # Weight artifact identity lives on Hugging Face; the separate Laya
    # executable/library source is NandhaKishorM/laya and must be audited too.
    "laya_original": ("convaiinnovations/laya", 421_000_000),
    "laya_typed": ("convaiinnovations/laya-typed-decisions", 421_000_000),
    "deberta_v3_large": ("microsoft/deberta-v3-large", 435_000_000),
    "modernbert_large": ("answerdotai/ModernBERT-large", 395_000_000),
}
PHASES = ("checkpoint", "equal_budget")
SPLITS = ("train", "calibration", "held_out", "future_1", "future_2", "ood")
SCORING = SPLITS[1:]
TEMPERATURES = (.5, .75, 1., 1.5, 2., 3., 5.)
SCHEMA = "hepta.stem-cell-decision-421m-shadow.v1"


def no_duplicate_json_keys(pairs):
    record = {}
    for key, value in pairs:
        if key in record:
            raise ValueError("duplicate field in pinned Decision evidence")
        record[key] = value
    return record


def read_strict_jsonl(path):
    """Byte-bound frozen Decision evidence, rejecting ambiguous JSON numbers/keys."""
    with Path(path).open("rb") as handle:
        number = 0
        while raw := handle.readline(MAX_EVIDENCE_ROW_BYTES + 1):
            number += 1
            if len(raw) > MAX_EVIDENCE_ROW_BYTES:
                raise ValueError(f"oversized Decision JSONL row at line {number}")
            if not raw.strip():
                raise ValueError(f"empty Decision JSONL row at line {number}")
            try:
                record = json.loads(
                    raw.decode("utf-8"), object_pairs_hook=no_duplicate_json_keys,
                    parse_constant=reject_nonstandard_evidence_number,
                    parse_float=parse_finite_evidence_float)
            except (UnicodeError, ValueError, TypeError) as exc:
                raise ValueError(f"invalid/duplicate Decision JSONL at line {number}") from exc
            if type(record) is not dict:
                raise ValueError("Decision JSONL rows must be objects")
            yield record


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def input_fingerprint(row):
    """Bind exact label-free task input and provenance, not just sample_id."""
    fields = ("sample_id", "source_group", "episode_id", "split",
              "scope", "language", "state", "question", "options",
              "event_time")
    if any(key not in row for key in fields):
        raise ValueError("missing complete label-free input provenance")
    return digest({key: row[key] for key in fields})


def check_sha(value, size=64):
    return (isinstance(value, str) and len(value) == size
            and all(x in "0123456789abcdef" for x in value))


def event_time(row):
    try:
        parsed = datetime.fromisoformat(row["event_time"].replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone missing")
        return parsed.astimezone(timezone.utc)
    except (KeyError, ValueError, AttributeError) as exc:
        raise ValueError("timestamp must be timezone-aware") from exc


def audit_dataset(rows):
    indexed = validate_dataset(rows)
    if set(row["split"] for row in rows) != set(SPLITS):
        raise ValueError("all six train/calibration/test/future/OOD splits required")
    nclasses = None
    windows = defaultdict(list)
    for row in rows:
        if (not isinstance(row.get("state"), str) or
                not isinstance(row.get("question"), str) or
                not isinstance(row.get("scope"), str) or not row["scope"]):
            raise ValueError("typed state/question/scope required")
        opts = row.get("options")
        if (not isinstance(opts, list) or not 2 <= len(opts) <= 16 or
                any(not isinstance(o, str) or not o for o in opts)):
            raise ValueError("ordered nonempty options required")
        if nclasses is None:
            nclasses = len(opts)
        if len(opts) != nclasses or not 0 <= row["label"] < nclasses:
            raise ValueError("fixed option width and label range required")
        windows[row["split"]].append(event_time(row))
    for previous, later in zip(SPLITS[:5], SPLITS[1:5]):
        if max(windows[previous]) >= min(windows[later]):
            raise ValueError("chronological split overlap")
    train_ids = sorted((r["sample_id"], r["source_group"]) for r in rows
                       if r["split"] == "train")
    return indexed, nclasses, digest(train_ids)


def build_plan(dataset_path, descriptors, *, train_steps, trainable_budget,
               batch_size, context_tokens, seed, device, dtype,
               encoder_microbatch_size=1):
    dataset_path = Path(dataset_path).resolve()
    data = list(read_strict_jsonl(dataset_path))
    _, width, train_group_digest = audit_dataset(data)
    if set(descriptors) != set(SOURCES):
        raise ValueError("all four registered decision checkpoints required")
    if any(type(n) is not int or n <= 0 for n in
           (train_steps, trainable_budget, batch_size, context_tokens)):
        raise ValueError("invalid fixed training budget")
    if (type(encoder_microbatch_size) is not int or
            not 1 <= encoder_microbatch_size <= 32):
        raise ValueError("unregistered physical Encoder batch size")
    if not isinstance(seed, int) or not device or dtype not in ("fp32", "bf16", "fp16"):
        raise ValueError("invalid fixed environment")
    pinned = {}
    for key, (source, nominal) in SOURCES.items():
        item = descriptors[key]
        if item.get("source") != source or not check_sha(item.get("upstream_revision"), 40):
            raise ValueError("model source or immutable revision missing: " + key)
        if item.get("license_approved") is not True or item.get("adapter_reviewed") is not True:
            raise ValueError("model license/decision adapter not independently reviewed: " + key)
        path = Path(item["snapshot_path"]).resolve()
        tree = item.get("sha256")
        if not check_sha(tree) or snapshot_digest(path) != tree:
            raise ValueError("checkpoint bytes missing/drifted: " + key)
        actual = item.get("parameter_count")
        if type(actual) is not int or not 350_000_000 <= actual <= 480_000_000:
            raise ValueError("reported model size is outside comparable range")
        if abs(actual - nominal) / nominal > .10:
            raise ValueError("model size differs materially from nominal profile")
        pinned[key] = {
            "source": source, "nominal_parameters": nominal,
            "parameter_count_reported": actual,
            "upstream_revision": item["upstream_revision"],
            "snapshot_path": str(path), "sha256": tree,
            "license_approved": True, "adapter_reviewed": True,
        }
    return {
        "schema": SCHEMA, "stage": "shadow_only",
        "production_promotion_permitted": False, "model_execution_performed": False,
        "dataset_path": str(dataset_path),
        "dataset_sha256": sha256_file(dataset_path),
        "evaluator_source_sha256": sha256_file(__file__),
        "training_sample_groups_sha256": train_group_digest,
        "classes": width, "checkpoints": pinned,
        "input_contract": "state_question_all_ordered_options",
        "phases": list(PHASES), "train_steps": train_steps,
        "trainable_parameter_budget": trainable_budget,
        "batch_size": batch_size, "context_tokens": context_tokens,
        "encoder_microbatch_size": encoder_microbatch_size,
        "seed": seed, "device": device, "dtype": dtype,
        "comparison_note": ("checkpoint phase includes any upstream task exposure; "
                            "it is not assumed to be a zero-shot model comparison"),
    }


def write_frozen(path, payload):
    path = Path(path)
    key = "plan_sha256" if payload.get("schema") == SCHEMA else "report_sha256"
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps({**payload, key: digest(payload)},
                                ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def load_plan(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=no_duplicate_json_keys)
    token = payload.pop("plan_sha256", None)
    if (not check_sha(token) or digest(payload) != token or
            payload.get("schema") != SCHEMA or payload.get("stage") != "shadow_only" or
            payload.get("production_promotion_permitted") is not False):
        raise ValueError("modified or non-shadow plan")
    if sha256_file(payload["dataset_path"]) != payload["dataset_sha256"]:
        raise ValueError("dataset contents changed since freeze")
    if sha256_file(__file__) != payload.get("evaluator_source_sha256"):
        raise ValueError("evaluator source changed since freeze")
    for item in payload["checkpoints"].values():
        if snapshot_digest(item["snapshot_path"]) != item["sha256"]:
            raise ValueError("checkpoint contents changed since freeze")
    return payload, token


def softmax(values, temperature):
    shifted = [v / temperature for v in values]
    m = max(shifted)
    exp = [math.exp(v - m) for v in shifted]
    total = sum(exp)
    return [v / total for v in exp]


def fit_temperature(rows, indexed):
    calibration = [r for r in rows if indexed[r["sample_id"]]["split"] == "calibration"]
    if not calibration:
        raise ValueError("missing calibration predictions")
    def nll(temp):
        return sum(-math.log(max(softmax(r["logits"], temp)
                                     [indexed[r["sample_id"]]["label"]], 1e-15))
                   for r in calibration) / len(calibration)
    return min(TEMPERATURES, key=nll)


def metrics(rows, indexed, threshold):
    if not rows:
        return {"count": 0}
    correct, br, nl, bin_rows = [], [], [], [[] for _ in range(15)]
    ood_accept = 0
    for r in rows:
        y = indexed[r["sample_id"]]["label"]
        p = r["probabilities"]
        conf = max(p)
        ok = int(p.index(conf) == y)
        correct.append(ok)
        br.append(sum((v - float(i == y)) ** 2 for i, v in enumerate(p)) / len(p))
        nl.append(-math.log(max(p[y], 1e-15)))
        bin_rows[min(14, int(conf * 15))].append((conf, ok))
        if indexed[r["sample_id"]]["split"] == "ood":
            ood_accept += int(conf >= threshold)
    n = len(rows)
    ece = sum(len(group) / n *
              abs(sum(v[0] for v in group) / len(group) -
                  sum(v[1] for v in group) / len(group))
              for group in bin_rows if group)
    return {
        "count": n, "accuracy": sum(correct) / n,
        "multiclass_brier": sum(br) / n, "nll": sum(nl) / n,
        "ece_15": ece,
        "ood_false_acceptance": ood_accept / n if all(
            indexed[r["sample_id"]]["split"] == "ood" for r in rows) else None,
        "latency_p99_ms_unattested": quantile([r["latency_ms"] for r in rows], .99),
    }


def grouped_pair(indexed, candidate, baseline, split):
    groups = defaultdict(list)
    for sid, row in indexed.items():
        if row["split"] != split:
            continue
        y = row["label"]
        p = candidate[sid]["probabilities"]
        b = baseline[sid]["probabilities"]
        def correct(x):
            return float(x.index(max(x)) == y)
        def brier(x):
            return sum((v - float(i == y)) ** 2 for i, v in enumerate(x)) / len(x)
        groups[row["source_group"]].append((correct(p) - correct(b),
                                           brier(p) - brier(b)))
    return [tuple(sum(pair[k] for pair in items) / len(items) for k in (0, 1))
            for _, items in sorted(groups.items())]


def bootstrap(groups, seed, *, replicates=2000, alpha=.05 / 24):
    if not groups:
        raise ValueError("no independent paired groups")
    rng = random.Random(seed)
    n = len(groups)
    values = [[], []]
    for _ in range(replicates):
        indices = [rng.randrange(n) for _ in range(n)]
        for k in (0, 1):
            values[k].append(sum(groups[i][k] for i in indices) / n)
    return {
        "independent_source_groups": n,
        "accuracy_gain": sum(g[0] for g in groups) / n,
        "accuracy_gain_lower_bonferroni": quantile(values[0], alpha),
        "brier_delta": sum(g[1] for g in groups) / n,
        "brier_delta_upper_bonferroni": quantile(values[1], 1 - alpha),
        "passes_predictive_only": (
            quantile(values[0], alpha) > 0 and quantile(values[1], 1 - alpha) < 0),
    }


def evaluate(plan, run_receipts, prediction_rows, indexed, *,
             replicates=2000, comparison_scope="full"):
    if type(replicates) is not int or replicates < 1000:
        raise ValueError("at least 1000 grouped bootstrap samples required")
    if comparison_scope not in ("full", "equal_budget"):
        raise ValueError("unknown preregistered comparison scope")
    # Original full comparison remains strict. Raw HF encoder checkpoints
    # cannot be relabelled zero-shot DecisionModels without an upstream
    # pretrained typed Head. The narrower paired equal-budget report is
    # useful, but is explicitly NOT a complete model-vs-model assessment.
    phases = PHASES if comparison_scope == "full" else ("equal_budget",)
    expected = {f"{key}:{phase}" for key in SOURCES for phase in phases}
    runs = {}
    budgets = []
    for item in run_receipts:
        arm = item.get("arm")
        if arm not in expected or arm in runs:
            raise ValueError("duplicate or unknown run arm")
        model, phase = arm.split(":")
        original = plan["checkpoints"][model]
        if (item.get("checkpoint_sha256") != original["sha256"] or
                item.get("upstream_revision") != original["upstream_revision"] or
                item.get("dataset_sha256") != plan["dataset_sha256"] or
                item.get("runtime_profile") != {
                    "device": plan["device"], "dtype": plan["dtype"],
                    "batch_size": plan["batch_size"],
                    "context_tokens": plan["context_tokens"]} or
                item.get("training_sample_groups_sha256") != plan["training_sample_groups_sha256"] or
                item.get("seed") != plan["seed"] or
                item.get("physical_encoder_microbatch_ceiling", 1) !=
                plan.get("encoder_microbatch_size", 1) or
                item.get("truncated_input_count") != 0 or
                item.get("input_contract") != plan["input_contract"] or
                not check_sha(item.get("weights_sha256"))):
            raise ValueError("run provenance, training groups or input contract mismatch")
        if phase == "checkpoint":
            if item.get("train_steps") != 0 or item.get("trainable_parameters") != 0:
                raise ValueError("checkpoint phase cannot train on evaluation data")
            # Raw pretrained HF encoders have no typed Decision Head. Reject a
            # randomly initialized readout masquerading as a zero-shot model.
            if item.get("pretrained_typed_decision_head_present") is not True:
                raise ValueError("checkpoint missing genuinely pretrained typed Decision Head")
            if item.get("upstream_task_exposure") not in (
                    "task_specific", "generic_decision", "unknown"):
                raise ValueError("checkpoint task-pretraining exposure must be disclosed")
        else:
            n = item.get("trainable_parameters")
            if (item.get("train_steps") != plan["train_steps"] or
                    type(n) is not int or not 0 < n <= plan["trainable_parameter_budget"] or
                    item.get("optimizer") != "adamw" or item.get("training_split") != "train"):
                raise ValueError("fine-tuned arm has mismatched training budget")
            budgets.append(n)
        runs[arm] = item
    if set(runs) != expected:
        if comparison_scope == "full":
            raise ValueError("full four-model two-phase comparison is required")
        raise ValueError("all four equal-budget arms must have actual run evidence")
    if min(budgets) / max(budgets) < .90:
        raise ValueError("equal-budget arms differ by more than 10% trainable parameters")

    data = defaultdict(dict)
    required = {sid for sid, row in indexed.items() if row["split"] in SCORING}
    for r in prediction_rows:
        arm, sid = r.get("arm"), r.get("sample_id")
        if arm not in expected or sid not in required or sid in data[arm]:
            raise ValueError("duplicate, extra, or leaked train prediction")
        if any(field in r for field in ("label", "external_ndu_utility",
                                        "total_cost", "observer_digest")):
            raise ValueError("model-generated prediction cannot contain labels or NDU outcomes")
        logits = r.get("logits")
        if (not isinstance(logits, list) or
                len(logits) != plan["classes"] or
                any(type(x) not in (float, int) or not math.isfinite(x)
                    or abs(x) > 1e6 for x in logits)):
            raise ValueError("invalid aligned ordered-action logits")
        if r.get("input_digest") != input_fingerprint(indexed[sid]):
            raise ValueError("prediction input/source/options digest mismatch")
        latency = r.get("latency_ms")
        if (type(latency) not in (int, float) or not math.isfinite(latency)
                or latency < 0 or r.get("weights_sha256") != runs[arm]["weights_sha256"]):
            raise ValueError("unbound model weights or missing real latency measurement")
        data[arm][sid] = dict(r)
    if set(data) != expected or any(set(rows) != required for rows in data.values()):
        raise ValueError("incomplete paired candidate/sample coverage")

    reports = {}
    calibrated = {}
    for arm in sorted(expected):
        rows = data[arm]
        temperature = fit_temperature(list(rows.values()), indexed)
        for sid, r in rows.items():
            r["probabilities"] = softmax(r["logits"], temperature)
        cal_conf = [max(r["probabilities"]) for sid, r in rows.items()
                    if indexed[sid]["split"] == "calibration"]
        cutoff = quantile(cal_conf, .2)  # 80% ID calibration coverage
        calibrated[arm] = rows
        reports[arm] = {
            "temperature_calibration_only": temperature,
            "confidence_threshold_calibration_only": cutoff,
            "trained_parameters_reported": runs[arm]["trainable_parameters"],
            "weight_digest_reported": runs[arm]["weights_sha256"],
            "by_split": {
                split: metrics([r for sid, r in rows.items() if indexed[sid]["split"] == split],
                               indexed, cutoff) for split in SCORING},
        }
    pairs = {}
    for phase in phases:
        base = calibrated["laya_original:" + phase]
        for key in SOURCES:
            if key == "laya_original":
                continue
            arm = key + ":" + phase
            pairs[arm] = {
                window: bootstrap(
                    grouped_pair(indexed, calibrated[arm], base, window),
                    plan["seed"] + i, replicates=replicates)
                for i, window in enumerate(("future_1", "future_2"))
            }
    return {
        "schema": "hepta.stem-cell-decision-421m-review.v1",
        "status": "offline_predictive_diagnostic_only",
        "production_promotion_permitted": False,
        "independent_ndu_signature_verified": False,
        "owner_backend_receipts_authenticated": False,
        "model_weights_executed_by_this_script": False,
        "full_comparison_present": comparison_scope == "full",
        "comparison_scope": comparison_scope,
        "checkpoint_comparison_status": (
            "operator_claimed_pretrained_typed_heads_not_proven_zero_shot"
            if comparison_scope == "full"
            else "NOT_COMPARABLE_missing_genuine_HF_pretrained_decision_heads"),
        "excluded_checkpoint_arms": (
            sorted(f"{key}:checkpoint" for key in SOURCES)
            if comparison_scope == "equal_budget" else []),
        "checkpoint_is_not_proven_zero_shot": True,
        "pretrained_typed_checkpoint_head_required": True,
        "brier_definition": "sum_squared_class_error_divided_by_number_of_options",
        "trainable_parameter_ratio": min(budgets) / max(budgets),
        "arm_metrics": reports, "paired_future_vs_original_laya": pairs,
        "limitations": [
            "Model and run metadata are operator assertions, not signed owner receipts",
            "Checkpoint arms may contain upstream task-specific supervised training",
            "Equal-budget-only report cannot establish superior zero-shot decisions",
            "Equal trainable parameters and steps do not prove equal total FLOPs",
            "Descriptive held-out labels are not independently authenticated NDU utility",
            "No production worker, Cell state/CAS, recovery or 4096 Cell evidence",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--dataset", required=True)
    p.add_argument("--descriptors", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--train-steps", type=int, required=True)
    p.add_argument("--trainable-budget", type=int, default=262144)
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--encoder-microbatch-size", type=int, default=1)
    p.add_argument("--context-tokens", type=int, default=512)
    p.add_argument("--seed", type=int, default=7347)
    p.add_argument("--device", required=True)
    p.add_argument("--dtype", choices=("fp32", "bf16", "fp16"), required=True)
    p = sub.add_parser("evaluate")
    p.add_argument("--plan", required=True)
    p.add_argument("--runs", required=True)
    p.add_argument("--predictions", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--bootstrap-replicates", type=int, default=2000)
    p.add_argument("--comparison-scope", choices=("full", "equal_budget"),
                   default="full",
                   help="equal_budget never fabricates HF pretrained Decision Heads")
    a = parser.parse_args()
    if a.command == "plan":
        records = json.loads(Path(a.descriptors).read_text(encoding="utf-8"), object_pairs_hook=no_duplicate_json_keys)
        write_frozen(a.output, build_plan(
            a.dataset, records, train_steps=a.train_steps,
            trainable_budget=a.trainable_budget, batch_size=a.batch_size,
            context_tokens=a.context_tokens, seed=a.seed, device=a.device,
            dtype=a.dtype, encoder_microbatch_size=a.encoder_microbatch_size))
    else:
        plan, token = load_plan(a.plan)
        indexed, _, groups = audit_dataset(list(read_strict_jsonl(plan["dataset_path"])))
        if groups != plan["training_sample_groups_sha256"]:
            raise ValueError("training group lineage changed")
        report = evaluate(
            plan, json.loads(Path(a.runs).read_text(encoding="utf-8"), object_pairs_hook=no_duplicate_json_keys),
            list(read_strict_jsonl(a.predictions)), indexed,
            replicates=a.bootstrap_replicates,
            comparison_scope=a.comparison_scope)
        report.update({
            "plan_sha256": token,
            "run_receipts_sha256": sha256_file(a.runs),
            "predictions_sha256": sha256_file(a.predictions),
            "dataset_sha256": plan["dataset_sha256"],
            "independent_outcomes_supplied": False,
        })
        write_frozen(a.output, report)


if __name__ == "__main__":
    main()
