"""Independent dense first-step oracle; imports no candidate implementation."""

import hashlib
import json
import math
import struct
from fractions import Fraction as F
from pathlib import Path

import numpy as np
from scipy.linalg import expm


TIME = F(1, 1000)
DISCOUNT = 0.15


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _source(bundle, kind, start, end, target, origin, parents):
    return hashlib.sha256(
        _canonical(
            {
                "bundle": bundle,
                "kind": kind,
                "start": [start.numerator, start.denominator],
                "end": [end.numerator, end.denominator],
                "target": target,
                "origin": origin,
                "parents": sorted(parents),
            }
        )
    ).hexdigest()


def _spatial(metadata, nodes):
    mu, sigma = metadata["physics"]["mu"], metadata["physics"]["sigma"]
    gaps = np.diff(nodes)
    matrix = np.zeros((127, 127))
    lower, upper = np.zeros(127), np.zeros(127)
    for index in range(127):
        left, right = gaps[index], gaps[index + 1]
        down = (sigma**2 - mu * right) / (left * (left + right))
        up = (sigma**2 + mu * left) / (right * (left + right))
        matrix[index, index] = -(down + up)
        if index:
            matrix[index, index - 1] = down
        else:
            lower[index] = down
        if index + 1 < 127:
            matrix[index, index + 1] = up
        else:
            upper[index] = up
    position = metadata["reset_distance"]
    right = int(np.searchsorted(nodes, position, side="right"))
    weight = (position - nodes[right - 1]) / (nodes[right] - nodes[right - 1])
    reset = np.zeros(127)
    reset[right - 2] = 1.0 - weight
    reset[right - 1] = weight
    return matrix, lower, upper, reset


def _integrated(matrix, selectors, duration, discount):
    n, outputs = selectors.shape
    augmented = np.zeros((n + outputs, n + outputs))
    augmented[:n, :n] = matrix - discount * np.eye(n)
    augmented[:n, n:] = selectors
    evolution = expm(augmented * float(duration))
    return evolution[:n, :n], evolution[:n, n:]


def run(law_path, metadata_path, npz_path):
    paths = {
        "law": Path(law_path),
        "json": Path(metadata_path),
        "npz": Path(npz_path),
    }
    hashes = {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in paths.items()
    }
    metadata = json.loads(paths["json"].read_text())
    with np.load(paths["npz"], allow_pickle=False) as stored:
        active, content, nodes = (
            stored[name].copy() for name in ("active", "content", "nodes")
        )
    matrix, lower, upper_flow, reset = _spatial(metadata, nodes)
    bundle = hashlib.sha256(_canonical(hashes)).hexdigest()
    phases = []
    for item in metadata["phase"]:
        start, end = F(item["start"]), F(item["end"])
        width = end - start
        phases.append(
            {
                "source": _source(bundle, item["identity"], start, end, 1, 0, ()),
                "generation": 1,
                "target": 1,
                "origin": 0,
                "start": start,
                "end": end,
                "generator": np.zeros((1, 1)),
                "alpha": np.asarray(
                    (float(F(item["mass"]) / width),)
                    + tuple(float(F(value) / width) for value in item["content"])
                ),
                "output": np.ones(1),
            }
        )
    combined = np.zeros((128, 128))
    combined[0, 1:] = reset
    combined[1:, 1:] = matrix
    combined_output = np.r_[0.0, lower]
    interior = np.column_stack((active[1:-1], content[1:-1])).T
    alpha = np.concatenate((phases[0]["alpha"][:, None], interior), axis=1)
    extended = np.zeros((129, 129))
    extended[:-1, :-1] = combined
    extended[1:-1, -1] = upper_flow
    initial = np.concatenate((alpha, np.zeros((5, 1))), axis=1)
    lower_selector = np.zeros((129, 1))
    lower_selector[1:-1, 0] = lower
    evolution, lower_integral = _integrated(extended, lower_selector, TIME, 0.0)
    final = initial @ evolution
    selectors = np.zeros((129, 2))
    selectors[1:-1, 0] = lower
    selectors[1:, 1] = 1.0
    _, discounted = _integrated(extended, selectors, TIME, DISCOUNT)
    live = np.zeros((5, 2, 127))
    live[:, 0] = final[:, 1:-1]
    upper = np.zeros((5, 3))
    upper[:, 0] = np.r_[active[-1], content[-1]]
    upper[:, 1] = final[:, -1]
    mass = np.zeros((5, 2))
    mass[:, 0] = (initial @ lower_integral)[:, 0]
    hit = np.zeros((5, 2))
    hit[:, 0] = (initial @ discounted)[:, 0]
    occupation = np.zeros((5, 3))
    occupation[:, 0] = upper[:, 0] * (-math.expm1(-DISCOUNT * float(TIME)) / DISCOUNT)
    occupation[:, 1] = (initial @ discounted)[:, 1]
    state = np.concatenate(
        (live.ravel(), upper.ravel(), mass.ravel(), hit.ravel(), occupation.ravel())
    )
    phases[0] = dict(phases[0], start=TIME, alpha=final[:, 0])
    phases.append(
        {
            "source": _source(
                bundle, "lower-flux", F(0), TIME, 2, 1, (phases[0]["source"],)
            ),
            "generation": 2,
            "target": 2,
            "origin": 1,
            "start": F(1, 5),
            "end": F(201, 1000),
            "generator": combined,
            "alpha": alpha,
            "output": combined_output,
        }
    )
    return {"state": state, "packets": tuple(phases)}, {"oracle_matrix_exponentials": 2}


def coordinate_lines(capsule):
    rows = [
        {"key": ["state", index], "fp64_le": struct.pack("<d", value).hex()}
        for index, value in enumerate(capsule["state"])
    ]
    for order, packet in enumerate(capsule["packets"]):
        for index, value in enumerate(np.asarray(packet["alpha"]).flat):
            rows.append(
                {
                    "key": ["packet", order, "alpha", index],
                    "fp64_le": struct.pack("<d", value).hex(),
                }
            )
        for row in range(len(packet["generator"])):
            for column in range(len(packet["generator"])):
                rows.append(
                    {
                        "key": ["packet", order, "generator", row, column],
                        "fp64_le": struct.pack(
                            "<d", packet["generator"][row, column]
                        ).hex(),
                    }
                )
        for index, value in enumerate(packet["output"]):
            rows.append(
                {
                    "key": ["packet", order, "output", index],
                    "fp64_le": struct.pack("<d", value).hex(),
                }
            )
    return sorted(rows, key=lambda row: json.dumps(row["key"], separators=(",", ":")))
