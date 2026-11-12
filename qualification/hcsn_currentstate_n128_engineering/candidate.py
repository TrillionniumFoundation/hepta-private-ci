"""Hash-bound N128 DAG/CSR materializer and canonical cold container.

The materializer consumes the authentic #6263 roster. It performs no matrix
exponential and cannot manufacture packet alpha values. The serializer is
exercised only with bounded fixtures in this stage.
"""

import ast
import hashlib
import json
import math
import struct
import zipfile
from dataclasses import dataclass, replace
from fractions import Fraction as F
from pathlib import Path


EXPECTED_INPUTS = {
    "law": "7a4b7485bf224b5e343f2c17fccf4ea7ca2dfdd06121810d16c503134f9e92fb",
    "json": "8f4f77b8ba2bc1d1e3012f64ce9614711d178503601878e091b3db8e7eadaf09",
    "npz": "fda047c1a8fce3cc042246b5249859cd0a0ba449647460ba9e0a39592386ff7d",
}
ROSTER_IDENTITY = "1f874854559eea2d1eb6ac846428d5b2e3ffebabd569db4f066929e3564d6a3b"
WARM = tuple(
    F(value) for value in ("0", ".001", ".02", ".16", ".2", ".201", ".28", ".36")
)
COARSE = (F(0), F(1, 5), F(9, 25))
COLD = (F(201, 1000), F(7, 25), F(9, 25))
CHANNELS = 5
MAGIC = b"HCSNN128"
VERSION = 1
SECTION_IDS = (1, 2, 3, 4, 5)


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def checked_float(value):
    value = float(value)
    if not math.isfinite(value) or struct.pack("<d", value) == struct.pack(
        "<Q", 1 << 63
    ):
        raise ValueError("finite nonnegative-zero binary64 required")
    return value


def checked_hash(value):
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError("SHA-256 required")
    raw = bytes.fromhex(value)
    if len(raw) != 32:
        raise ValueError("SHA-256 required")
    return raw


def read_npy(raw):
    if raw[:6] != b"\x93NUMPY":
        raise ValueError("NPY magic")
    major = raw[6]
    if major == 1:
        size, offset = struct.unpack("<H", raw[8:10])[0], 10
    elif major in (2, 3):
        size, offset = struct.unpack("<I", raw[8:12])[0], 12
    else:
        raise ValueError("NPY version")
    header = ast.literal_eval(raw[offset : offset + size].decode("latin1"))
    if header["descr"] != "<f8" or header["fortran_order"] is not False:
        raise ValueError("NPY layout")
    shape = tuple(header["shape"])
    data = raw[offset + size :]
    if len(data) != 8 * math.prod(shape):
        raise ValueError("NPY size")
    values = tuple(item[0] for item in struct.iter_unpack("<d", data))
    if any(not math.isfinite(value) for value in values):
        raise ValueError("nonfinite input")
    return shape, values


@dataclass(frozen=True)
class CSR:
    dimension: int
    indptr: tuple
    indices: tuple
    data: tuple

    def __post_init__(self):
        data = tuple(checked_float(value) for value in self.data)
        if (
            type(self.dimension) is not int
            or self.dimension < 1
            or len(self.indptr) != self.dimension + 1
            or self.indptr[0] != 0
            or any(right < left for left, right in zip(self.indptr, self.indptr[1:]))
            or self.indptr[-1] != len(self.indices)
            or len(self.indices) != len(data)
        ):
            raise ValueError("CSR shape")
        for row in range(self.dimension):
            columns = self.indices[self.indptr[row] : self.indptr[row + 1]]
            if tuple(sorted(set(columns))) != columns or any(
                not 0 <= col < self.dimension for col in columns
            ):
                raise ValueError("CSR canonical row")
        if any(value == 0 for value in data):
            raise ValueError("explicit CSR zero")
        object.__setattr__(self, "data", data)

    @classmethod
    def from_rows(cls, rows):
        indptr = [0]
        indices = []
        data = []
        for row in rows:
            for column, value in sorted(row.items()):
                value = checked_float(value)
                if value != 0:
                    indices.append(column)
                    data.append(value)
            indptr.append(len(indices))
        return cls(len(rows), tuple(indptr), tuple(indices), tuple(data))

    @property
    def identity(self):
        raw = struct.pack("<IQ", self.dimension, len(self.data))
        raw += struct.pack(f"<{len(self.indptr)}Q", *self.indptr)
        raw += struct.pack(f"<{len(self.indices)}I", *self.indices)
        raw += struct.pack(f"<{len(self.data)}d", *self.data)
        return digest(raw)


