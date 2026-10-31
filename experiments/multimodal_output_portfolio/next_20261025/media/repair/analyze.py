# Separate development repair; every earlier frozen candidate remains unchanged.
# V3 ensemble-specific execution; original V2 module is retained unchanged.
"""Recompute complete writer-cluster summaries from frozen actual media rows."""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import random
import statistics


MODES = ("image", "text", "audio", "video", "audio_video")


def percentile(values, probability):
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower = int(position)
    upper = min(len(ordered) - 1, lower + 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = json.loads((args.evaluation / "summary.json").read_text())
    if summary.get("status") != "completed" or summary.get("phase") != "confirmation":
        raise ValueError("Only closed prospective confirmation produces writer intervals")
    records = [json.loads(path.read_text()) for path in sorted(args.evaluation.glob("row-*.json"))]
    if len(records) != 640 or len({(row["index"], row["mode"]) for row in records}) != 640:
        raise ValueError("Require all five routes for all one hundred twenty-eight sources")
    sources, files, grouped = defaultdict(list), {}, defaultdict(lambda: defaultdict(list))
    for row in records:
        expected, observed = row["score"]["expected_after_observation"], row["observation"]
        relation = "less" if expected[0] < expected[1] else "greater" if expected[0] > expected[1] else "equal"
        checks = {"text": observed["caption_digits"] == expected and observed["caption_relation"] == relation,
                  "image": observed["image_digits"] == expected,
                  "audio": observed["speech"]["predictions"]["consensus_or_single_v3"] == expected,
                  "video": observed["video_digits"] == [d for d in expected for _ in range(10)]}
        joint = all(checks.values()) and observed["content_checks"]["moving_video"] and observed["content_checks"]["nonempty_audio"]
        if checks != row["score"]["success"] or joint != row["score"]["joint_success"]:
            raise ValueError("Stored score differs from target-free observations")
        grouped[row["writer"]][row["mode"]].append(int(joint))
        sources[row["index"]].append(row)
        for bundle in (row["input"], row["generation"]["output"]):
            for file in bundle["files"].values():
                if file["path"] in files and files[file["path"]] != file["sha256"]:
                    raise ValueError("Conflicting actual-file identity")
                files[file["path"]] = file["sha256"]
    if len(grouped) != 32 or any(len(values) != 4 for group in grouped.values() for values in group.values()):
        raise ValueError("Writer cluster census changed")
    if len(sources) != 128 or any(len(rows) != 5 or {row["mode"] for row in rows} != set(MODES) for rows in sources.values()):
        raise ValueError("Each source task must retain every input route")
    writer_speakers = defaultdict(set)
    for row in records:
        writer_speakers[row["writer"]].update(row["speech_speakers"])
    if (any(len(values) != 1 for values in writer_speakers.values())
            or len(set.union(*writer_speakers.values())) != 32):
        raise ValueError("Audio speakers are not independent across the declared writer clusters")
    for path, digest in files.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
            raise ValueError("Actual codec artifact changed after observation")
    writer_means = {writer: {mode: statistics.mean(group[mode]) for mode in MODES}
                    for writer, group in grouped.items()}
    writers, rng, boot = sorted(writer_means), random.Random(23917), {mode: [] for mode in MODES}
    for _ in range(5000):
        selected = [rng.choice(writers) for _ in writers]
        for mode in MODES:
            boot[mode].append(statistics.mean(writer_means[writer][mode] for writer in selected))
    per_mode = {}
    for mode in MODES:
        rows = [row for row in records if row["mode"] == mode]
        per_mode[mode] = {"strict_joint_correct": sum(row["score"]["joint_success"] for row in rows),
                          "tasks": len(rows),
                          "component_correct": {name: sum(row["score"]["success"][name] for row in rows)
                                                for name in ("text", "image", "audio", "video")},
                          "secondary_audio_correct": sum(row["score"]["secondary_audio_success"] for row in rows),
                          "writer_bootstrap_95_interval": [percentile(boot[mode], .025), percentile(boot[mode], .975)],
                          "mean_execution_ms": statistics.mean(row["execution_wall_ns"] for row in rows) / 1e6,
                          "mean_audit_included_ms": statistics.mean(row["execution_wall_ns"] + row["observation"]["audit_wall_ns"] for row in rows) / 1e6}
    result = {"schema": "hepta.next.media-repair-analysis.v1", "outputs": len(records),
              "source_tasks": len(sources), "independent_writer_speaker_clusters": len(writers),
              "per_mode": per_mode,
              "tasks_successful_in_all_five_routes": sum(all(row["score"]["joint_success"] for row in rows) for rows in sources.values()),
              "actual_artifact_sha256_checks": len(files), "all_hashes_matched": True,
              "bootstrap": {"resamples": 5000, "seed": 23917, "unit": "matched image-writer/audio-speaker cluster",
                            "intervals": "Descriptive per-route percentile95, not simultaneous lower-bound gates"},
              "all_original_numeric_sample_gates_pass": summary["all_media_sample_gates_pass"],
              "human_naturalness_or_foundation_model_claim": False}
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"writers": len(writers), "tasks": len(sources), "verified_files": len(files)}))


if __name__ == "__main__":
    main()
