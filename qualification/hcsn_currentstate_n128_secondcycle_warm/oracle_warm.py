"""Independent dense continuation of the #6282 terminal capsule."""

import hashlib
import json
import math
import struct
from fractions import Fraction as F
from pathlib import Path

import numpy as np

from qualification.hcsn_currentstate_n128_firststep.oracle_step import (
    DISCOUNT,
    _integrated,
    _source,
    _spatial,
)


START_SHA256 = "833474bcdaf45c7787a2869fa86efbad2f8b22fdb0c88d0fbcbef1764f8a72a9"
QUERIES = (F(201, 1000), F(7, 25), F(9, 25))


class Cursor:
    def __init__(self, raw):
        self.raw = raw
        self.offset = 0

    def take(self, size):
        value = self.raw[self.offset : self.offset + size]
        if len(value) != size:
            raise ValueError("truncated #6282 container")
        self.offset += size
        return value

    def unpack(self, fmt):
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))

    def fraction(self):
        return F(*self.unpack("<qQ"))

    def finish(self):
        if self.offset != len(self.raw):
            raise ValueError("trailing #6282 container bytes")


def _decode_start(path):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != START_SHA256:
        raise ValueError("#6282 terminal capsule hash")
    if raw[:8] != b"HCSNN128" or hashlib.sha256(raw[:-32]).digest() != raw[-32:]:
        raise ValueError("#6282 container identity")
    if struct.unpack("<HHHH", raw[8:16]) != (1, 0x4C45, 5, 236):
        raise ValueError("#6282 container header")
    cursor = Cursor(raw[16:-32])
    directory = []
    for kind in (1, 2, 3, 4, 5):
        actual, flags, size = cursor.unpack("<HHQ")
        section_hash = cursor.take(32)
        if (actual, flags) != (kind, 0):
            raise ValueError("#6282 section order")
        directory.append((size, section_hash))
    sections = []
    for size, expected in directory:
        section = cursor.take(size)
        if hashlib.sha256(section).digest() != expected:
            raise ValueError("#6282 section hash")
        sections.append(section)
    cursor.finish()

    metadata = Cursor(sections[0])
    roster_identity = metadata.take(32).hex()
    capsule_identity = metadata.take(32).hex()
    lane, nodes = metadata.unpack("<BI")
    time = metadata.fraction()
    count = metadata.unpack("<I")[0]
    input_hashes = {}
    for _ in range(count):
        size = metadata.unpack("<H")[0]
        name = metadata.take(size).decode()
        input_hashes[name] = metadata.take(32).hex()
    metadata.finish()
    if lane != 0 or nodes != 127 or time != F(1, 5):
        raise ValueError("#6282 terminal coordinates")

    state_section = Cursor(sections[1])
    count = state_section.unpack("<Q")[0]
    state = np.asarray(state_section.unpack(f"<{count}d"))
    state_section.finish()

    operator_section = Cursor(sections[3])
    count = operator_section.unpack("<I")[0]
    operators = {}
    for _ in range(count):
        identity = operator_section.take(32).hex()
        dimension, nnz = operator_section.unpack("<IQ")
        indptr = operator_section.unpack(f"<{dimension + 1}Q")
        indices = operator_section.unpack(f"<{nnz}I")
        values = operator_section.unpack(f"<{nnz}d")
        matrix = np.zeros((dimension, dimension))
        for row in range(dimension):
            for index in range(indptr[row], indptr[row + 1]):
                matrix[row, indices[index]] = values[index]
        operators[identity] = matrix
    operator_section.finish()

    packet_section = Cursor(sections[2])
    packets = []
    for _ in range(packet_section.unpack("<I")[0]):
        source = packet_section.take(32).hex()
        generation, target, origin = packet_section.unpack("<III")
        start, end = packet_section.fraction(), packet_section.fraction()
        operator = operators[packet_section.take(32).hex()]
        dimension = len(operator)
        alpha = np.asarray(packet_section.unpack(f"<{5 * dimension}d")).reshape(
            5, dimension
        )
        output = np.asarray(packet_section.unpack(f"<{dimension}d"))
        packets.append(
            {
                "source": source,
                "generation": generation,
                "target": target,
                "origin": origin,
                "start": start,
                "end": end,
                "generator": operator,
                "alpha": alpha,
                "output": output,
            }
        )
    packet_section.finish()
    return {
        "roster_identity": roster_identity,
        "capsule_identity": capsule_identity,
        "input_hashes": input_hashes,
        "state": state,
        "packets": packets,
        "time": time,
    }


