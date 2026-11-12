"""Candidate N128 first cycle using the source-bound #6264 primitives."""

import hashlib
import json
import math
from dataclasses import replace
from fractions import Fraction as F

import numpy as np

from qualification.hcsn_currentstate_n128_engineering import candidate
from qualification.hcsn_currentstate_n128_firststep.candidate_step import (
    CHANNELS,
    DISCOUNT,
    _dense,
    _integrated,
    _phase,
    _source,
)


QUERIES = (F(0), F(1, 1000), F(1, 50), F(4, 25), F(1, 5))


def state_tuple(active, upper, mass, hit, occupation):
    return tuple(
        np.concatenate(
            (
                active.ravel(),
                upper.ravel(),
                mass.ravel(),
                hit.ravel(),
                occupation.ravel(),
            )
        )
    )


def capsule(summary, hashes, published, roster, order, state, pending):
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
    if len(candidate.coordinate_lines(result)) != roster[order]["coordinate_count"]:
        raise ValueError(f"warm-{order} coordinate denominator")
    return result


def run(law_path, metadata_path, npz_path, roster_dir):
    hashes, _, metadata, arrays = candidate.load_inputs(
        law_path, metadata_path, npz_path
    )
    summary, published, roster, _ = candidate.roster_records(roster_dir)
    nodes = arrays["nodes.npy"][1]
    original_active = np.asarray(arrays["active.npy"][1])
    original_content = np.asarray(arrays["content.npy"][1]).reshape(129, 4)
    spatial, lower, upper_flow, reset = candidate.spatial_operator(metadata, nodes)
    bundle = hashlib.sha256(
        json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    pending, templates = _phase(metadata, bundle)
    active = np.zeros((CHANNELS, 2, 127))
    active[:, 0] = np.column_stack((original_active[1:-1], original_content[1:-1])).T
    upper = np.zeros((CHANNELS, 3))
    upper[:, 0] = np.r_[original_active[-1], original_content[-1]]
    mass = np.zeros((CHANNELS, 2))
    hit = np.zeros((CHANNELS, 2))
    occupation = np.zeros((CHANNELS, 3))
    time = F(0)
    capsules = [
        capsule(
            summary,
            hashes,
            published,
            roster,
            0,
            state_tuple(active, upper, mass, hit, occupation),
            pending,
        )
    ]
    segments = 0
    exponentials = 0
    for order, query in enumerate(QUERIES[1:], 1):
        while time < query:
            boundaries = [query, time + F(1, 5)]
            for packet in pending:
                boundaries.extend((packet.start, packet.end))
            right = min(value for value in boundaries if value > time)
            releasing = [packet for packet in pending if packet.start == time]
            if len(releasing) != 1 or releasing[0].target != 1:
                raise ValueError("bounded first-cycle phase release")
            parent = releasing[0]
            template = candidate.Template(
                parent.source,
                parent.generation,
                parent.start,
                parent.end,
                parent.target,
                parent.origin,
                parent.operator,
                parent.output,
                (),
            )
            operator, output = candidate.block_operator(
                (template,), spatial, lower, reset
            )
            source = _source(bundle, "lower-flux", time, right, 2, 1, (parent.source,))
            alpha = np.concatenate(
                (np.asarray(parent.alpha)[:, None], active[:, 0]), axis=1
            )
            extended = np.zeros((operator.dimension + 1, operator.dimension + 1))
            extended[:-1, :-1] = _dense(operator)
            extended[1:-1, -1] = upper_flow
            initial = np.concatenate((alpha, upper[:, 1, None]), axis=1)
            lower_selector = np.zeros((len(extended), 1))
            lower_selector[1:-1, 0] = lower
            evolution, lower_integral = _integrated(
                extended, lower_selector, right - time, 0.0
            )
            final = initial @ evolution
            selectors = np.zeros((len(extended), 2))
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
                    if packet.end > right:
                        retained.append(
                            replace(packet, start=right, alpha=tuple(final[:, 0]))
                        )
                else:
                    retained.append(packet)
            retained.append(
                candidate.NumericPacket(
                    source,
                    2,
                    2,
                    1,
                    time + F(1, 5),
                    right + F(1, 5),
                    operator,
                    tuple(alpha.ravel()),
                    output,
                )
            )
            pending = retained
            time = right
            segments += 1
            exponentials += 2
        capsules.append(
            capsule(
                summary,
                hashes,
                published,
                roster,
                order,
                state_tuple(active, upper, mass, hit, occupation),
                pending,
            )
        )
    return tuple(capsules), {
        "candidate_dynamic_segments": segments,
        "candidate_matrix_exponentials": exponentials,
        "candidate_capsules": len(capsules),
        "candidate_coordinates": sum(
            len(candidate.coordinate_lines(item)) for item in capsules
        ),
    }
