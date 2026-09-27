#!/usr/bin/env python3
"""Offline retrieval/head-learning experiment, never a runtime selector.

Annotations are supplied separately from model inputs. This evaluates retrieval
labels, not causal task utility, full NDU, or longitudinal production efficacy.
All artifacts are candidate-only; the existing native evaluator/selector remains
responsible for any later adoption. No second store, executor or authority exists.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from dataclasses import asdict, dataclass
import math
from pathlib import Path
import re
import sys
import time
from typing import Any

try:
    from .hepta_laya_retrieval import (
        PinnedLaya, PredictionPort, Rejected, Request, Source, canonical,
        digest, identity, integer, require_digest, score, strict_json,
    )
except ImportError:  # Direct script execution, not an alternate model backend.
    from hepta_laya_retrieval import (
        PinnedLaya, PredictionPort, Rejected, Request, Source, canonical,
        digest, identity, integer, require_digest, score, strict_json,
    )

SPLITS = frozenset({"train", "calibration", "future", "retention"})
ARMS = ("lexical", "classifier", "laya_no_change", "laya_head")


@dataclass(frozen=True)
class Budget:
    per_request_ms: int = 5000
    max_total_input_tokens: int = 131072
    max_elapsed_ms: int = 600000
    minimum_train: int = 32
    epochs: int = 40

    def validate(self) -> None:
        integer(self.per_request_ms, 1, 60000)
        integer(self.max_total_input_tokens, 1, 100000000)
        integer(self.max_elapsed_ms, 1, 3600000)
        integer(self.minimum_train, 1, 100000)
        integer(self.epochs, 1, 200)


def dataset_rows(dataset: dict[str, Any], outcomes: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate disjoint tasks and event-time splits before loading a model."""
    if set(dataset) != {"schema", "workspace_id", "objective_digest", "rows"}:
        raise Rejected("unknown or missing dataset fields")
    if dataset["schema"] != "hepta.retrieval.dataset.v1":
        raise Rejected("unknown dataset version")
    identity(dataset["workspace_id"])
    require_digest(dataset["objective_digest"])
    if set(outcomes) != {"schema", "dataset_digest", "observer_id", "labels"}:
        raise Rejected("unknown or missing observation fields")
    if outcomes["schema"] != "hepta.retrieval.annotations.v1" or outcomes["dataset_digest"] != digest(dataset):
        raise Rejected("annotations belong to a different dataset")
    identity(outcomes["observer_id"])
    if not isinstance(dataset["rows"], list) or not 1 <= len(dataset["rows"]) <= 10000:
        raise Rejected("dataset size outside profile")
    if not isinstance(outcomes["labels"], list):
        raise Rejected("invalid annotations")
    labels = {}
    for label in outcomes["labels"]:
        if set(label) != {"row_id", "correct_source", "observed_at_ms"}:
            raise Rejected("invalid annotation fields")
        identity(label["row_id"])
        integer(label["observed_at_ms"], 1, 2**63 - 1)
        if label["row_id"] in labels:
            raise Rejected("duplicate annotation")
        labels[label["row_id"]] = label
    seen = set()
    groups: dict[str, str] = {}
    queries: dict[str, str] = {}
    rows = []
    for row in dataset["rows"]:
        if set(row) != {"row_id", "group_id", "split", "event_at_ms", "query", "sources"}:
            raise Rejected("invalid input fields; outcome labels cannot enter model inputs")
        identity(row["row_id"])
        identity(row["group_id"])
        integer(row["event_at_ms"], 1, 2**63 - 1)
        split = row["split"]
        if split not in SPLITS or row["row_id"] in seen:
            raise Rejected("invalid split or duplicate row")
        seen.add(row["row_id"])
        if groups.setdefault(row["group_id"], split) != split:
            raise Rejected("task group crosses train/evaluation boundary")
        if not isinstance(row["query"], str):
            raise Rejected("invalid query")
        query = " ".join(row["query"].casefold().split())
        if queries.setdefault(query, split) != split:
            raise Rejected("normalized query crosses train/evaluation boundary")
        if not isinstance(row["sources"], list):
            raise Rejected("invalid sources")
        sources = tuple(Source(**source) for source in row["sources"])
        Request(row["row_id"], dataset["workspace_id"], 1, dataset["objective_digest"],
                digest(row), "1" * 64, 2, row["query"], sources).validate(1)
        label = labels.get(row["row_id"])
        if label is None or label["observed_at_ms"] < row["event_at_ms"]:
            raise Rejected("missing or premature annotation")
        correct = label["correct_source"]
        if correct is not None and correct not in {s.source_id for s in sources}:
            raise Rejected("annotation is not an admitted source")
        rows.append({**row, "sources": sources, "correct_source": correct,
                     "observed_at_ms": label["observed_at_ms"]})
    if set(labels) != seen:
        raise Rejected("unmatched annotations")
    by_split = {split: [r for r in rows if r["split"] == split] for split in SPLITS}
    # All partitions are explicit, including old-task retention. Labels arriving
    # after a later evaluation window would leak knowledge into the candidate.
    if any(not partition for partition in by_split.values()):
        raise Rejected("all train/calibration/future/retention partitions are required")
    train_end = max(r["observed_at_ms"] for r in by_split["train"])
    calibration_start = min(r["event_at_ms"] for r in by_split["calibration"])
    calibration_end = max(r["observed_at_ms"] for r in by_split["calibration"])
    future_start = min(r["event_at_ms"] for r in by_split["future"])
    if not train_end < calibration_start or not calibration_end < future_start:
        raise Rejected("future-time evaluation overlaps training or calibration knowledge")
    return sorted(rows, key=lambda r: r["row_id"])


