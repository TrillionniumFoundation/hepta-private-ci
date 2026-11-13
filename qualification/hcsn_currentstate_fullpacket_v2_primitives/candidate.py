"""Lossless packet roster and canonical container for bounded fixtures only.

This module never reads the N128 inputs and contains no dynamic or exponential
code.  It freezes wire invariants that a future N128 implementation must meet.
"""

import hashlib
import itertools
import json
import math
import struct
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

MAGIC = b"HCSNFPV2"
VERSION = 1
ENDIAN = 0x4C45
SECTION_IDS = (1, 2, 3, 4, 5)
CHANNELS = 5
ACTIVE = 1
UPPER = 2
NONRETURNING_UPPER = 1


def _digest(value):
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError("SHA-256 hex required")
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError("SHA-256 hex required") from exc
    if len(raw) != 32:
        raise ValueError("SHA-256 hex required")
    return raw


def _fraction(value):
    if not isinstance(value, Fraction) or value.denominator <= 0:
        raise TypeError("canonical Fraction required")
    if not -(1 << 63) <= value.numerator < (1 << 63):
        raise ValueError("fraction numerator outside int64")
    if not 1 <= value.denominator < (1 << 64):
        raise ValueError("fraction denominator outside uint64")
    return value


def _float(value):
    value = float(value)
    if not math.isfinite(value) or struct.pack("<d", value) == struct.pack(
        "<Q", 1 << 63
    ):
        raise ValueError("finite canonical binary64 required")
    return value


@dataclass(frozen=True)
class StateCoordinate:
    region: int
    channel: int
    node: int
    value: float

    def __post_init__(self):
        if self.region not in (ACTIVE, UPPER):
            raise ValueError("unknown state region")
        if not 0 <= self.channel < CHANNELS or not 0 <= self.node < 1 << 32:
            raise ValueError("state coordinate index")
        if self.region == UPPER and self.node != 0:
            raise ValueError("upper coordinate node must be zero")
        object.__setattr__(self, "value", _float(self.value))

    @property
    def key(self):
        return self.region, self.channel, self.node


@dataclass(frozen=True)
class CSR:
    dimension: int
    indptr: tuple
    indices: tuple
    data: tuple

    def __post_init__(self):
        if type(self.dimension) is not int or not 1 <= self.dimension < 1 << 32:
            raise ValueError("operator dimension")
        indptr = tuple(self.indptr)
        indices = tuple(self.indices)
        data = tuple(_float(value) for value in self.data)
        if (
            len(indptr) != self.dimension + 1
            or indptr[0] != 0
            or any(type(value) is not int or value < 0 for value in indptr)
            or any(right < left for left, right in itertools.pairwise(indptr))
            or indptr[-1] != len(indices)
            or len(indices) != len(data)
            or any(value == 0.0 for value in data)
        ):
            raise ValueError("invalid CSR structure")
        for row in range(self.dimension):
            begin, end = indptr[row : row + 2]
            columns = indices[begin:end]
            if any(
                type(col) is not int or not 0 <= col < self.dimension for col in columns
            ):
                raise ValueError("CSR column")
            if tuple(sorted(set(columns))) != columns or any(
                data[index] == 0 for index in range(begin, end)
            ):
                raise ValueError("CSR rows must be sorted, unique and nonzero")
        object.__setattr__(self, "indptr", indptr)
        object.__setattr__(self, "indices", indices)
        object.__setattr__(self, "data", data)

    @property
    def identity(self):
        value = struct.pack("<IQ", self.dimension, len(self.data))
        value += struct.pack(f"<{len(self.indptr)}Q", *self.indptr)
        value += struct.pack(f"<{len(self.indices)}I", *self.indices)
        value += struct.pack(f"<{len(self.data)}d", *self.data)
        return hashlib.sha256(value).hexdigest()

    def dense(self):
        result = [[0.0] * self.dimension for _ in range(self.dimension)]
        for row in range(self.dimension):
            for index in range(self.indptr[row], self.indptr[row + 1]):
                result[row][self.indices[index]] = self.data[index]
        return tuple(tuple(row) for row in result)


