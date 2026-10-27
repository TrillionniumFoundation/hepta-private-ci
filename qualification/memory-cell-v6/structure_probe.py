"""Bounded post-freeze structural controls with an equal arithmetic budget."""

import argparse
import copy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import statistics
import time

from native_router import FrozenRouter
from v5.contracts import INTENTS, REJECT, canonical, unlabeled, write_json
from v5.corpus import build_public_corpus
from v5.graph_runtime import GraphRuntime
from legacy_v3.numeric_graph import SERIES_NAMES, target_for


def verify_freeze(root):
    freeze = json.loads((root / "FREEZE.json").read_text())
    for name, identity in freeze["files"].items():
        raw = (root / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != identity["sha256"]:
            raise ValueError("frozen artifact/source changed: " + name)
    for name, identity in freeze["source_inventory"].items():
        if hashlib.sha256((root.parent / name).read_bytes()).hexdigest() != identity["sha256"]:
            raise ValueError("frozen dependency changed: " + name)
    return freeze


def metrics(rows, decisions):
    known = [(row, decision) for row, decision in zip(rows, decisions, strict=True) if row["intent"] in INTENTS]
    ood = [(row, decision) for row, decision in zip(rows, decisions, strict=True) if row["intent"] == REJECT]
    correct = sum(row["intent"] == decision["accepted_intent"] for row, decision in known)
    accepted = sum(decision["accepted"] for _, decision in known)
    return {"known": len(known), "correct": correct, "wrong": accepted - correct,
            "ood": len(ood), "false_accepted": sum(decision["accepted"] for _, decision in ood)}


def topology_probe(router, rows):
    requests = [unlabeled(row) for row in rows]
    encoded = [router.features(request) for request in requests]
    partitions = {"flat": (tuple(range(7)),), "split2": ((0, 1, 2), (3, 4, 5, 6)),
                  "split7": tuple((i,) for i in range(7))}
    predictions = {name: [router.decide(request, groups) for request in requests] for name, groups in partitions.items()}
    timings = {name: [] for name in partitions}
    for repeat in range(15):
        order = list(partitions)
        order = order[repeat % 3:] + order[:repeat % 3]
        for name in order:
            started = time.perf_counter_ns()
            scores = [router.linear_scores(features, partitions[name]) for features in encoded]
            timings[name].append((time.perf_counter_ns() - started) / len(encoded))
            if scores != [row["linear_scores"] for row in predictions["flat"]]:
                raise AssertionError("partition changed primitive numerical results")
    summaries = {}
    base = metrics(rows, predictions["flat"])
    baseline_time = statistics.median(timings["flat"])
    for name, groups in partitions.items():
        score = metrics(rows, predictions[name])
        median = statistics.median(timings[name])
        summaries[name] = {"groups": groups, "metrics": score, "identical_predictions": predictions[name] == predictions["flat"],
            "group_manifest_bytes": len(canonical(groups)), "cell_dispatches_per_request": len(groups),
            "scalar_multiply_adds_per_corpus": sum(7 * len(features) for features in encoded),
            "median_dispatch_ns_per_request": median, "interleaved_dispatch_samples_ns_per_request": timings[name],
            "adopted": name == "flat" or (score["correct"] > base["correct"] and score["wrong"] <= base["wrong"] and score["false_accepted"] <= base["false_accepted"] and median <= baseline_time * 1.10)}
    invalid = [((0, 1, 2), (2, 3, 4, 5, 6)), ((0, 1), (2, 3, 4, 5))]
    rejected = 0
    for groups in invalid:
        try:
            router.linear_scores(encoded[0], groups)
        except ValueError:
            rejected += 1
        else:
            raise AssertionError("invalid owner partition admitted")
    zero = copy.deepcopy(router)
    zero.weights = [[0.0 for value in row] for row in zero.weights]
    zero.bias = [0.0] * 7
    permuted = copy.deepcopy(router)
    permuted.weights = permuted.weights[1:] + permuted.weights[:1]
    permuted.bias = permuted.bias[1:] + permuted.bias[:1]
    ablations = {"zero_parameters": metrics(rows, [zero.decide(request) for request in requests]),
                "cyclic_head_reassignment": metrics(rows, [permuted.decide(request) for request in requests])}
    return {"candidates": summaries, "invalid_owner_partitions_rejected": rejected,
            "semantic_parameter_ablations": ablations, "active_split_adoptions": sum(summary["adopted"] for name, summary in summaries.items() if name != "flat"),
            "interpretation": "No information or arithmetic changes when identical heads are merely partitioned. Any timing change is scheduler overhead/noise, not intelligence gain."}


def numeric_probe(router, rows, assets):
    domain, date = "co2", "2020-07"
    graph = GraphRuntime(assets, domain, 26027, mode="parameter")
    exact = GraphRuntime(assets, domain, 26027, mode="strong")
    source = {"domain": domain, "years": list(exact.reader.years), "values": exact.reader.matrix.tolist()}
    names = ("parameter_connected", "parameter_removed", "parameter_permuted", "strong_planner", "parameter_oracle")
    summaries = {name: {"known_exact": 0, "composed_exact": 0, "hop_calls": 0, "numeric_coordinates": 0} for name in names}
    receipts = []
    for row in rows:
        request = {"utterance": row["template"].format(series_name=SERIES_NAMES[domain], date=date), "series_name": SERIES_NAMES[domain], "date": date}
        decision = router.decide(request)
        intent = decision["accepted_intent"]
        gold = row["intent"] if row["intent"] in INTENTS else None
        target = asdict(target_for(source, gold, (2020, 7))) if gold else None
        outputs = {name: graph.execute(request, intent, name) for name in names[:3]}
        outputs["strong_planner"] = exact.execute(request, intent, "strong_planner")
        outputs["parameter_oracle"] = graph.execute(request, gold, "parameter_connected")
        scored = {}
        for name, output in outputs.items():
            correct = target is not None and output["actual"] == target
            summaries[name]["known_exact"] += int(correct)
            summaries[name]["composed_exact"] += int(correct and gold != "at")
            summaries[name]["hop_calls"] += output["execution"]["calls"]
            summaries[name]["numeric_coordinates"] += output["numeric_coordinates_read"]
            scored[name] = {"exact": correct, "actual": output["actual"], "path": output["selected_path"]}
        receipts.append({"public_template_id": row["id"], "gold_operation": gold,
            "predicted_operation": intent, "target": target, "arms": scored})
    graph_receipt, exact_receipt = graph.receipt(), exact.receipt()
    return {"domain": domain, "date": date, "known_templates": sum(row["intent"] in INTENTS for row in rows),
            "composed_templates": sum(row["intent"] in INTENTS and row["intent"] != "at" for row in rows),
            "arms": summaries, "parameter_minus_strong_exact": summaries["parameter_connected"]["known_exact"] - summaries["strong_planner"]["known_exact"],
            "parameter_receipt": graph_receipt, "exact_receipt": exact_receipt, "rows": receipts,
            "unique_numeric_task_count": 6, "new_numeric_or_layout_training": False,
            "interpretation": "Recovered supplied arithmetic capabilities and learned layout; exact codec/planner receives identical language decisions. These repeated templates are not independent numeric tasks."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    frozen = verify_freeze(root)
    router = FrozenRouter(root / frozen["selected"]["model"], frozen["selected"]["artifact"]["sha256"])
    folds, _ = build_public_corpus()
    report = {"schema": "memory-cell-v6.bounded-structure-results.v1", "protocol_sha256": hashlib.sha256((root / "STRUCTURE_PROTOCOL.json").read_bytes()).hexdigest(),
        "semantic_freeze_sha256": hashlib.sha256((root / "FREEZE.json").read_bytes()).hexdigest(),
        "held_rows_read": 0, "topology": topology_probe(router, folds["development"]),
        "numeric": numeric_probe(router, folds["development"], root.parent / "memory-cell-v5" / "assets")}
    if verify_freeze(root) != frozen:
        raise AssertionError("inference mutated frozen source/model")
    write_json(args.output, report)
    print(json.dumps({"output": str(args.output), "split_adoptions": report["topology"]["active_split_adoptions"],
        "numeric_arms": report["numeric"]["arms"], "graph_minus_strong": report["numeric"]["parameter_minus_strong_exact"]}, sort_keys=True))


if __name__ == "__main__":
    main()