@dataclass(frozen=True)
class Template:
    source: str
    start: F
    end: F
    target: int
    origin: int
    operator: CSR
    output: tuple
    parents: tuple

    @property
    def dimension(self):
        return self.operator.dimension


def source_identity(bundle, kind, start, end, target, origin, parents):
    return digest(
        canonical(
            {
                "bundle": bundle,
                "kind": kind,
                "start": [start.numerator, start.denominator],
                "end": [end.numerator, end.denominator],
                "target": target,
                "origin": origin,
                "parents": sorted(parents),
            }
        )
    )


def load_inputs(law_path, json_path, npz_path):
    paths = {"law": Path(law_path), "json": Path(json_path), "npz": Path(npz_path)}
    hashes = {name: digest(path.read_bytes()) for name, path in paths.items()}
    if hashes != EXPECTED_INPUTS:
        raise ValueError("authentic input hash mismatch")
    law = json.loads(paths["law"].read_text())
    metadata = json.loads(paths["json"].read_text())
    with zipfile.ZipFile(paths["npz"]) as archive:
        arrays = {name: read_npy(archive.read(name)) for name in archive.namelist()}
    if set(arrays) != {"active.npy", "content.npy", "nodes.npy"}:
        raise ValueError("NPZ member set")
    if (
        arrays["active.npy"][0] != (129,)
        or arrays["content.npy"][0] != (129, 4)
        or arrays["nodes.npy"][0] != (129,)
    ):
        raise ValueError("N128 array shape")
    if metadata["intervals"] != 128 or metadata["reset_distance"] != 0.3131468965881033:
        raise ValueError("N128 metadata")
    if law["grid"]["phase_cells"] != 8 or F(str(law["grid"]["refractory"])) != F(1, 5):
        raise ValueError("selected-law geometry")
    return hashes, law, metadata, arrays


def spatial_operator(metadata, nodes):
    mu, sigma = metadata["physics"]["mu"], metadata["physics"]["sigma"]
    gaps = [right - left for left, right in zip(nodes, nodes[1:])]
    rows = [dict() for _ in range(127)]
    lower = [0.0] * 127
    upper = [0.0] * 127
    for index in range(127):
        left, right = gaps[index], gaps[index + 1]
        down = (sigma**2 - mu * right) / (left * (left + right))
        up = (sigma**2 + mu * left) / (right * (left + right))
        rows[index][index] = -(down + up)
        if index:
            rows[index][index - 1] = down
        else:
            lower[index] = down
        if index + 1 < 127:
            rows[index][index + 1] = up
        else:
            upper[index] = up
    reset_position = metadata["reset_distance"]
    right = next(index for index, value in enumerate(nodes) if value > reset_position)
    left = right - 1
    fraction = (reset_position - nodes[left]) / (nodes[right] - nodes[left])
    reset = [0.0] * 127
    for full_index, weight in ((left, 1 - fraction), (right, fraction)):
        if not 1 <= full_index <= 127:
            raise ValueError("reset is not interior")
        reset[full_index - 1] = weight
    return CSR.from_rows(rows), tuple(lower), tuple(upper), tuple(reset)


