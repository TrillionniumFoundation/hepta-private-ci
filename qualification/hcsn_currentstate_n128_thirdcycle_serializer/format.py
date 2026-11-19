"""Canonical serializer for the bounded three-generation N128 state."""

import hashlib
import struct
from dataclasses import dataclass
from fractions import Fraction as F

from qualification.hcsn_currentstate_n128_engineering import candidate


MAGIC = b"HCSN3C01"
VERSION = 1
SECTION_IDS = (1, 2, 3, 4, 5)
CHANNELS = 5


@dataclass(frozen=True)
class ThirdCycleCapsule:
    roster_identity: str
    input_hashes: tuple
    capsule_identity: str
    lane: int
    time: F
    interior_nodes: int
    readouts: tuple
    state: tuple
    packets: tuple

    def __post_init__(self):
        candidate.checked_hash(self.roster_identity)
        candidate.checked_hash(self.capsule_identity)
        if tuple(sorted(self.input_hashes)) != self.input_hashes:
            raise ValueError("input hashes ordered")
        for _, value in self.input_hashes:
            candidate.checked_hash(value)
        if tuple(sorted(self.readouts, key=lambda row: (row.lane, row.lane_order))) != self.readouts:
            raise ValueError("readout schedule ordered")
        state = tuple(candidate.checked_float(value) for value in self.state)
        if len(state) != 15 * self.interior_nodes + 70:
            raise ValueError("three-generation complete state coordinate count")
        object.__setattr__(self, "state", state)


def _fraction(value):
    return struct.pack("<qQ", value.numerator, value.denominator)


def dump(capsule):
    metadata = candidate.checked_hash(capsule.roster_identity)
    metadata += candidate.checked_hash(capsule.capsule_identity)
    metadata += struct.pack("<BI", capsule.lane, capsule.interior_nodes)
    metadata += _fraction(capsule.time)
    metadata += struct.pack("<I", len(capsule.input_hashes))
    for name, value in capsule.input_hashes:
        raw = name.encode()
        metadata += struct.pack("<H", len(raw)) + raw + candidate.checked_hash(value)
    state = struct.pack("<Q", len(capsule.state))
    state += struct.pack(f"<{len(capsule.state)}d", *capsule.state)
    packets = struct.pack("<I", len(capsule.packets))
    operators = {}
    for packet in capsule.packets:
        operators[packet.operator.identity] = packet.operator
        packets += candidate.checked_hash(packet.source)
        packets += struct.pack("<III", packet.generation, packet.target, packet.origin)
        packets += _fraction(packet.start) + _fraction(packet.end)
        packets += candidate.checked_hash(packet.operator.identity)
        packets += struct.pack(f"<{len(packet.alpha)}d", *packet.alpha)
        packets += struct.pack(f"<{len(packet.output)}d", *packet.output)
    operator_section = struct.pack("<I", len(operators))
    for identity, operator in sorted(operators.items()):
        operator_section += candidate.checked_hash(identity)
        operator_section += struct.pack("<IQ", operator.dimension, len(operator.data))
        operator_section += struct.pack(f"<{len(operator.indptr)}Q", *operator.indptr)
        operator_section += struct.pack(f"<{len(operator.indices)}I", *operator.indices)
        operator_section += struct.pack(f"<{len(operator.data)}d", *operator.data)
    readouts = struct.pack("<I", len(capsule.readouts))
    for readout in capsule.readouts:
        readouts += struct.pack("<BI", readout.lane, readout.lane_order)
        readouts += _fraction(readout.time)
        readouts += candidate.checked_hash(readout.capsule_identity)
    sections = (metadata, state, packets, operator_section, readouts)
    header = MAGIC + struct.pack("<HHHH", VERSION, 0x4C45, len(sections), 16 + 44 * len(sections))
    directory = b"".join(
        struct.pack("<HHQ", kind, 0, len(raw)) + hashlib.sha256(raw).digest()
        for kind, raw in zip(SECTION_IDS, sections)
    )
    body = header + directory + b"".join(sections)
    return body + hashlib.sha256(body).digest()