def features(row: dict[str, Any], labels: tuple[str | None, ...], ppm: tuple[int, ...],
             *, use_model: bool) -> list[tuple[float, ...]]:
    query = set(re.findall(r"\w+", row["query"].casefold()))
    sources = {s.source_id: s for s in row["sources"]}
    result = []
    for label, probability in zip(labels, ppm, strict=True):
        text = "" if label is None else sources[label].text
        overlap = len(query & set(re.findall(r"\w+", text.casefold()))) / max(1, len(query))
        result.append((math.log(max(probability / 1000000, 1e-6)) if use_model else 0.0,
                       overlap, float(label is None), float(label is not None)))
    return result


def distribution(weights: list[float], vectors: list[tuple[float, ...]], temperature: float = 1.0) -> list[float]:
    logits = [math.fsum(w * x for w, x in zip(weights, vector, strict=True)) / temperature
              for vector in vectors]
    normal = max(logits)
    values = [math.exp(value - normal) for value in logits]
    total = math.fsum(values)
    return [v / total for v in values]


def train_head(records: list[dict[str, Any]], *, use_model: bool, budget: Budget,
               deadline_ns: int | None = None) -> dict[str, Any]:
    """Fit a four-parameter candidate head; never mutate Laya/base parameters."""
    train = [r for r in records if r["split"] == "train"]
    weights = [1.0 if use_model else 0.0, 0.0, 0.0, 0.0]
    if len(train) < budget.minimum_train:
        return {"status": "no_update_insufficient_data", "weights": weights, "temperature": 1.0,
                "training_rows": len(train), "training_us": 0, "calibration_us": 0}
    started = time.perf_counter_ns()
    for _ in range(budget.epochs):
        if deadline_ns is not None and time.perf_counter_ns() >= deadline_ns:
            raise Rejected("training budget exhausted")
        gradient = [0.0] * 4
        for record in train:
            vectors = record["model_features" if use_model else "lexical_features"]
            p = distribution(weights, vectors)
            target = record["labels"].index(record["correct_source"])
            for j, vector in enumerate(vectors):
                for k, feature in enumerate(vector):
                    gradient[k] += (p[j] - float(j == target)) * feature / len(train)
        weights = [max(-8.0, min(8.0, w - 0.2 * (g + 0.001 * w)))
                   for w, g in zip(weights, gradient, strict=True)]
        if not use_model:
            weights[0] = 0.0
    training_us = (time.perf_counter_ns() - started) // 1000
    calibration = [r for r in records if r["split"] == "calibration"]
    if not calibration:
        raise Rejected("calibration partition required")
    started = time.perf_counter_ns()
    def loss(temperature):
        return math.fsum(-math.log(max(distribution(
            weights, r["model_features" if use_model else "lexical_features"], temperature
        )[r["labels"].index(r["correct_source"])], 1e-12)) for r in calibration)
    temperature = min((0.5, 1.0, 2.0, 4.0), key=loss)
    return {"status": "candidate_only", "weights": weights, "temperature": temperature,
            "training_rows": len(train), "training_us": training_us,
            "calibration_us": (time.perf_counter_ns() - started) // 1000}


def experiment(dataset: dict[str, Any], outcomes: dict[str, Any], port: PredictionPort,
               budget: Budget) -> dict[str, Any]:
    budget.validate()
    rows = dataset_rows(dataset, outcomes)
    require_digest(port.bundle_digest)
    started = time.perf_counter_ns()
    maximum_tokens = getattr(port, "maximum_input_tokens", None)
    integer(maximum_tokens, 1, 131072)
    records = []
    input_tokens = 0
    for row in rows:
        elapsed_ms = (time.perf_counter_ns() - started) // 1000000
        remaining_ms = budget.max_elapsed_ms - elapsed_ms
        if remaining_ms <= 0 or input_tokens + maximum_tokens > budget.max_total_input_tokens:
            raise Rejected("experiment budget exhausted; no partial efficacy report")
        now = lambda: time.monotonic_ns() // 1000000
        request = Request(row["row_id"], dataset["workspace_id"], 1,
                          dataset["objective_digest"], digest({k: v for k, v in row.items()
                          if k not in {"correct_source", "observed_at_ms", "sources"}} | {
                              "sources": [asdict(s) for s in row["sources"]]}),
                          port.bundle_digest, now() + min(budget.per_request_ms, remaining_ms),
                          row["query"], row["sources"])
        # This is an immutable offline dataset, NOT a source authority callback.
        receipt = score(request, port, now_ms=now, current=lambda _: True)
        input_tokens += receipt["input_tokens"]
        if receipt["input_tokens"] > maximum_tokens or input_tokens > budget.max_total_input_tokens:
            raise Rejected("observed token budget exceeded; no partial efficacy report")
        labels = receipt["labels"]
        ppm = receipt["prediction_ppm"]
        records.append({**row, "labels": labels, "receipt": receipt,
                        "model_features": features(row, labels, ppm, use_model=True),
                        "lexical_features": features(row, labels, ppm, use_model=False)})
    deadline = started + budget.max_elapsed_ms * 1000000
    classifier = train_head(records, use_model=False, budget=budget, deadline_ns=deadline)
    head = train_head(records, use_model=True, budget=budget, deadline_ns=deadline)
    metrics = {}
    for arm in ARMS:
        metrics[arm] = {}
        for split in ("future", "retention"):
            partition = [r for r in records if r["split"] == split]
            correct = abstained = 0
            total_loss = total_brier = 0.0
            eval_started = time.perf_counter_ns()
            for r in partition:
                if arm == "lexical":
                    overlaps = [v[1] for v in r["lexical_features"]]
                    chosen = max(range(len(overlaps)), key=lambda i: (overlaps[i], -i))
                    p = [float(i == chosen) for i in range(len(overlaps))]
                elif arm == "laya_no_change" or (arm == "laya_head" and head["status"] != "candidate_only"):
                    p = [v / 1000000 for v in r["receipt"]["prediction_ppm"]]
                else:
                    candidate = head if arm == "laya_head" else classifier
                    p = distribution(candidate["weights"], r["model_features" if arm == "laya_head"
                                         else "lexical_features"], candidate["temperature"])
                choice = max(range(len(p)), key=lambda i: (p[i], -i))
                target = r["labels"].index(r["correct_source"])
                correct += choice == target
                abstained += choice == 0
                total_loss -= math.log(max(p[target], 1e-12))
                total_brier += math.fsum((v - float(i == target)) ** 2 for i, v in enumerate(p))
            uses_laya = arm.startswith("laya")
            metrics[arm][split] = {
                "rows": len(partition), "correct": correct, "abstained": abstained,
                "accuracy": correct / len(partition), "log_loss": total_loss / len(partition),
                "brier": total_brier / len(partition),
                "scoring_us": (time.perf_counter_ns() - eval_started) // 1000,
                "feature_inference_us": sum(r["receipt"]["latency_us"] for r in partition) if uses_laya else 0,
                "feature_input_tokens": sum(r["receipt"]["input_tokens"] for r in partition) if uses_laya else 0,
            }
    elapsed_us = (time.perf_counter_ns() - started) // 1000
    if elapsed_us > budget.max_elapsed_ms * 1000:
        raise Rejected("training/evaluation exceeded total budget; no efficacy report")
    report = {"schema": "hepta.laya.experiment.v1", "dataset_digest": digest(dataset),
              "annotations_digest": digest(outcomes), "observer_id": outcomes["observer_id"],
              "observer_authenticated": False, "bundle_digest": port.bundle_digest,
              "budget": asdict(budget), "metrics": metrics, "classifier": classifier, "head": head,
              "feature_collection_input_tokens": input_tokens, "total_elapsed_us": elapsed_us,
              "comparison": "common_ceiling_not_equal_realized_resources",
              "cost_note": "Feature collection shared once; each Laya arm charged its own inference cost. Training/calibration are separate. Hardware memory/power and native migration are not measured.",
              "no_change_included": True, "production_authority": False,
              "adoption": "not_selected", "causal_or_longitudinal_efficacy": False,
              "decisions": [{"row_id": r["row_id"], "split": r["split"],
                             "receipt": r["receipt"]} for r in records]}
    report["report_digest"] = digest(report)
    return report


def read_input(path: Path) -> Any:
    # Bounded regular offline inputs; never fetch URLs or recursively follow aliases.
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
        raise Rejected("experiment input outside file profile")
    return strict_json(path.read_bytes())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-root", required=True, type=Path)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--bundle-digest", required=True)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--annotations", required=True, type=Path)
    parser.add_argument("--budget", required=True, type=Path)
    args = parser.parse_args()
    dataset, outcomes = read_input(args.dataset), read_input(args.annotations)
    dataset_rows(dataset, outcomes)
    budget = Budget(**read_input(args.budget))
    budget.validate()
    load_start = time.perf_counter_ns()
    with redirect_stdout(sys.stderr):
        model = PinnedLaya(args.model_root, read_input(args.bundle), args.bundle_digest)
        load_us = (time.perf_counter_ns() - load_start) // 1000
        report = experiment(dataset, outcomes, model, budget)
    report.pop("report_digest")
    report["bundle_verification_and_load_us"] = load_us
    report["loading_cost_scope"] = "measured_separately_from_steady_state_experiment_budget"
    report["report_digest"] = digest(report)
    print(canonical(report).decode("utf-8"))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, TypeError, KeyError, OSError, ImportError) as error:
        print(f"No valid experiment result: {error}", file=sys.stderr)
        raise SystemExit(2) from error
