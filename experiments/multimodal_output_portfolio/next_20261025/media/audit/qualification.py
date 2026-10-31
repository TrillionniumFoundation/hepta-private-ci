"""Recompute both fixed endpoints and describe their shared speaker clusters."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import random
import time


PRIMARY = "consensus_or_single_v3"
COMPONENTS = ("base.en", "small.en")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def percentile(values, probability):
    position = (len(values) - 1) * probability
    low = int(position)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (position - low)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "allocation", "process-receipt", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Never replace a completed qualification audit")
    cost = json.loads(args.process_receipt.read_text())
    if cost["returncode"] != 0:
        raise ValueError("No complete-qualification inference from an interrupted child")
    allocation = json.loads(args.allocation.read_text())
    expected = allocation["recordings"]
    summary = json.loads((args.run / "summary.json").read_text())
    asr_summary = json.loads((args.run / "asr/summary.json").read_text())
    ingress_summary = json.loads((args.run / "ingress/summary.json").read_text())
    asr_paths = sorted((args.run / "asr").glob("row-*.json"))
    asr = [json.loads(path.read_text()) for path in asr_paths]
    ingress = json.loads((args.run / "ingress/observations.json").read_text())
    if len(asr) != 300 or len(ingress) != 300 or len(expected) != 300:
        raise ValueError("Registered 300-row cohort incomplete")
    endpoints = [*COMPONENTS, PRIMARY, "input_classifier"]
    correct = Counter()
    by_speaker = defaultdict(lambda: Counter())
    confusion = {name: defaultdict(Counter) for name in endpoints}
    abstentions = Counter()
    wrong_accepted = Counter()
    source_bytes = defaultdict(list)
    agreement = Counter()
    for index, (observed, classified, source) in enumerate(zip(asr, ingress, expected)):
        if observed["source"] != source or classified["source"] != source:
            raise ValueError("Actual observation source identity or ordering changed")
        target = source["label"]
        if observed["expected_after_observation"] != target or classified["expected_after_observation"] != target:
            raise ValueError("Post-observation expected label changed")
        predictions = dict(observed["observed_without_target"]["predictions"])
        a, b = (predictions[name] for name in COMPONENTS)
        recomputed = a if a == b else b if a is None else a if b is None else None
        if predictions[PRIMARY] != recomputed:
            raise ValueError("Fixed target-free ensemble rule differs from recorded prediction")
        predictions["input_classifier"] = classified["predicted_digit_without_target"]
        group = by_speaker[source["speaker"]]
        group["n"] += 1
        source_bytes[source["sha256"]].append({"index": index, "path": source["path"], "speaker": source["speaker"]})
        for name in endpoints:
            prediction = predictions[name]
            if prediction is not None and prediction not in range(10):
                raise ValueError("Unexpected prediction class")
            success = prediction == target
            saved = classified["correct"] if name == "input_classifier" else observed["correct"][name]
            if success != saved:
                raise ValueError("Recorded score disagrees with target-free prediction")
            correct[name] += int(success)
            group[name] += int(success)
            confusion[name][str(target)]["abstain" if prediction is None else str(prediction)] += 1
            abstentions[name] += int(prediction is None)
            wrong_accepted[name] += int(prediction is not None and not success)
        agreement[str((predictions[PRIMARY] == target, predictions["input_classifier"] == target))] += 1
    if len(by_speaker) != 147:
        raise ValueError("Registered independent speaker census changed")
    accuracy = {name: correct[name] / 300 for name in endpoints}
    for name in (*COMPONENTS, PRIMARY):
        if accuracy[name] != asr_summary["accuracy"][name]:
            raise ValueError("ASR summary score differs from all saved observations")
    if accuracy["input_classifier"] != ingress_summary["qualification_accuracy"]:
        raise ValueError("Classifier summary differs from all saved observations")
    eligible = {name: accuracy[name] >= .85 for name in endpoints}
    if (eligible[PRIMARY] != asr_summary["primary_eligible"]
            or eligible["input_classifier"] != ingress_summary["qualification_pass"]
            or (eligible[PRIMARY] and eligible["input_classifier"]) != summary["both_eligible"]):
        raise ValueError("Eligibility differs from the original unchanged point gates")
    clusters = [by_speaker[key] for key in sorted(by_speaker)]
    rng = random.Random(23919)
    samples = {name: [] for name in endpoints}
    for _ in range(5000):
        draw = [clusters[rng.randrange(len(clusters))] for _ in clusters]
        denominator = sum(row["n"] for row in draw)
        for name in endpoints:
            samples[name].append(sum(row[name] for row in draw) / denominator)
    intervals = {}
    for name, values in samples.items():
        values.sort()
        intervals[name] = [percentile(values, .025), percentile(values, .975)]
    result = {"schema": "hepta.next.media-shared-qualification-audit.v1", "status": "passed",
              "recorded_unix_ns": time.time_ns(), "registered_recordings": 300,
              "unique_original_wav_sha256": len(source_bytes), "speaker_clusters": len(clusters),
              "same_cohort_correlated_endpoints": True, "independent_replications_claimed": False,
              "duplicate_bytes": [rows for rows in source_bytes.values() if len(rows) > 1],
              "correct": dict(correct), "accuracy": accuracy, "unchanged_point_gate": .85,
              "eligible": eligible, "both_primary_and_input_eligible": summary["both_eligible"],
              "abstentions": dict(abstentions), "incorrect_nonempty_predictions": dict(wrong_accepted),
              "confusion": {name: {key: dict(value) for key, value in matrix.items()} for name, matrix in confusion.items()},
              "primary_and_input_joint_correctness": dict(agreement),
              "speaker_cluster_bootstrap": {"draws": 5000, "seed": 23919, "confidence": .95,
                     "intervals": intervals, "scope": "Descriptive marginal intervals; no multiplicity-adjusted certificate or replacement gate"},
              "whole_child_process_cost": cost, "actual_output_row_files": len(asr_paths),
              "asr_actual_wav_events": len(list((args.run / "asr/observed-events").glob("*.wav"))),
              "frozen_inputs": {str(args.allocation.resolve()): sha(args.allocation),
                                str(args.process_receipt.resolve()): sha(args.process_receipt),
                                str(Path(__file__).resolve()): sha(__file__)},
              "no_model_selection_or_threshold_changes": True, "reserved_media_confirmation_opened_by_audit": False}
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"audit": "passed", "correct": dict(correct), "both_eligible": summary["both_eligible"],
                      "speaker_clusters": len(clusters), "unique_wav_sha256": len(source_bytes)}))


if __name__ == "__main__":
    main()
