"""Writer/speaker-connected inference for a fixed three-seed joint model panel."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def metrics(rows, gamma):
    utility = np.array([row["utility"] for row in rows], dtype=float)
    joint = np.array([row["score"]["joint_success"] for row in rows], dtype=float)
    return {"mean_utility": float(utility.mean()),
            "CE": float(-np.log(np.exp(-gamma * utility).mean()) / gamma),
            "joint_success": float(joint.mean()),
            **{name + "_success": float(np.mean([row["score"]["success"][name] for row in rows]))
               for name in ("image", "text", "audio", "video")}}


def paired_interval(rows, spec):
    """Resample connected source groups while keeping arms and seeds paired.

    Eight groups contain two image writers because they share a speech speaker.
    Sixteen contain one. Resampling includes every observation in each selected
    group and therefore keeps that unequal source structure intact.
    """
    groups = sorted({row["connected_cluster"] for row in rows})
    arms = {profile: [row for row in rows if row["profile"] == profile]
            for profile in spec["profiles"]}
    actual = {profile: metrics(value, spec["gamma"]) for profile, value in arms.items()}
    difference = {key: actual["entropic"][key] - actual["mean"][key] for key in actual["mean"]}
    cells = {profile: {group: [row for row in values if row["connected_cluster"] == group]
                      for group in groups} for profile, values in arms.items()}
    rng = np.random.default_rng(spec["bootstrap"]["seed"])
    samples = {key: [] for key in difference}
    for _ in range(spec["bootstrap"]["replicates"]):
        chosen = rng.choice(groups, len(groups), replace=True)
        draw = {profile: metrics([row for group in chosen for row in cells[profile][group]], spec["gamma"])
                for profile in arms}
        for key in difference:
            samples[key].append(draw["entropic"][key] - draw["mean"][key])
    alpha = (1 - spec["bootstrap"]["level"]) / 2
    return {"groups": len(groups), "arms": actual,
            "difference_entropic_minus_mean": {
                key: {"estimate": value, "interval": np.quantile(samples[key], [alpha, 1 - alpha]).tolist()}
                for key, value in difference.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "protocol", "training", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    complete = json.loads((args.run / "completion.json").read_text())
    spec = json.loads(args.protocol.read_text())
    registration = json.loads((args.run / "registration.json").read_text())
    if complete["status"] != "completed" or registration["protocol_sha256"] != sha(args.protocol):
        raise ValueError("Require the completed registered confirmation")
    if complete["actual_outputs"] != 768 or len(complete["rows"]) != 768:
        raise ValueError("Every registered source/seed/profile must retain an actual output")
    rows = complete["rows"]
    identifiers = {(row["seed"], row["profile"], row["case"]) for row in rows}
    expected = {(seed, profile, case) for seed in spec["seeds"] for profile in spec["profiles"] for case in range(128)}
    if identifiers != expected or len(identifiers) != len(rows):
        raise ValueError("Duplicate, missing, or unregistered output")
    for row in rows:
        if row["connected_cluster"] != (row["case"] // 4) % 24:
            raise ValueError("Source group allocation changed")
        if row["input_route"] != spec["input_routes"][row["case"] % 4]:
            raise ValueError("Input route allocation changed")
        if row["utility"] != sum(row["score"]["success"].values()) / 4:
            raise ValueError("Declared actual-output utility differs")
    files = complete["physical_codec_files_sha256"]
    if len(files) != 3072 or any(sha(path) != expected for path, expected in files.items()):
        raise ValueError("Physical output evidence is missing or changed")
    primary = paired_interval(rows, spec)
    differences = primary["difference_entropic_minus_mean"]
    gates = {"CE_superiority": differences["CE"]["interval"][0] > 0,
             "joint_success_noninferiority": differences["joint_success"]["interval"][0] >= 0}
    descriptive = {}
    for profile in spec["profiles"]:
        selected = [row for row in rows if row["profile"] == profile]
        descriptive[profile] = {"by_route": {route: metrics([row for row in selected if row["input_route"] == route], spec["gamma"])
                                              for route in spec["input_routes"]},
                                "by_seed": {str(seed): metrics([row for row in selected if row["seed"] == seed], spec["gamma"])
                                            for seed in spec["seeds"]}}
        for field in ("generation_and_codec_ns", "whole_request_ns"):
            value = np.array([row[field] for row in selected], dtype=float) / 1e6
            descriptive[profile][field.replace("_ns", "_ms")] = {
                "mean": float(value.mean()), "p50": float(np.quantile(value, .5)), "p95": float(np.quantile(value, .95))}
    training = json.loads((args.training / "RESULTS.json").read_text())
    report = {"schema": "hepta.next.joint-analysis.v1", "status": "completed",
              "protocol_sha256": sha(args.protocol), "completion_sha256": sha(args.run / "completion.json"),
              "training_sha256": sha(args.training / "RESULTS.json"),
              "actual_outputs": 768, "actual_codec_files_verified": len(files),
              "source_pairs": 128, "image_writers": 32, "audio_speakers": 24, "independent_connected_groups": 24,
              "seeds": spec["seeds"], "seed_inference": "Conditional on this fixed trained panel; three seeds are not three hundred eighty-four independent sources",
              "primary": primary, "registered_gates": gates, "quality_claim_eligible": all(gates.values()),
              "descriptive_only": descriptive,
              "training_updates": {arm: {"all_five_components_changed": all(value["component_before"][key] != after
                                                                            for key, after in value["component_after"].items()),
                                          "all_five_components_received_gradient": all(value > 0 for value in value["gradient_abs_sum_max"].values())}
                                   for arm, value in training["arms"].items()},
              "cost_scope": {key: complete[key] for key in ("wall_ns", "cpu_ns", "child_codec_cpu_seconds", "peak_rss_bytes", "actual_event_asr_calls", "actual_event_cache_hits")},
              "limitations": ["Constructed digit tasks; twenty motion-transformed frames do not constitute natural-video generation",
                              "Wave decoder distills ten fixed teacher conditions; no open-vocabulary audio claim",
                              "Training uses sampled outputs and pre-codec proxy utility; deployment here is greedy with physical codecs and separate observers",
                              "No unchanged-generator arm: the between-arm comparison isolates the two continued-training objectives, not the gain from continued training itself",
                              "Fixed arm order and waveform-byte caching make cost comparisons descriptive",
                              "ASR point qualification does not certify all output distributions or unknown ASR pretraining data independence",
                              "Per-route and per-seed summaries are descriptive; the only registered superiority claim is the joint primary contrast"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"report": str(args.output), "registered_gates": gates, "primary": differences}), flush=True)


if __name__ == "__main__":
    main()
