"""Candidate continuation from the exact #6287 three-generation capsule."""

import hashlib
import json
import math
from dataclasses import replace
from fractions import Fraction as F
from pathlib import Path

import numpy as np

from qualification.hcsn_currentstate_n128_engineering import candidate
from qualification.hcsn_currentstate_n128_firststep.candidate_step import (
    CHANNELS,
    DISCOUNT,
    _dense,
    _integrated,
    _source,
)
from qualification.hcsn_currentstate_n128_thirdcycle_serializer import format as capsule_format


START_SHA256 = "4da73ed41ca89680a77f8bb3a5b7c04a805aa7af132f01ce9ea5e749e906d065"
START_IDENTITY = "0a2aa32bf4972781bb3dd218a12e8d4a1d3d93f2ea25bbc19d7fcf86f24cae8b"
OUTPUT_IDENTITY = "a1b28a130e282bb042d382f2f310df5a3d22bd321bf052e55a6336ab279eecba"
QUERY = F(401, 1000)


def _split_state(state):
    values = np.asarray(state)
    offset = 0
    active = values[offset : offset + CHANNELS * 3 * 127].reshape(CHANNELS, 3, 127).copy()
    offset += CHANNELS * 3 * 127
    upper = values[offset : offset + CHANNELS * 4].reshape(CHANNELS, 4).copy()
    offset += CHANNELS * 4
    mass = values[offset : offset + CHANNELS * 3].reshape(CHANNELS, 3).copy()
    offset += CHANNELS * 3
    hit = values[offset : offset + CHANNELS * 3].reshape(CHANNELS, 3).copy()
    offset += CHANNELS * 3
    occupation = values[offset : offset + CHANNELS * 4].reshape(CHANNELS, 4).copy()
    offset += CHANNELS * 4
    if offset != len(values):
        raise ValueError("three-generation complete state layout")
    return active, upper, mass, hit, occupation


def _state_tuple(active, upper, mass, hit, occupation):
    return tuple(
        np.concatenate(
            (active.ravel(), upper.ravel(), mass.ravel(), hit.ravel(), occupation.ravel())
        )
    )