@dataclass(frozen=True)
class PacketRecord:
    generation: int
    target: int
    origin: int
    channel: int
    start: Fraction
    end: Fraction
    coefficient: float
    source_id: str
    operator_id: str

    def __post_init__(self):
        if any(
            type(value) is not int or not 0 <= value < 1 << 32
            for value in (self.generation, self.target, self.origin)
        ):
            raise ValueError("packet index")
        if type(self.channel) is not int or not 0 <= self.channel < CHANNELS:
            raise ValueError("packet channel")
        _fraction(self.start)
        _fraction(self.end)
        if self.end < self.start:
            raise ValueError("packet support")
        object.__setattr__(self, "coefficient", _float(self.coefficient))
        _digest(self.source_id)
        _digest(self.operator_id)

    @property
    def key(self):
        return (
            self.generation,
            self.target,
            self.origin,
            self.start,
            self.end,
            self.source_id,
            self.operator_id,
            self.channel,
        )

    @property
    def logical_key(self):
        return self.key[:-1]


@dataclass(frozen=True)
class Capsule:
    bindings: tuple
    interior_nodes: int
    reset: Fraction
    time: Fraction
    schedule: tuple
    upper_mode: int
    state: tuple
    packets: tuple
    operators: tuple

    def __post_init__(self):
        if (
            type(self.interior_nodes) is not int
            or not 1 <= self.interior_nodes < 1 << 32
        ):
            raise ValueError("interior node count")
        _fraction(self.reset)
        _fraction(self.time)
        schedule = tuple(self.schedule)
        if (
            any(_fraction(value) is not value for value in schedule)
            or tuple(sorted(set(schedule))) != schedule
        ):
            raise ValueError("schedule must be sorted and unique")
        if self.upper_mode != NONRETURNING_UPPER:
            raise ValueError("upper must be permanently active and nonreturning")
        bindings = tuple(self.bindings)
        if tuple(sorted(set(bindings))) != bindings:
            raise ValueError("bindings must be sorted and unique")
        for kind, name, digest in bindings:
            if kind not in ("input", "source") or not isinstance(name, str) or not name:
                raise ValueError("binding record")
            _digest(digest)
        state = tuple(self.state)
        packets = tuple(self.packets)
        operators = tuple(self.operators)
        if tuple(sorted(state, key=lambda value: value.key)) != state or len(
            {value.key for value in state}
        ) != len(state):
            raise ValueError("state roster must be sorted and unique")
        expected_state = {
            (ACTIVE, channel, node)
            for channel in range(CHANNELS)
            for node in range(self.interior_nodes)
        }
        expected_state |= {(UPPER, channel, 0) for channel in range(CHANNELS)}
        if {value.key for value in state} != expected_state:
            raise ValueError("lossless active/upper state roster required")
        if tuple(sorted(packets, key=lambda value: value.key)) != packets or len(
            {value.key for value in packets}
        ) != len(packets):
            raise ValueError("packet roster must be sorted and unique")
        binding_ids = {digest for _, _, digest in bindings}
        if any(packet.source_id not in binding_ids for packet in packets):
            raise ValueError("packet source identity")
        groups = {}
        for packet in packets:
            groups.setdefault(packet.logical_key, set()).add(packet.channel)
        if not groups or any(
            channels != set(range(CHANNELS)) for channels in groups.values()
        ):
            raise ValueError(
                "all probability and signed-content packet channels required"
            )
        operator_ids = tuple(operator.identity for operator in operators)
        if tuple(sorted(set(operator_ids))) != operator_ids:
            raise ValueError("operator roster must be sorted and unique")
        if any(packet.operator_id not in operator_ids for packet in packets):
            raise ValueError("packet operator identity")
        object.__setattr__(self, "schedule", schedule)
        object.__setattr__(self, "bindings", bindings)
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "packets", packets)
        object.__setattr__(self, "operators", operators)


def _pack_string(value):
    raw = value.encode("utf-8")
    if len(raw) >= 1 << 16:
        raise ValueError("string too long")
    return struct.pack("<H", len(raw)) + raw


def _pack_fraction(value):
    value = _fraction(value)
    return struct.pack("<qQ", value.numerator, value.denominator)


