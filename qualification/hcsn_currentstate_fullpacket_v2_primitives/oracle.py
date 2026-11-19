"""Independent dense oracle for the bounded fixture.

This module deliberately imports no candidate, serializer, or loader code.
"""

import hashlib
import json
import math
import struct
from fractions import Fraction
from pathlib import Path


def _binary64(value):
    value = float.fromhex(value)
    if not math.isfinite(value) or struct.pack("<d", value) == struct.pack(
        "<Q", 1 << 63
    ):
        raise ValueError("oracle requires finite canonical binary64")
    return value


def _operator_identity(dimension, dense):
    indptr = [0]
    indices = []
    data = []
    for row in dense:
        for column, value in enumerate(row):
            if value != 0.0:
                indices.append(column)
                data.append(value)
        indptr.append(len(indices))
    raw = struct.pack("<IQ", dimension, len(data))
    raw += struct.pack(f"<{len(indptr)}Q", *indptr)
    raw += struct.pack(f"<{len(indices)}I", *indices)
    raw += struct.pack(f"<{len(data)}d", *data)
    return hashlib.sha256(raw).hexdigest()


def from_fixture(path):
    """Return independent metadata and complete dense numeric coordinates."""
    payload = json.loads(Path(path).read_text())
    bindings = tuple(tuple(item) for item in payload["bindings"])
    operator_ids = {}
    coordinates = {}
    for item in payload["operators"]:
        dense = [[0.0] * item["dimension"] for _ in range(item["dimension"])]
        for row, column, value in item["entries"]:
            if dense[row][column] != 0.0:
                raise ValueError("oracle duplicate dense entry")
            value = _binary64(value)
            if value == 0.0:
                raise ValueError("oracle explicit zero entry")
            dense[row][column] = value
        identity = _operator_identity(item["dimension"], dense)
        operator_ids[item["name"]] = identity
        for row in range(item["dimension"]):
            for column in range(item["dimension"]):
                coordinates[("operator", identity, row, column)] = dense[row][column]
    state_metadata = []
    for region, channel, node, value in payload["state"]:
        key = (region, channel, node)
        state_metadata.append(key)
        coordinates[("state", *key)] = _binary64(value)
    packet_metadata = []
    for item in payload["packets"]:
        key = (
            item["generation"],
            item["target"],
            item["origin"],
            Fraction(*item["start"]),
            Fraction(*item["end"]),
            item["source_id"],
            operator_ids[item["operator"]],
            item["channel"],
        )
        packet_metadata.append(key)
        coordinates[("packet", *key)] = _binary64(item["coefficient"])
    return {
        "bindings": bindings,
        "interior_nodes": payload["interior_nodes"],
        "reset": Fraction(*payload["reset"]),
        "time": Fraction(*payload["time"]),
        "schedule": tuple(Fraction(*item) for item in payload["schedule"]),
        "upper_mode": payload["upper_mode"],
        "state_metadata": tuple(sorted(state_metadata)),
        "packet_metadata": tuple(sorted(packet_metadata)),
        "coordinates": coordinates,
    }


def aggregate_packet_totals(result):
    totals = {}
    for key, value in result["coordinates"].items():
        if key[0] == "packet":
            channel = key[-1]
            totals[channel] = totals.get(channel, 0.0) + value
    return totals


def aggregate_rz_witness(result):
    """Return a deliberately insufficient totals-only R/Z-style witness."""
    state = {channel: [0.0, 0.0] for channel in range(5)}
    for key, value in result["coordinates"].items():
        if key[0] == "state":
            _, region, channel, _ = key
            state[channel][region - 1] += value
    return {
        "R": tuple(tuple(state[channel]) for channel in range(5)),
        "Z": aggregate_packet_totals(result),
    }
