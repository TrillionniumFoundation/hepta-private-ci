"""Frozen source-held-out ASR policy and paired execution-cost experiment."""
import argparse
import importlib.metadata
from pathlib import Path
import time

import numpy as np

from ...repair_20261026.natural.speech import score
from .common import freeze, read, save, sha, verify_files
from .speech_engine import SpeechEngine


def summarize(rows, spec):
    arms = spec["test_arms"]
    keys = sorted({(r["speaker_id"], r["id"]) for r in rows})
    utterances = []
    for speaker, identity in keys:
        record = {"id": identity, "speaker_id": speaker, "arms": {}}
        for arm in arms:
            chosen = [r for r in rows if r["id"] == identity and r["arm"] == arm]
            if len(chosen) != spec["timing_repetitions"] or len({r["transcript"] for r in chosen}) != 1:
                raise ValueError("Missing repetition or nondeterministic transcript")
            record["arms"][arm] = {"word_errors": chosen[0]["word_errors"],
                "reference_words": chosen[0]["reference_words"], "transcript": chosen[0]["transcript"],
                "cpu_seconds": float(np.mean([r["whole_cpu_seconds"] for r in chosen])),
                "wall_seconds": float(np.mean([r["whole_wall_seconds"] for r in chosen])),
                "encoder_calls": chosen[0]["encoder_calls"], "decoder_calls": chosen[0]["decoder_calls"]}
        utterances.append(record)
    speakers = sorted({r["speaker_id"] for r in utterances})
    summary = {}
    for arm in arms:
        group = [r["arms"][arm] for r in utterances]
        summary[arm] = {"utterances": len(group), "independent_speakers": len(speakers),
            "micro_WER": sum(r["word_errors"] for r in group) / sum(r["reference_words"] for r in group),
            "word_errors": sum(r["word_errors"] for r in group),
            "reference_words": sum(r["reference_words"] for r in group),
            "mean_whole_cpu_seconds_per_utterance": float(np.mean([r["cpu_seconds"] for r in group])),
            "mean_whole_wall_seconds_per_utterance": float(np.mean([r["wall_seconds"] for r in group])),
            "encoder_calls_per_repetition": sum(r["encoder_calls"] for r in group),
            "decoder_calls_per_repetition": sum(r["decoder_calls"] for r in group)}
    comparisons = {}
    same_policy_identical = all(r["arms"]["cached_continuation"]["transcript"] ==
        r["arms"]["reencoded_continuation"]["transcript"] for r in utterances)
    for baseline in ("reencoded_continuation", "fixed_beam5"):
        grouped = []
        for speaker in speakers:
            selected = [r for r in utterances if r["speaker_id"] == speaker]
            dynamic = [r["arms"]["cached_continuation"] for r in selected]
            static = [r["arms"][baseline] for r in selected]
            grouped.append([sum(r["word_errors"] for r in dynamic), sum(r["word_errors"] for r in static),
                sum(r["reference_words"] for r in dynamic),
                np.mean([a["cpu_seconds"] - b["cpu_seconds"] for a, b in zip(dynamic, static)]),
                np.mean([a["wall_seconds"] - b["wall_seconds"] for a, b in zip(dynamic, static)])])
        matrix = np.asarray(grouped)
        rng = np.random.default_rng(2701)
        indices = rng.integers(len(speakers), size=(4000, len(speakers)))
        samples = matrix[indices]
        wer = (samples[:, :, 0].sum(1) - samples[:, :, 1].sum(1)) / samples[:, :, 2].sum(1)
        cpu, wall = samples[:, :, 3].mean(1), samples[:, :, 4].mean(1)
        record = {"delta_micro_WER": float((matrix[:, 0].sum()-matrix[:, 1].sum())/matrix[:, 2].sum()),
            "delta_WER_CI95": np.quantile(wer, [.025, .975]).tolist(),
            "delta_cpu_seconds_per_utterance": float(matrix[:, 3].mean()),
            "delta_cpu_CI95": np.quantile(cpu, [.025, .975]).tolist(),
            "delta_wall_seconds_per_utterance": float(matrix[:, 4].mean()),
            "delta_wall_CI95": np.quantile(wall, [.025, .975]).tolist()}
        quality = same_policy_identical if baseline == "reencoded_continuation" else record["delta_WER_CI95"][1] <= .01
        record["acceptance_passed"] = bool(quality and record["delta_cpu_CI95"][1] < 0 and record["delta_wall_CI95"][1] < 0)
        comparisons[baseline] = record
    return {"summary": summary, "comparisons": comparisons,
        "same_policy_transcripts_identical": same_policy_identical, "utterance_rows": utterances}


