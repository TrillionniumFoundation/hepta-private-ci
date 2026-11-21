"""Zero-model localization of the immutable #6890 coordinate mismatches."""

import argparse
import hashlib
import json
import math
import os
import resource
import struct
import time
import zipfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MAGIC = b"HCSNFSP2"
TRAILER_SIZE = 32
MAX_DIMS = 8


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("ascii")


def archive_member(path, archive_sha, member, member_sha):
    raw_archive = Path(path).read_bytes()
    if sha(raw_archive) != archive_sha:
        raise ValueError("archive identity")
    with zipfile.ZipFile(path) as package:
        if package.namelist().count(member) != 1:
            raise ValueError("archive member identity")
        raw = package.read(member)
    if sha(raw) != member_sha:
        raise ValueError("archive member digest")
    return raw


def take(view, offset, length):
    end = offset + length
    if length < 0 or end > len(view):
        raise ValueError("truncated capsule")
    return bytes(view[offset:end]), end


def read_u32(view, offset):
    raw, offset = take(view, offset, 4)
    return struct.unpack(">I", raw)[0], offset


def read_u64(view, offset):
    raw, offset = take(view, offset, 8)
    return struct.unpack(">Q", raw)[0], offset


def tensor(view, offset):
    dimensions, offset = read_u32(view, offset)
    if not 0 < dimensions <= MAX_DIMS:
        raise ValueError("tensor dimension bound")
    shape = []
    for _ in range(dimensions):
        size, offset = read_u64(view, offset)
        if size <= 0:
            raise ValueError("tensor shape")
        shape.append(size)
    payload_size, offset = read_u64(view, offset)
    payload, offset = take(view, offset, payload_size)
    elements = math.prod(shape)
    if payload_size != elements * 8:
        raise ValueError("tensor payload length")
    return {"shape": tuple(shape), "payload": payload}, offset


def decode(raw):
    if len(raw) < len(MAGIC) + TRAILER_SIZE or raw[: len(MAGIC)] != MAGIC:
        raise ValueError("capsule magic")
    body, trailer = raw[:-TRAILER_SIZE], raw[-TRAILER_SIZE:]
    if hashlib.sha256(body).digest() != trailer:
        raise ValueError("capsule checksum")
    view = memoryview(body)
    offset = len(MAGIC)
    metadata_size, offset = read_u32(view, offset)
    metadata_raw, offset = take(view, offset, metadata_size)
    metadata = json.loads(metadata_raw)
    if canonical(metadata) != metadata_raw:
        raise ValueError("noncanonical metadata")
    block_count, offset = read_u32(view, offset)
    blocks = []
    for _ in range(block_count):
        name_size, offset = read_u32(view, offset)
        name, offset = take(view, offset, name_size)
        value, offset = tensor(view, offset)
        blocks.append((name.decode("ascii"), value))
    packet_count, offset = read_u32(view, offset)
    packets = []
    for _ in range(packet_count):
        metadata_size, offset = read_u32(view, offset)
        packet_raw, offset = take(view, offset, metadata_size)
        packet_metadata = json.loads(packet_raw)
        if canonical(packet_metadata) != packet_raw:
            raise ValueError("noncanonical packet metadata")
        values = {}
        for field in ("alpha", "generator", "output"):
            values[field], offset = tensor(view, offset)
        packets.append((packet_metadata, values))
    if offset != len(view):
        raise ValueError("capsule trailing bytes")
    return {"metadata": metadata, "blocks": blocks, "packets": packets}


def unravel(index, shape):
    coordinates = []
    for size in reversed(shape):
        coordinates.append(index % size)
        index //= size
    return list(reversed(coordinates))


