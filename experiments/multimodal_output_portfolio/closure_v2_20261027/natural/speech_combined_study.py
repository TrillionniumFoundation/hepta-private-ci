"""Frozen predecoder policy plus the original same-policy cache controls."""
import argparse
from pathlib import Path
import time

import numpy as np

from ...continuation_20261027.natural.speech_engine import SpeechEngine
from ...repair_20261026.natural.speech import score
from .common import freeze, paired_ci, read, save, sha, verify_frozen
from .speech_encoder_gate import episode as encoder_episode
from .speech_study import summarize


def encoder_comparison(rows, model):
    groups = sorted({r["speaker_id"] for r in rows})
    matrix = []
    for speaker in groups:
        a = [r for r in rows if r["speaker_id"] == speaker and r["arm"] == "encoder_gate" and r["repetition"] == 0]
        b = [r for r in rows if r["speaker_id"] == speaker and r["arm"] == "fixed_beam5" and r["repetition"] == 0]
        matrix.append([sum(r["word_errors"] for r in a) - sum(r["word_errors"] for r in b), sum(r["reference_words"] for r in a)])
    matrix = np.asarray(matrix)
    rng = np.random.default_rng(2821)
    samples = matrix[rng.integers(len(groups), size=(5000, len(groups)))].sum(1)
    interval = np.quantile(samples[:, 0] / samples[:, 1], [.025, .975]).tolist()
    cpu = paired_ci(rows, "encoder_gate", "fixed_beam5", "cpu_seconds", "speaker_id", 2821)
    wall = paired_ci(rows, "encoder_gate", "fixed_beam5", "wall_seconds", "speaker_id", 2821)
    cheap = sum(r["generations"][0]["beam"] == 1 for r in rows if r["arm"] == "encoder_gate" and r["repetition"] == 0)
    return {"WER_difference": float(matrix[:, 0].sum() / matrix[:, 1].sum()), "WER_difference_CI95": interval,
        "CPU": cpu, "wall": wall, "beam1_calls_per_repetition": cheap,
        "deployment_kind": model["choice"]["kind"], "compiled_fixed_baseline": model["choice"]["kind"] == "fixed_beam5",
        "quality_cost_gate_passed": bool(interval[1] <= .01 and cpu["CI95"][1] < 0 and wall["CI95"][1] < 0
            and cheap > 0 and model["choice"]["kind"] == "encoder_gate")}


def run(assets, continuation_path, encoder_path, output):
    source = Path(__file__).parent
    spec, manifest = read(source / "SPEECH_PROTOCOL.json"), read(assets / "MANIFEST.json")
    amendment = read(source / "SPEECH_ENCODER_PRETEST_AMENDMENT.json")
    if manifest["protocol_sha256"] != amendment["prior_protocol_sha256"] or sha(source / "SPEECH_PROTOCOL.json") != amendment["amended_protocol_sha256"]:
        raise ValueError("Unregistered source/deployment protocol amendment")
    continuation, encoder = read(continuation_path), read(encoder_path)
    for row in manifest["files"]:
        if sha(row["path"]) != row["sha256"]:
            raise ValueError("Speech source changed")
    weight_sha = sha(Path(manifest["model_directory"]) / "model.bin")
    if weight_sha != continuation["base_model_sha256"] or weight_sha != encoder["base_model_sha256"]:
        raise ValueError("Frozen base neural weights changed")
    output.mkdir(parents=True, exist_ok=False)
    registration = freeze(source, assets / "MANIFEST.json", output, spec,
        {"continuation_sha256": sha(continuation_path), "encoder_policy_sha256": sha(encoder_path),
        "model_sha256": weight_sha, "pretest_amendment_sha256": sha(source / "SPEECH_ENCODER_PRETEST_AMENDMENT.json")})
    save(output / "FROZEN_MODEL.json", continuation)
    save(output / "ENCODER_MODEL.json", encoder)
    start = time.perf_counter()
    engine = SpeechEngine(manifest["model_directory"], 1)
    load_wall = time.perf_counter() - start
    warmup = engine.episode(manifest["speech"][0]["path"], "fixed_greedy", -1000, output / "warmup")
    rows = []
    for repetition in range(spec["timing_repetitions"]):
        for index, item in enumerate(manifest["speech"]):
            rotation = (index + repetition) % len(spec["test_arms"])
            for arm in spec["test_arms"][rotation:] + spec["test_arms"][:rotation]:
                destination = output / "test" / f"repeat-{repetition}" / item["id"] / arm
                if arm == "encoder_gate" and encoder["choice"]["kind"] == "encoder_gate":
                    public = encoder_episode(engine, item["path"], encoder["model"], encoder["choice"]["threshold"], destination)
                else:
                    deployed_arm = "fixed_beam5" if arm == "encoder_gate" else arm
                    public = engine.episode(item["path"], deployed_arm, continuation["selected_threshold"], destination)
                rows.append({**public, "id": item["id"], "speaker_id": item["speaker_id"], "config": item["config"],
                    "arm": arm, "repetition": repetition, **score(item["reference"], public["transcript"]),
                    "cpu_seconds": public["whole_cpu_seconds"], "wall_seconds": public["whole_wall_seconds"],
                    "scored_ns": time.time_ns()})
            if (index + 1) % 4 == 0:
                print({"speech_repetition": repetition, "completed": index + 1}, flush=True)
    result = {"schema": "hepta.ndu.closure-v2.natural.speech.result.v2", "status": "completed",
        "selected_threshold": continuation["selected_threshold"], "encoder_selection": encoder["choice"],
        "model_load_wall_seconds": load_wall, "warmup": warmup,
        "neural_model_parameters_updated": False, "encoder_controller_fitted": True,
        "original_Hepta_neuron_integrated": False, "actual_deliveries": len(rows),
        "new_independent_speakers": len(manifest["test_speakers"]), **summarize(rows, spec),
        "encoder_vs_fixed_beam5": encoder_comparison(rows, encoder)}
    save(output / "ROWS.json", rows)
    save(output / "RESULT.json", result)
    verify_frozen(registration)
    print(result["comparisons"], result["encoder_vs_fixed_beam5"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("assets", "continuation", "encoder", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.assets, args.continuation, args.encoder, args.output)
