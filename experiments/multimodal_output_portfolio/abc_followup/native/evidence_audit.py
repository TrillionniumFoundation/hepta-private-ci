"""Read-only audit of committed forecasts against the actual reopened futures."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch

from ...abc_recovery.training_run import file_sha, write_json
from ...v6.data import render_tokens
from ...v6.observer import read_bundle
from ...v7.snapshot import Snapshot
from .boundaries import verified_data
from .forecast import ACTIONS, Q, emitted_state, predict
from .qualify import check_freeze


def audit(protocol, data, model, output):
    check_freeze(protocol, model, "calibrator-freeze.json")
    d = verified_data(data, protocol, "verification")
    with gzip.open(data / "rows.jsonl.gz", "rt") as stream:
        rows = [json.loads(line) for line in stream]
    if len(rows) != len(d["pair"]):
        raise ValueError("Stored row census differs from the frozen arrays")
    groups, pairs = {}, {}
    for i, row in enumerate(rows):
        if (row["pair"] != int(d["pair"][i]) or ACTIONS.index(row["action"]) != int(d["action"][i])
                or row["joint_correct"] != int(d["y"][i]) or row["forecast_used_current_outcome"]):
            raise ValueError("Row identity or declared forecast causality changed")
        groups.setdefault(row["commit_file"], []).append(i)
        pairs.setdefault(row["pair"], []).append(row)
    minimum_lead = None
    for pair_rows in pairs.values():
        if (len(pair_rows) != 2 or {r["action"] for r in pair_rows} != set(ACTIONS)
                or len({r["prefix_public_digest"] for r in pair_rows}) != 1
                or len({tuple(r["source_ids"]) for r in pair_rows}) != 1):
            raise ValueError("The two futures do not share their recorded public prefix/source")
        lead = min(r["transition_started_unix_ns"] for r in pair_rows) - max(
            r["commit_unix_ns"] for r in pair_rows)
        if lead <= 0:
            raise ValueError("A forecast commitment followed the first future transition")
        minimum_lead = lead if minimum_lead is None else min(minimum_lead, lead)
    weights = json.loads((model / "weights.json").read_text())
    spec = json.loads(protocol.read_text())
    torch.set_num_threads(1)
    generator = Snapshot.load(spec["paths"]["model"],
                              expected_file_sha256=spec["input_sha256"]["model"])._model
    media_digest = hashlib.sha256()
    for name, indices in groups.items():
        path = data / "commits" / name
        digest = file_sha(path)
        if any(rows[i]["commit_sha256"] != digest for i in indices):
            raise ValueError("Committed forecast file bytes changed")
        with np.load(path, allow_pickle=False) as committed:
            if set(committed.files) != {"x_q24", "past_q24", "forecast", "raw_probability"}:
                raise ValueError("Reserved forecast commitment has the wrong schema")
            if (not np.array_equal(committed["x_q24"], d["x_q24"][indices])
                    or not np.array_equal(committed["past_q24"], d["past_q24"][indices])):
                raise ValueError("Committed public inputs or past differ from the evaluation arrays")
            forecast, probability = predict(weights, committed["x_q24"] / Q)
            if (not np.array_equal(forecast, committed["forecast"])
                    or not np.array_equal(probability, committed["raw_probability"])):
                raise ValueError("Committed forecasts differ from the frozen predictor")
        pixels = []
        for i in indices:
            row = rows[i]
            directory = data / "media" / f"{row['pair']:04d}-{row['action']}"
            image, caption, identity = read_bundle({"image": directory / "image.png",
                                                    "text": directory / "caption.txt"})
            if identity != row["media"] or caption != render_tokens(torch.tensor(d["future_tokens"][i])):
                raise ValueError("Reopened future media differs from its recorded identity/tokens")
            pixels.append(image[0])
            media_digest.update(json.dumps(identity, sort_keys=True).encode())
        frame = SimpleNamespace(pixels=torch.stack(pixels), tokens=torch.tensor(d["future_tokens"][indices]))
        if not np.array_equal(emitted_state(generator, frame), d["future_q24"][indices]):
            raise ValueError("Re-encoded persisted future differs from the actual target state")
    source_ids = sorted({s for row in rows for s in row["source_ids"]})
    result = {"schema": "hepta.abc4.future-evidence-audit.v1",
        "protocol_sha256": file_sha(protocol), "data_sha256": file_sha(data / "data.npz"),
        "rows_sha256": file_sha(data / "rows.jsonl.gz"),
        "weights_sha256": file_sha(model / "weights.json"),
        "source_pairs": len(pairs), "future_rows": len(rows), "committed_forecast_files": len(groups),
        "individual_source_ids": len(source_ids),
        "source_id_census_sha256": hashlib.sha256("\n".join(source_ids).encode()).hexdigest(),
        "actual_media_identity_sequence_sha256": media_digest.hexdigest(),
        "minimum_recorded_commit_lead_ns": minimum_lead,
        "two_forecasts_before_first_future_transition_for_every_pair": True,
        "committed_input_past_forecast_and_probability_exact": True,
        "all_png_and_caption_hashes_match": True, "all_rendered_tokens_match": True,
        "all_reopened_future_state_coordinates_exact_q24": True,
        "new_independent_samples": 0,
        "scope": "post-execution audit of frozen commits and reopened actual media; local timestamps plus frozen code order, not an authenticated external clock or independent replication"}
    if output.exists():
        raise ValueError("Audit output already exists")
    write_json(output, result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("protocol", "data", "model", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    audit(args.protocol, args.data, args.model, args.output)
