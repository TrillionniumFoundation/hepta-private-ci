"""Continue the frozen #6282 N128 capsule through the second-cycle warm lane."""

import hashlib
import json
import math
from dataclasses import replace
from fractions import Fraction as F
from pathlib import Path

import numpy as np

from qualification.hcsn_currentstate_n128_engineering import candidate
from qualification.hcsn_currentstate_n128_firstcycle import candidate_cycle
from qualification.hcsn_currentstate_n128_firststep.candidate_step import (
    CHANNELS,
    DISCOUNT,
    _dense,
    _integrated,
    _source,
)


START_SHA256 = "833474bcdaf45c7787a2869fa86efbad2f8b22fdb0c88d0fbcbef1764f8a72a9"
QUERIES = (F(201, 1000), F(7, 25), F(9, 25))
GLOBAL_ORDERS = (5, 6, 7)


def _capsule(summary, hashes, published, roster, order, state, pending):
    expected = [row for row in published if row["capsule_order"] == order]
    actual = [
        (
            packet.source,
            packet.generation,
            packet.operator.dimension,
            packet.target,
            packet.origin,
            [packet.start.numerator, packet.start.denominator],
            [packet.end.numerator, packet.end.denominator],
        )
        for packet in pending
    ]
    target = [
        (
            row["source"],
            row["generation"],
            row["dimension"],
            row["target"],
            row["origin"],
            row["start"]["fraction"],
            row["end"]["fraction"],
        )
        for row in expected
    ]
    if actual != target:
        raise ValueError(f"warm-{order} packet roster mismatch")
    readouts = tuple(
        candidate.Readout(
            0,
            index,
            F(*roster[index]["time"]["fraction"]),
            roster[index]["capsule_identity"],
        )
        for index in range(order + 1)
    )
    result = candidate.NumericCapsule(
        summary["coordinate_identity_sha256"],
        tuple(sorted(hashes.items())),
        roster[order]["capsule_identity"],
        0,
        F(*roster[order]["time"]["fraction"]),
        127,
        readouts,
        state,
        tuple(pending),
    )
    conceptual = len(state) + sum(
        packet.operator.dimension**2
        + 6 * packet.operator.dimension
        for packet in pending
    )
    if conceptual != roster[order]["coordinate_count"]:
        raise ValueError(f"warm-{order} coordinate denominator")
    return result


def _split_state(state):
    values = np.asarray(state)
    offset = 0
    active = values[offset : offset + CHANNELS * 2 * 127].reshape(CHANNELS, 2, 127).copy()
    offset += CHANNELS * 2 * 127
    upper = values[offset : offset + CHANNELS * 3].reshape(CHANNELS, 3).copy()
    offset += CHANNELS * 3
    mass = values[offset : offset + CHANNELS * 2].reshape(CHANNELS, 2).copy()
    offset += CHANNELS * 2
    hit = values[offset : offset + CHANNELS * 2].reshape(CHANNELS, 2).copy()
    offset += CHANNELS * 2
    occupation = values[offset : offset + CHANNELS * 3].reshape(CHANNELS, 3).copy()
    offset += CHANNELS * 3
    if offset != len(values):
        raise ValueError("complete state layout")
    return active, upper, mass, hit, occupation


def run(start_path, law_path, metadata_path, npz_path, roster_dir):
    raw = Path(start_path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != START_SHA256:
        raise ValueError("#6282 terminal capsule hash")
    start = candidate.load(raw)
    hashes, _, metadata, arrays = candidate.load_inputs(
        law_path, metadata_path, npz_path
    )
    summary, published, roster, _ = candidate.roster_records(roster_dir)
    if (
        start.time != F(1, 5)
        or start.lane != 0
        or start.capsule_identity != roster[4]["capsule_identity"]
        or start.input_hashes != tuple(sorted(hashes.items()))
    ):
        raise ValueError("#6282 terminal capsule identity")
    nodes = arrays["nodes.npy"][1]
    spatial, lower, upper_flow, reset = candidate.spatial_operator(metadata, nodes)
    bundle = hashlib.sha256(
        json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    active, upper, mass, hit, occupation = _split_state(start.state)
    pending = list(start.packets)
    time = start.time
    capsules = []
    segments = 0
    exponentials = 0
    for global_order, query in zip(GLOBAL_ORDERS, QUERIES):
        while time < query:
            boundaries = [query, time + F(1, 5)]
            for packet in pending:
                boundaries.extend((packet.start, packet.end))
            right = min(value for value in boundaries if value > time)
            releasing = [packet for packet in pending if packet.start == time]
            if len(releasing) != 1 or releasing[0].target not in (1, 2):
                raise ValueError("bounded second-cycle release")
            global_discount = math.exp(-DISCOUNT * float(time))
            occupation[:, 0] += (
                global_discount
                * upper[:, 0]
                * (-math.expm1(-DISCOUNT * float(right - time)) / DISCOUNT)
            )
            updates = {}
            emissions = []
            for origin in (1, 2):
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
                operator, output = candidate.block_operator(
                    templates, spatial, lower, reset
                )
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
                lower_selector[spatial_offset:operator.dimension, 0] = lower
                evolution, lower_integral = _integrated(
                    extended, lower_selector, right - time, 0.0
                )
                final = initial @ evolution
                selectors = np.zeros((len(extended), 2))
                selectors[spatial_offset:operator.dimension, 0] = lower
                selectors[:operator.dimension, 1] = 1.0
                _, discounted = _integrated(
                    extended, selectors, right - time, DISCOUNT
                )
                active[:, origin - 1] = final[
                    :, spatial_offset:operator.dimension
                ]
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
                        retained.append(
                            replace(packet, start=right, alpha=updates[packet.source])
                        )
                elif packet.start == time:
                    raise ValueError("unhandled releasing packet")
                else:
                    retained.append(packet)
            pending = retained + emissions
            time = right
            segments += 1
        capsules.append(
            _capsule(
                summary,
                hashes,
                published,
                roster,
                global_order,
                candidate_cycle.state_tuple(active, upper, mass, hit, occupation),
                pending,
            )
        )
    return tuple(capsules), {
        "candidate_dynamic_segments": segments,
        "candidate_matrix_exponentials": exponentials,
        "candidate_capsules": len(capsules),
    }
