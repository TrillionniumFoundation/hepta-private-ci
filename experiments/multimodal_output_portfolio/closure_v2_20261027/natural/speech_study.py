"""One untouched-speaker qualification of the quality-constrained ASR policy."""
import argparse
from pathlib import Path
import time

import numpy as np

from ...continuation_20261027.natural.speech_engine import SpeechEngine
from ...repair_20261026.natural.speech import score
from .common import freeze, paired_ci, read, save, sha, verify_frozen


def summarize(rows, spec):
    summaries = {}
    for arm in spec["test_arms"]:
        group = [r for r in rows if r["arm"] == arm]
        first = [r for r in group if r["repetition"] == 0]
        summaries[arm] = {"word_errors": sum(r["word_errors"] for r in first),
            "reference_words": sum(r["reference_words"] for r in first),
            "mean_CPU": float(np.mean([r["cpu_seconds"] for r in group])),
            "mean_wall": float(np.mean([r["wall_seconds"] for r in group])),
            "encoder_calls_per_repetition": sum(r["encoder_calls"] for r in first),
            "decoder_calls_per_repetition": sum(r["decoder_calls"] for r in first)}
        summaries[arm]["WER"] = summaries[arm]["word_errors"] / summaries[arm]["reference_words"]
    comparisons = {}
    for baseline in ("fixed_beam5", "reencoded_continuation"):
        first = [r for r in rows if r["repetition"] == 0]
        groups = sorted({r["speaker_id"] for r in first})
        matrix = []
        equality = True
        for speaker in groups:
            a = sorted([r for r in first if r["speaker_id"] == speaker and r["arm"] == "cached_continuation"], key=lambda r: r["id"])
            b = sorted([r for r in first if r["speaker_id"] == speaker and r["arm"] == baseline], key=lambda r: r["id"])
            equality &= all(x["transcript"] == y["transcript"] for x, y in zip(a, b))
            matrix.append([sum(r["word_errors"] for r in a) - sum(r["word_errors"] for r in b), sum(r["reference_words"] for r in a)])
        matrix = np.asarray(matrix)
        rng = np.random.default_rng(2821)
        sample = matrix[rng.integers(len(groups), size=(5000, len(groups)))].sum(1)
        difference = float(matrix[:, 0].sum() / matrix[:, 1].sum())
        interval = np.quantile(sample[:, 0] / sample[:, 1], [.025, .975]).tolist()
        cpu = paired_ci(rows, "cached_continuation", baseline, "cpu_seconds", "speaker_id", 2821)
        wall = paired_ci(rows, "cached_continuation", baseline, "wall_seconds", "speaker_id", 2821)
        nonzero = summaries["cached_continuation"]["decoder_calls_per_repetition"] > len(first) / len(spec["test_arms"])
        quality = interval[1] <= .01 if baseline == "fixed_beam5" else equality and nonzero
        comparisons[baseline] = {"WER_difference": difference, "WER_difference_CI95": interval,
            "CPU": cpu, "wall": wall, "exact_transcript_equality": equality,
            "nonzero_continuation": bool(nonzero),
            "gate_passed": bool(quality and cpu["CI95"][1] < 0 and wall["CI95"][1] < 0)}
    for identity in {r["id"] for r in rows}:
        for arm in spec["test_arms"]:
            group = [r for r in rows if r["id"] == identity and r["arm"] == arm]
            if len(group) != spec["timing_repetitions"] or len({r["transcript"] for r in group}) != 1:
                raise ValueError("Missing repetition or nonidentical transcript")
    return {"summary": summaries, "comparisons": comparisons}


def run(assets, model_path, output):
    source = Path(__file__).parent
    spec, manifest, model = read(source / "SPEECH_PROTOCOL.json"), read(assets / "MANIFEST.json"), read(model_path)
    if manifest["protocol_sha256"] != sha(source / "SPEECH_PROTOCOL.json"):
        raise ValueError("Speech source protocol changed")
    for row in manifest["files"]:
        if sha(row["path"]) != row["sha256"]:
            raise ValueError("Speech source bytes changed")
    if sha(Path(manifest["model_directory"]) / "model.bin") != model["base_model_sha256"]:
        raise ValueError("Frozen neural model changed")
    output.mkdir(parents=True, exist_ok=False)
    registration = freeze(source, assets / "MANIFEST.json", output, spec,
        {"frozen_model_sha256": sha(model_path), "neural_model_sha256": model["base_model_sha256"]})
    save(output / "FROZEN_MODEL.json", model)
    start = time.perf_counter()
    engine = SpeechEngine(manifest["model_directory"], spec["cpu_threads"])
    load_wall = time.perf_counter() - start
    # Public-only warm-up; this output is retained and never used for threshold selection.
    warmup = engine.episode(manifest["speech"][0]["path"], "fixed_greedy", -1000, output / "warmup")
    rows = []
    for repetition in range(spec["timing_repetitions"]):
        for index, item in enumerate(manifest["speech"]):
            rotation = (index + repetition) % len(spec["test_arms"])
            arms = spec["test_arms"][rotation:] + spec["test_arms"][:rotation]
            for arm in arms:
                public = engine.episode(item["path"], arm, model["selected_threshold"],
                    output / "test" / f"repeat-{repetition}" / item["id"] / arm)
                rows.append({**public, "id": item["id"], "speaker_id": item["speaker_id"], "config": item["config"],
                    "arm": arm, "repetition": repetition, **score(item["reference"], public["transcript"]),
                    "cpu_seconds": public["whole_cpu_seconds"], "wall_seconds": public["whole_wall_seconds"],
                    "scored_ns": time.time_ns()})
            if (index + 1) % 4 == 0:
                print({"speech_repetition": repetition, "completed": index + 1}, flush=True)
    result = {"schema": "hepta.ndu.closure-v2.natural.speech.result.v1", "status": "completed",
        "selected_threshold": model["selected_threshold"], "model_load_wall_seconds": load_wall,
        "warmup": warmup, "model_parameters_updated": False, "original_Hepta_neuron_integrated": False,
        "actual_deliveries": len(rows), "new_independent_speakers": len(manifest["test_speakers"]), **summarize(rows, spec)}
    save(output / "ROWS.json", rows)
    save(output / "RESULT.json", result)
    verify_frozen(registration)
    print(result["comparisons"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.assets, args.model, args.output)
