"""Independent stdlib-only full-denominator audit of the two raw containers."""

import hashlib
import json
import struct
from pathlib import Path


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "RUN_OUTPUT"
EXPECTED = (
    ("extended_generator", (257, 257)),
    ("initial", (5, 257)),
    ("lower_selector", (257, 1)),
    ("discounted_selectors", (257, 2)),
)
MAGIC = b"HCSNBND1"
TOTAL = 68105


def _take(data, offset, count):
    end = offset + count
    if end > len(data):
        raise ValueError("truncated independent audit")
    return data[offset:end], end


def _parse(data):
    if len(data) != 545171:
        raise ValueError("container byte denominator")
    body, trailer = data[:-32], data[-32:]
    if hashlib.sha256(body).digest() != trailer:
        raise ValueError("whole-container digest")
    preamble, offset = _take(body, 0, 20)
    if struct.unpack("<8sHHQ", preamble) != (MAGIC, 1, 4, TOTAL):
        raise ValueError("container preamble")
    result = []
    for expected_name, expected_shape in EXPECTED:
        raw, offset = _take(body, offset, 2)
        name_size = struct.unpack("<H", raw)[0]
        raw, offset = _take(body, offset, name_size)
        if raw.decode("ascii") != expected_name:
            raise ValueError("section identity or order")
        raw, offset = _take(body, offset, 1)
        rank = raw[0]
        raw, offset = _take(body, offset, rank * 4)
        shape = tuple(value[0] for value in struct.iter_unpack("<I", raw))
        if shape != expected_shape:
            raise ValueError("section shape")
        raw, offset = _take(body, offset, 1)
        dtype_size = raw[0]
        dtype, offset = _take(body, offset, dtype_size)
        if dtype != b"<f8":
            raise ValueError("section dtype")
        raw, offset = _take(body, offset, 8)
        payload_size = struct.unpack("<Q", raw)[0]
        coordinates = 1
        for dimension in shape:
            coordinates *= dimension
        if payload_size != coordinates * 8:
            raise ValueError("payload size")
        expected_digest, offset = _take(body, offset, 32)
        payload, offset = _take(body, offset, payload_size)
        if hashlib.sha256(payload).digest() != expected_digest:
            raise ValueError("section digest")
        for (bits,) in struct.iter_unpack("<Q", payload):
            if bits & 0x7FF0000000000000 == 0x7FF0000000000000:
                raise ValueError("nonfinite coordinate")
        result.append((expected_name, payload))
    if offset != len(body):
        raise ValueError("trailing container bytes")
    return result


def main():
    oracle_path = OUTPUT / "ORACLE_BOUNDARY.bin"
    candidate_path = OUTPUT / "CANDIDATE_BOUNDARY.bin"
    report = {
        "identity": "hcsn-n256-authentic-boundary-attempt002-audit-20261121-c06d",
        "implementation": "independent-stdlib-byte-audit",
        "qualification": False,
        "all_closed": False,
    }
    try:
        oracle_raw, candidate_raw = oracle_path.read_bytes(), candidate_path.read_bytes()
        oracle, candidate = _parse(oracle_raw), _parse(candidate_raw)
        mismatches = 0
        compared = 0
        by_section = {}
        first = []
        for (left_name, left), (right_name, right) in zip(
            oracle, candidate, strict=True
        ):
            if left_name != right_name or len(left) != len(right):
                raise ValueError("section pairing")
            section_mismatches = 0
            for offset in range(0, len(left), 8):
                compared += 1
                if left[offset : offset + 8] != right[offset : offset + 8]:
                    mismatches += 1
                    section_mismatches += 1
                    if len(first) < 32:
                        first.append(
                            {
                                "section": left_name,
                                "index": offset // 8,
                                "oracle_hex": left[offset : offset + 8].hex(),
                                "candidate_hex": right[offset : offset + 8].hex(),
                            }
                        )
            by_section[left_name] = section_mismatches
        if compared != TOTAL:
            raise ValueError("coordinate denominator")
        report.update(
            {
                "status": "EXACT" if mismatches == 0 else "RED",
                "coordinates_compared": compared,
                "mismatches": mismatches,
                "mismatches_by_section": by_section,
                "first_mismatches": first,
                "oracle_sha256": hashlib.sha256(oracle_raw).hexdigest(),
                "candidate_sha256": hashlib.sha256(candidate_raw).hexdigest(),
            }
        )
    except Exception as error:
        report.update(
            {
                "status": "INCOMPLETE",
                "coordinates_compared": None,
                "mismatches": None,
                "error_type": type(error).__name__,
                "error": str(error),
            }
        )
    (OUTPUT / "AUDIT.json").write_text(
        json.dumps(report, allow_nan=False, indent=2, sort_keys=True) + "\n"
    )


if __name__ == "__main__":
    main()
