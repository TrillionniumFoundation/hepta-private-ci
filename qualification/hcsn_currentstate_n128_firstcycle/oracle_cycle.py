"""Independent dense N128 first-cycle oracle; imports no candidate source."""

import hashlib
import json
import math
from fractions import Fraction as F
from pathlib import Path

import numpy as np

from qualification.hcsn_currentstate_n128_firststep.oracle_step import (
    DISCOUNT,
    _integrated,
    _source,
    _spatial,
    coordinate_lines,
)


QUERIES = (F(0), F(1, 1000), F(1, 50), F(4, 25), F(1, 5))


def state_array(active, upper, mass, hit, occupation):
    return np.concatenate(
        (active.ravel(), upper.ravel(), mass.ravel(), hit.ravel(), occupation.ravel())
    )


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
        original_active, original_content, nodes = (
            stored[name].copy() for name in ("active", "content", "nodes")
        )
    spatial, lower, upper_flow, reset = _spatial(metadata, nodes)
    bundle = hashlib.sha256(
        json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    pending = []
    for item in metadata["phase"]:
        start, end = F(item["start"]), F(item["end"])
        width = end - start
        pending.append(
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
    active = np.zeros((5, 2, 127))
    active[:, 0] = np.column_stack((original_active[1:-1], original_content[1:-1])).T
    upper = np.zeros((5, 3))
    upper[:, 0] = np.r_[original_active[-1], original_content[-1]]
    mass = np.zeros((5, 2))
    hit = np.zeros((5, 2))
    occupation = np.zeros((5, 3))
    time = F(0)
    capsules = [
        {
            "state": state_array(active, upper, mass, hit, occupation),
            "packets": tuple(pending),
        }
    ]
    segments = 0
    exponentials = 0
    for query in QUERIES[1:]:
        while time < query:
            boundaries = [query, time + F(1, 5)]
            for packet in pending:
                boundaries.extend((packet["start"], packet["end"]))
            right = min(value for value in boundaries if value > time)
            releasing = [packet for packet in pending if packet["start"] == time]
            if len(releasing) != 1 or releasing[0]["target"] != 1:
                raise ValueError("bounded first-cycle phase release")
            parent = releasing[0]
            combined = np.zeros((128, 128))
            combined[0, 1:] = reset
            combined[1:, 1:] = spatial
            output = np.r_[0.0, lower]
            source = _source(
                bundle, "lower-flux", time, right, 2, 1, (parent["source"],)
            )
            alpha = np.concatenate((parent["alpha"][:, None], active[:, 0]), axis=1)
            extended = np.zeros((129, 129))
            extended[:-1, :-1] = combined
            extended[1:-1, -1] = upper_flow
            initial = np.concatenate((alpha, upper[:, 1, None]), axis=1)
            lower_selector = np.zeros((129, 1))
            lower_selector[1:-1, 0] = lower
            evolution, lower_integral = _integrated(
                extended, lower_selector, right - time, 0.0
            )
            final = initial @ evolution
            selectors = np.zeros((129, 2))
            selectors[1:-1, 0] = lower
            selectors[1:, 1] = 1.0
            _, discounted = _integrated(extended, selectors, right - time, DISCOUNT)
            global_discount = math.exp(-DISCOUNT * float(time))
            active[:, 0] = final[:, 1:-1]
            upper[:, 1] = final[:, -1]
            mass[:, 0] += (initial @ lower_integral)[:, 0]
            hit[:, 0] += global_discount * (initial @ discounted)[:, 0]
            occupation[:, 0] += (
                global_discount
                * upper[:, 0]
                * (-math.expm1(-DISCOUNT * float(right - time)) / DISCOUNT)
            )
            occupation[:, 1] += global_discount * (initial @ discounted)[:, 1]
            retained = []
            for packet in pending:
                if packet is parent:
                    if packet["end"] > right:
                        retained.append(dict(packet, start=right, alpha=final[:, 0]))
                else:
                    retained.append(packet)
            retained.append(
                {
                    "source": source,
                    "generation": 2,
                    "target": 2,
                    "origin": 1,
                    "start": time + F(1, 5),
                    "end": right + F(1, 5),
                    "generator": combined,
                    "alpha": alpha,
                    "output": output,
                }
            )
            pending = retained
            time = right
            segments += 1
            exponentials += 2
        capsules.append(
            {
                "state": state_array(active, upper, mass, hit, occupation),
                "packets": tuple(pending),
            }
        )
    return tuple(capsules), {
        "oracle_dynamic_segments": segments,
        "oracle_matrix_exponentials": exponentials,
        "oracle_capsules": len(capsules),
        "oracle_coordinates": sum(len(coordinate_lines(item)) for item in capsules),
    }
