#!/usr/bin/env python3
"""Verify an immutable h operation-result page set and its bounded ZIP tail."""

import argparse
import base64
import hashlib
import json
import struct
from pathlib import Path


EXPECTED_OPERATION_ID = (
    "185441d37ac6e5e976f67a3a142304d21f618234183b12ef17c1152a15d57f7d"
)
EXPECTED_OPERATION_BYTES = 87_789
EXPECTED_OPERATION_SHA256 = (
    "d3c201e61f9b5e0511883431ed136c05c1f426bd175f83ece9921aeec3703051"
)
EXPECTED_TAIL_BYTES = 65_536
EXPECTED_TAIL_SHA256 = (
    "ba3c005f7ed325d96a6863f429b5b4cb9f8244f76633e4d8097c8a3392d21d18"
)
EXPECTED_ZIP_BYTES = 11_397_159


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_pages(raw_dir: Path) -> tuple[list[dict[str, object]], bytes]:
    pages = [
        json.loads(path.read_text())
        for path in sorted(raw_dir.glob("operation-result-page-*.json"))
    ]
    if len(pages) != 6:
        raise ValueError(f"expected six pages, got {len(pages)}")
    pages.sort(key=lambda page: int(page["offset"]))
    cursor = 0
    chunks: list[bytes] = []
    for index, page in enumerate(pages):
        if page["operation_id"] != EXPECTED_OPERATION_ID:
            raise ValueError(f"operation id mismatch on page {index}")
        if int(page["offset"]) != cursor:
            raise ValueError(
                f"non-contiguous page {index}: {page['offset']} != {cursor}"
            )
        if int(page["total_bytes"]) != EXPECTED_OPERATION_BYTES:
            raise ValueError(f"total byte mismatch on page {index}")
        if page["result_sha256"] != EXPECTED_OPERATION_SHA256:
            raise ValueError(f"result hash metadata mismatch on page {index}")
        chunk = base64.b64decode(str(page["data_base64"]), validate=True)
        chunks.append(chunk)
        cursor = int(page["next_offset"])
        if bool(page["eof"]) != (index == len(pages) - 1):
            raise ValueError(f"unexpected eof on page {index}")
    payload = b"".join(chunks)
    if cursor != EXPECTED_OPERATION_BYTES or len(payload) != EXPECTED_OPERATION_BYTES:
        raise ValueError("operation payload length mismatch")
    if sha256(payload) != EXPECTED_OPERATION_SHA256:
        raise ValueError("operation payload hash mismatch")
    return pages, payload


def parse_tail(payload: bytes, raw_dir: Path) -> tuple[dict[str, object], bytes]:
    outer = json.loads(payload)
    if outer.get("resultType") != "complete" or outer.get("isError") is not False:
        raise ValueError("operation payload is not a complete non-error CallToolResult")
    nested = json.loads(outer["content"][0]["text"])
    tail = base64.b64decode(nested["data_base64"], validate=True)
    frozen_tail = base64.b64decode(
        (raw_dir / "zip-tail-offset-11331623.b64").read_text().strip(), validate=True
    )
    if tail != frozen_tail:
        raise ValueError("separately frozen tail differs from nested payload")
    if len(tail) != EXPECTED_TAIL_BYTES or sha256(tail) != EXPECTED_TAIL_SHA256:
        raise ValueError("ZIP tail identity mismatch")
    if nested["chunk_sha256"] != EXPECTED_TAIL_SHA256:
        raise ValueError("nested chunk hash metadata mismatch")
    if (
        int(nested["offset"]) != 11_331_623
        or int(nested["next_offset"]) != EXPECTED_ZIP_BYTES
    ):
        raise ValueError("unexpected ZIP tail range")
    if int(nested["size"]) != EXPECTED_ZIP_BYTES or nested["eof"] is not True:
        raise ValueError("unexpected ZIP size/eof")
    return nested, tail


