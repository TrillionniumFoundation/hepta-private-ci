"""Independent held-source Brier test for two pre-frozen old-head proposals."""

import argparse
import copy
import gzip
import json
from pathlib import Path

import numpy as np
import torch

from ...abc_next.native.qualify import confidence, raw_prediction
from ...abc_recovery.training_run import file_sha, write_json
from ...v6.data import render_tokens
from ...v6.observer import read_bundle
from ...v7.snapshot import Snapshot
from .boundaries import verified_data
from .candidate_features import reconstruct_text_future
from .forecast import Q


def verify(protocol, registration, data, output):
    declared = json.loads(registration.read_text()); primary = json.loads(protocol.read_text())
    if declared["primary_protocol_sha256"] != file_sha(protocol):
        raise ValueError("Candidate study protocol changed")
    for name, digest in declared["source_pins"].items():
        if file_sha(Path(__file__).parent / name) != digest:
            raise ValueError("Frozen candidate analysis source changed")
    for name, digest in declared["file_pins"].items():
        if file_sha(Path(declared["paths"][name])) != digest:
            raise ValueError("Frozen candidate or baseline changed")
    d = verified_data(data, protocol, "verification")
    with gzip.open(data / "rows.jsonl.gz", "rt") as stream:
        raw = [json.loads(line) for line in stream]
    if len(raw) != len(d["pair"]):
        raise ValueError("Future output census mismatch")
    torch.set_num_threads(1)
    generator = Snapshot.load(primary["paths"]["model"], expected_file_sha256=primary["input_sha256"]["model"])._model
    groups = {}
    for i in np.flatnonzero(d["action"] == 0):
        row = raw[i]
        if row["pair"] != d["pair"][i] or row["action"] != "refine_text" or row["joint_correct"] != d["y"][i]:
            raise ValueError("Actual output row binding changed")
        groups.setdefault(row["commit_file"], []).append(int(i))
    xs, ys, pairs, oods = [], [], [], []
    for indices in groups.values():
        pixels = []
        for i in indices:
            row = raw[i]; root = data / "media" / f"{row['pair']:04d}-refine_text"
            image, caption, hashes = read_bundle({"image": root / "image.png", "text": root / "caption.txt"})
            if hashes != row["media"] or caption != render_tokens(torch.tensor(d["future_tokens"][i])):
                raise ValueError("Observed media identity changed")
            pixels.append(image[0])
        xs.append(reconstruct_text_future(generator, d["x_q24"][indices], torch.stack(pixels),
                                         torch.tensor(d["future_tokens"][indices])))
        ys.extend(d["y"][indices]); pairs.extend(d["pair"][indices]); oods.extend(d["ood"][indices])
    x = np.concatenate(xs) / Q; y = np.asarray(ys); ood = np.asarray(oods)
    if len(pairs) != 1432 or len(set(pairs)) != len(pairs):
        raise ValueError("Candidate test must contain one text future for every reserved source pair")
    weights = json.loads(Path(declared["paths"]["weights"]).read_text())
    calibration = json.loads(Path(declared["paths"]["calibration"]).read_text())
    candidates = json.loads(Path(declared["paths"]["candidates"]).read_text())
    if candidates["baseline_weights_sha256"] != declared["file_pins"]["weights"]:
        raise ValueError("Native candidate baseline differs")
    base = raw_prediction(weights, x); base_loss = (base - y) ** 2
    base_cp = confidence(weights, calibration, x)[0]; results, advantages = [], []
    for candidate in candidates["candidates"]:
        if candidate["kind"] != "Update":
            continue
        updated = copy.deepcopy(weights)
        for delta in candidate["deltas"]:
            field, index = delta["parameter"].split(".")
            if field != "w2" or not 0 <= int(index) < 32 or abs(delta["delta_q32"]) > 429497:
                raise ValueError("Typed native parameter bound changed")
            updated[field][int(index)] += delta["delta_q32"] / 2**32
        probability = raw_prediction(updated, x); loss = (probability - y) ** 2
        gain = base_loss - loss; advantages.append(gain)
        results.append({"candidate": candidate["id"], "raw_brier": float(loss.mean()),
            "mean_brier_improvement": float(gain.mean()), "id_brier_improvement": float(gain[~ood].mean()),
            "ood_brier_improvement": float(gain[ood].mean()),
            "maximum_raw_probability_change": float(np.abs(probability - base).max()),
            "calibrated_confidence_rows_changed": int(np.count_nonzero(confidence(updated, calibration, x)[0] != base_cp))})
    if len(results) != 2 or [r["candidate"] for r in results] != declared["candidate_ids"]:
        raise ValueError("Frozen two-candidate comparison family changed")
    gain = np.stack(advantages, 1); rng = np.random.default_rng(194019)
    draws = np.asarray([gain[rng.integers(0, len(pairs), len(pairs))].mean(0) for _ in range(4000)])
    bounds = np.quantile(draws, [.0125, .9875], axis=0)
    for i, result in enumerate(results):
        result["paired_source_bonferroni_family95_interval"] = bounds[:, i].tolist()
        result["positive_adjusted_lower_endpoint"] = bool(bounds[0, i] > 0)
    output.mkdir(parents=True, exist_ok=False)
    result = {"schema": "hepta.abc4.native-old-head-independent-candidates.v1",
        "registration_sha256": file_sha(registration), "data_sha256": file_sha(data / "data.npz"),
        "independent_source_pairs": len(pairs), "id_pairs": int((~ood).sum()), "ood_pairs": int(ood.sum()),
        "baseline_raw_brier": float(base_loss.mean()), "candidates": results,
        "comparisons": 2, "individual_interval_confidence": .975, "nominal_family_confidence": .95,
        "bootstrap_draws": 4000, "source_pair_draws_shared_between_candidates": True,
        "generator_digest": candidates["generator_digest"], "eligible_for_independent_acceptance": False,
        "statistically_unseen_sources_for_fixed_candidates": True, "authenticated_evaluator": False,
        "new_independent_sources_beyond_primary": 0, "applied_update": False,
        "scope": "old508-to32 current-output correctness head only; not future-state prediction, generator improvement or authenticated native acceptance"}
    write_json(output / "result.json", result); print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("protocol", "registration", "data", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(); verify(args.protocol, args.registration, args.data, args.output)
