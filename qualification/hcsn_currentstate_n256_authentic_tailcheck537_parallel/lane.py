"""Execute one authentic index256-to-537 lane and persist full originals."""

import hashlib
import io
import json
import os
import platform
import resource
import sys
import time
from pathlib import Path
import zipfile

from qualification.hcsn_currentstate_n256_authentic_compact_checkpoint.compact import (
    INDEX256_SCHEMA,
    decode_compact_checkpoint,
    encode_compact_checkpoint,
)
from qualification.hcsn_currentstate_n256_authentic_tailcheck537_parallel.tail537 import (
    SCHEMA,
    advance_to_index537,
    encode_raw_index537,
    first_tail_check,
    parse_index256,
)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
INPUT_PARTS = ROOT / "qualification/hcsn_ci_readbacks/6948"
DETACHED_ZIP = ROOT / "qualification/hcsn_ci_readbacks/6934/ORIGINAL.zip"
PARENT_PARTS = ROOT / "qualification/hcsn_ci_readbacks/6931"
OUTPUT_ROOT = HERE / "RUN_OUTPUT"
INPUT_PART_COUNT = 35
PARENT_PART_COUNT = 3
INPUT_SHA256 = "fe98992972a1779e6ffe1baf2142a2010bd71eb92e633dc69e459578caa9e8f6"
DETACHED_SHA256 = "5d745460761940b86add99436bcbf953a8c0111d4d97c49ba9d18db7c2b52444"
PARENT_SHA256 = "41f938e49dbebd6cdd4580285bed1cff9752b17633eb55a154f01ec34372e8ae"
EXECUTION_KEY = "hcsn-n256-authentic-tailcheck537-parallel-20261122-c6bc-001"
IDENTITY = "hcsn-n256-authentic-tailcheck537-parallel-20261122-c6bc-v1"


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _parts(root, count):
    return b"".join(
        (root / f"ORIGINAL.zip.part{index:03d}").read_bytes()
        for index in range(count)
    )


def _journal(path, event, **fields):
    record = {"event": event, "monotonic_seconds": time.perf_counter(), **fields}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _load_lane(ordinal):
    input_raw = _parts(INPUT_PARTS, INPUT_PART_COUNT)
    detached_raw = DETACHED_ZIP.read_bytes()
    parent_raw = _parts(PARENT_PARTS, PARENT_PART_COUNT)
    if (
        _sha256(input_raw) != INPUT_SHA256
        or _sha256(detached_raw) != DETACHED_SHA256
        or _sha256(parent_raw) != PARENT_SHA256
    ):
        raise SystemExit("authentic input digest mismatch")
    with zipfile.ZipFile(io.BytesIO(input_raw)) as compact_archive, zipfile.ZipFile(
        io.BytesIO(detached_raw)
    ) as detached_archive, zipfile.ZipFile(io.BytesIO(parent_raw)) as parent_archive:
        compact_result = json.loads(compact_archive.read("RESULT.json"))
        detached_result = json.loads(detached_archive.read("RESULT.json"))
        records = compact_result["checkpoints"]
        cursors = detached_result["cursors"]
        if len(records) != 10 or len(cursors) != 10 or not 0 <= ordinal < 10:
            raise SystemExit("authentic lane denominator mismatch")
        record = records[ordinal]
        cursor = cursors[ordinal]
        stem = record["source_file"].replace(".index256.checkpoint.json", "")
        if cursor["file"].replace(".detached.cursor.json", "") != stem:
            raise SystemExit("authentic lane order mismatch")
        compact = compact_archive.read(record["file"])
        if len(compact) != record["compact_bytes"] or _sha256(compact) != record[
            "compact_sha256"
        ]:
            raise SystemExit("authentic compact checkpoint identity mismatch")
        parent_envelope = json.loads(parent_archive.read(cursor["source_file"]))
        parent = parent_envelope["body"]["parent_payload_ascii"].encode("ascii")
    raw256 = decode_compact_checkpoint(compact, INDEX256_SCHEMA, 256)
    if _sha256(raw256) != record["raw_sha256"]:
        raise SystemExit("restored index256 raw digest mismatch")
    return stem, raw256, parent, record