def parse_visible_central_directory(
    nested: dict[str, object], tail: bytes
) -> dict[str, object]:
    eocd = tail.rfind(b"PK\x05\x06")
    if eocd < 0 or eocd + 22 != len(tail):
        raise ValueError("canonical EOCD not found at tail end")
    (
        disk,
        central_disk,
        disk_entries,
        total_entries,
        central_size,
        central_offset,
        comment_len,
    ) = struct.unpack_from("<HHHHIIH", tail, eocd + 4)
    if (disk, central_disk, disk_entries, total_entries, comment_len) != (
        0,
        0,
        556,
        556,
        0,
    ):
        raise ValueError("unexpected EOCD counts or multipart metadata")
    tail_offset = int(nested["offset"])
    missing_central_prefix_bytes = tail_offset - central_offset
    first_visible = tail.find(b"PK\x01\x02")
    if first_visible < 0:
        raise ValueError("no visible central-directory record")
    cursor = first_visible
    entries: list[dict[str, object]] = []
    while cursor + 46 <= eocd and tail[cursor : cursor + 4] == b"PK\x01\x02":
        fields = struct.unpack_from("<6H3I5H2I", tail, cursor + 4)
        method = fields[3]
        crc32 = fields[6]
        compressed_size = fields[7]
        uncompressed_size = fields[8]
        name_length, extra_length, comment_length = fields[9:12]
        local_header_offset = fields[15]
        name_start = cursor + 46
        name = tail[name_start : name_start + name_length].decode("utf-8")
        entries.append(
            {
                "name": name,
                "method": method,
                "crc32": f"{crc32:08x}",
                "compressed_size": compressed_size,
                "uncompressed_size": uncompressed_size,
                "local_header_offset": local_header_offset,
            }
        )
        cursor = name_start + name_length + extra_length + comment_length
    if cursor != eocd:
        raise ValueError("visible central-directory records do not terminate at EOCD")
    if len(entries) != 441:
        raise ValueError(f"expected 441 complete visible records, got {len(entries)}")
    if total_entries - len(entries) != 115:
        raise ValueError("unexpected count of records outside the returned range")
    if (
        central_size != 83_624
        or central_offset != 11_313_513
        or missing_central_prefix_bytes != 18_110
    ):
        raise ValueError("unexpected central-directory bounds")
    index_entries = [entry for entry in entries if entry["name"] == "INDEX.json"]
    if len(index_entries) != 1:
        raise ValueError("INDEX.json central record is not uniquely visible")
    index_entry = index_entries[0]
    index_end = (
        int(index_entry["local_header_offset"])
        + 30
        + len("INDEX.json")
        + int(index_entry["compressed_size"])
    )
    if (
        int(index_entry["local_header_offset"]) >= tail_offset
        or index_end >= tail_offset
    ):
        raise ValueError("INDEX.json data unexpectedly overlaps the returned tail")
    return {
        "zip_total_bytes": EXPECTED_ZIP_BYTES,
        "eocd_absolute_offset": tail_offset + eocd,
        "central_directory_offset": central_offset,
        "central_directory_bytes": central_size,
        "central_directory_total_entries": total_entries,
        "returned_tail_offset": tail_offset,
        "returned_tail_bytes": len(tail),
        "missing_central_prefix_bytes": missing_central_prefix_bytes,
        "complete_visible_entries": len(entries),
        "entries_outside_returned_range": total_entries - len(entries),
        "first_visible_entry": entries[0]["name"],
        "last_visible_entry": entries[-1]["name"],
        "index_entry": index_entry,
        "index_data_available_in_returned_tail": False,
    }


def inspect(raw_dir: Path) -> dict[str, object]:
    pages, payload = load_pages(raw_dir)
    nested, tail = parse_tail(payload, raw_dir)
    central = parse_visible_central_directory(nested, tail)
    return {
        "schema": "hcsn-c2-operation-tail-readback-v1",
        "operation_id": EXPECTED_OPERATION_ID,
        "operation_pages": len(pages),
        "operation_payload_bytes": len(payload),
        "operation_payload_sha256": sha256(payload),
        "nested_path": nested["path"],
        "nested_version": nested["version"],
        "zip_tail_sha256": sha256(tail),
        "central_directory": central,
        "bounded_result": {
            "existing_operation_result_fully_recovered": True,
            "full_zip_recovered_by_this_operation_result": False,
            "six_start_parent_identities_closed": False,
            "per_fit_active_wall_closed": False,
            "per_fit_remaining_wall_closed": False,
            "full_independent_training_replay_completed": "0/6",
            "lifetime_optimizer_calls": "UNKNOWN",
            "original_controller_terminal": "UNKNOWN",
            "global_status": "HOLD_NO_GO",
            "all_closed": False,
        },
        "execution_counts": {
            "new_h_operations": 0,
            "model_calls": 0,
            "optimizer_calls": 0,
            "native_training_calls": 0,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=Path(__file__).with_name("raw"))
    args = parser.parse_args()
    print(json.dumps(inspect(args.raw_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
