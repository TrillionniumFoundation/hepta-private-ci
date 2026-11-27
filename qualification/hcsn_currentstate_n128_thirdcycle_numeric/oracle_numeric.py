"""Independent dense oracle for the bounded third-cycle successor."""

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
)
from qualification.hcsn_currentstate_n128_thirdcycle_serializer import independent


START_SHA256 = "4da73ed41ca89680a77f8bb3a5b7c04a805aa7af132f01ce9ea5e749e906d065"
QUERY = F(401, 1000)


def _dense(operator):
    dimension, indptr, indices, data = operator
    matrix = np.zeros((dimension, dimension))
    for row in range(dimension):
        for cursor in range(indptr[row], indptr[row + 1]):
            matrix[row, indices[cursor]] = data[cursor]
    return matrix


def _decode(path):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != START_SHA256:
        raise ValueError("#6287 independent start hash")
    decoded = independent.decode(raw)
    packets = []
    for source, generation, target, origin, start, end, operator, alpha, output in decoded["packets"]:
        packets.append(
            {
                "source": source,
                "generation": generation,
                "target": target,
                "origin": origin,
                "start": start,
                "end": end,
                "generator": _dense(operator),
                "alpha": np.asarray(alpha).reshape(5, operator[0]),
                "output": np.asarray(output),
            }
        )
    return decoded, packets


def _split_state(values):
    values = np.asarray(values)
    offset = 0
    active = values[offset : offset + 1905].reshape(5, 3, 127).copy()
    offset += 1905
    upper = values[offset : offset + 20].reshape(5, 4).copy()
    offset += 20
    mass = values[offset : offset + 15].reshape(5, 3).copy()
    offset += 15
    hit = values[offset : offset + 15].reshape(5, 3).copy()
    offset += 15
    occupation = values[offset : offset + 20].reshape(5, 4).copy()
    offset += 20
    if offset != len(values):
        raise ValueError("independent three-generation state")
    return active, upper, mass, hit, occupation


def _block(parents, spatial, lower, reset):
    dimension = 127 + sum(len(packet["generator"]) for packet in parents)
    matrix = np.zeros((dimension, dimension))
    offset = 0
    for packet in parents:
        parent = packet["generator"]
        width = len(parent)
        matrix[offset : offset + width, offset : offset + width] = parent
        matrix[offset : offset + width, -127:] += np.outer(packet["output"], reset)
        offset += width
    matrix[offset:, offset:] = spatial
    return matrix, np.r_[np.zeros(offset), lower]


