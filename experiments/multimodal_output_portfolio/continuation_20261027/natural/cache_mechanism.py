"""Validation-only forced-continuation mechanism check, separate from qualification."""
import argparse
from pathlib import Path
import time

import numpy as np

from .common import read, save, sha, verify_files
from .speech_engine import SpeechEngine


def run(assets, output):
    manifest = read(assets / "MANIFEST.json")
    selected = [next(r for r in manifest["speech"] if r["role"] == "fit" and r["speaker_id"] == speaker)
        for speaker in sorted(manifest["fit_speakers"])]
    verify_files(manifest["files"])
    output.mkdir(parents=True, exist_ok=False)
    spec = {"schema": "hepta.ndu.cache.mechanism.protocol.v1", "registered_ns": time.time_ns(),
        "source_ids": [r["id"] for r in selected], "selection": "First fitting utterance per earlier fitting speaker, sorted speaker ID",
        "threshold": 1000, "repetitions": 3, "cpu_threads": 1,
        "scope": "Forced-continuation execution mechanism only; these are development/fit sources, not new qualification evidence",
        "source_sha256": {p.name: sha(p) for p in (Path(__file__), Path(__file__).with_name("speech_engine.py"))},
        "acceptance": "Every transcript and encoder digest identical across reuse/reencoding; paired speaker timing CI upper differences below zero"}
    save(output / "PROTOCOL.json", spec)
    engine = SpeechEngine(manifest["model_directory"], 1)
    engine.episode(selected[0]["path"], "cached_continuation", 1000, output / "warmup")
    rows = []
    for repetition in range(3):
        for index, source in enumerate(selected):
            arms = ["cached_continuation", "reencoded_continuation"]
            if (index+repetition) % 2:
                arms.reverse()
            for arm in arms:
                record = engine.episode(source["path"], arm, 1000,
                    output / "outputs" / str(repetition) / source["id"] / arm)
                rows.append({"id": source["id"], "speaker_id": source["speaker_id"], "repetition": repetition, **record})
    differences = []
    for source in selected:
        cached = [r for r in rows if r["id"] == source["id"] and r["arm"] == "cached_continuation"]
        repeated = [r for r in rows if r["id"] == source["id"] and r["arm"] == "reencoded_continuation"]
        if len({r["transcript"] for r in cached+repeated}) != 1:
            raise ValueError("Caching changed actual generated transcript")
        if any(r["encoder_calls"] != 1 or r["decoder_calls"] != 2 for r in cached):
            raise ValueError("Reuse path did not execute actual continuation")
        if any(r["encoder_calls"] != 2 or r["decoder_calls"] != 2 for r in repeated):
            raise ValueError("Reference path did not re-encode")
        differences.append([np.mean([r[key] for r in cached])-np.mean([r[key] for r in repeated])
            for key in ("whole_cpu_seconds", "whole_wall_seconds")])
    delta = np.asarray(differences)
    rng = np.random.default_rng(2715)
    sample = delta[rng.integers(len(delta), size=(4000, len(delta)))].mean(1)
    result = {"schema": "hepta.ndu.cache.mechanism.result.v1", "status": "completed",
        "sources": len(selected), "episodes": len(rows), "actual_continue_every_episode": True,
        "all_transcripts_identical": True, "new_source_qualification": False,
        "CPU_difference_mean": float(delta[:, 0].mean()), "CPU_difference_CI95": np.quantile(sample[:, 0], [.025, .975]).tolist(),
        "wall_difference_mean": float(delta[:, 1].mean()), "wall_difference_CI95": np.quantile(sample[:, 1], [.025, .975]).tolist()}
    result["mechanism_acceptance_passed"] = result["CPU_difference_CI95"][1] < 0 and result["wall_difference_CI95"][1] < 0
    save(output / "ROWS.json", rows)
    save(output / "RESULT.json", result)
    print(result, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.assets, args.output)
