"""Freeze an encoder-only decoder-work choice using historical train/validation."""
import argparse
from pathlib import Path
import time

import numpy as np

from ...continuation_20261027.natural.speech_engine import SpeechEngine
from ...repair_20261026.natural.speech import score
from .common import freeze, read, save, sha, verify_frozen
from .speech_encoder_gate import episode, fit, predict, public_features


def run(assets, previous, output):
    source = Path(__file__).parent
    manifest = read(assets / "MANIFEST.json")
    output.mkdir(parents=True, exist_ok=False)
    spec = {"purpose": "Remove redundant first decoder by choosing beam from observed encoder state",
        "training_speakers": manifest["groups"]["train"], "validation_speakers": manifest["groups"]["validation"],
        "ridge_lambda": 10., "thresholds": "Training gain quartiles plus all-beam5/all-beam1 endpoints",
        "selection": "Validation paired speaker95percentWER upper difference<=0.01 versus actual beam5, then minimum actualCPU; fixedbeam5 is an eligible deployment fallback",
        "test_not_received": True, "fresh_test_outputs_exist": False}
    registration = freeze(source, assets / "MANIFEST.json", output, spec)
    engine = SpeechEngine(manifest["base_model_directory"], 1)
    rows = []
    for item in (r for r in manifest["speech"] if r["role"] == "train"):
        encoded, preparation = engine.prepare(item["path"])
        low = engine.generate(encoded, 1, output / "train" / item["id"] / "beam1.txt")
        high = engine.generate(encoded, 5, output / "train" / item["id"] / "beam5.txt")
        rows.append({"id": item["id"], "speaker_id": item["speaker_id"], "features": public_features(encoded, preparation).tolist(),
            "preparation": preparation, "low": {**low, **score(item["reference"], low["transcript"])},
            "high": {**high, **score(item["reference"], high["transcript"])}})
    model = fit(rows)
    training_predictions = [predict(np.asarray(r["features"]), model) for r in rows]
    thresholds = [-1000.] + np.quantile(training_predictions, [.25, .5, .75]).tolist() + [1000.]
    validation = [r for r in manifest["speech"] if r["role"] == "validation"]
    baseline = read(previous / "FIXED_ROWS.json")
    all_rows, candidates = [], []
    for index, threshold in enumerate(thresholds):
        group = []
        for item in validation:
            public = episode(engine, item["path"], model, threshold, output / "validation" / f"gate-{index}" / item["id"])
            group.append({"id": item["id"], "speaker_id": item["speaker_id"], **public,
                **score(item["reference"], public["transcript"])})
        all_rows.extend({"candidate": index, **r} for r in group)
        matrix = []
        for speaker in manifest["groups"]["validation"]:
            a = [r for r in group if r["speaker_id"] == speaker]
            b = [r for r in baseline if r["speaker_id"] == speaker]
            matrix.append([sum(r["word_errors"] for r in a) - sum(r["word_errors"] for r in b), sum(r["reference_words"] for r in a)])
        matrix = np.asarray(matrix)
        rng = np.random.default_rng(2820)
        draws = matrix[rng.integers(len(matrix), size=(5000, len(matrix)))].sum(1)
        interval = np.quantile(draws[:, 0] / draws[:, 1], [.025, .975]).tolist()
        candidates.append({"kind": "encoder_gate", "threshold": threshold, "mean_CPU": float(np.mean([r["whole_cpu_seconds"] for r in group])),
            "WER_difference_CI95": interval, "feasible": interval[1] <= .01,
            "beam5_calls": sum(r["generations"][0]["beam"] == 5 for r in group)})
        print({"encoder_candidate": index, "result": candidates[-1]}, flush=True)
    candidates.append({"kind": "fixed_beam5", "threshold": None,
        "mean_CPU": float(np.mean([r["whole_cpu_seconds"] for r in baseline])),
        "WER_difference_CI95": [0., 0.], "feasible": True, "beam5_calls": len(baseline)})
    selected = min([r for r in candidates if r["feasible"]], key=lambda r: (r["mean_CPU"], r["kind"] != "fixed_beam5"))
    frozen = {"choice": selected, "model": model, "candidates": candidates, "frozen_ns": time.time_ns(),
        "heldout_generation_not_started": True, "base_model_sha256": sha(Path(manifest["base_model_directory"]) / "model.bin"),
        "baseline_validation_sha256": sha(previous / "FIXED_ROWS.json"),
        "model_parameters_updated": False, "encoder_gate_weights_updated": True}
    save(output / "TRAINING_ROWS.json", rows)
    save(output / "VALIDATION_ROWS.json", all_rows)
    save(output / "FROZEN_MODEL.json", frozen)
    verify_frozen(registration)
    print(selected, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.assets, args.previous, args.output)