def run(assets, output):
    source = Path(__file__).parent
    spec = read(source / "SPEECH_PROTOCOL.json")
    manifest = read(assets / "MANIFEST.json")
    if manifest["protocol_sha256"] != sha(source / "SPEECH_PROTOCOL.json"):
        raise ValueError("Protocol changed after source selection")
    verify_files(manifest["files"])
    output.mkdir(parents=True, exist_ok=False)
    versions = {name: importlib.metadata.version(name) for name in ("numpy", "faster-whisper", "ctranslate2", "av")}
    registration = freeze(source, source / "SPEECH_PROTOCOL.json", assets / "MANIFEST.json", output,
        {"runtime_versions": versions, "upstream_API_reference": "SYSTRAN/faster-whisper v1.2.1 transcribe.py encode/get_prompt/generate_with_fallback"})
    loading = time.perf_counter_ns()
    engine = SpeechEngine(manifest["model_directory"], spec["cpu_threads"])
    load_seconds = (time.perf_counter_ns() - loading) / 1e9
    fit_rows = [r for r in manifest["speech"] if r["role"] == "fit"]
    warmup = engine.episode(fit_rows[0]["path"], "fixed_greedy", -1000, output / "warmup")
    fit = []
    for item in fit_rows:
        encoded, preparation = engine.prepare(item["path"])
        low = engine.generate(encoded, 1, output / "fit" / item["id"] / "greedy.txt")
        high = engine.generate(encoded, 5, output / "fit" / item["id"] / "beam5.txt")
        fit.append({"id": item["id"], "speaker_id": item["speaker_id"], "prepare": preparation,
            "low": {**low, **score(item["reference"], low["transcript"])},
            "high": {**high, **score(item["reference"], high["transcript"])}})
    candidates = []
    for threshold in spec["thresholds"]:
        by_speaker = []
        for speaker in manifest["fit_speakers"]:
            values = []
            for row in (r for r in fit if r["speaker_id"] == speaker):
                proceed = row["low"]["confidence"] < threshold
                selected = row["high"] if proceed else row["low"]
                cost = row["prepare"]["cpu_seconds"] + row["low"]["cpu_seconds"] + proceed*row["high"]["cpu_seconds"]
                values.append(min(1, selected["WER"]) + .01*cost)
            by_speaker.append(np.mean(values))
        candidates.append({"threshold": threshold, "objective": float(np.mean(by_speaker))})
    chosen = min(candidates, key=lambda r: (r["objective"], r["threshold"]))
    save(output / "FIT.json", fit)
    gate = {"selected_threshold": chosen["threshold"], "candidates": candidates,
        "fitting_complete_ns": time.time_ns(), "heldout_scoring_not_started": True,
        "fit_speakers": manifest["fit_speakers"], "test_speakers": manifest["test_speakers"],
        "fitted_parameters": 1, "neural_parameters_updated": False}
    save(output / "GATE_FROZEN.json", gate)
    rows = []
    test_rows = [r for r in manifest["speech"] if r["role"] == "test"]
    for repetition in range(spec["timing_repetitions"]):
        for i, item in enumerate(test_rows):
            rotation = (i + repetition) % len(spec["test_arms"])
            order = spec["test_arms"][rotation:] + spec["test_arms"][:rotation]
            for arm in order:
                public = engine.episode(item["path"], arm, chosen["threshold"],
                    output / "test" / f"repeat-{repetition}" / item["id"] / arm)
                row = {"id": item["id"], "speaker_id": item["speaker_id"], "config": item["config"],
                    "repetition": repetition, **public, **score(item["reference"], public["transcript"]),
                    "private_scoring_ns": time.time_ns()}
                rows.append(row)
            print({"speech_repetition": repetition, "utterance": i+1, "of": len(test_rows)}, flush=True)
    save(output / "ROWS.json", rows)
    result = {"schema": "hepta.ndu.continuation.natural.speech.result.v1", "status": "completed",
        "gate": gate, "model_load_wall_seconds": load_seconds, "warmup": warmup,
        "neural_parameters_updated": False, "original_Hepta_neuron_integrated": False,
        "general_multimodal_generation_proven": False, **summarize(rows, spec)}
    result.pop("utterance_rows")
    save(output / "RESULT.json", result)
    for name, digest in registration["source_sha256"].items():
        if sha(source / name) != digest:
            raise ValueError("Registered scientific source changed during execution")
    verify_files(manifest["files"])
    print(result["comparisons"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.assets, args.output)
    except Exception as error:
        if args.output.exists():
            save(args.output / "FAILED.json", {"error": type(error).__name__ + ": " + str(error), "partial_evidence_retained": True})
        raise