def run(start_path, law_path, metadata_path, npz_path):
    raw = Path(start_path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != START_SHA256:
        raise ValueError("#6287 capsule hash")
    start = capsule_format.load(raw)
    hashes, _, metadata, arrays = candidate.load_inputs(law_path, metadata_path, npz_path)
    if (
        start.time != F(9, 25)
        or start.lane != 0
        or start.interior_nodes != 127
        or start.capsule_identity != START_IDENTITY
        or start.input_hashes != tuple(sorted(hashes.items()))
        or len(start.state) != 1975
        or len(start.packets) != 22
    ):
        raise ValueError("#6287 start identity")
    nodes = arrays["nodes.npy"][1]
    spatial, lower, upper_flow, reset = candidate.spatial_operator(metadata, nodes)
    bundle = hashlib.sha256(
        json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    active, upper, mass, hit, occupation = _split_state(start.state)
    pending = list(start.packets)
    time = start.time
    segments = 0
    exponentials = 0
    release_counts = []
    while time < QUERY:
        boundaries = [QUERY, time + F(1, 5)]
        for packet in pending:
            boundaries.extend((packet.start, packet.end))
        right = min(value for value in boundaries if value > time)
        releasing = [packet for packet in pending if packet.start == time]
        expected = 2 if time == F(2, 5) else 1
        if len(releasing) != expected or {packet.target for packet in releasing} != (
            {2, 3} if expected == 2 else {2}
        ):
            raise ValueError("bounded third-cycle release schedule")
        release_counts.append(len(releasing))
        global_discount = math.exp(-DISCOUNT * float(time))
        occupation[:, 0] += (
            global_discount
            * upper[:, 0]
            * (-math.expm1(-DISCOUNT * float(right - time)) / DISCOUNT)
        )
        updates = {}
        emissions = []
        origins = (1, 2, 3) if any(packet.target == 3 for packet in releasing) else (1, 2)
        for origin in origins:
            parents = [packet for packet in releasing if packet.target == origin]
            templates = tuple(
                candidate.Template(
                    packet.source,
                    packet.generation,
                    packet.start,
                    packet.end,
                    packet.target,
                    packet.origin,
                    packet.operator,
                    packet.output,
                    (),
                )
                for packet in parents
            )
            operator, output = candidate.block_operator(templates, spatial, lower, reset)
            source = _source(
                bundle,
                "lower-flux",
                time,
                right,
                origin + 1,
                origin,
                tuple(packet.source for packet in parents),
            )
            pieces = [
                np.asarray(packet.alpha).reshape(CHANNELS, packet.operator.dimension)
                for packet in parents
            ]
            pieces.append(active[:, origin - 1])
            alpha = np.concatenate(pieces, axis=1)
            extended = np.zeros((operator.dimension + 1, operator.dimension + 1))
            extended[:-1, :-1] = _dense(operator)
            spatial_offset = operator.dimension - 127
            extended[spatial_offset : operator.dimension, -1] = upper_flow
            initial = np.concatenate((alpha, upper[:, origin, None]), axis=1)
            lower_selector = np.zeros((len(extended), 1))
            lower_selector[spatial_offset : operator.dimension, 0] = lower
            evolution, lower_integral = _integrated(
                extended, lower_selector, right - time, 0.0
            )
            final = initial @ evolution
            selectors = np.zeros((len(extended), 2))
            selectors[spatial_offset : operator.dimension, 0] = lower
            selectors[: operator.dimension, 1] = 1.0
            _, discounted = _integrated(extended, selectors, right - time, DISCOUNT)
            active[:, origin - 1] = final[:, spatial_offset : operator.dimension]
            upper[:, origin] = final[:, -1]
            mass[:, origin - 1] += (initial @ lower_integral)[:, 0]
            hit[:, origin - 1] += global_discount * (initial @ discounted)[:, 0]
            occupation[:, origin] += global_discount * (initial @ discounted)[:, 1]
            parent_offset = 0
            for packet in parents:
                dimension = packet.operator.dimension
                updates[packet.source] = tuple(
                    final[:, parent_offset : parent_offset + dimension].ravel()
                )
                parent_offset += dimension
            emissions.append(
                candidate.NumericPacket(
                    source,
                    origin + 1,
                    origin + 1,
                    origin,
                    time + F(1, 5),
                    right + F(1, 5),
                    operator,
                    tuple(alpha.ravel()),
                    output,
                )
            )
            exponentials += 2
        retained = []
        for packet in pending:
            if packet.source in updates:
                if packet.end > right:
                    retained.append(replace(packet, start=right, alpha=updates[packet.source]))
            elif packet.start == time:
                raise ValueError("unhandled releasing packet")
            else:
                retained.append(packet)
        pending = retained + emissions
        time = right
        segments += 1
    readouts = start.readouts + (
        candidate.Readout(0, len(start.readouts), QUERY, OUTPUT_IDENTITY),
    )
    result = capsule_format.ThirdCycleCapsule(
        start.roster_identity,
        start.input_hashes,
        OUTPUT_IDENTITY,
        0,
        QUERY,
        127,
        readouts,
        _state_tuple(active, upper, mass, hit, occupation),
        tuple(pending),
    )
    conceptual = len(result.state) + sum(
        packet.operator.dimension**2 + 6 * packet.operator.dimension
        for packet in result.packets
    )
    target4 = [
        packet
        for packet in result.packets
        if packet.target == 4
        and packet.origin == 3
        and packet.start == F(3, 5)
        and packet.end == F(601, 1000)
    ]
    if (
        segments != 3
        or exponentials != 14
        or release_counts != [1, 1, 2]
        or len(result.packets) != 25
        or conceptual != 1151028
        or len(target4) != 1
        or target4[0].operator.dimension != 382
    ):
        raise ValueError("third-cycle result denominator")
    return result, {
        "candidate_dynamic_segments": segments,
        "candidate_matrix_exponentials": exponentials,
        "candidate_packets": len(result.packets),
        "candidate_target4_packets": len(target4),
        "coordinate_denominator": conceptual,
    }
