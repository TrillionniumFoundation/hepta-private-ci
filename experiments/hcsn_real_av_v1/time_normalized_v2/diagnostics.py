"""Preregistered duration-only and content-removal diagnostics, without refitting."""

import argparse
import json
from pathlib import Path
import resource
import time

import numpy as np
import torch
from torch.nn import functional as F

from ..data import digest, write_json
from ..study import PairEncoder, load_split, load_weights, evaluate, retrieval
from .study import BASE, HERE, verify_freeze


def ranked(scores, actors):
    result = {}
    for direction, matrix in (("audio_to_video", scores), ("video_to_audio", scores.T)):
        for scope in ("all_clips", "same_actor"):
            ranks = []
            for index, row in enumerate(matrix):
                candidates = np.arange(len(actors)) if scope == "all_clips" else np.flatnonzero(actors == actors[index])
                order = candidates[np.lexsort((candidates, -row[candidates]))]
                ranks.append(int(np.flatnonzero(order == index)[0]) + 1)
            ranks = np.asarray(ranks)
            result[direction + "." + scope] = dict(recall1=float(np.mean(ranks <= 1)),
                recall5=float(np.mean(ranks <= 5)), mrr=float(np.mean(1 / ranks)), ranks=ranks.tolist())
    return result


def run(run_root, output):
    started_cpu, started_wall = time.process_time(), time.perf_counter()
    verify_freeze()
    sealed_hash = digest(HERE / "FREEZE.json")
    summary = json.loads((run_root / "SUMMARY.json").read_text())
    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    assert summary["attempted"] == summary["expected"] == protocol["expected_jobs"]
    assert summary["freeze_sha256"] == sealed_hash
    output.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((BASE / "data/DATASET.json").read_text())
    row = manifest["splits"]["test"]
    test = load_split(BASE / "data" / row["path"], row["sha256"])
    durations = test["dt"].double().sum(1).numpy() / 10
    scores = -np.abs(durations[:, None] - durations[None, :])
    write_json(output / "DURATION_ONLY.json", dict(metrics=ranked(scores, test["actor"]),
        durations_seconds=durations.tolist(), unique_durations=int(len(np.unique(durations))),
        interpretation="Direct metadata baseline for the superseded unexecuted profile; no model fitting"))
    records = []
    for worker in summary["workers"]:
        label = f"{worker['model']}-seed{worker['seed']}"
        if not worker["completed"]:
            records.append(dict(model=worker["model"], seed=worker["seed"], completed=False,
                                reason="Main attempt did not complete; no selected checkpoint claimed"))
            continue
        try:
            directory = run_root / "jobs" / label
            primary = json.loads((directory / "RESULT.json").read_text())
            selection = json.loads((directory / "SELECTION.json").read_text())["selected"]
            assert primary["freeze_sha256"] == sealed_hash and primary["selected"] == selection
            assert digest(directory / "predictions.npz") == primary["predictions_sha256"]
            assert digest(directory / selection["weights"]) == selection["sha256"]
            model = PairEncoder(worker["model"], worker["seed"])
            load_weights(directory / selection["weights"], model)
            blank = dict(test, audio=torch.zeros_like(test["audio"]), video=torch.zeros_like(test["video"]))
            recognition, predictions = evaluate(model, blank)
            metrics, _ = retrieval(predictions, test["actor"])
            raw_clock = dict(recognition=recognition, retrieval=metrics)
            one = {key: value[:1] for key, value in blank.items()}
            one["dt"] = torch.ones_like(one["dt"])
            _, constant = evaluate(model, one)
            constant = {key: np.repeat(value, len(test["y"]), axis=0) for key, value in constant.items()}
            constant_recognition = {}
            for modality in ("audio", "video", "fused"):
                logits = torch.from_numpy(constant[modality + "_logits"])
                constant_recognition[modality] = dict(
                    accuracy=float((logits.argmax(-1) == test["y"]).float().mean()),
                    cross_entropy=float(F.cross_entropy(logits, test["y"])))
            # Identical inputs give identical embeddings: every pair score is
            # analytically equal, so impose exact ties instead of BLAS roundoff.
            constant_metrics = ranked(np.zeros_like(scores), test["actor"])
            np.savez_compressed(output / (label + ".npz"), **predictions,
                constant_audio_embedding=constant["audio_embedding"],
                constant_video_embedding=constant["video_embedding"],
                constant_fused_logits=constant["fused_logits"])
            record = dict(model=worker["model"], seed=worker["seed"], completed=True,
                selected_step=selection["step"], fixed_dt_with_content=dict(
                    recognition=primary["recognition"], retrieval=primary["retrieval"]),
                zero_content_original_dt=raw_clock,
                zero_content_fixed_dt=dict(recognition=constant_recognition, retrieval=constant_metrics),
                probability_checks=model.probability_checks,
                predictions_sha256=digest(output / (label + ".npz")))
        except Exception as error:
            record = dict(model=worker["model"], seed=worker["seed"], completed=False,
                          error=f"{type(error).__name__}: {error}")
        write_json(output / (label + ".json"), record)
        records.append(record)
    verify_freeze()
    assert digest(HERE / "FREEZE.json") == sealed_hash
    write_json(output / "SUMMARY.json", dict(records=records, freeze_sha256=sealed_hash,
        addendum_sha256=digest(HERE / "ADDENDUM.json"), no_refitting=True,
        inner_cpu_seconds=time.process_time()-started_cpu, inner_wall_seconds=time.perf_counter()-started_wall,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        measured_energy_joules=None))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    run(args.run_root, args.output)