def block_operator(parents, spatial, lower, reset):
    offsets = []
    dimension = 127 + sum(parent.dimension for parent in parents)
    rows = [dict() for _ in range(dimension)]
    offset = 0
    for parent in parents:
        offsets.append(offset)
        for row in range(parent.dimension):
            for index in range(
                parent.operator.indptr[row], parent.operator.indptr[row + 1]
            ):
                rows[offset + row][offset + parent.operator.indices[index]] = (
                    parent.operator.data[index]
                )
            if parent.output[row] != 0:
                for node, weight in enumerate(reset):
                    if weight != 0:
                        rows[offset + row][dimension - 127 + node] = (
                            parent.output[row] * weight
                        )
        offset += parent.dimension
    for row in range(127):
        for index in range(spatial.indptr[row], spatial.indptr[row + 1]):
            rows[offset + row][offset + spatial.indices[index]] = spatial.data[index]
    output = (0.0,) * (dimension - 127) + lower
    return CSR.from_rows(rows), output


def roster_records(roster_dir):
    roster_dir = Path(roster_dir)
    summary = json.loads((roster_dir / "SUMMARY.json").read_text())
    if (
        summary["coordinate_identity_sha256"] != ROSTER_IDENTITY
        or summary["fp64_coordinate_denominator"] != 4_623_492
    ):
        raise ValueError("#6263 roster identity")
    packets = [
        json.loads(line)
        for line in (roster_dir / "PACKET_ROSTER.jsonl").read_text().splitlines()
    ]
    capsules = json.loads((roster_dir / "CAPSULES.json").read_text())
    events = [
        json.loads(line)
        for line in (roster_dir / "EVENTS.jsonl").read_text().splitlines()
    ]
    return summary, packets, capsules, events