def _split_state(values):
    offset = 0
    active = values[offset : offset + 1270].reshape(5, 2, 127).copy()
    offset += 1270
    upper = values[offset : offset + 15].reshape(5, 3).copy()
    offset += 15
    mass = values[offset : offset + 10].reshape(5, 2).copy()
    offset += 10
    hit = values[offset : offset + 10].reshape(5, 2).copy()
    offset += 10
    occupation = values[offset : offset + 15].reshape(5, 3).copy()
    if offset + 15 != len(values):
        raise ValueError("complete state layout")
    return active, upper, mass, hit, occupation


def _block(parents, spatial, lower, reset):
    dimension = 127 + sum(len(packet["generator"]) for packet in parents)
    matrix = np.zeros((dimension, dimension))
    offset = 0
    for packet in parents:
        parent = packet["generator"]
        width = len(parent)
        matrix[offset : offset + width, offset : offset + width] = parent
        matrix[offset : offset + width, -127:] += np.outer(
            packet["output"], reset
        )
        offset += width
    matrix[offset:, offset:] = spatial
    return matrix, np.r_[np.zeros(offset), lower]


def run(start_path, law_path, metadata_path, npz_path):
    start = _decode_start(start_path)
    paths = {
        "law": Path(law_path),
        "json": Path(metadata_path),
        "npz": Path(npz_path),
    }
    hashes = {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in paths.items()
    }
    if hashes != start["input_hashes"]:
        raise ValueError("#6282 input identities")
    metadata = json.loads(paths["json"].read_text())
    with np.load(paths["npz"], allow_pickle=False) as stored:
        nodes = stored["nodes"].copy()
    spatial, lower, upper_flow, reset = _spatial(metadata, nodes)
    bundle = hashlib.sha256(
        json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    active, upper, mass, hit, occupation = _split_state(start["state"])
    pending = list(start["packets"])
    time = start["time"]
    capsules = []
    segments = 0
    exponentials = 0
    for query in QUERIES:
        while time < query:
            boundaries = [query, time + F(1, 5)]
            for packet in pending:
                boundaries.extend((packet["start"], packet["end"]))
            right = min(value for value in boundaries if value > time)
            releasing = [packet for packet in pending if packet["start"] == time]
            if len(releasing) != 1 or releasing[0]["target"] not in (1, 2):
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
                    [packet["alpha"] for packet in parents]
                    + [active[:, origin - 1]],
                    axis=1,
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
                _, discounted = _integrated(
                    extended, selectors, right - time, DISCOUNT
                )
                active[:, origin - 1] = final[:, spatial_offset:dimension]
                upper[:, origin] = final[:, -1]
                mass[:, origin - 1] += (initial @ lower_integral)[:, 0]
                hit[:, origin - 1] += global_discount * (initial @ discounted)[:, 0]
                occupation[:, origin] += global_discount * (initial @ discounted)[:, 1]
                parent_offset = 0
                for packet in parents:
                    width = len(packet["generator"])
                    updates[packet["source"]] = final[
                        :, parent_offset : parent_offset + width
                    ].copy()
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
                        retained.append(
                            dict(
                                packet,
                                start=right,
                                alpha=updates[packet["source"]],
                            )
                        )
                elif packet["start"] == time:
                    raise ValueError("unhandled releasing packet")
                else:
                    retained.append(packet)
            pending = retained + emissions
            time = right
            segments += 1
        state = np.concatenate(
            (active.ravel(), upper.ravel(), mass.ravel(), hit.ravel(), occupation.ravel())
        )
        capsules.append({"state": state.copy(), "packets": tuple(pending)})
    return tuple(capsules), {
        "oracle_dynamic_segments": segments,
        "oracle_matrix_exponentials": exponentials,
        "oracle_capsules": len(capsules),
    }
