"""Transform archived authentic index256 originals without numerical replay."""

import hashlib
import io
import json
import os
import platform
import resource
import shutil
import sys
import time
from pathlib import Path
import zipfile

from qualification.hcsn_currentstate_n256_authentic_compact_checkpoint.compact import (
    INDEX256_SCHEMA,
    MAX_COMPACT_BYTES,
    decode_compact_checkpoint,
    encode_compact_checkpoint,
    inspect_canonical_checkpoint,
)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
INPUT_PARTS = ROOT / "qualification/hcsn_ci_readbacks/6944"
OUTPUT = HERE / "RUN_OUTPUT"
PART_COUNT = 41
INPUT_ZIP_SHA256 = "452060c65949e9c1d8ffe74e4303d707e6fe4fe7c2e75e29caacfa3137c37a91"
EXECUTION_KEY = "hcsn-n256-authentic-compact-checkpoint-20261122-c6bc-001"
IDENTITY = "hcsn-n256-authentic-compact-checkpoint-20261122-c6bc-v1"
AGGREGATE_CAP_BYTES = 67_108_864


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _journal(event, **fields):
    record = {"event": event, "monotonic_seconds": time.perf_counter(), **fields}
    with (OUTPUT / "RUN.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _load_input_zip():
    raw = b"".join(
        (INPUT_PARTS / f"ORIGINAL.zip.part{index:03d}").read_bytes()
        for index in range(PART_COUNT)
    )
    if _sha256(raw) != INPUT_ZIP_SHA256:
        raise SystemExit("archived index256 artifact digest mismatch")
    return raw


def main():
    if os.environ.get("UNIQUE_EXECUTION_KEY") != EXECUTION_KEY:
        raise SystemExit("execution key mismatch")
    if os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
        raise SystemExit("rerun refused before archived input read")
    if OUTPUT.exists():
        raise SystemExit("output already exists")
    OUTPUT.mkdir(parents=True)
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    _journal("admitted", execution_key=EXECUTION_KEY)
    archive_raw = _load_input_zip()
    _journal("input_verified", bytes=len(archive_raw), sha256=_sha256(archive_raw))
    records = []
    raw_total = 0
    compact_total = 0
    with zipfile.ZipFile(io.BytesIO(archive_raw)) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise SystemExit(f"archived index256 ZIP CRC failure: {bad}")
        names = sorted(
            name for name in archive.namelist() if name.endswith(".checkpoint.json")
        )
        if len(names) != 10:
            raise SystemExit("archived index256 checkpoint denominator mismatch")
        for ordinal, name in enumerate(names):
            raw = archive.read(name)
            metadata = inspect_canonical_checkpoint(raw, INDEX256_SCHEMA, 256)
            first = encode_compact_checkpoint(raw, INDEX256_SCHEMA, 256)
            second = encode_compact_checkpoint(raw, INDEX256_SCHEMA, 256)
            if first != second:
                raise SystemExit("compact serializer is not byte deterministic")
            restored = decode_compact_checkpoint(first, INDEX256_SCHEMA, 256)
            if restored != raw:
                raise SystemExit("compact checkpoint does not restore exact raw bytes")
            output_name = name.replace(".checkpoint.json", ".checkpoint.hcsncp")
            (OUTPUT / output_name).write_bytes(first)
            record = {
                "ordinal": ordinal,
                "source_file": name,
                "file": output_name,
                "lane": metadata["lane"],
                "vector_length": metadata["vector_length"],
                "raw_bytes": len(raw),
                "raw_sha256": _sha256(raw),
                "compact_bytes": len(first),
                "compact_sha256": _sha256(first),
                "restored_raw_sha256": _sha256(restored),
                "byte_exact": restored == raw,
            }
            raw_total += len(raw)
            compact_total += len(first)
            records.append(record)
            _journal("checkpoint_complete", **record)
    if max(record["compact_bytes"] for record in records) > MAX_COMPACT_BYTES:
        raise SystemExit("per-cursor compact cap exceeded")
    if compact_total > AGGREGATE_CAP_BYTES:
        raise SystemExit("aggregate compact cap exceeded")
    usage = resource.getrusage(resource.RUSAGE_SELF)
    result = {
        "identity": IDENTITY,
        "execution_key": EXECUTION_KEY,
        "status": "AUTHENTIC_INDEX256_COMPACT_FULLSTATE_ONLY_HOLD",
        "input_zip_sha256": INPUT_ZIP_SHA256,
        "checkpoints": records,
        "raw_total_bytes": raw_total,
        "compact_total_bytes": compact_total,
        "aggregate_cap_bytes": AGGREGATE_CAP_BYTES,
        "aggregate_headroom_bytes": AGGREGATE_CAP_BYTES - compact_total,
        "maximum_compact_cursor_bytes": max(
            record["compact_bytes"] for record in records
        ),
        "work": {
            "serializer_encodes": 20,
            "serializer_decodes": 10,
            "recurrence_row_actions": 0,
            "tail_checks": 0,
            "provider_outputs": 0,
            "dynamic_steps": 0,
            "exponential_actions": 0,
            "torch_calls": 0,
            "optimizer_steps": 0,
        },
        "cost": {
            "wall_seconds": time.perf_counter() - started_wall,
            "cpu_seconds": time.process_time() - started_cpu,
            "max_rss_kib": usage.ru_maxrss,
        },
        "host": {
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "github_sha": os.environ.get("GITHUB_SHA"),
            "platform": platform.platform(),
            "python": sys.version,
            "disk_free_bytes_after": shutil.disk_usage(OUTPUT).free,
        },
        "tail_rounding_qualified": False,
        "n256_qualified": False,
        "production_adoption": False,
        "all_closed": False,
    }
    (OUTPUT / "RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    _journal("complete", compact_total_bytes=compact_total)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
