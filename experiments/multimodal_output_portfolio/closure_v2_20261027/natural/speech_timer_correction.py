"""A single frozen same-output remeasurement with identical timer boundaries."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from ...continuation_20261027.natural.speech_engine import SpeechEngine
from .common import freeze, paired_ci, read, save, sha, verify_frozen
from .speech_encoder_gate import public_features, predict


DECODING = {"patience": 1, "length_penalty": 1, "repetition_penalty": 1,
    "no_repeat_ngram_size": 0, "max_length": 448, "suppress_blank": True,
    "return_scores": True, "return_no_speech_prob": True, "sampling_temperature": 0}


def episode(engine, audio, arm, encoder, output):
    output.mkdir(parents=True, exist_ok=False)
    start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
    encoded, preparation = engine.prepare(audio)
    gate = None
    if arm == "encoder_gate":
        features = public_features(encoded, preparation)
        value = predict(features, encoder["model"])
        beam = 5 if value >= encoder["choice"]["threshold"] else 1
        gate = {"features": features.tolist(), "predicted_moment_gain": value,
            "threshold": encoder["choice"]["threshold"], "selected_beam": beam}
    elif arm == "fixed_beam5":
        beam = 5
    else:
        raise ValueError("Only the two prespecified policies may be measured")
    # Same original CT2 call parameters, prompt and suppression list. All JSON
    # serialization is deliberately below the shared pair of stop timestamps.
    generated = engine.model.model.generate(encoded, [engine.prompt], beam_size=beam,
        suppress_tokens=engine.suppress, **DECODING)[0]
    tokens = generated.sequences_ids[0]
    transcript = engine.tokenizer.decode(tokens).strip()
    first = output / "FIRST.txt"
    first.write_text(transcript + "\n", encoding="utf-8")
    first_readback = first.read_text(encoding="utf-8").strip()
    delivered = output / "DELIVERED.txt"
    delivered.write_text(first_readback + "\n", encoding="utf-8")
    observed = delivered.read_text(encoding="utf-8").strip()
    identity = hashlib.sha256(delivered.read_bytes()).hexdigest()
    if observed != transcript or first_readback != transcript:
        raise ValueError("Actual UTF8 transcript did not survive delivery")
    stop_cpu, stop_wall = time.process_time_ns(), time.perf_counter_ns()
    metadata_wall, metadata_cpu = time.perf_counter_ns(), time.process_time_ns()
    public = {"arm": arm, "transcript": observed, "beam": beam, "tokens": tokens,
        "encoder": preparation, "gate": gate, "encoder_calls": 1, "decoder_calls": 1,
        "output_path": str(delivered), "output_sha256": identity,
        "decoder_score": float(generated.scores[0]),
        "no_speech_probability": float(generated.no_speech_prob),
        "cpu_seconds": (stop_cpu - start_cpu) / 1e9,
        "wall_seconds": (stop_wall - start_wall) / 1e9,
        "timer_stop_monotonic_ns": stop_wall, "metadata_start_monotonic_ns": metadata_wall,
        "private_reference_received": False, "actual_text_readback_in_timer": True,
        "all_json_writes_and_readback_after_timer": True}
    save(output / "PUBLIC_RESULT.json", public)
    if json.loads((output / "PUBLIC_RESULT.json").read_text()) != public:
        raise ValueError("Outside-timer metadata readback differs")
    metadata_end_cpu, metadata_end_wall = time.process_time_ns(), time.perf_counter_ns()
    return {**public, "metadata_cpu_seconds": (metadata_end_cpu - metadata_cpu) / 1e9,
        "metadata_wall_seconds": (metadata_end_wall - metadata_wall) / 1e9,
        "metadata_inclusive_cpu_seconds": (metadata_end_cpu - start_cpu) / 1e9,
        "metadata_inclusive_wall_seconds": (metadata_end_wall - start_wall) / 1e9}


def run(assets, original, output):
    code = Path(__file__).parent
    spec = read(code / "SPEECH_TIMER_CORRECTION_PROTOCOL.json")
    checks = {assets / "MANIFEST.json": spec["source_manifest_sha256"],
        original / "ROWS.json": spec["original_rows_sha256"],
        original / "RESULT.json": spec["original_result_sha256"],
        original / "ENCODER_MODEL.json": spec["encoder_policy_sha256"]}
    for path, expected in checks.items():
        if sha(path) != expected:
            raise ValueError("A frozen input or original result changed")
    manifest, encoder = read(assets / "MANIFEST.json"), read(original / "ENCODER_MODEL.json")
    if len(manifest["speech"]) != 64 or len(manifest["test_speakers"]) != 16:
        raise ValueError("Correction source cohort differs")
    if encoder["choice"]["kind"] != "encoder_gate" or encoder["choice"]["threshold"] != -.0007247636911868068:
        raise ValueError("A different policy is not a timing correction")
    model = Path(manifest["model_directory"]) / "model.bin"
    if sha(model) != spec["base_model_sha256"]:
        raise ValueError("Frozen neural checkpoint changed")
    for row in manifest["files"]:
        if sha(row["path"]) != row["sha256"]:
            raise ValueError("Frozen speech source changed")
    expected_rows = {(r["id"], r["arm"], r["repetition"]): r for r in read(original / "ROWS.json")}
    output.mkdir(parents=True, exist_ok=False)
    registration = freeze(code, assets / "MANIFEST.json", output, spec,
        {"input_pins": {str(p): h for p, h in checks.items()}, "model_sha256": sha(model),
        "decoding_kwargs": DECODING, "new_source_or_model_selection": False})
    save(output / "PROTOCOL.json", spec)
    save(output / "ENCODER_MODEL.json", encoder)
    load_start = time.perf_counter()
    engine = SpeechEngine(manifest["model_directory"], 1)
    load_seconds = time.perf_counter() - load_start
    warmup = engine.episode(manifest["speech"][0]["path"], "fixed_greedy", -1000, output / "warmup")
    rows = []
    for repetition in range(2):
        for index, source in enumerate(manifest["speech"]):
            rotation = (index + repetition) % 2
            arms = spec["arms"][rotation:] + spec["arms"][:rotation]
            for arm in arms:
                public = episode(engine, source["path"], arm, encoder,
                    output / "test" / f"repeat-{repetition}" / source["id"] / arm)
                previous = expected_rows[(source["id"], arm, repetition)]
                if public["output_sha256"] != previous["output_sha256"] or public["transcript"] != previous["transcript"]:
                    raise ValueError("Timer correction changed an actual original transcript")
                if public["beam"] != previous["generations"][0]["beam"] or public["encoder"]["encoded_sha256"] != previous["encodings"][0]["encoded_sha256"]:
                    raise ValueError("Timer correction changed a decoder choice or encoder state")
                rows.append({**public, "id": source["id"], "speaker_id": source["speaker_id"],
                    "repetition": repetition, "original_output_sha256": previous["output_sha256"],
                    "byte_identical_to_original": True, "identity_checked_ns": time.time_ns()})
            if (index + 1) % 8 == 0:
                print({"timer_correction_repetition": repetition, "completed_sources": index + 1,
                    "policy_and_output_unchanged_so_far": True}, flush=True)
    metrics = ["cpu_seconds", "wall_seconds", "metadata_cpu_seconds", "metadata_wall_seconds",
        "metadata_inclusive_cpu_seconds", "metadata_inclusive_wall_seconds"]
    summaries = {arm: {key: float(np.mean([r[key] for r in rows if r["arm"] == arm])) for key in metrics} for arm in spec["arms"]}
    comparisons = {key: paired_ci(rows, "encoder_gate", "fixed_beam5", key, "speaker_id", spec["bootstrap"]["seed"]) for key in metrics}
    old_quality = read(original / "RESULT.json")["encoder_vs_fixed_beam5"]
    result = {"schema": "hepta.ndu.closure-v2.natural.speech.timer-correction.result.v1", "status": "completed",
        "measured_episodes": len(rows), "independent_speakers": 16, "new_independent_cohort": False,
        "all_256_transcript_hashes_encoder_hashes_and_beams_equal_original": True,
        "summary": summaries, "encoder_minus_fixed_beam5": comparisons,
        "same_output_original_WER_difference": old_quality["WER_difference"],
        "same_output_original_WER_difference_CI95": old_quality["WER_difference_CI95"],
        "corrected_shared_boundary_cost_gate_passed": all(comparisons[key]["CI95"][1] < 0 for key in ("cpu_seconds", "wall_seconds")),
        "corrected_metadata_inclusive_cost_gate_passed": all(comparisons[key]["CI95"][1] < 0 for key in ("metadata_inclusive_cpu_seconds", "metadata_inclusive_wall_seconds")),
        "original_5arm_result_and_cheap_greedy_diagnostic_unchanged": True,
        "model_load_wall_seconds_excluded": load_seconds, "same_original_warmup_excluded": warmup,
        "registration_sha256": sha(output / "FROZEN_REGISTRATION.json")}
    save(output / "ROWS.json", rows)
    save(output / "RESULT.json", result)
    verify_frozen(registration)
    for path, expected in checks.items():
        if sha(path) != expected:
            raise ValueError("A frozen input changed during measurement")
    print(result, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("assets", "original", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.assets, args.original, args.output)
