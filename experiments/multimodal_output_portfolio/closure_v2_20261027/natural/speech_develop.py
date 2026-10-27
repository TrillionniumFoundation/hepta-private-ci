"""Fit a quality-constrained base-model continuation without new test inputs."""
import argparse
from pathlib import Path
import time

import numpy as np

from ...continuation_20261027.natural.speech_engine import SpeechEngine
from ...repair_20261026.natural.speech import score
from .common import freeze, read, save, sha, verify_frozen


def run(assets, output):
    source = Path(__file__).parent
    manifest = read(assets / "MANIFEST.json")
    output.mkdir(parents=True, exist_ok=False)
    spec = read(source / "SPEECH_PROTOCOL.json")
    registration = freeze(source, assets / "MANIFEST.json", output, spec)
    engine = SpeechEngine(manifest["base_model_directory"], 1)
    validation = [r for r in manifest["speech"] if r["role"] == "validation"]
    fitting = [r for r in manifest["speech"] if r["role"] == "train"]
    warmup = engine.episode(fitting[0]["path"], "fixed_greedy", -1000, output / "warmup")
    candidates, all_rows = [], []
    # Actually execute every threshold: candidate costs include routing and delivery.
    for candidate_index, threshold in enumerate(spec["thresholds"]):
        rows = []
        for item in validation:
            public = engine.episode(item["path"], "cached_continuation", threshold,
                output / "validation" / f"gate-{candidate_index}" / item["id"])
            rows.append({"id": item["id"], "speaker_id": item["speaker_id"], **public,
                **score(item["reference"], public["transcript"])})
        all_rows.extend({"candidate_index": candidate_index, "threshold": threshold, **r} for r in rows)
        candidates.append({"threshold": threshold, "mean_CPU": float(np.mean([r["whole_cpu_seconds"] for r in rows])),
            "word_errors": sum(r["word_errors"] for r in rows), "reference_words": sum(r["reference_words"] for r in rows),
            "continued_utterances": sum(r["decoder_calls"] == 2 for r in rows)})
        print({"speech_validation_threshold": threshold, "continued": candidates[-1]["continued_utterances"]}, flush=True)
    fixed = []
    for item in validation:
        public = engine.episode(item["path"], "fixed_beam5", -1000, output / "validation" / "fixed_beam5" / item["id"])
        fixed.append({"id": item["id"], "speaker_id": item["speaker_id"], **public,
            **score(item["reference"], public["transcript"])})
    for candidate in candidates:
        selected = [r for r in all_rows if r["threshold"] == candidate["threshold"]]
        groups = sorted({r["speaker_id"] for r in selected})
        matrix = []
        for speaker in groups:
            a = [r for r in selected if r["speaker_id"] == speaker]
            b = [r for r in fixed if r["speaker_id"] == speaker]
            matrix.append([sum(r["word_errors"] for r in a) - sum(r["word_errors"] for r in b), sum(r["reference_words"] for r in a)])
        matrix = np.asarray(matrix)
        rng = np.random.default_rng(2820)
        sample = matrix[rng.integers(len(groups), size=(5000, len(groups)))].sum(1)
        interval = np.quantile(sample[:, 0] / sample[:, 1], [.025, .975]).tolist()
        candidate["WER_difference_CI95"] = interval
        candidate["validation_quality_feasible"] = interval[1] <= .01
    feasible = [r for r in candidates if r["validation_quality_feasible"]]
    if not feasible:
        raise ValueError("Even always-continue failed exact beam5 equality or quality gate")
    chosen = min(feasible, key=lambda r: (r["mean_CPU"], r["threshold"]))
    save(output / "VALIDATION_ROWS.json", all_rows)
    save(output / "FIXED_ROWS.json", fixed)
    frozen = {"selected_threshold": chosen["threshold"], "choice": chosen, "candidates": candidates,
        "frozen_ns": time.time_ns(), "heldout_generation_not_started": True,
        "base_model_directory": manifest["base_model_directory"],
        "base_model_sha256": sha(Path(manifest["base_model_directory"]) / "model.bin"),
        "validation_speakers": manifest["groups"]["validation"], "model_parameters_updated": False}
    save(output / "FROZEN_MODEL.json", frozen)
    verify_frozen(registration)
    print(frozen, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.assets, args.output)