def build_graph(law_path, json_path, npz_path, roster_dir):
    hashes, law, metadata, arrays = load_inputs(law_path, json_path, npz_path)
    summary, published, capsules, events = roster_records(roster_dir)
    nodes = arrays["nodes.npy"][1]
    spatial, lower, upper, reset = spatial_operator(metadata, nodes)
    zero = CSR.from_rows(({},))
    bundle = digest(canonical(hashes))
    initial = []
    for item in metadata["phase"]:
        start, end = F(item["start"]), F(item["end"])
        source = source_identity(bundle, item["identity"], start, end, 1, 0, ())
        initial.append(Template(source, start, end, 1, 0, zero, (1.0,), ()))
    emitted = []
    capsule_rows = []
    event_rows = []

    def lane(name, queries, start=None):
        time, pending = (F(0), tuple(initial)) if start is None else start
        for lane_order, query in enumerate(queries):
            while time < query:
                left = time
                boundaries = [query, left + F(1, 5)]
                for packet in pending:
                    boundaries.extend((packet.start, packet.end))
                right = min(value for value in boundaries if value > left)
                releasing = tuple(packet for packet in pending if packet.start == left)
                retained = [
                    replace(packet, start=right)
                    if packet.start == left and packet.end > right
                    else packet
                    for packet in pending
                    if packet.start != left or packet.end > right
                ]
                for origin, target in ((1, 2), (2, 3)):
                    if origin == 2 and left < F(1, 5):
                        continue
                    parents = tuple(
                        packet for packet in releasing if packet.target == origin
                    )
                    operator, output = block_operator(parents, spatial, lower, reset)
                    source = source_identity(
                        bundle,
                        "lower-flux",
                        left,
                        right,
                        target,
                        origin,
                        [packet.source for packet in parents],
                    )
                    packet = Template(
                        source,
                        left + F(1, 5),
                        right + F(1, 5),
                        target,
                        origin,
                        operator,
                        output,
                        tuple(parent.source for parent in parents),
                    )
                    retained.append(packet)
                    emitted.append(packet)
                pending = tuple(retained)
                time = right
                event_rows.append((name, left, right, len(releasing), len(pending)))
            capsule_rows.append((name, lane_order, time, pending))
        return time, pending

    saved = None
    time, pending = F(0), tuple(initial)
    for index, query in enumerate(WARM):
        time, pending = lane("warm", (query,), (time, pending))
        if query == COLD[0]:
            saved = (time, pending)
    lane("coarse", COARSE)
    if saved is None:
        raise ValueError("cold source capsule")
    lane("cold", COLD, saved)
    # lane() is called once per warm query, so normalize the recorded lane order.
    counters = {"warm": 0, "coarse": 0, "cold": 0}
    normalized = []
    for name, _, time, pending in capsule_rows:
        normalized.append((name, counters[name], time, pending))
        counters[name] += 1
    capsule_rows = normalized
    if len(capsule_rows) != 14 or len(event_rows) != 45:
        raise ValueError("candidate event count")
    published_by_capsule = {}
    for record in published:
        published_by_capsule.setdefault(record["capsule_order"], []).append(record)
    conceptual = 0
    for order, ((lane_name, lane_order, time, pending), capsule) in enumerate(
        zip(capsule_rows, capsules)
    ):
        if (
            lane_name,
            lane_order,
            [time.numerator, time.denominator],
            len(pending),
        ) != (
            capsule["lane"],
            capsule["lane_order"],
            capsule["time"]["fraction"],
            capsule["packets"],
        ):
            raise ValueError("candidate capsule roster mismatch")
        records = published_by_capsule[order]
        if len(records) != len(pending):
            raise ValueError("candidate packet count")
        for packet, record in zip(pending, records):
            actual = (
                packet.source,
                packet.dimension,
                packet.target,
                packet.origin,
                [packet.start.numerator, packet.start.denominator],
                [packet.end.numerator, packet.end.denominator],
            )
            expected = (
                record["source"],
                record["dimension"],
                record["target"],
                record["origin"],
                record["start"]["fraction"],
                record["end"]["fraction"],
            )
            if actual != expected:
                raise ValueError("candidate packet roster mismatch")
        count = (
            10 * 127
            + 50
            + sum(packet.dimension**2 + 6 * packet.dimension for packet in pending)
        )
        if count != capsule["coordinate_count"]:
            raise ValueError("candidate denominator mismatch")
        conceptual += count
    event_expected = [
        (
            event["lane"],
            F(*event["left"]["fraction"]),
            F(*event["right"]["fraction"]),
            event["releasing"],
            event["pending_after"],
        )
        for event in events
        if event["kind"] == "transition"
    ]
    if event_rows != event_expected:
        raise ValueError("candidate transition roster mismatch")
    operators = {
        packet.operator.identity: packet.operator for packet in (*initial, *emitted)
    }
    sparse_bytes = sum(
        8 * len(op.indptr) + 4 * len(op.indices) + 8 * len(op.data)
        for op in operators.values()
    )
    return {
        "summary": summary,
        "input_sha256": hashes,
        "input_bundle_sha256": bundle,
        "operators": len(operators),
        "operator_nnz": sum(len(op.data) for op in operators.values()),
        "unique_sparse_operator_bytes": sparse_bytes,
        "conceptual_coordinates": conceptual,
        "templates_emitted": len(emitted),
        "transition_segments": len(event_rows),
        "upper_sink_nnz": sum(value != 0 for value in upper),
        "matrix_exponentials": 0,
        "oracle_calls": 0,
    }


@dataclass(frozen=True)
class NumericPacket:
    source: str
    generation: int
    target: int
    origin: int
    start: F
    end: F
    operator: CSR
    alpha: tuple
    output: tuple

    def __post_init__(self):
        checked_hash(self.source)
        alpha = tuple(checked_float(value) for value in self.alpha)
        output = tuple(checked_float(value) for value in self.output)
        if (
            len(alpha) != CHANNELS * self.operator.dimension
            or len(output) != self.operator.dimension
        ):
            raise ValueError("numeric packet shape")
        object.__setattr__(self, "alpha", alpha)
        object.__setattr__(self, "output", output)


@dataclass(frozen=True)
class Readout:
    lane: int
    lane_order: int
    time: F
    capsule_identity: str

    def __post_init__(self):
        if type(self.lane) is not int or not 0 <= self.lane <= 2:
            raise ValueError("readout lane")
        if type(self.lane_order) is not int or self.lane_order < 0:
            raise ValueError("readout lane order")
        checked_hash(self.capsule_identity)