def _sections(capsule):
    bindings = struct.pack("<I", len(capsule.bindings))
    for kind, name, digest in capsule.bindings:
        bindings += (
            bytes([1 if kind == "source" else 2]) + _pack_string(name) + _digest(digest)
        )
    geometry = struct.pack("<HIB", CHANNELS, capsule.interior_nodes, capsule.upper_mode)
    geometry += _pack_fraction(capsule.reset) + _pack_fraction(capsule.time)
    geometry += struct.pack("<I", len(capsule.schedule)) + b"".join(
        _pack_fraction(value) for value in capsule.schedule
    )
    state = struct.pack("<I", len(capsule.state))
    state += b"".join(
        struct.pack("<BBId", value.region, value.channel, value.node, value.value)
        for value in capsule.state
    )
    packets = struct.pack("<I", len(capsule.packets))
    for packet in capsule.packets:
        packets += struct.pack(
            "<IIIH2x", packet.generation, packet.target, packet.origin, packet.channel
        )
        packets += _pack_fraction(packet.start) + _pack_fraction(packet.end)
        packets += (
            struct.pack("<d", packet.coefficient)
            + _digest(packet.source_id)
            + _digest(packet.operator_id)
        )
    operators = struct.pack("<I", len(capsule.operators))
    for operator in capsule.operators:
        operators += _digest(operator.identity) + struct.pack(
            "<IQ", operator.dimension, len(operator.data)
        )
        operators += struct.pack(f"<{len(operator.indptr)}Q", *operator.indptr)
        operators += struct.pack(f"<{len(operator.indices)}I", *operator.indices)
        operators += struct.pack(f"<{len(operator.data)}d", *operator.data)
    return bindings, geometry, state, packets, operators


def dump(capsule):
    sections = _sections(capsule)
    header_length = 16 + 44 * len(sections)
    header = MAGIC + struct.pack("<HHHH", VERSION, ENDIAN, len(sections), header_length)
    directory = b"".join(
        struct.pack("<HHQ", section_id, 0, len(payload))
        + hashlib.sha256(payload).digest()
        for section_id, payload in zip(SECTION_IDS, sections)
    )
    body = header + directory + b"".join(sections)
    return body + hashlib.sha256(body).digest()


class _Cursor:
    def __init__(self, raw):
        self.raw = raw
        self.offset = 0

    def take(self, size):
        if size < 0 or self.offset + size > len(self.raw):
            raise ValueError("truncated canonical container")
        value = self.raw[self.offset : self.offset + size]
        self.offset += size
        return value

    def unpack(self, fmt):
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))

    def string(self):
        (size,) = self.unpack("<H")
        return self.take(size).decode("utf-8")

    def fraction(self):
        numerator, denominator = self.unpack("<qQ")
        return _fraction(Fraction(numerator, denominator))

    def finish(self):
        if self.offset != len(self.raw):
            raise ValueError("trailing canonical bytes")


