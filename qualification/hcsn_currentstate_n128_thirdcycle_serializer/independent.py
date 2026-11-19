"""Independent decoder for the bounded three-generation capsule bytes."""

import hashlib
import struct
from fractions import Fraction as F


class Cursor:
    def __init__(self, raw):
        self.raw = raw
        self.offset = 0

    def take(self, size):
        value = self.raw[self.offset : self.offset + size]
        if len(value) != size:
            raise ValueError("truncated independent container")
        self.offset += size
        return value

    def unpack(self, shape):
        return struct.unpack(shape, self.take(struct.calcsize(shape)))

    def fraction(self):
        return F(*self.unpack("<qQ"))

    def finish(self):
        if self.offset != len(self.raw):
            raise ValueError("trailing independent bytes")


def decode(raw):
    if raw[:8] != b"HCSN3C01" or hashlib.sha256(raw[:-32]).digest() != raw[-32:]:
        raise ValueError("independent container identity")
    if struct.unpack("<HHHH", raw[8:16]) != (1, 0x4C45, 5, 236):
        raise ValueError("independent container header")
    cursor = Cursor(raw[16:-32])
    directory = []
    for expected in (1, 2, 3, 4, 5):
        kind, flags, size = cursor.unpack("<HHQ")
        section_hash = cursor.take(32)
        if (kind, flags) != (expected, 0):
            raise ValueError("independent section order")
        directory.append((size, section_hash))
    sections = []
    for size, expected in directory:
        section = cursor.take(size)
        if hashlib.sha256(section).digest() != expected:
            raise ValueError("independent section hash")
        sections.append(section)
    cursor.finish()
    metadata = Cursor(sections[0])
    roster_identity = metadata.take(32).hex()
    capsule_identity = metadata.take(32).hex()
    lane, nodes = metadata.unpack("<BI")
    time = metadata.fraction()
    inputs = []
    for _ in range(metadata.unpack("<I")[0]):
        size = metadata.unpack("<H")[0]
        inputs.append((metadata.take(size).decode(), metadata.take(32).hex()))
    metadata.finish()
    state_cursor = Cursor(sections[1])
    state_count = state_cursor.unpack("<Q")[0]
    state = state_cursor.unpack(f"<{state_count}d")
    state_cursor.finish()
    operator_cursor = Cursor(sections[3])
    operators = {}
    for _ in range(operator_cursor.unpack("<I")[0]):
        identity = operator_cursor.take(32).hex()
        dimension, nnz = operator_cursor.unpack("<IQ")
        indptr = operator_cursor.unpack(f"<{dimension + 1}Q")
        indices = operator_cursor.unpack(f"<{nnz}I")
        data = operator_cursor.unpack(f"<{nnz}d")
        body = struct.pack("<IQ", dimension, nnz)
        body += struct.pack(f"<{dimension + 1}Q", *indptr)
        body += struct.pack(f"<{nnz}I", *indices)
        body += struct.pack(f"<{nnz}d", *data)
        if hashlib.sha256(body).hexdigest() != identity:
            raise ValueError("independent operator identity")
        operators[identity] = (dimension, indptr, indices, data)
    operator_cursor.finish()
    packet_cursor = Cursor(sections[2])
    packets = []
    for _ in range(packet_cursor.unpack("<I")[0]):
        source = packet_cursor.take(32).hex()
        generation, target, origin = packet_cursor.unpack("<III")
        start, end = packet_cursor.fraction(), packet_cursor.fraction()
        operator_identity = packet_cursor.take(32).hex()
        operator = operators[operator_identity]
        dimension = operator[0]
        alpha = packet_cursor.unpack(f"<{5 * dimension}d")
        output = packet_cursor.unpack(f"<{dimension}d")
        packets.append((source, generation, target, origin, start, end, operator, alpha, output))
    packet_cursor.finish()
    readouts = Cursor(sections[4])
    readout_count = readouts.unpack("<I")[0]
    for _ in range(readout_count):
        readouts.unpack("<BI")
        readouts.fraction()
        readouts.take(32)
    readouts.finish()
    return {"roster_identity": roster_identity, "capsule_identity": capsule_identity, "lane": lane, "nodes": nodes, "time": time, "inputs": tuple(inputs), "state": state, "packets": tuple(packets), "readouts": readout_count}


def coordinates(decoded):
    yield from decoded["state"]
    for packet in decoded["packets"]:
        operator, alpha, output = packet[6], packet[7], packet[8]
        dimension, indptr, indices, data = operator
        yield from alpha
        for row in range(dimension):
            start, end = indptr[row], indptr[row + 1]
            cursor = start
            for column in range(dimension):
                if cursor < end and indices[cursor] == column:
                    yield data[cursor]
                    cursor += 1
                else:
                    yield 0.0
            if cursor != end:
                raise ArithmeticError("independent CSR row stream")
        yield from output
