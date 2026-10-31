"""Matched packed delta, absolute-count and FP64 conditional-law transport."""

import math
import struct
import zlib

from .runtime_law import Q24, make_law, positive_q24, validate_law


MODES = ("event", "direct", "float")
KINDS = ("observed", "missing", "propagation")
HEADER = struct.Struct("<4sBBBBId")
MAGIC = b"HE4P"
MAX_COUNT = 1 << 48


def _integer(value):
    if type(value) is not int or abs(value) >= MAX_COUNT:
        raise ValueError("Signed count outside protocol domain")
    number = 2 * value if value >= 0 else -2 * value - 1
    result = bytearray()
    while number >= 128:
        result.append((number & 127) | 128)
        number >>= 7
    result.append(number)
    return bytes(result)


def _integers(payload, count):
    values, index = [], 0
    for _ in range(count):
        start, value, shift = index, 0, 0
        while True:
            if index >= len(payload) or shift > 49:
                raise ValueError("Truncated or oversized packed integer")
            byte = payload[index]
            index += 1
            value |= (byte & 127) << shift
            if byte < 128:
                break
            shift += 7
        decoded = value // 2 if value % 2 == 0 else -(value // 2) - 1
        if _integer(decoded) != payload[start:index]:
            raise ValueError("Noncanonical packed integer")
        values.append(decoded)
    if index != len(payload):
        raise ValueError("Trailing packet payload")
    return values


def levels(law):
    weights, means, variances = validate_law(law)
    counts = positive_q24(weights)
    values = counts[:-1] + [math.floor(float(x) * 4096 + .5) for x in means]
    values += [math.floor(math.log(float(x)) * 4096 + .5) for x in variances]
    return values


def _law(values, components, mode):
    n = components - 1
    weights = values[:n]
    means, logs = values[n:n + components], values[n + components:]
    if mode != "float":
        weights = [v / Q24 for v in weights]
        means, logs = [[v / 4096 for v in group] for group in (means, logs)]
    weights = [*weights, 1.0 - sum(weights)]
    law = make_law(weights, means, [math.exp(v) for v in logs])
    if any(abs(v) > 8 for v in law["means"]) or any(not 2**-24 <= v <= 8 for v in law["variances"]):
        raise ValueError("Decoded law outside shared native domain")
    return law


class Decoder:
    def __init__(self, mode):
        if mode not in MODES:
            raise ValueError("Unknown transport mode")
        self.mode, self.sequence, self.time = mode, 0, None
        self.components, self.values = None, None

    def apply(self, packet):
        if not isinstance(packet, bytes) or len(packet) < HEADER.size + 4:
            raise ValueError("Truncated conditional-law frame")
        body, check = packet[:-4], packet[-4:]
        if struct.pack("<I", zlib.crc32(body)) != check:
            raise ValueError("Frame CRC mismatch")
        magic, version, mode, kind, components, sequence, timestamp = HEADER.unpack(body[:HEADER.size])
        if (magic != MAGIC or version != 1 or mode != MODES.index(self.mode) or kind >= len(KINDS)
                or components not in (1, 2) or (self.components is not None and components != self.components)
                or sequence != self.sequence + 1 or sequence > 16 or not math.isfinite(timestamp)
                or timestamp < 0 or (self.time is not None and timestamp < self.time)
                or (KINDS[kind] == "propagation" and timestamp != self.time)):
            raise ValueError("Frame schema, sequence, time or profile mismatch")
        count, payload = 3 * components - 1, body[HEADER.size:]
        if self.mode == "float":
            if len(payload) != 8 * count:
                raise ValueError("FP64 frame length mismatch")
            values = list(struct.unpack("<" + "d" * count, payload))
            if not all(math.isfinite(x) for x in values):
                raise ValueError("Nonfinite FP64 state")
        else:
            values = _integers(payload, count)
            if self.mode == "event":
                base = self.values or [0] * count
                values = [old + change for old, change in zip(base, values)]
            if any(abs(x) >= MAX_COUNT for x in values):
                raise ValueError("Accumulated count outside protocol domain")
        law = _law(values, components, self.mode)
        self.sequence, self.time = sequence, timestamp
        self.components, self.values = components, values
        return law

    def snapshot(self):
        return {"schema": "hepta.packed-law.decoder.v4", "mode": self.mode, "sequence": self.sequence,
                "time": self.time, "components": self.components, "values": self.values}

    @classmethod
    def restore(cls, state):
        if set(state) != {"schema", "mode", "sequence", "time", "components", "values"} or state["schema"] != "hepta.packed-law.decoder.v4":
            raise ValueError("Unknown decoder state")
        decoder = cls(state["mode"])
        if state["sequence"] == 0:
            if state != decoder.snapshot():
                raise ValueError("Invalid initial decoder state")
            return decoder
        if (type(state["sequence"]) is not int or not 1 <= state["sequence"] <= 16
                or state["components"] not in (1, 2) or not isinstance(state["values"], list)
                or len(state["values"]) != 3 * state["components"] - 1
                or type(state["time"]) not in (int, float) or not math.isfinite(state["time"]) or state["time"] < 0
                or (state["mode"] != "float" and any(type(v) is not int or abs(v) >= MAX_COUNT for v in state["values"]))):
            raise ValueError("Invalid restored decoder domain")
        _law(state["values"], state["components"], state["mode"])
        decoder.sequence, decoder.time = state["sequence"], state["time"]
        decoder.components, decoder.values = state["components"], list(state["values"])
        return decoder


class Encoder:
    """Difference coding of a fixed absolute quantizer; no new function class."""
    def __init__(self, mode, state=None):
        self.decoder = Decoder(mode) if state is None else Decoder.restore(state)
        if self.decoder.mode != mode:
            raise ValueError("Encoder mode mismatch")

    def encode(self, law, sequence, timestamp, kind="observed"):
        w, m, v = validate_law(law)
        mode, components = self.decoder.mode, len(w)
        if kind not in KINDS:
            raise ValueError("Unknown observation kind")
        if mode == "float":
            values = [*w[:-1], *m, *map(math.log, v)]
            payload = struct.pack("<" + "d" * len(values), *values)
        else:
            values = levels(law)
            if mode == "event":
                base = self.decoder.values or [0] * len(values)
                values = [new - old for new, old in zip(values, base)]
            payload = b"".join(_integer(x) for x in values)
        body = HEADER.pack(MAGIC, 1, MODES.index(mode), KINDS.index(kind), components, sequence, timestamp) + payload
        packet = body + struct.pack("<I", zlib.crc32(body))
        self.decoder.apply(packet)
        return packet
