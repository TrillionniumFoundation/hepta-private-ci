"""Independent unreduced dense-oracle source.

This module imports no candidate, serializer, loader, or comparator. The N128
source is frozen here but is not numerically executed in this stage.
"""

import hashlib
import json
import math
import struct
from dataclasses import dataclass
from fractions import Fraction as F
from pathlib import Path


CHANNELS = 5


def finite(value):
    value = float(value)
    if not math.isfinite(value) or struct.pack("<d", value) == struct.pack(
        "<Q", 1 << 63
    ):
        raise ValueError("oracle binary64")
    return value


@dataclass(frozen=True)
class DenseOperator:
    rows: tuple

    def __post_init__(self):
        rows = tuple(tuple(finite(value) for value in row) for row in self.rows)
        if not rows or any(len(row) != len(rows) for row in rows):
            raise ValueError("square dense operator")
        object.__setattr__(self, "rows", rows)

    @property
    def dimension(self):
        return len(self.rows)


@dataclass(frozen=True)
class DensePacket:
    source: str
    generation: int
    target: int
    origin: int
    start: F
    end: F
    operator: DenseOperator
    alpha: tuple
    output: tuple

    def __post_init__(self):
        alpha = tuple(finite(value) for value in self.alpha)
        output = tuple(finite(value) for value in self.output)
        if (
            len(alpha) != CHANNELS * self.operator.dimension
            or len(output) != self.operator.dimension
        ):
            raise ValueError("oracle packet shape")
        object.__setattr__(self, "alpha", alpha)
        object.__setattr__(self, "output", output)


def combine(parents, spatial, lower, reset):
    """Unreduced row-generator construction, independently implemented."""
    n = len(spatial)
    dimension = n + sum(packet.operator.dimension for packet in parents)
    matrix = [[0.0] * dimension for _ in range(dimension)]
    offset = 0
    for packet in parents:
        for row in range(packet.operator.dimension):
            for column, value in enumerate(packet.operator.rows[row]):
                matrix[offset + row][offset + column] = value
            for node, weight in enumerate(reset):
                matrix[offset + row][dimension - n + node] = packet.output[row] * weight
        offset += packet.operator.dimension
    for row in range(n):
        for column in range(n):
            matrix[offset + row][offset + column] = spatial[row][column]
    return DenseOperator(tuple(tuple(row) for row in matrix)), (0.0,) * (
        dimension - n
    ) + tuple(lower)


def from_fixture(path):
    payload = json.loads(Path(path).read_text())
    operators = {
        item["name"]: DenseOperator(
            tuple(tuple(float.fromhex(value) for value in row) for row in item["dense"])
        )
        for item in payload["operators"]
    }
    packets = []
    for item in payload["packets"]:
        packets.append(
            DensePacket(
                item["source"],
                item["generation"],
                item["target"],
                item["origin"],
                F(*item["start"]),
                F(*item["end"]),
                operators[item["operator"]],
                tuple(float.fromhex(value) for value in item["alpha"]),
                tuple(float.fromhex(value) for value in item["output"]),
            )
        )
    state = tuple(float.fromhex(value) for value in payload["state"])
    return {"state": state, "packets": tuple(packets)}


def coordinate_lines(capsule):
    rows = []
    for index, value in enumerate(capsule["state"]):
        rows.append(
            {"key": ["state", index], "fp64_le": struct.pack("<d", value).hex()}
        )
    for packet_order, packet in enumerate(capsule["packets"]):
        for index, value in enumerate(packet.alpha):
            rows.append(
                {
                    "key": ["packet", packet_order, "alpha", index],
                    "fp64_le": struct.pack("<d", value).hex(),
                }
            )
        for row in range(packet.operator.dimension):
            for column in range(packet.operator.dimension):
                rows.append(
                    {
                        "key": ["packet", packet_order, "generator", row, column],
                        "fp64_le": struct.pack(
                            "<d", packet.operator.rows[row][column]
                        ).hex(),
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


def source_digest():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
