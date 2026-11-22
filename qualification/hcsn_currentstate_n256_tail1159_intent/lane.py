"""Execute one admitted authentic index537-to-1159 lane."""

import hashlib
import io
import json
import os
from pathlib import Path
import resource
import time
import zipfile

from qualification.hcsn_currentstate_n256_authentic_compact_checkpoint.compact import (
    decode_compact_checkpoint,
    encode_compact_checkpoint,
)
from qualification.hcsn_currentstate_n256_authentic_tailcheck537_hexfix.lane import (
    DETACHED_SHA256,
    DETACHED_ZIP,
    PARENT_PART_COUNT,
    PARENT_PARTS,
    PARENT_SHA256,
    _parts,
)
from qualification.hcsn_currentstate_n256_index1159_resource_projection.audit import (
    _restore_537_collector,
)

from .admission import admit_runtime
from .continuation import (
    SOURCE_SCHEMA,
    TARGET_INDEX,
    TARGET_SCHEMA,
    advance_to_index1159,
    encode_raw_index1159,
    final_tail_check,
    parse_index537,
)


IDENTITY = "hcsn-n256-authentic-tail1159-process-cost-ledger-20261122-c6bc-v8"


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _journal(path, event, **fields):
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {"event": event, "monotonic_seconds": time.perf_counter(), **fields},
                sort_keys=True,
            )
            + "\n"
        )
        stream.flush()
        os.fsync(stream.fileno())


def _load_lane(ordinal):
    collector = _restore_537_collector()
    detached = DETACHED_ZIP.read_bytes()
    parent_archive_raw = _parts(PARENT_PARTS, PARENT_PART_COUNT)
    if _sha256(detached) != DETACHED_SHA256 or _sha256(parent_archive_raw) != PARENT_SHA256:
        raise SystemExit("parent original digest mismatch")
    with zipfile.ZipFile(io.BytesIO(collector)) as combined, zipfile.ZipFile(
        io.BytesIO(detached)
    ) as detached_archive, zipfile.ZipFile(io.BytesIO(parent_archive_raw)) as parents:
        result = json.loads(combined.read(f"lane-{ordinal:02d}.RESULT.json"))
        stem = result["stem"]
        checkpoint_raw = combined.read(result["checkpoint_file"])
        detached_result = json.loads(detached_archive.read("RESULT.json"))
        matches = [
            item
            for item in detached_result["cursors"]
            if item["file"].replace(".detached.cursor.json", "") == stem
        ]
        if len(matches) != 1:
            raise SystemExit("parent cursor mapping differs")
        parent_envelope = json.loads(parents.read(matches[0]["source_file"]))
        parent_payload = parent_envelope["body"]["parent_payload_ascii"].encode()
    if (
        result["lane_ordinal"] != ordinal
        or result["checkpoint_compact_sha256"] != _sha256(checkpoint_raw)
        or result["tail"]["all_coordinates_unique"]
    ):
        raise SystemExit("index537 lane identity or negative result differs")
    raw537 = decode_compact_checkpoint(checkpoint_raw, SOURCE_SCHEMA, 537)
    return result, raw537, parent_payload


def main():
    request = admit_runtime()
    try:
        ordinal = int(os.environ["HCSN_LANE_ORDINAL"])
    except (KeyError, ValueError) as error:
        raise SystemExit("lane ordinal is invalid") from error
    if not 0 <= ordinal < request["lane_count"]:
        raise SystemExit("lane ordinal is outside the frozen denominator")
    root = Path(os.environ["HCSN_OUTPUT_ROOT"])
    output = root / f"lane-{ordinal:02d}"
    if output.exists():
        raise SystemExit("lane output already exists")
    output.mkdir(parents=True)
    progress = output / "PROGRESS.jsonl"
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    _journal(progress, "admitted", lane_ordinal=ordinal)
    source_result, raw537, parent = _load_lane(ordinal)
    _journal(progress, "inputs_verified", stem=source_result["stem"])
    checkpoint537 = parse_index537(raw537, parent)

    def report(index):
        _journal(progress, "extension_progress", included_index=index)

    checkpoint1159 = advance_to_index1159(checkpoint537, parent, report)
    tail = final_tail_check(checkpoint1159, parent)
    tail_path = output / "TAIL.json"
    tail_path.write_text(json.dumps(tail, indent=2, sort_keys=True) + "\n")
    raw1159 = encode_raw_index1159(checkpoint1159)
    compact = encode_compact_checkpoint(raw1159, TARGET_SCHEMA, TARGET_INDEX)
    if decode_compact_checkpoint(compact, TARGET_SCHEMA, TARGET_INDEX) != raw1159:
        raise SystemExit("index1159 compact checkpoint is not byte exact")
    checkpoint_name = f"{source_result['stem']}.index1159.checkpoint.hcsncp"
    (output / checkpoint_name).write_bytes(compact)
    usage = resource.getrusage(resource.RUSAGE_SELF)
    result = {
        "identity": IDENTITY,
        "execution_key": request["execution_key"],
        "lane_ordinal": ordinal,
        "stem": source_result["stem"],
        "checkpoint_file": checkpoint_name,
        "checkpoint_raw_bytes": len(raw1159),
        "checkpoint_raw_sha256": _sha256(raw1159),
        "checkpoint_compact_bytes": len(compact),
        "checkpoint_compact_sha256": _sha256(compact),
        "tail_file": tail_path.name,
        "tail_sha256": _sha256(tail_path.read_bytes()),
        "tail": {
            "coordinate_count": tail["coordinate_count"],
            "unique_coordinate_count": tail["unique_coordinate_count"],
            "all_coordinates_unique": tail["all_coordinates_unique"],
            "rounding_sha256": tail["rounding_sha256"],
        },
        "work": {
            "index537_compact_decodes": 1,
            "recurrence_row_actions": 622,
            "tail_checks": 1,
            "rounding_calls": tail["rounding_calls"],
            "index1159_compact_encodes": 1,
            "index1159_compact_decodes": 1,
        },
        "cost": {
            "wall_seconds": time.perf_counter() - started_wall,
            "cpu_seconds": time.process_time() - started_cpu,
            "max_rss_kib": usage.ru_maxrss,
        },
    }
    (output / "RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    _journal(progress, "lane_complete", stem=result["stem"])
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
