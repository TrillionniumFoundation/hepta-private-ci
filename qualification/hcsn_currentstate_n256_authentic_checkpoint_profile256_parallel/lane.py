"""Execute one frozen authentic lane and persist interruption-visible progress."""

import hashlib
import io
import json
import os
import platform
import resource
import sys
import time
from dataclasses import replace
from pathlib import Path
import zipfile

from qualification.hcsn_currentstate_n256_authentic_checkpoint_profile256.profile256 import (
    encode_index256,
    start_from_index128,
)
from qualification.hcsn_currentstate_n256_authentic_firststep_cursor.cursor import (
    decode_authentic_firststep_cursor,
)
from qualification.hcsn_currentstate_n256_non_substochastic_signed_interval.signed_interval import (
    _row_action,
)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROFILE128_PARTS = ROOT / "qualification/hcsn_ci_readbacks/6940"
PROFILE32_PARTS = ROOT / "qualification/hcsn_ci_readbacks/6936"
DETACHED_ZIP = ROOT / "qualification/hcsn_ci_readbacks/6934/ORIGINAL.zip"
PARENT_PARTS = ROOT / "qualification/hcsn_ci_readbacks/6931"
OUTPUT_ROOT = HERE / "RUN_OUTPUT"
EXECUTION_KEY = "hcsn-n256-authentic-checkpoint-profile256-parallel-20261122-c6bc-001"
IDENTITY = "hcsn-n256-authentic-checkpoint-profile256-parallel-20261122-c6bc-v1"
PROFILE128_SHA256 = "2ecc44ac2d769105908e1b44b5bfabb99713c791b45c237da48913847af9de41"
PROFILE32_SHA256 = "e1775ee832acc431282bcca9b7b5f0e21b38ac5a0f3ac46c2228f787c0e8a0a8"
DETACHED_SHA256 = "5d745460761940b86add99436bcbf953a8c0111d4d97c49ba9d18db7c2b52444"
PARENT_SHA256 = "41f938e49dbebd6cdd4580285bed1cff9752b17633eb55a154f01ec34372e8ae"
MAX_CURSOR_BYTES = 8_388_608


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _parts_raw(root, count):
    return b"".join(
        (root / f"ORIGINAL.zip.part{index:03d}").read_bytes()
        for index in range(count)
    )


def _progress(path, event, **fields):
    record = {"event": event, "monotonic_seconds": time.perf_counter(), **fields}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _advance(checkpoint, parent_payload, progress_path, phase):
    parent = decode_authentic_firststep_cursor(parent_payload)
    argument = parent.rate * parent.duration
    tail_argument = argument * parent.transition_l1_norm
    current = checkpoint
    for next_index in range(129, 257):
        coefficient = current.coefficient * argument / next_index
        growth = current.growth_coefficient * tail_argument / next_index
        iterate = _row_action(current.iterate, parent.transition)
        current = replace(
            current,
            included_index=next_index,
            iterate=iterate,
            coefficient=coefficient,
            growth_coefficient=growth,
            exponential_sum=current.exponential_sum + coefficient,
            partial=tuple(
                left + coefficient * right
                for left, right in zip(current.partial, iterate, strict=True)
            ),
        )
        if next_index % 8 == 0:
            _progress(progress_path, "extension_progress", phase=phase, index=next_index)
    return current


