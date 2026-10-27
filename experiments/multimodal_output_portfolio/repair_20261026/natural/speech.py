"""Frozen neural ASR with a fitted continuation gate and real output readback."""
import json
from pathlib import Path
import re
import time

import numpy as np
from faster_whisper import WhisperModel


def words(text):
    return re.findall(r"[a-z0-9']+", text.lower())


def score(reference, transcript):
    truth, predicted = words(reference), words(transcript)
    previous = list(range(len(predicted) + 1))
    for i, target in enumerate(truth, 1):
        row = [i]
        for j, observed in enumerate(predicted, 1):
            row.append(min(row[-1] + 1, previous[j] + 1, previous[j - 1] + (observed != target)))
        previous = row
    return {"word_errors": previous[-1], "reference_words": len(truth), "WER": previous[-1] / max(1, len(truth))}


def decode(model, audio_path, beam, destination):
    """No reference text, speaker label, target or future decode enters this call."""
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    segments, info = model.transcribe(str(audio_path), beam_size=beam, language="en", temperature=0,
        vad_filter=False, condition_on_previous_text=False, initial_prompt=None)
    segments = list(segments)
    transcript = " ".join(s.text.strip() for s in segments).strip()
    confidence = float(np.mean([s.avg_logprob for s in segments])) if segments else -100.0
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(transcript + "\n", encoding="utf-8")
    observed = destination.read_text(encoding="utf-8").strip()
    if observed != transcript:
        raise ValueError("Actual emitted transcript readback differs")
    return {"transcript": observed, "mean_segment_logprob": confidence,
        "beam_size": beam, "actual_model_calls": 1, "audio_duration_seconds": info.duration,
        "wall_seconds": (time.perf_counter_ns() - started) / 1e9,
        "cpu_seconds": (time.process_time_ns() - cpu) / 1e9,
        "reference_supplied_to_model": False, "output_file": str(destination)}


def run_speech(manifest, spec, output):
    output.mkdir(parents=True, exist_ok=False)
    model_path = Path(manifest["files"][-1]["path"]).parent
    started = time.perf_counter_ns()
    model = WhisperModel(str(model_path), device="cpu", compute_type="int8", cpu_threads=spec["cpu_threads"], num_workers=1,
                         local_files_only=True)
    loading = (time.perf_counter_ns() - started) / 1e9
    fit_rows = [r for r in manifest["speech"] if r["role"] == "fit"]
    test_rows = [r for r in manifest["speech"] if r["role"] == "test"]
    fit = []
    for i, row in enumerate(fit_rows):
        outputs = {}
        for beam in ([1, 5] if i % 2 == 0 else [5, 1]):
            record = decode(model, row["path"], beam, output / "fit" / row["id"] / f"beam{beam}.txt")
            outputs[str(beam)] = {**record, **score(row["reference"], record["transcript"])}
        fit.append({"id": row["id"], "speaker_id": row["speaker_id"], "outputs": outputs})
    candidates = []
    for threshold in spec["threshold_candidates"]:
        values, calls = [], 0
        for row in fit:
            first, second = row["outputs"]["1"], row["outputs"]["5"]
            continue_decode = first["mean_segment_logprob"] < threshold
            selected = second if continue_decode else first
            values.append(min(1.0, selected["WER"]) + .01 * (first["wall_seconds"] + continue_decode * second["wall_seconds"]))
            calls += int(continue_decode)
        candidates.append({"threshold": threshold, "fit_objective": float(np.mean(values)), "extra_calls": calls})
    chosen = min(candidates, key=lambda r: (r["fit_objective"], r["threshold"]))
    threshold = chosen["threshold"]
    gate = {"selected_threshold": threshold, "candidate_fit_results": candidates,
            "fit_speakers": manifest["fit_speakers"], "test_speakers": manifest["test_speakers"],
            "test_has_not_started": True, "neural_weights_updated": False, "fitted_parameters": 1,
            "note": "Actual fit wall seconds are part of the prespecified pilot objective; selected gate can be machine-dependent"}
    (output / "GATE_FROZEN.json").write_text(json.dumps(gate, sort_keys=True, indent=2) + "\n")
    (output / "FIT.json").write_text(json.dumps(fit, sort_keys=True, indent=2) + "\n")
    rows = []
    for i, item in enumerate(test_rows):
        arms = spec["arms"][i % 3:] + spec["arms"][:i % 3]
        for arm in arms:
            root = output / "test" / item["id"] / arm
            start, cpu = time.perf_counter_ns(), time.process_time_ns()
            first = decode(model, item["path"], 5 if arm == "fixed_beam5" else 1, root / "first.txt")
            calls = [first]
            if arm == "dynamic" and first["mean_segment_logprob"] < threshold:
                calls.append(decode(model, item["path"], 5, root / "continued.txt"))
            selected = calls[-1]
            output_path = root / "DELIVERED.txt"
            output_path.write_text(selected["transcript"] + "\n", encoding="utf-8")
            delivered = output_path.read_text(encoding="utf-8").strip()
            record = {"id": item["id"], "speaker_id": item["speaker_id"], "arm": arm,
                "actual_model_calls": len(calls), "calls": calls, "transcript": delivered,
                "wall_seconds": (time.perf_counter_ns() - start) / 1e9, "cpu_seconds": (time.process_time_ns() - cpu) / 1e9,
                "continuation_before_reference_score": True}
            (root / "PUBLIC_RESULT.json").write_text(json.dumps(record, sort_keys=True, indent=2) + "\n")
            rows.append({**record, **score(item["reference"], delivered)})
        print(json.dumps({"natural_speech_test_completed": i + 1, "of": len(test_rows)}), flush=True)
    summary = {}
    for arm in spec["arms"]:
        group = [r for r in rows if r["arm"] == arm]
        by_speaker = {str(s): float(np.mean([r["WER"] for r in group if r["speaker_id"] == s])) for s in manifest["test_speakers"]}
        summary[arm] = {"utterances": len(group), "independent_speakers": len(by_speaker),
            "micro_WER": sum(r["word_errors"] for r in group) / sum(r["reference_words"] for r in group),
            "mean_utterance_WER": float(np.mean([r["WER"] for r in group])), "speaker_mean_WER": by_speaker,
            "wall_seconds": sum(r["wall_seconds"] for r in group), "cpu_seconds": sum(r["cpu_seconds"] for r in group),
            "actual_model_calls": sum(r["actual_model_calls"] for r in group)}
    result = {"status": "completed", "model_loading_wall_seconds": loading, "gate": gate, "summary": summary,
        "actual_neural_inference": True, "neural_parameter_updates": False, "generated_modality": "recognized transcript text",
        "speech_or_video_synthesis": False, "statistical_superiority_claim": False}
    (output / "ROWS.json").write_text(json.dumps(rows, sort_keys=True, indent=2) + "\n")
    (output / "RESULT.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    return result