def main():
    if os.environ.get("UNIQUE_EXECUTION_KEY") != EXECUTION_KEY:
        raise SystemExit("execution key mismatch")
    if os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
        raise SystemExit("rerun refused before authentic input read")
    try:
        ordinal = int(os.environ["LANE_ORDINAL"])
    except (KeyError, ValueError) as error:
        raise SystemExit("invalid lane ordinal") from error
    output = OUTPUT_ROOT / f"lane-{ordinal:02d}"
    if output.exists():
        raise SystemExit("lane output already exists")
    output.mkdir(parents=True)
    progress = output / "PROGRESS.jsonl"
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    _journal(progress, "admitted", lane_ordinal=ordinal)
    stem, raw256, parent, source_record = _load_lane(ordinal)
    _journal(progress, "inputs_verified", stem=stem)
    checkpoint256 = parse_index256(raw256, parent)

    def report(index):
        _journal(progress, "extension_progress", included_index=index)

    checkpoint537 = advance_to_index537(checkpoint256, parent, report)
    _journal(progress, "index537_reached")
    tail = first_tail_check(checkpoint537, parent)
    (output / "TAIL.json").write_text(
        json.dumps(tail, indent=2, sort_keys=True) + "\n"
    )
    _journal(
        progress,
        "tail_checked",
        unique_coordinate_count=tail["unique_coordinate_count"],
        coordinate_count=tail["coordinate_count"],
        all_coordinates_unique=tail["all_coordinates_unique"],
    )
    raw537 = encode_raw_index537(checkpoint537)
    first = encode_compact_checkpoint(raw537, SCHEMA, 537)
    second = encode_compact_checkpoint(raw537, SCHEMA, 537)
    if first != second:
        raise SystemExit("index537 compact bytes are not deterministic")
    if decode_compact_checkpoint(first, SCHEMA, 537) != raw537:
        raise SystemExit("index537 compact checkpoint is not byte exact")
    checkpoint_name = f"{stem}.index537.checkpoint.hcsncp"
    (output / checkpoint_name).write_bytes(first)
    usage = resource.getrusage(resource.RUSAGE_SELF)
    result = {
        "identity": IDENTITY,
        "execution_key": EXECUTION_KEY,
        "status": "AUTHENTIC_INDEX537_FIRST_TAIL_CHECK_COMPLETE_HOLD",
        "lane_ordinal": ordinal,
        "stem": stem,
        "lane": checkpoint537.lane,
        "source_index256_compact_sha256": source_record["compact_sha256"],
        "source_index256_raw_sha256": source_record["raw_sha256"],
        "checkpoint_file": checkpoint_name,
        "checkpoint_raw_bytes": len(raw537),
        "checkpoint_raw_sha256": _sha256(raw537),
        "checkpoint_compact_bytes": len(first),
        "checkpoint_compact_sha256": _sha256(first),
        "tail_file": "TAIL.json",
        "tail_sha256": _sha256((output / "TAIL.json").read_bytes()),
        "tail": {
            "coordinate_count": tail["coordinate_count"],
            "unique_coordinate_count": tail["unique_coordinate_count"],
            "all_coordinates_unique": tail["all_coordinates_unique"],
            "rounding_sha256": tail["rounding_sha256"],
        },
        "work": {
            "index256_compact_decodes": 1,
            "recurrence_row_actions": 281,
            "tail_checks": 1,
            "tail_vector_fp64_conversions": tail["tail_vector_fp64_conversions"],
            "rounding_calls": tail["rounding_calls"],
            "index537_compact_encodes": 2,
            "index537_compact_decodes": 1,
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
        },
        "n256_qualified": False,
        "production_adoption": False,
        "all_closed": False,
    }
    (output / "RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    _journal(progress, "lane_complete", stem=stem)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