def _load_lane(ordinal):
    profile128_raw = _parts_raw(PROFILE128_PARTS, 28)
    profile32_raw = _parts_raw(PROFILE32_PARTS, 31)
    detached_raw = DETACHED_ZIP.read_bytes()
    parent_raw = _parts_raw(PARENT_PARTS, 3)
    observed = (
        _sha256(profile128_raw),
        _sha256(profile32_raw),
        _sha256(detached_raw),
        _sha256(parent_raw),
    )
    expected = (
        PROFILE128_SHA256,
        PROFILE32_SHA256,
        DETACHED_SHA256,
        PARENT_SHA256,
    )
    if observed != expected:
        raise SystemExit("authentic input digest mismatch")
    archives = (
        zipfile.ZipFile(io.BytesIO(profile128_raw)),
        zipfile.ZipFile(io.BytesIO(profile32_raw)),
        zipfile.ZipFile(io.BytesIO(detached_raw)),
        zipfile.ZipFile(io.BytesIO(parent_raw)),
    )
    profile128, profile32, detached, parent_archive = archives
    result128 = json.loads(profile128.read("RESULT.json"))
    result32 = json.loads(profile32.read("RESULT.json"))
    detached_result = json.loads(detached.read("RESULT.json"))
    items128 = {
        item["file"].replace(".index128.checkpoint.json", ""): item
        for item in result128["checkpoints"]
        if item["boundary"] == 128
    }
    items32 = {
        item["file"].replace(".index32.checkpoint.json", ""): item
        for item in result32["checkpoints"]
        if item["boundary"] == 32
    }
    cursors = detached_result["cursors"]
    if len(cursors) != 10 or not 0 <= ordinal < 10:
        raise SystemExit("invalid authentic lane ordinal")
    item = cursors[ordinal]
    stem = item["file"].replace(".detached.cursor.json", "")
    item128 = items128[stem]
    item32 = items32[stem]
    source = detached.read(item["file"])
    second = parent_archive.read(item["source_file"])
    parent = json.loads(second)["body"]["parent_payload_ascii"].encode("ascii")
    checkpoint32 = profile32.read(item32["file"])
    checkpoint128 = profile128.read(item128["file"])
    for archive in archives:
        archive.close()
    return stem, source, parent, checkpoint32, checkpoint128


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
        raise SystemExit("output already exists")
    output.mkdir(parents=True)
    progress = output / "PROGRESS.jsonl"
    _progress(progress, "admitted", lane_ordinal=ordinal)
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    stem, source, parent, checkpoint32, checkpoint128 = _load_lane(ordinal)
    _progress(progress, "inputs_verified", stem=stem)
    warm128 = start_from_index128(checkpoint128, checkpoint32, source, parent)
    _progress(progress, "warm_index128_verified")
    warm256 = _advance(warm128, parent, progress, "warm")
    payload = encode_index256(warm256)
    _progress(progress, "warm_index256_encoded", bytes=len(payload), sha256=_sha256(payload))
    cold128 = start_from_index128(checkpoint128, checkpoint32, source, parent)
    _progress(progress, "cold_index128_verified")
    cold256 = _advance(cold128, parent, progress, "cold")
    if encode_index256(cold256) != payload:
        raise SystemExit("warm/cold index-256 bytes differ")
    output_name = f"{stem}.index256.checkpoint.json"
    (output / output_name).write_bytes(payload)
    usage = resource.getrusage(resource.RUSAGE_SELF)
    result = {
        "identity": IDENTITY,
        "execution_key": EXECUTION_KEY,
        "status": "AUTHENTIC_INDEX256_LANE_RESOURCE_PROFILE_ONLY_HOLD",
        "lane_ordinal": ordinal,
        "lane": warm256.lane,
        "file": output_name,
        "bytes": len(payload),
        "sha256": _sha256(payload),
        "cost": {
            "wall_seconds": time.perf_counter() - started_wall,
            "cpu_seconds": time.process_time() - started_cpu,
            "max_rss_kib": usage.ru_maxrss,
        },
        "work": {
            "index_two_relation_recomputations": 2,
            "index32_source_replay_row_actions": 60,
            "index128_source_replay_row_actions": 192,
            "warm_extension_row_actions": 128,
            "cold_extension_row_actions": 128,
            "total_row_actions": 508,
            "tail_checks": 0,
            "provider_outputs": 0,
            "dynamic_steps": 0,
            "exponential_actions": 0,
            "torch_calls": 0,
            "optimizer_steps": 0,
        },
        "host": {
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "github_sha": os.environ.get("GITHUB_SHA"),
            "platform": platform.platform(),
            "python": sys.version,
        },
    }
    (output / "RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    _progress(progress, "lane_complete", stem=stem)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