def load(raw):
    if not isinstance(raw, bytes) or len(raw) < 48 or raw[:8] != MAGIC:
        raise ValueError("container magic")
    if hashlib.sha256(raw[:-32]).digest() != raw[-32:]:
        raise ValueError("whole-container digest")
    version, endian, count, header_length = struct.unpack("<HHHH", raw[8:16])
    if (version, endian, count, header_length) != (
        VERSION,
        ENDIAN,
        len(SECTION_IDS),
        16 + 44 * len(SECTION_IDS),
    ):
        raise ValueError("container header")
    cursor = _Cursor(raw[16:-32])
    directory = []
    for expected in SECTION_IDS:
        section_id, flags, size = cursor.unpack("<HHQ")
        digest = cursor.take(32)
        if section_id != expected or flags != 0:
            raise ValueError("unknown, missing or reordered section")
        directory.append((size, digest))
    payloads = []
    for size, digest in directory:
        payload = cursor.take(size)
        if hashlib.sha256(payload).digest() != digest:
            raise ValueError("section digest")
        payloads.append(payload)
    cursor.finish()
    bind = _Cursor(payloads[0])
    (count,) = bind.unpack("<I")
    bindings = []
    for _ in range(count):
        kind = bind.take(1)[0]
        if kind not in (1, 2):
            raise ValueError("binding kind")
        bindings.append(
            ("source" if kind == 1 else "input", bind.string(), bind.take(32).hex())
        )
    bind.finish()
    geom = _Cursor(payloads[1])
    channels, nodes, upper_mode = geom.unpack("<HIB")
    if channels != CHANNELS:
        raise ValueError("five channels required")
    reset, time = geom.fraction(), geom.fraction()
    (count,) = geom.unpack("<I")
    schedule = tuple(geom.fraction() for _ in range(count))
    geom.finish()
    state_cursor = _Cursor(payloads[2])
    (count,) = state_cursor.unpack("<I")
    state = tuple(StateCoordinate(*state_cursor.unpack("<BBId")) for _ in range(count))
    state_cursor.finish()
    packet_cursor = _Cursor(payloads[3])
    (count,) = packet_cursor.unpack("<I")
    packets = []
    for _ in range(count):
        generation, target, origin, channel = packet_cursor.unpack("<IIIH2x")
        start, end = packet_cursor.fraction(), packet_cursor.fraction()
        (coefficient,) = packet_cursor.unpack("<d")
        packets.append(
            PacketRecord(
                generation,
                target,
                origin,
                channel,
                start,
                end,
                coefficient,
                packet_cursor.take(32).hex(),
                packet_cursor.take(32).hex(),
            )
        )
    packet_cursor.finish()
    operator_cursor = _Cursor(payloads[4])
    (count,) = operator_cursor.unpack("<I")
    operators = []
    for _ in range(count):
        expected = operator_cursor.take(32).hex()
        dimension, nnz = operator_cursor.unpack("<IQ")
        indptr = operator_cursor.unpack(f"<{dimension + 1}Q")
        indices = operator_cursor.unpack(f"<{nnz}I")
        data = operator_cursor.unpack(f"<{nnz}d")
        operator = CSR(dimension, indptr, indices, data)
        if operator.identity != expected:
            raise ValueError("operator digest")
        operators.append(operator)
    operator_cursor.finish()
    capsule = Capsule(
        tuple(bindings),
        nodes,
        reset,
        time,
        schedule,
        upper_mode,
        state,
        tuple(packets),
        tuple(operators),
    )
    if dump(capsule) != raw:
        raise ValueError("noncanonical container")
    return capsule


def from_fixture(path):
    """Build the candidate roster from a bounded synthetic JSON fixture."""
    payload = json.loads(Path(path).read_text())
    operators_by_name = {}
    for item in payload["operators"]:
        rows = [[] for _ in range(item["dimension"])]
        for row, col, value in item["entries"]:
            rows[row].append((col, float.fromhex(value)))
        indptr = [0]
        indices = []
        data = []
        for row in rows:
            for col, value in sorted(row):
                indices.append(col)
                data.append(value)
            indptr.append(len(indices))
        operators_by_name[item["name"]] = CSR(
            item["dimension"], tuple(indptr), tuple(indices), tuple(data)
        )
    operators = tuple(
        sorted(operators_by_name.values(), key=lambda value: value.identity)
    )
    state = tuple(
        sorted(
            (
                StateCoordinate(item[0], item[1], item[2], float.fromhex(item[3]))
                for item in payload["state"]
            ),
            key=lambda value: value.key,
        )
    )
    packets = []
    for item in payload["packets"]:
        packets.append(
            PacketRecord(
                item["generation"],
                item["target"],
                item["origin"],
                item["channel"],
                Fraction(*item["start"]),
                Fraction(*item["end"]),
                float.fromhex(item["coefficient"]),
                item["source_id"],
                operators_by_name[item["operator"]].identity,
            )
        )
    return Capsule(
        tuple(tuple(item) for item in payload["bindings"]),
        payload["interior_nodes"],
        Fraction(*payload["reset"]),
        Fraction(*payload["time"]),
        tuple(Fraction(*item) for item in payload["schedule"]),
        payload["upper_mode"],
        state,
        tuple(sorted(packets, key=lambda value: value.key)),
        operators,
    )
