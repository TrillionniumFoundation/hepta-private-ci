"""Execute the source-bound N128 generation-2 warm continuation."""

import argparse
import hashlib
import itertools
import json
import math
import resource
import struct
import time
from pathlib import Path

import numpy as np

from qualification.hcsn_currentstate_n128_engineering import candidate

from . import candidate_warm, oracle_warm


EXPECTED_CAPSULE_COORDINATES = (256286, 604908, 870084)
EXPECTED_TOTAL = sum(EXPECTED_CAPSULE_COORDINATES)
CALLS = {
    "candidate_dynamic_segments": 10,
    "candidate_matrix_exponentials": 40,
    "oracle_dynamic_segments": 10,
    "oracle_matrix_exponentials": 40,
    "torch_operations": 0,
    "optimizer_updates": 0,
}


def candidate_coordinates(capsule):
    for index, value in enumerate(capsule.state):
        yield ("state", index), value
    for order, packet in enumerate(capsule.packets):
        for index, value in enumerate(packet.alpha):
            yield ("packet", order, "alpha", index), value
        operator = packet.operator
        for row in range(operator.dimension):
            start, end = operator.indptr[row], operator.indptr[row + 1]
            cursor = start
            for column in range(operator.dimension):
                if cursor < end and operator.indices[cursor] == column:
                    value = operator.data[cursor]
                    cursor += 1
                else:
                    value = 0.0
                yield ("packet", order, "generator", row, column), value
            if cursor != end:
                raise ArithmeticError("CSR row stream")
        for index, value in enumerate(packet.output):
            yield ("packet", order, "output", index), value


def oracle_coordinates(capsule):
    for index, value in enumerate(capsule["state"]):
        yield ("state", index), value
    for order, packet in enumerate(capsule["packets"]):
        for index, value in enumerate(packet["alpha"].flat):
            yield ("packet", order, "alpha", index), value
        for row in range(len(packet["generator"])):
            for column, value in enumerate(packet["generator"][row]):
                yield ("packet", order, "generator", row, column), value
        for index, value in enumerate(packet["output"]):
            yield ("packet", order, "output", index), value


class RawWriter:
    def __init__(self, path):
        self.handle = Path(path).open("wb")
        self.buffer = bytearray()
        self.sha256 = hashlib.sha256()
        self.values = 0

    def write(self, raw):
        self.buffer.extend(raw)
        self.sha256.update(raw)
        self.values += 1
        if len(self.buffer) >= 1 << 20:
            self.handle.write(self.buffer)
            self.buffer.clear()

    def close(self):
        self.handle.write(self.buffer)
        self.handle.close()
        self.buffer.clear()
        return self.sha256.hexdigest()


def file_record(path):
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            size += len(block)
            digest.update(block)
    return {"bytes": size, "sha256": digest.hexdigest()}


def capsule_schema(order, capsule, expected):
    packets = [
        {
            "order": packet_order,
            "source": packet.source,
            "generation": packet.generation,
            "target": packet.target,
            "origin": packet.origin,
            "start": [packet.start.numerator, packet.start.denominator],
            "end": [packet.end.numerator, packet.end.denominator],
            "dimension": packet.operator.dimension,
            "layout": [
                ["alpha", 5 * packet.operator.dimension],
                ["generator_row_major", packet.operator.dimension**2],
                ["output", packet.operator.dimension],
            ],
        }
        for packet_order, packet in enumerate(capsule.packets)
    ]
    conceptual = len(capsule.state) + sum(
        sum(item[1] for item in packet["layout"]) for packet in packets
    )
    if conceptual != expected:
        raise ArithmeticError(f"capsule {order} schema denominator")
    return {
        "order": order,
        "warm_global_order": order + 5,
        "time": [capsule.time.numerator, capsule.time.denominator],
        "state_coordinates": len(capsule.state),
        "packets": packets,
        "coordinate_order": "state_then_packet_order_alpha_generator_row_major_output",
        "coordinates": conceptual,
    }