@dataclass(frozen=True)
class NumericCapsule:
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
        checked_hash(self.roster_identity)
        checked_hash(self.capsule_identity)
        if tuple(sorted(self.input_hashes)) != self.input_hashes:
            raise ValueError("input hashes ordered")
        for name, value in self.input_hashes:
            checked_hash(value)
        if (
            tuple(sorted(self.readouts, key=lambda item: (item.lane, item.lane_order)))
            != self.readouts
        ):
            raise ValueError("readout schedule ordered")
        if len({(item.lane, item.lane_order) for item in self.readouts}) != len(
            self.readouts
        ):
            raise ValueError("duplicate readout")
        state = tuple(checked_float(value) for value in self.state)
        if len(state) != 10 * self.interior_nodes + 50:
            raise ValueError("complete state coordinate count")
        object.__setattr__(self, "state", state)


def pack_fraction(value):
    return struct.pack("<qQ", value.numerator, value.denominator)


def dump(capsule):
    metadata = checked_hash(capsule.roster_identity) + checked_hash(
        capsule.capsule_identity
    )
    metadata += struct.pack(
        "<BI", capsule.lane, capsule.interior_nodes
    ) + pack_fraction(capsule.time)
    metadata += struct.pack("<I", len(capsule.input_hashes))
    for name, value in capsule.input_hashes:
        raw = name.encode()
        metadata += struct.pack("<H", len(raw)) + raw + checked_hash(value)
    state = struct.pack("<Q", len(capsule.state)) + struct.pack(
        f"<{len(capsule.state)}d", *capsule.state
    )
    packets = struct.pack("<I", len(capsule.packets))
    operators = {}
    for packet in capsule.packets:
        operators[packet.operator.identity] = packet.operator
        packets += checked_hash(packet.source) + struct.pack(
            "<III", packet.generation, packet.target, packet.origin
        )
        packets += (
            pack_fraction(packet.start)
            + pack_fraction(packet.end)
            + checked_hash(packet.operator.identity)
        )
        packets += struct.pack(f"<{len(packet.alpha)}d", *packet.alpha) + struct.pack(
            f"<{len(packet.output)}d", *packet.output
        )
    operator_section = struct.pack("<I", len(operators))
    for identity, operator in sorted(operators.items()):
        operator_section += checked_hash(identity) + struct.pack(
            "<IQ", operator.dimension, len(operator.data)
        )
        operator_section += struct.pack(f"<{len(operator.indptr)}Q", *operator.indptr)
        operator_section += struct.pack(f"<{len(operator.indices)}I", *operator.indices)
        operator_section += struct.pack(f"<{len(operator.data)}d", *operator.data)
    readouts = struct.pack("<I", len(capsule.readouts))
    for readout in capsule.readouts:
        readouts += struct.pack("<BI", readout.lane, readout.lane_order)
        readouts += pack_fraction(readout.time)
        readouts += checked_hash(readout.capsule_identity)
    sections = (metadata, state, packets, operator_section, readouts)
    header = MAGIC + struct.pack(
        "<HHHH", VERSION, 0x4C45, len(sections), 16 + 44 * len(sections)
    )
    directory = b"".join(
        struct.pack("<HHQ", kind, 0, len(raw)) + hashlib.sha256(raw).digest()
        for kind, raw in zip(SECTION_IDS, sections)
    )
    body = header + directory + b"".join(sections)
    return body + hashlib.sha256(body).digest()


class Cursor:
    def __init__(self, raw):
        self.raw = raw
        self.offset = 0

    def take(self, size):
        if self.offset + size > len(self.raw):
            raise ValueError("truncated container")
        value = self.raw[self.offset : self.offset + size]
        self.offset += size
        return value

    def unpack(self, fmt):
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))

    def fraction(self):
        return F(*self.unpack("<qQ"))

    def finish(self):
        if self.offset != len(self.raw):
            raise ValueError("trailing bytes")