def run(start_path, law_path, metadata_path, npz_path):
    start, pending = _decode(start_path)
    paths = {"law": Path(law_path), "json": Path(metadata_path), "npz": Path(npz_path)}
    hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}
    if tuple(sorted(hashes.items())) != start["inputs"]:
        raise ValueError("independent input identities")
    metadata = json.loads(paths["json"].read_text())
    with np.load(paths["npz"], allow_pickle=False) as stored:
        nodes = stored["nodes"].copy()
    spatial, lower, upper_flow, reset = _spatial(metadata, nodes)
    bundle = hashlib.sha256(
        json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    active, upper, mass, hit, occupation = _split_state(start["state"])
    time = start["time"]
    segments = 0
    exponentials = 0
    while time < QUERY:
        boundaries = [QUERY, time + F(1, 5)]
        for packet in pending:
            boundaries.extend((packet["start"], packet["end"]))
        right = min(value for value in boundaries if value > time)
        releasing = [packet for packet in pending if packet["start"] == time]
        expected = 2 if time == F(2, 5) else 1
        if len(releasing) != expected or {packet["target"] for packet in releasing} != (
            {2, 3} if expected == 2 else {2}
        ):
            raise ValueError("independent release schedule")
        global_discount = math.exp(-DISCOUNT * float(time))
        occupation[:, 0] += (
            global_discount
            * upper[:, 0]
            * (-math.expm1(-DISCOUNT * float(right - time)) / DISCOUNT)
        )
        updates = {}
        emissions = []
        origins = (1, 2, 3) if any(packet["target"] == 3 for packet in releasing) else (1, 2)
        for origin in origins:
            parents = [packet for packet in releasing if packet["target"] == origin]
            operator, output = _block(parents, spatial, lower, reset)
            source = _source(
                bundle,
                "lower-flux",
                time,
                right,
                origin + 1,
                origin,
                tuple(packet["source"] for packet in parents),
            )
            alpha = np.concatenate(
                [packet["alpha"] for packet in parents] + [active[:, origin - 1]], axis=1
            )
            dimension = len(operator)
            spatial_offset = dimension - 127
            extended = np.zeros((dimension + 1, dimension + 1))
            extended[:-1, :-1] = operator
            extended[spatial_offset:dimension, -1] = upper_flow
            initial = np.concatenate((alpha, upper[:, origin, None]), axis=1)
            lower_selector = np.zeros((dimension + 1, 1))
            lower_selector[spatial_offset:dimension, 0] = lower
            evolution, lower_integral = _integrated(
                extended, lower_selector, right - time, 0.0
            )
            final = initial @ evolution
            selectors = np.zeros((dimension + 1, 2))
            selectors[spatial_offset:dimension, 0] = lower
            selectors[:dimension, 1] = 1.0
            _, discounted = _integrated(extended, selectors, right - time, DISCOUNT)
            active[:, origin - 1] = final[:, spatial_offset:dimension]
            upper[:, origin] = final[:, -1]
            mass[:, origin - 1] += (initial @ lower_integral)[:, 0]
            hit[:, origin - 1] += global_discount * (initial @ discounted)[:, 0]
            occupation[:, origin] += global_discount * (initial @ discounted)[:, 1]
            parent_offset = 0
            for packet in parents:
                width = len(packet["generator"])
                updates[packet["source"]] = final[:, parent_offset : parent_offset + width].copy()
                parent_offset += width
            emissions.append(
                {
                    "source": source,
                    "generation": origin + 1,
                    "target": origin + 1,
                    "origin": origin,
                    "start": time + F(1, 5),
                    "end": right + F(1, 5),
                    "generator": operator,
                    "alpha": alpha.copy(),
                    "output": output,
                }
            )
            exponentials += 2
        retained = []
        for packet in pending:
            if packet["source"] in updates:
                if packet["end"] > right:
                    retained.append(dict(packet, start=right, alpha=updates[packet["source"]]))
            elif packet["start"] == time:
                raise ValueError("independent unhandled release")
            else:
                retained.append(packet)
        pending = retained + emissions
        time = right
        segments += 1
    state = np.concatenate(
        (active.ravel(), upper.ravel(), mass.ravel(), hit.ravel(), occupation.ravel())
    )
    conceptual = len(state) + sum(
        len(packet["generator"]) ** 2 + 6 * len(packet["generator"])
        for packet in pending
    )
    target4 = [
        packet
        for packet in pending
        if packet["target"] == 4
        and packet["origin"] == 3
        and packet["start"] == F(3, 5)
        and packet["end"] == F(601, 1000)
        and len(packet["generator"]) == 382
    ]
    if (segments, exponentials, len(pending), conceptual, len(target4)) != (
        3,
        14,
        25,
        1151028,
        1,
    ):
        raise ValueError("independent denominator")
    return {"state": state, "packets": tuple(pending)}, {
        "oracle_dynamic_segments": segments,
        "oracle_matrix_exponentials": exponentials,
        "oracle_packets": len(pending),
        "oracle_target4_packets": len(target4),
        "coordinate_denominator": conceptual,
    }


def coordinates(result):
    yield from result["state"]
    for packet in result["packets"]:
        yield from packet["alpha"].ravel()
        yield from packet["generator"].ravel()
        yield from packet["output"]