def run(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    candidate_capsules, candidate_cost = candidate_warm.run(
        args.start, args.law, args.metadata, args.npz, args.roster
    )
    oracle_capsules, oracle_cost = oracle_warm.run(
        args.start, args.law, args.metadata, args.npz
    )
    if candidate_cost != {
        "candidate_dynamic_segments": 10,
        "candidate_matrix_exponentials": 40,
        "candidate_capsules": 3,
    } or oracle_cost != {
        "oracle_dynamic_segments": 10,
        "oracle_matrix_exponentials": 40,
        "oracle_capsules": 3,
    }:
        raise ArithmeticError("actual call ledger")

    candidate_writer = RawWriter(output / "CANDIDATE-COORDINATES.f64le")
    oracle_writer = RawWriter(output / "ORACLE-COORDINATES.f64le")
    schemas = []
    checks = []
    comparisons = 0
    failures = 0
    max_abs = 0.0
    sentinel = object()
    for order, (left, right, expected) in enumerate(
        zip(candidate_capsules, oracle_capsules, EXPECTED_CAPSULE_COORDINATES)
    ):
        schema = capsule_schema(order, left, expected)
        schemas.append(schema)
        before = comparisons
        for candidate_row, oracle_row in itertools.zip_longest(
            candidate_coordinates(left), oracle_coordinates(right), fillvalue=sentinel
        ):
            if candidate_row is sentinel or oracle_row is sentinel:
                raise ArithmeticError(f"capsule {order} coordinate length")
            left_key, left_value = candidate_row
            right_key, right_value = oracle_row
            if left_key != right_key:
                raise ArithmeticError(f"capsule {order} coordinate identity")
            left_raw = struct.pack("<d", left_value)
            right_raw = struct.pack("<d", right_value)
            candidate_writer.write(left_raw)
            oracle_writer.write(right_raw)
            comparisons += 1
            if left_raw != right_raw:
                failures += 1
                if math.isfinite(left_value) and math.isfinite(right_value):
                    max_abs = max(max_abs, abs(left_value - right_value))
        if comparisons - before != expected:
            raise ArithmeticError(f"capsule {order} denominator")
        raw = candidate.dump(left)
        restored = candidate.load(raw)
        byte_exact = candidate.dump(restored) == raw
        if not byte_exact:
            raise ArithmeticError(f"capsule {order} cold container")
        capsule_path = output / f"CAPSULE-{order + 5}.bin"
        capsule_path.write_bytes(raw)
        checks.append(
            {
                "order": order,
                "warm_global_order": order + 5,
                "coordinates": expected,
                "cold_container_bytes_exact": byte_exact,
                "container": file_record(capsule_path),
            }
        )
    candidate_sha = candidate_writer.close()
    oracle_sha = oracle_writer.close()
    if (
        comparisons != EXPECTED_TOTAL
        or candidate_writer.values != EXPECTED_TOTAL
        or oracle_writer.values != EXPECTED_TOTAL
        or failures != 0
        or candidate_sha != oracle_sha
    ):
        raise ArithmeticError("complete binary64 comparison")
    schema = {
        "format": "little-endian IEEE-754 binary64 without headers",
        "source_start_sha256": candidate_warm.START_SHA256,
        "capsules": schemas,
        "coordinates": comparisons,
    }
    (output / "COORDINATE-SCHEMA.json").write_text(
        json.dumps(schema, indent=2, sort_keys=True) + "\n"
    )
    comparison = {
        "coordinates": comparisons,
        "failures": failures,
        "bitwise_equal": failures == 0,
        "max_absolute_error": max_abs,
        "candidate_sha256": candidate_sha,
        "oracle_sha256": oracle_sha,
    }
    result = {
        "identity": args.identity,
        "unique_execution_key": args.key,
        "source_commit": args.source_commit,
        "parent_source_commit": args.parent_source_commit,
        "status": "PASS_BOUNDED_N128_SECOND_CYCLE_WARM_ONLY",
        "qualification": False,
        "start_capsule_sha256": candidate_warm.START_SHA256,
        "queries": [
            [value.numerator, value.denominator] for value in candidate_warm.QUERIES
        ],
        "capsules": checks,
        "comparison": comparison,
        "candidate": candidate_cost,
        "oracle": oracle_cost,
        "calls": CALLS,
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu,
        "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "preserved_development_red": {
            "status": "KILLED_137_NO_RESULT",
            "cause": "UNKNOWN",
            "admission": False,
        },
        "remaining_open": [
            "coarse/cold independent dynamic lanes",
            "third-cycle release after .4",
            "arbitrary histories",
            "N256/N512 dynamics",
            "full-network training",
            "finite-domain qualification",
            "asynchronous complete cost",
        ],
        "all_closed": False,
    }
    (output / "RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    artifacts = {
        path.name: file_record(path)
        for path in sorted(output.iterdir())
        if path.name != "ARTIFACTS.json"
    }
    (output / "ARTIFACTS.json").write_text(
        json.dumps(artifacts, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(result, sort_keys=True))


def main():
    parser = argparse.ArgumentParser()
    for name in (
        "start",
        "law",
        "metadata",
        "npz",
        "roster",
        "output",
        "identity",
        "key",
        "source_commit",
        "parent_source_commit",
    ):
        parser.add_argument(f"--{name.replace('_', '-')}", required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
