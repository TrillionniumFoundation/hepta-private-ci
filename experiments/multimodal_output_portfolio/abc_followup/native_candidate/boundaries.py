"""Verify the complete source/action census, predictions and persisted evidence."""

import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch

from ...abc_recovery.training_run import file_sha
from ...v6.data import render_tokens
from ...v6.observer import read_bundle
from ...v7.snapshot import Snapshot
from ...v7.sources import read_manifest
from ..native.forecast import ACTIONS, Q, absent, emitted_state
from .protocol import forecasts, heads, segments, verify
from .source_guard import verify_access


def check_arrays(data):
    shapes = {"x_q24": (2000, 478), "past_q24": (2000, 32), "future_q24": (2000, 32),
        "future_tokens": (2000, 8), "forecast": (2000, 3, 32), "raw_probability": (2000, 3),
        "calibrated_probability": (2000, 3), "calibration_group": (2000, 3),
        **{key: (2000,) for key in ("y", "pair", "action", "ood", "view")}}
    if set(data) != set(shapes) or any(data[k].shape != shape for k, shape in shapes.items()):
        raise ValueError("Candidate data schema or complete census changed")
    if (any(not np.issubdtype(data[k].dtype, np.integer) for k in ("pair", "action", "y", "future_tokens", "calibration_group"))
            or data["ood"].dtype != np.dtype(bool)):
        raise ValueError("Source/action/label integer and OOD boolean types required")
    assignment = {i: view for view, start, count in segments() for i in range(start, start+count)}
    seen = set()
    for pair, action, view, ood in zip(data["pair"], data["action"], data["view"], data["ood"]):
        key = int(pair), int(action)
        if (key in seen or key[0] not in assignment or key[1] not in (0, 1)
                or assignment[key[0]] != view or bool(ood) != (view == "both_missing")):
            raise ValueError("Duplicate, missing, or relabeled source/action")
        seen.add(key)
    if seen != {(pair, action) for pair in range(1000) for action in (0, 1)}:
        raise ValueError("Incomplete candidate source/action family")
    if not np.isin(data["y"], (0, 1)).all() or not np.isin(data["future_tokens"], np.arange(24)).all():
        raise ValueError("Invalid observed label or token domain")
    action_flags = np.eye(2, dtype=np.int64)[data["action"]] * Q
    if (not np.array_equal(data["x_q24"][:, 476:478], action_flags)
            or not np.array_equal(absent(data["x_q24"] / Q), data["ood"])):
        raise ValueError("Actual public input action or absence differs from row identity")
    for key, bound in (("x_q24", 8*Q), ("past_q24", Q), ("future_q24", Q)):
        if (not np.issubdtype(data[key].dtype, np.integer)
                or (data[key] < -bound).any() or (data[key] > bound).any()):
            raise ValueError("Invalid actual Q24 state")
    for key in ("forecast", "raw_probability", "calibrated_probability"):
        if not np.isfinite(data[key]).all() or np.abs(data[key]).max() > 1:
            raise ValueError("Invalid committed forward value")
    if ((data["raw_probability"] < 0).any() or (data["calibrated_probability"] < 0).any()
            or not np.isin(data["calibration_group"], np.arange(8)).all()):
        raise ValueError("Invalid probability or frozen calibration group")