def rows(envelope):
    result = []
    for name, value in envelope["blocks"]:
        for index in range(len(value["payload"]) // 8):
            result.append((f"state/{name}", index, value["shape"], value["payload"][8 * index : 8 * index + 8]))
    for metadata, fields in envelope["packets"]:
        identity = metadata["identity"]
        for field in ("alpha", "generator", "output"):
            value = fields[field]
            for index in range(len(value["payload"]) // 8):
                result.append((f"packet/{identity}/{field}", index, value["shape"], value["payload"][8 * index : 8 * index + 8]))
    return result


def ordered(raw):
    bits = int.from_bytes(raw, "little")
    return 0xFFFFFFFFFFFFFFFF - bits if bits >> 63 else bits + 0x8000000000000000


def write_json(path, value):
    Path(path).write_text(json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n")


def metadata_delta(expected, observed):
    keys = sorted(set(expected) | set(observed))
    return [{"key": key, "expected": expected.get(key), "observed": observed.get(key)} for key in keys if expected.get(key) != observed.get(key)]


def main(output):
    request = json.loads((HERE / "REQUEST.json").read_text())
    started_wall, started_cpu = time.monotonic(), time.process_time()
    oracle_raw = archive_member(ROOT / request["oracle_archive"], request["oracle_archive_sha256"], request["oracle_member"], request["oracle_member_sha256"])
    candidate_raw = archive_member(ROOT / request["candidate_archive"], request["candidate_archive_sha256"], request["candidate_member"], request["candidate_member_sha256"])
    expected, observed = decode(oracle_raw), decode(candidate_raw)
    left, right = rows(expected), rows(observed)
    if [(a, b, c) for a, b, c, _ in left] != [(a, b, c) for a, b, c, _ in right]:
        raise ValueError("coordinate identity")
    mismatches = []
    by_path = {}
    by_tensor_class = {}
    ulp_histogram = {"1": 0, "2": 0, "3-4": 0, "5-8": 0, "9-16": 0, "17-32": 0, "33-64": 0, "65-128": 0, ">128": 0}
    sign = {"observed_less": 0, "observed_greater": 0, "equal_numeric_nonidentical": 0}
    maximum_abs, maximum_ulp = 0.0, 0
    for (path, index, shape, a_raw), (_, _, _, b_raw) in zip(left, right):
        if a_raw == b_raw:
            continue
        a, b = struct.unpack("<d", a_raw)[0], struct.unpack("<d", b_raw)[0]
        if not math.isfinite(a) or not math.isfinite(b):
            raise ValueError("non-finite coordinate")
        distance = abs(ordered(a_raw) - ordered(b_raw))
        absolute = abs(a - b)
        maximum_abs, maximum_ulp = max(maximum_abs, absolute), max(maximum_ulp, distance)
        by_path[path] = by_path.get(path, 0) + 1
        tensor_class = path.split("/")[-1] if path.startswith("packet/") else "state"
        by_tensor_class[tensor_class] = by_tensor_class.get(tensor_class, 0) + 1
        bucket = "1" if distance == 1 else "2" if distance == 2 else "3-4" if distance <= 4 else "5-8" if distance <= 8 else "9-16" if distance <= 16 else "17-32" if distance <= 32 else "33-64" if distance <= 64 else "65-128" if distance <= 128 else ">128"
        ulp_histogram[bucket] += 1
        relation = "observed_less" if b < a else "observed_greater" if b > a else "equal_numeric_nonidentical"
        sign[relation] += 1
        mismatches.append({
            "path": path,
            "flat_index": index,
            "coordinate": unravel(index, shape),
            "shape": list(shape),
            "expected_hex": a.hex(),
            "observed_hex": b.hex(),
            "expected_bytes_le": a_raw.hex(),
            "observed_bytes_le": b_raw.hex(),
            "delta_hex": (b - a).hex(),
            "abs_error_hex": absolute.hex(),
            "ulp_distance": distance,
        })
    summary = {
        "schema": "hcsn-n256-runtime-v3-mismatch-localization-result-v1",
        "identity": request["identity"],
        "parent_red_preserved": True,
        "coordinate_comparisons": len(left),
        "bitwise_mismatches": len(mismatches),
        "max_abs_error_hex": maximum_abs.hex(),
        "max_ulp_distance": maximum_ulp,
        "mismatches_by_path": dict(sorted(by_path.items())),
        "mismatches_by_tensor_class": dict(sorted(by_tensor_class.items())),
        "ulp_histogram": ulp_histogram,
        "delta_sign": sign,
        "capsule_metadata_delta": metadata_delta(expected["metadata"], observed["metadata"]),
        "model_calls": 0,
        "dynamic_steps": 0,
        "dense_expm_actions": 0,
        "sparse_expm_actions": 0,
        "oracle_reexecutions": 0,
        "torch_calls": 0,
        "optimizer_steps": 0,
        "qualification": False,
        "production_adoption": False,
        "all_closed": False,
    }
    if len(left) != request["expected_coordinate_comparisons"] or len(mismatches) != request["expected_bitwise_mismatches"]:
        raise ValueError("preserved RED denominator")
    if maximum_abs.hex() != request["expected_max_abs_error_hex"] or maximum_ulp != request["expected_max_ulp_distance"]:
        raise ValueError("preserved RED maxima")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "SUMMARY.json", summary)
    (output / "MISMATCHES.jsonl").write_text("".join(json.dumps(row, allow_nan=False, sort_keys=True) + "\n" for row in mismatches))
    usage = resource.getrusage(resource.RUSAGE_SELF)
    write_json(output / "COST.json", {
        "wall_seconds": time.monotonic() - started_wall,
        "cpu_seconds": time.process_time() - started_cpu,
        "maximum_rss_kib": usage.ru_maxrss,
        "capsule_decodes": 2,
        "coordinate_comparisons": len(left),
        "model_calls": 0,
        "dynamic_steps": 0,
        "expm_actions": 0,
        "torch_calls": 0,
        "optimizer_steps": 0,
    })
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    raise SystemExit(main(parser.parse_args().output))
