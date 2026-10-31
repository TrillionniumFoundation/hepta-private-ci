"""Frozen-model cooperation, removal, and substitution audit; no new training.

Memory is a current source read, semantics uses a trained selector, and procedures
are exact registered functions. Breaking a path proves dependency, not superiority
of the cell vocabulary. Identical substitutes explicitly refute exclusivity.
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from adapter import Adapter
from baselines import BM25, NearestExample
import tasks


ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                   indent=2, allow_nan=False) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FixedExperts:
    """Load actual fixed experts and expose only their selected invocations."""

    def __init__(self, path, encoder_hash, source_version):
        self.description = read(path / "network.json")
        if self.description["partition"] != [list(range(i, i + 4)) for i in (0, 4, 8)]:
            raise ValueError("Expected the preregistered fixed semantic partition")
        if sha(path / "router.npy") != self.description["router_sha256"]:
            raise ValueError("Router identity mismatch")
        self.router = np.load(path / "router.npy", allow_pickle=False)
        self.experts = [Adapter.load(path / f"expert-{i}.npz",
                       expected_encoder_hash=encoder_hash,
                       expected_source_version=source_version) for i in range(3)]

    def predict(self, feature, disabled=None):
        logits = np.append(feature, 1.0) @ self.router
        weights = np.exp(logits - logits.max())
        weights /= weights.sum()
        selected = np.argsort(-weights, kind="stable")[:self.description["top_k"]]
        scores, calls = np.zeros(len(tasks.SKILLS)), []
        for group in selected:
            group = int(group)
            if group == disabled:
                calls.append({"group": group, "status": "disabled", "weight": float(weights[group])})
                continue
            values = self.experts[group].predict_proba(feature[None, :])[0]
            scores[self.description["partition"][group]] = values * weights[group]
            calls.append({"group": group, "status": "invoked", "weight": float(weights[group]),
                          "local_probabilities": values.tolist()})
        label = int(scores.argmax()) if scores.sum() > 0 else None
        return label, {"router_weights": weights.tolist(), "expert_calls": calls}


class Selectors:
    def __init__(self, inputs, results, model_dir):
        manifest = read(inputs / "encoder_manifest.json")
        self.single = Adapter.load(results / "seed-713/single.npz",
                      expected_encoder_hash=manifest["encoder_hash"],
                      expected_source_version=manifest["source_version"])
        self.fixed = FixedExperts(results / "seed-713/fixed", manifest["encoder_hash"],
                                  manifest["source_version"])
        train = read(inputs / "train_rows.json")
        with np.load(inputs / "train_features.npz", allow_pickle=False) as data:
            self.nearest = NearestExample(train, data["X"].copy())
        self.bm25 = BM25(train)
        if model_dir is None:
            raise ValueError("Cooperation requires live encoding of current and stale source contexts")
        from backend import FrozenEncoder
        self.encoder = FrozenEncoder(model_dir, threads=1)
        if self.encoder.manifest_hash != manifest["encoder_hash"]:
            raise ValueError("Encoder differs from the frozen training encoder")
        self.manifest = manifest

    def select(self, name, text, disabled=None):
        started, cpu = time.perf_counter_ns(), time.process_time_ns()
        if name == "bm25":
            label, score = self.bm25.predict(text)
            details = {"rank_score": score, "encoder_calls": 0}
        else:
            feature = self.encoder.encode([text])[0]
            details = {"encoder_calls": 1, "preencoded_feature_used": False}
            if name == "fixed":
                label, expert_trace = self.fixed.predict(feature, disabled)
                details.update(expert_trace)
            elif name == "nearest":
                label, score = self.nearest.predict(feature)
                details["cosine_score"] = score
            elif name == "single":
                probabilities = self.single.predict_proba(feature[None, :])[0]
                label = int(probabilities.argmax())
                details["probabilities"] = probabilities.tolist()
            else:
                raise ValueError("Unknown selector")
        return label, {"stage": "semantic", "selector": name, "text": text, "label": label,
                       "wall_ns": time.perf_counter_ns() - started,
                       "cpu_ns": time.process_time_ns() - cpu, **details}


def procedure(label, payload, mode):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    output, error = None, None
    domain = tasks.SKILL_DOMAIN[tasks.SKILLS[label]] if label is not None else None
    try:
        if label is None or mode == "removed" or mode == f"disabled:{domain}":
            raise ValueError("ProcedureUnavailable")
        # The generic substitute uses exactly the same registered computation;
        # the typed domain wrapper cannot claim a different learned capability.
        output = tasks.execute(label, payload)
    except (ValueError, TypeError, ArithmeticError, csv.Error, OverflowError) as exc:
        error = type(exc).__name__ + ":" + str(exc)
    return output, {"stage": "procedure", "mode": mode, "predicted_domain": domain,
                    "label": label, "output": output, "error": error,
                    "shared_exact_executor": True, "wall_ns": time.perf_counter_ns() - started,
                    "cpu_ns": time.process_time_ns() - cpu}


def profile_run(case, arm, selectors):
    started, cpu, trace = time.perf_counter_ns(), time.process_time_ns(), []
    frontier = min(case["as_of"], 3) if arm == "memory_stale" else case["as_of"]
    source_start = time.perf_counter_ns()
    event = None if arm == "memory_removed" else tasks.resolve_profile(
        tasks.profile_journal(), case["project"], frontier)
    trace.append({"stage": "memory", "requested_frontier": case["as_of"],
                  "read_frontier": frontier, "source": event, "source_reads": int(event is not None),
                  "wall_ns": time.perf_counter_ns() - source_start})
    label = None
    if event is not None:
        if event["sequence"] > case["as_of"]:
            raise ValueError("Future source escaped its frontier")
        if arm == "current_exact_kv":
            label = tasks.SKILLS.index(event["operation_id"])
            trace.append({"stage": "semantic", "selector": "source_operation_id", "label": label})
        else:
            request = case.get("original_text", case["text"])
            text = f"Current project rule: {event['policy']}\nRequest: {request}"
            selector = arm.removeprefix("semantic_") if arm.startswith("semantic_") else "single"
            label, receipt = selectors.select(selector, text)
            trace.append(receipt)
    mode = arm.removeprefix("procedure_") if arm.startswith("procedure_") else "typed"
    output, receipt = procedure(label, case["payload"], mode)
    trace.append(receipt)
    return finish(case, arm, output, trace, started, cpu)


def composition_run(case, arm, selectors):
    started, cpu, trace = time.perf_counter_ns(), time.process_time_ns(), []
    value, mode = case["initial_payload"], "typed"
    selector = arm.removeprefix("semantic_") if arm.startswith("semantic_") else "fixed"
    disabled = int(arm.rsplit(":", 1)[1]) if arm.startswith("expert_disabled:") else None
    if arm.startswith("procedure_"):
        mode = arm.removeprefix("procedure_")
    for step, text in enumerate(case["steps"]):
        label, receipt = selectors.select(selector, text, disabled)
        trace.append({"step": step, **receipt})
        value, receipt = procedure(label, value, mode)
        trace.append({"step": step, **receipt})
        if receipt["error"] is not None:
            break
    return finish(case, arm, value, trace, started, cpu)


def finish(case, arm, output, trace, started, cpu):
    valid = all(item.get("error") is None for item in trace)
    # Expected data is read only after every inference and execution has ended.
    return {"id": case["id"], "arm": arm, "output": output, "trace": trace,
            "correct": valid and tasks.canonical(output) == tasks.canonical(case["expected"]),
            "expected_output": case["expected"], "valid_execution": valid,
            "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu}


def summarize(records):
    full = {row["id"]: row for row in records if row["arm"] == "full"}
    result = {}
    for arm in sorted({row["arm"] for row in records}):
        group = [row for row in records if row["arm"] == arm]
        same = sum(tasks.canonical(row["output"]) == tasks.canonical(full[row["id"]]["output"])
                   and row["valid_execution"] == full[row["id"]]["valid_execution"] for row in group)
        result[arm] = {"evaluated": len(group), "correct": sum(row["correct"] for row in group),
                       "identical_output_and_status_to_full": same,
                       "exclusive_functional_advantage_supported": False,
                       "interpretation": ("substitute matches full; no exclusive capability shown"
                                          if arm != "full" and same == len(group)
                                          else "dependency/substitution diagnostic, not evidence of statistical superiority"),
                       "wall_ms_sum": sum(row["wall_ns"] for row in group) / 1e6,
                       "cpu_ms_sum": sum(row["cpu_ns"] for row in group) / 1e6}
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, default=ROOT / "evidence/inputs")
    parser.add_argument("--results", type=Path, default=ROOT / "evidence/run")
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/cooperation")
    parser.add_argument("--model-dir", type=Path, required=True, help="Pinned encoder for actual per-request inference")
    args = parser.parse_args()
    for name, expected in read(args.inputs / "FREEZE.json")["source_hashes"].items():
        if sha(ROOT / name) != expected:
            raise ValueError(f"Original frozen source changed: {name}")
    for name, identity in read(args.inputs / "INVENTORY.json").items():
        if sha(args.inputs / name) != identity["sha256"]:
            raise ValueError(f"Frozen input identity mismatch: {name}")
    args.output.mkdir(parents=True, exist_ok=False)
    artifacts = sorted((args.results / "seed-713/fixed").glob("*")) + [args.results / "seed-713/single.npz"]
    proposal = {"source_sha256": sha(__file__), "seed": 713, "training_added": False,
                "artifacts": {str(path): {"sha256": sha(path), "bytes": path.stat().st_size} for path in artifacts},
                "statistical_claim": "fixed finite functional audit; no new efficacy selection",
                "encoder_timing": "live per-request encoding including stale-source contexts",
                "memory_kind": "current explicit journal read, not a parametric memory cell"}
    write(args.output / "FREEZE.json", proposal)
    selectors = Selectors(args.inputs, args.results, args.model_dir)
    profiles, compositions = read(args.inputs / "hybrid_rows.json"), read(args.inputs / "composition_rows.json")
    shared = ["procedure_removed", "procedure_generic"] + [f"procedure_disabled:{d}" for d in tasks.DOMAINS]
    specs = [("profile", profiles, ["full", "memory_removed", "memory_stale", "current_exact_kv",
              "semantic_nearest", "semantic_bm25", "semantic_fixed"] + shared, profile_run),
             ("composition", compositions, ["full", "semantic_single", "semantic_nearest", "semantic_bm25"]
              + [f"expert_disabled:{i}" for i in range(3)] + shared, composition_run)]
    summaries = {}
    with (args.output / "PREDICTIONS.jsonl").open("w", encoding="utf-8") as stream:
        for family, cases, arms, runner in specs:
            records = []
            for arm in arms:
                for case in cases:
                    record = {"family": family, **runner(case, arm, selectors)}
                    stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                    stream.flush()
                    records.append(record)
            summaries[family] = summarize(records)
    write(args.output / "RESULTS.json", {**proposal, "families": summaries,
          "encoder_stats": selectors.encoder.stats, "preencoded_feature_reads": 0,
          "preprocessing_ledger": {key: selectors.manifest[key] for key in ("stats", "wall_seconds", "cpu_seconds")},
          "cost_scope": "local requests plus separately reported shared feature preparation and checkpoint files; training, queueing and deployment are not measured here",
          "same_executor_limitation": "typed and generic procedure arms call the same exact operation; matching outputs cannot establish a specialized-procedure benefit"})


if __name__ == "__main__":
    main()