def load(raw):
    if raw[:8] != MAGIC or hashlib.sha256(raw[:-32]).digest() != raw[-32:]:
        raise ValueError("container identity")
    if struct.unpack("<HHHH", raw[8:16]) != (
        VERSION,
        0x4C45,
        len(SECTION_IDS),
        16 + 44 * len(SECTION_IDS),
    ):
        raise ValueError("container header")
    cursor = Cursor(raw[16:-32])
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
    meta = Cursor(sections[0])
    roster = meta.take(32).hex()
    capsule_id = meta.take(32).hex()
    lane, nodes = meta.unpack("<BI")
    time = meta.fraction()
    (count,) = meta.unpack("<I")
    inputs = []
    for _ in range(count):
        (size,) = meta.unpack("<H")
        inputs.append((meta.take(size).decode(), meta.take(32).hex()))
    meta.finish()
    state_cursor = Cursor(sections[1])
    (count,) = state_cursor.unpack("<Q")
    state = state_cursor.unpack(f"<{count}d")
    state_cursor.finish()
    operator_cursor = Cursor(sections[3])
    (count,) = operator_cursor.unpack("<I")
    operators = {}
    for _ in range(count):
        identity = operator_cursor.take(32).hex()
        dimension, nnz = operator_cursor.unpack("<IQ")
        operator = CSR(
            dimension,
            operator_cursor.unpack(f"<{dimension + 1}Q"),
            operator_cursor.unpack(f"<{nnz}I"),
            operator_cursor.unpack(f"<{nnz}d"),
        )
        if operator.identity != identity:
            raise ValueError("operator identity")
        operators[identity] = operator
    operator_cursor.finish()
    readout_cursor = Cursor(sections[4])
    (count,) = readout_cursor.unpack("<I")
    readouts = []
    for _ in range(count):
        lane, lane_order = readout_cursor.unpack("<BI")
        readout_time = readout_cursor.fraction()
        readouts.append(
            Readout(lane, lane_order, readout_time, readout_cursor.take(32).hex())
        )
    readout_cursor.finish()
    packet_cursor = Cursor(sections[2])
    (count,) = packet_cursor.unpack("<I")
    packets = []
    for _ in range(count):
        source = packet_cursor.take(32).hex()
        generation, target, origin = packet_cursor.unpack("<III")
        start, end = packet_cursor.fraction(), packet_cursor.fraction()
        operator_id = packet_cursor.take(32).hex()
        operator = operators[operator_id]
        alpha = packet_cursor.unpack(f"<{CHANNELS * operator.dimension}d")
        output = packet_cursor.unpack(f"<{operator.dimension}d")
        packets.append(
            NumericPacket(
                source, generation, target, origin, start, end, operator, alpha, output
            )
        )
    packet_cursor.finish()
    capsule = NumericCapsule(
        roster,
        tuple(inputs),
        capsule_id,
        lane,
        time,
        nodes,
        tuple(readouts),
        state,
        tuple(packets),
    )
    if dump(capsule) != raw:
        raise ValueError("noncanonical cold container")
    return capsule


def coordinate_lines(capsule):
    """Return the complete conceptual dense coordinate stream for comparison."""
    rows = []
    for index, value in enumerate(capsule.state):
        rows.append(
            {"key": ["state", index], "fp64_le": struct.pack("<d", value).hex()}
        )
    for packet_order, packet in enumerate(capsule.packets):
        for index, value in enumerate(packet.alpha):
            rows.append(
                {
                    "key": ["packet", packet_order, "alpha", index],
                    "fp64_le": struct.pack("<d", value).hex(),
                }
            )
        dense = [
            [0.0] * packet.operator.dimension for _ in range(packet.operator.dimension)
        ]
        for row in range(packet.operator.dimension):
            for offset in range(
                packet.operator.indptr[row], packet.operator.indptr[row + 1]
            ):
                dense[row][packet.operator.indices[offset]] = packet.operator.data[
                    offset
                ]
        for row in range(packet.operator.dimension):
            for column in range(packet.operator.dimension):
                rows.append(
                    {
                        "key": ["packet", packet_order, "generator", row, column],
                        "fp64_le": struct.pack("<d", dense[row][column]).hex(),
                    }
                )
        for index, value in enumerate(packet.output):
            rows.append(
                {
                    "key": ["packet", packet_order, "output", index],
                    "fp64_le": struct.pack("<d", value).hex(),
                }
            )
    return sorted(rows, key=lambda row: json.dumps(row["key"], separators=(",", ":")))