def load(raw):
    if raw[:8] != MAGIC or hashlib.sha256(raw[:-32]).digest() != raw[-32:]:
        raise ValueError("three-generation container identity")
    if struct.unpack("<HHHH", raw[8:16]) != (VERSION, 0x4C45, 5, 236):
        raise ValueError("three-generation container header")
    cursor = candidate.Cursor(raw[16:-32])
    directory = []
    for expected in SECTION_IDS:
        kind, flags, size = cursor.unpack("<HHQ")
        section_hash = cursor.take(32)
        if (kind, flags) != (expected, 0):
            raise ValueError("section order")
        directory.append((size, section_hash))
    sections = []
    for size, expected in directory:
        section = cursor.take(size)
        if hashlib.sha256(section).digest() != expected:
            raise ValueError("section hash")
        sections.append(section)
    cursor.finish()
    meta = candidate.Cursor(sections[0])
    roster = meta.take(32).hex()
    capsule_id = meta.take(32).hex()
    lane, nodes = meta.unpack("<BI")
    time = meta.fraction()
    inputs = []
    for _ in range(meta.unpack("<I")[0]):
        size = meta.unpack("<H")[0]
        inputs.append((meta.take(size).decode(), meta.take(32).hex()))
    meta.finish()
    state_cursor = candidate.Cursor(sections[1])
    count = state_cursor.unpack("<Q")[0]
    state = state_cursor.unpack(f"<{count}d")
    state_cursor.finish()
    operator_cursor = candidate.Cursor(sections[3])
    operators = {}
    for _ in range(operator_cursor.unpack("<I")[0]):
        identity = operator_cursor.take(32).hex()
        dimension, nnz = operator_cursor.unpack("<IQ")
        operator = candidate.CSR(
            dimension,
            operator_cursor.unpack(f"<{dimension + 1}Q"),
            operator_cursor.unpack(f"<{nnz}I"),
            operator_cursor.unpack(f"<{nnz}d"),
        )
        if operator.identity != identity:
            raise ValueError("operator identity")
        operators[identity] = operator
    operator_cursor.finish()
    packet_cursor = candidate.Cursor(sections[2])
    packets = []
    for _ in range(packet_cursor.unpack("<I")[0]):
        source = packet_cursor.take(32).hex()
        generation, target, origin = packet_cursor.unpack("<III")
        start, end = packet_cursor.fraction(), packet_cursor.fraction()
        operator = operators[packet_cursor.take(32).hex()]
        alpha = packet_cursor.unpack(f"<{CHANNELS * operator.dimension}d")
        output = packet_cursor.unpack(f"<{operator.dimension}d")
        packets.append(candidate.NumericPacket(source, generation, target, origin, start, end, operator, alpha, output))
    packet_cursor.finish()
    readout_cursor = candidate.Cursor(sections[4])
    readouts = []
    for _ in range(readout_cursor.unpack("<I")[0]):
        lane, lane_order = readout_cursor.unpack("<BI")
        readouts.append(candidate.Readout(lane, lane_order, readout_cursor.fraction(), readout_cursor.take(32).hex()))
    readout_cursor.finish()
    capsule = ThirdCycleCapsule(roster, tuple(inputs), capsule_id, lane, time, nodes, tuple(readouts), state, tuple(packets))
    if dump(capsule) != raw:
        raise ValueError("noncanonical three-generation container")
    return capsule


def coordinates(capsule):
    yield from capsule.state
    for packet in capsule.packets:
        yield from packet.alpha
        operator = packet.operator
        for row in range(operator.dimension):
            start, end = operator.indptr[row], operator.indptr[row + 1]
            cursor = start
            for column in range(operator.dimension):
                if cursor < end and operator.indices[cursor] == column:
                    yield operator.data[cursor]
                    cursor += 1
                else:
                    yield 0.0
            if cursor != end:
                raise ArithmeticError("CSR row stream")
        yield from packet.output