def verified_data(protocol):
    spec = verify(protocol); directory = Path(spec["output"])
    access = verify_access(protocol, directory)
    cost = json.loads((directory / "cost.json").read_text())
    if (cost["protocol_sha256"] != file_sha(protocol) or cost["source_pairs"] != 1000
            or cost["future_rows"] != 2000 or cost["model_predictions"] != 6000
            or cost["data_sha256"] != file_sha(directory / "data.npz")
            or cost["rows_sha256"] != file_sha(directory / "rows.jsonl.gz")):
        raise ValueError("Actual candidate artifacts or costs differ from registration")
    with np.load(directory / "data.npz", allow_pickle=False) as stream:
        data = {key: stream[key] for key in stream.files}
    check_arrays(data)
    with gzip.open(directory / "rows.jsonl.gz", "rt") as stream:
        rows = [json.loads(line) for line in stream]
    if len(rows) != 2000:
        raise ValueError("Actual future rows incomplete")
    groups, pairs, source_ids = {}, {}, set()
    assigned_ids = read_manifest(Path(spec["paths"]["manifest"]))["roles"][spec["origin_role"]]["source_ids"]
    if len(assigned_ids) != 2000:
        raise ValueError("Registered source population changed")
    for i, row in enumerate(rows):
        score = row["scores"]
        observed_label = int(score["caption_valid"] and all(score[k] == 0 for k in
            ("text_fact", "relation", "image_fact", "crossmodal_disagreement")))
        if (row["pair"] != data["pair"][i] or ACTIONS.index(row["action"]) != data["action"][i]
                or row["view"] != data["view"][i] or row["joint_correct"] != data["y"][i]
                or observed_label != data["y"][i] or row["forecast_used_current_outcome"]):
            raise ValueError("Observed row/data identity mismatch")
        if row["source_ids"] != assigned_ids[2*row["pair"]:2*row["pair"]+2]:
            raise ValueError("Observed pair does not belong to its exact assigned source IDs")
        times = [row[key] for key in ("commit_unix_ns", "transition_started_unix_ns", "generation_finished_unix_ns")]
        if (any(type(value) is not int for value in times)
                or not access["opened_unix_ns"] <= times[0] < times[1] <= times[2]):
            raise ValueError("Actual commitment/generation order differs from new access registration")
        groups.setdefault(row["commit_file"], []).append(i)
        pairs.setdefault(row["pair"], []).append(row)
        source_ids.update(row["source_ids"])
    if len(source_ids) != 2000:
        raise ValueError("Original individual-source census changed")
    for pair_rows in pairs.values():
        if (len(pair_rows) != 2 or len({r["prefix_public_digest"] for r in pair_rows}) != 1
                or len({tuple(r["source_ids"]) for r in pair_rows}) != 1
                or max(r["commit_unix_ns"] for r in pair_rows) >= min(r["transition_started_unix_ns"] for r in pair_rows)):
            raise ValueError("Both three-head commitments must precede the first future branch")
    models, calibration = heads(spec)
    torch.set_num_threads(1)
    generator = Snapshot.load(spec["paths"]["generator"], expected_file_sha256=spec["file_pins"]["generator"])._model
    for name, indices in groups.items():
        path = directory / "commits" / name
        digest = file_sha(path)
        if any(digest != rows[i]["commit_sha256"] for i in indices):
            raise ValueError("Durable forward commitment bytes changed")
        with np.load(path, allow_pickle=False) as committed:
            expected = {"x_q24": data["x_q24"][indices], "past_q24": data["past_q24"][indices],
                **forecasts(models, calibration, data["x_q24"][indices])}
            if set(committed.files) != set(expected):
                raise ValueError("Commitment schema changed")
            for key, value in expected.items():
                if not np.array_equal(committed[key], value) or not np.array_equal(data[key][indices], value):
                    raise ValueError("Committed forecasts, frozen heads, and evaluation arrays disagree")
        pixels = []
        for i in indices:
            row = rows[i]; root = directory / "media" / f"{row['pair']:04d}-{row['action']}"
            image, caption, identity = read_bundle({"image": root / "image.png", "text": root / "caption.txt"})
            if identity != row["media"] or caption != render_tokens(torch.tensor(data["future_tokens"][i])):
                raise ValueError("Observed future media changed")
            pixels.append(image[0])
        state = emitted_state(generator, SimpleNamespace(pixels=torch.stack(pixels), tokens=torch.tensor(data["future_tokens"][indices])))
        if not np.array_equal(state, data["future_q24"][indices]):
            raise ValueError("Persisted future state target differs from actual media")
    return spec, data, {"all_commitments_exact": True, "all_actual_media_reopened": True,
        "both_actions_all_three_forecasts_precede_future": True, "source_pairs": len(pairs),
        "individual_sources": len(source_ids), "future_rows": len(rows), "commit_files": len(groups)}
