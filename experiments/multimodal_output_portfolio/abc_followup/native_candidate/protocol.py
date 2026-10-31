"""Bind one immutable candidate family, data census, and evaluation method."""

import json
from pathlib import Path

import numpy as np

from ...abc_recovery.training_run import file_sha
from ..native.forecast import ACTIONS, Q, groups, predict
from ..native.future_candidate import apply_candidate, check_weights
from ..native.qualify import check_freeze


HERE = Path(__file__).parent
VIEWS = ("clean", "noise", "occlusion", "missing_trusted", "conflict_untrusted")
IDS = (
    "candidate:no-change:9058ec1051babac8df4de39e582bdb045eba111d422c7e9725f01c10b2919b01",
    "candidate:update:a37048291fca37e406e593f8f5309660db09accf4ab954b411db672c203dc3d4",
    "candidate:update:fdd02ddb1908450167c2169d7f51744c9b3de663d76fd6f672e005c01ce55640",
)


def segments():
    return [(view, i * 100, 100) for i, view in enumerate(VIEWS)] + [("both_missing", 500, 500)]


def verify(path):
    spec = json.loads(Path(path).read_text())
    expected = {"schema": "hepta.abc4.native-candidate-prospective.v1",
        "source_role": "repair_test", "origin_role": "unallocated_test",
        "study_role": "native_candidate_reuse", "pair_start": 0, "pair_count": 1000,
        "candidate_ids": list(IDS), "actions": list(ACTIONS), "id_views": list(VIEWS),
        "segments": [list(x) for x in segments()], "bootstrap_draws": 4000,
        "individual_confidence": .975, "family_confidence": .95,
        "new_project_independent_source_pairs": 0, "seed": 291017}
    if any(spec.get(k) != v for k, v in expected.items()):
        raise ValueError("Frozen family, source census, or inferential contract changed")
    for name, digest in spec["source_pins"].items():
        if file_sha(HERE / name) != digest:
            raise ValueError("Frozen implementation changed: " + name)
    for name, digest in spec["file_pins"].items():
        if file_sha(Path(spec["paths"][name])) != digest:
            raise ValueError("Frozen input changed: " + name)
    if (spec["reuse_assignment_sha256"] != spec["file_pins"]["reuse_assignment"]
            or spec["timeline_sha256"] != spec["file_pins"]["timeline"]):
        raise ValueError("Reuse/timeline identity differs from the pinned files")
    check_freeze(Path(spec["paths"]["primary_protocol"]), Path(spec["paths"]["model"]),
                 "calibrator-freeze.json")
    primary = json.loads(Path(spec["paths"]["primary_protocol"]).read_text())
    for name in ("weights", "calibration"):
        if file_sha(Path(spec["paths"]["model"]) / (name + ".json")) != spec["file_pins"][name]:
            raise ValueError("Head artifacts differ from original calibrator freeze")
    for name, original in (("generator", "model"), ("observer", "observer"), ("manifest", "manifest")):
        if spec["file_pins"][name] != primary["input_sha256"][original]:
            raise ValueError("Original native generator, observer, or source identity changed")
    heads(spec)
    return spec


def heads(spec):
    weights = json.loads(Path(spec["paths"]["weights"]).read_text())
    check_weights(weights)
    candidates = json.loads(Path(spec["paths"]["candidates"]).read_text())
    if (candidates["baseline_weights_sha256"] != spec["file_pins"]["weights"]
            or candidates["generator_digest"] != spec["generator_digest"]
            or candidates["head_contract"] != "future_correctness"
            or candidates["context"]["sequence"] != 802
            or candidates["context"]["anchor"] != spec["candidate_anchor"]
            or [c["id"] for c in candidates["candidates"]] != list(IDS)
            or [c["kind"] for c in candidates["candidates"]] != ["NoChange", "Update", "Update"]):
        raise ValueError("Not the exact pre-existing sequence802 future candidate family")
    models = [apply_candidate(weights, c) for c in candidates["candidates"]]
    return models, json.loads(Path(spec["paths"]["calibration"]).read_text())


def forecasts(models, calibration, x_q24):
    x = x_q24 / Q
    states, raw, calibrated, bins = [], [], [], []
    for model in models:
        state, probability = predict(model, x)
        group = groups(x, probability, calibration["cuts"])
        states.append(state); raw.append(probability); bins.append(group)
        calibrated.append(np.asarray(calibration["probabilities"])[group])
    if any(not np.array_equal(states[0], state) for state in states[1:]):
        raise ValueError("Correctness-only candidates changed state prediction")
    return {"forecast": np.stack(states, 1), "raw_probability": np.stack(raw, 1),
            "calibrated_probability": np.stack(calibrated, 1), "calibration_group": np.stack(bins, 1)}
