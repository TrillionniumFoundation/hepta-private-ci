"""Candidate first dynamic step using the source-bound #6264 graph primitives."""

import hashlib
import json
import math
from fractions import Fraction as F

import numpy as np
from scipy.linalg import expm

from qualification.hcsn_currentstate_n128_engineering import candidate


TIME = F(1, 1000)
DISCOUNT = 0.15
CHANNELS = 5


def _dense(operator):
    matrix = np.zeros((operator.dimension, operator.dimension))
    for row in range(operator.dimension):
        for index in range(operator.indptr[row], operator.indptr[row + 1]):
            matrix[row, operator.indices[index]] = operator.data[index]
    return matrix


def _source(bundle, kind, start, end, target, origin, parents):
    return candidate.source_identity(bundle, kind, start, end, target, origin, parents)


def _phase(metadata, bundle):
    zero = candidate.CSR.from_rows(({},))
    packets = []
    templates = []
    for item in metadata["phase"]:
        start, end = F(item["start"]), F(item["end"])
        width = end - start
        alpha = (float(F(item["mass"]) / width),) + tuple(
            float(F(value) / width) for value in item["content"]
        )
        source = _source(bundle, item["identity"], start, end, 1, 0, ())
        packets.append(
            candidate.NumericPacket(source, 1, 1, 0, start, end, zero, alpha, (1.0,))
        )
        templates.append(
            candidate.Template(source, 1, start, end, 1, 0, zero, (1.0,), ())
        )
    return packets, templates


def _integrated(matrix, selectors, duration, discount):
    n, outputs = selectors.shape
    augmented = np.zeros((n + outputs, n + outputs))
    augmented[:n, :n] = matrix - discount * np.eye(n)
    augmented[:n, n:] = selectors
    evolution = expm(augmented * float(duration))
    return evolution[:n, :n], evolution[:n, n:]


def run(law_path, metadata_path, npz_path, roster_dir):
    hashes, _, metadata, arrays = candidate.load_inputs(
        law_path, metadata_path, npz_path
    )
    summary, published, capsules, _ = candidate.roster_records(roster_dir)
    if len(capsules) != 14 or capsules[1]["time"]["fraction"] != [1, 1000]:
        raise ValueError("authentic warm-1 roster")
    nodes = arrays["nodes.npy"][1]
    active = np.asarray(arrays["active.npy"][1])
    content = np.asarray(arrays["content.npy"][1]).reshape(129, 4)
    spatial, lower, upper_flow, reset = candidate.spatial_operator(metadata, nodes)
    bundle = hashlib.sha256(
        json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    phases, templates = _phase(metadata, bundle)
    if len(phases) != 8 or phases[0].start != 0 or phases[0].end <= TIME:
        raise ValueError("first phase support")
    operator, output = candidate.block_operator((templates[0],), spatial, lower, reset)
    source = _source(
        bundle,
        "lower-flux",
        F(0),
        TIME,
        2,
        1,
        (templates[0].source,),
    )
    interior = np.column_stack((active[1:-1], content[1:-1])).T
    phase_alpha = np.asarray(phases[0].alpha)[:, None]
    alpha = np.concatenate((phase_alpha, interior), axis=1)
    matrix = _dense(operator)
    extended = np.zeros((operator.dimension + 1, operator.dimension + 1))
    extended[:-1, :-1] = matrix
    extended[1:-1, -1] = upper_flow
    initial = np.concatenate((alpha, np.zeros((CHANNELS, 1))), axis=1)
    lower_selector = np.zeros((len(extended), 1))
    lower_selector[1:-1, 0] = lower
    evolution, lower_integral = _integrated(extended, lower_selector, TIME, 0.0)
    final = initial @ evolution
    discounted_selectors = np.zeros((len(extended), 2))
    discounted_selectors[:, 1] = 1.0
    discounted_selectors[0, 1] = 0.0
    discounted_selectors[1:-1, 0] = lower
    _, discounted_integral = _integrated(extended, discounted_selectors, TIME, DISCOUNT)
    active_state = np.zeros((CHANNELS, 2, 127))
    active_state[:, 0] = final[:, 1:-1]
    upper = np.zeros((CHANNELS, 3))
    upper[:, 0] = np.r_[active[-1], content[-1]]
    upper[:, 1] = final[:, -1]
    mass = np.zeros((CHANNELS, 2))
    mass[:, 0] = (initial @ lower_integral)[:, 0]
    discounted_mass = np.zeros((CHANNELS, 2))
    discounted_mass[:, 0] = (initial @ discounted_integral)[:, 0]
    occupation = np.zeros((CHANNELS, 3))
    occupation[:, 0] = upper[:, 0] * (-math.expm1(-DISCOUNT * float(TIME)) / DISCOUNT)
    occupation[:, 1] = (initial @ discounted_integral)[:, 1]
    state = tuple(
        np.concatenate(
            (
                active_state.ravel(),
                upper.ravel(),
                mass.ravel(),
                discounted_mass.ravel(),
                occupation.ravel(),
            )
        )
    )
    retained = [
        candidate.NumericPacket(
            packet.source,
            packet.generation,
            packet.target,
            packet.origin,
            TIME if index == 0 else packet.start,
            packet.end,
            packet.operator,
            tuple(final[:, 0]) if index == 0 else packet.alpha,
            packet.output,
        )
        for index, packet in enumerate(phases)
    ]
    retained.append(
        candidate.NumericPacket(
            source,
            2,
            2,
            1,
            F(1, 5),
            F(201, 1000),
            operator,
            tuple(alpha.ravel()),
            output,
        )
    )
    records = [row for row in published if row["capsule_order"] == 1]
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
        for packet in retained
    ]
    expected = [
        (
            row["source"],
            row["generation"],
            row["dimension"],
            row["target"],
            row["origin"],
            row["start"]["fraction"],
            row["end"]["fraction"],
        )
        for row in records
    ]
    if actual != expected:
        raise ValueError("warm-1 packet roster mismatch")
    readouts = tuple(
        candidate.Readout(
            0,
            index,
            F(*capsules[index]["time"]["fraction"]),
            capsules[index]["capsule_identity"],
        )
        for index in (0, 1)
    )
    capsule = candidate.NumericCapsule(
        summary["coordinate_identity_sha256"],
        tuple(sorted(hashes.items())),
        capsules[1]["capsule_identity"],
        0,
        TIME,
        127,
        readouts,
        state,
        tuple(retained),
    )
    if len(candidate.coordinate_lines(capsule)) != capsules[1]["coordinate_count"]:
        raise ValueError("warm-1 coordinate denominator")
    return capsule, {
        "candidate_matrix_exponentials": 2,
        "candidate_operator_dimension": operator.dimension,
        "candidate_state_coordinates": len(state),
        "candidate_packet_coordinates": capsules[1]["coordinate_count"] - len(state),
    }
