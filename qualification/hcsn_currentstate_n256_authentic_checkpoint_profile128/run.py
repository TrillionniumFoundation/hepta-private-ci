"""One-shot exact N256 profile from authentic index 32 to 64 and 128."""

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

from .extended import (
    advance_extended_checkpoint,
    decode_extended_checkpoint,
    encode_extended_checkpoint,
    start_from_index32,
)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROFILE_PARTS = ROOT / "qualification/hcsn_ci_readbacks/6936"
DETACHED_ZIP = ROOT / "qualification/hcsn_ci_readbacks/6934/ORIGINAL.zip"
PARENT_PARTS = ROOT / "qualification/hcsn_ci_readbacks/6931"
OUTPUT = HERE / "RUN_OUTPUT"
EXECUTION_KEY = "hcsn-n256-authentic-checkpoint-hex-20261122-c6bc-001"
PROFILE_SHA256 = "e1775ee832acc431282bcca9b7b5f0e21b38ac5a0f3ac46c2228f787c0e8a0a8"
DETACHED_SHA256 = "5d745460761940b86add99436bcbf953a8c0111d4d97c49ba9d18db7c2b52444"
PARENT_SHA256 = "41f938e49dbebd6cdd4580285bed1cff9752b17633eb55a154f01ec34372e8ae"
PROFILE_PART_COUNT = 31
PARENT_PART_NAMES = (
    "ORIGINAL.zip.part000",
    "ORIGINAL.zip.part001",
    "ORIGINAL.zip.part002",
)
BOUNDARIES = (64, 128)
MAX_OUTPUT_BYTES = 67_108_864


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _profile_raw():
    return b"".join(
        (PROFILE_PARTS / f"ORIGINAL.zip.part{index:03d}").read_bytes()
        for index in range(PROFILE_PART_COUNT)
    )


def _parent_raw():
    return b"".join(
        (PARENT_PARTS / name).read_bytes() for name in PARENT_PART_NAMES
    )


def main():
    if os.environ.get("UNIQUE_EXECUTION_KEY") != EXECUTION_KEY:
        raise SystemExit("execution key mismatch")
    if os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
        raise SystemExit("rerun refused before authentic input read")
    if OUTPUT.exists():
        raise SystemExit("output already exists")
    profile_raw = _profile_raw()
    detached_raw = DETACHED_ZIP.read_bytes()
    parent_raw = _parent_raw()
    if (
        _sha256(profile_raw) != PROFILE_SHA256
        or _sha256(detached_raw) != DETACHED_SHA256
        or _sha256(parent_raw) != PARENT_SHA256
    ):
        raise SystemExit("authentic input digest mismatch")
    OUTPUT.mkdir()

    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    rows = []
    output_bytes = 0
    with (
        zipfile.ZipFile(io.BytesIO(profile_raw)) as profile_archive,
        zipfile.ZipFile(io.BytesIO(detached_raw)) as detached_archive,
        zipfile.ZipFile(io.BytesIO(parent_raw)) as parent_archive,
    ):
        profile_result = json.loads(profile_archive.read("RESULT.json"))
        index32 = {
            item["file"].replace(".index32.checkpoint.json", ""): item
            for item in profile_result["checkpoints"]
            if item["boundary"] == 32
        }
        detached_result = json.loads(detached_archive.read("RESULT.json"))
        if len(index32) != 10 or len(detached_result["cursors"]) != 10:
            raise SystemExit("expected exactly ten authentic index-32 lanes")
        for item in detached_result["cursors"]:
            stem = item["file"].replace(".detached.cursor.json", "")
            source_item = index32.get(stem)
            if source_item is None:
                raise SystemExit("index-32 lane roster mismatch")
            source = detached_archive.read(item["file"])
            second = parent_archive.read(item["source_file"])
            second_body = json.loads(second)["body"]
            parent = second_body["parent_payload_ascii"].encode("ascii")
            source_checkpoint = profile_archive.read(source_item["file"])
            if (
                _sha256(parent) != item["parent_sha256"]
                or _sha256(source_checkpoint) != source_item["sha256"]
            ):
                raise SystemExit("authentic lane binding mismatch")
            current = start_from_index32(source_checkpoint, source, parent)
            for boundary in BOUNDARIES:
                started_boundary = time.perf_counter()
                current = advance_extended_checkpoint(current, parent, boundary)
                payload = encode_extended_checkpoint(current)
                cold = decode_extended_checkpoint(
                    payload, source_checkpoint, source, parent
                )
                if encode_extended_checkpoint(cold) != payload:
                    raise SystemExit("warm/cold extended checkpoint bytes differ")
                output_name = f"{stem}.index{boundary}.checkpoint.json"
                (OUTPUT / output_name).write_bytes(payload)
                output_bytes += len(payload)
                if output_bytes > MAX_OUTPUT_BYTES:
                    raise SystemExit("extended checkpoint output byte cap exceeded")
                rows.append(
                    {
                        "boundary": boundary,
                        "bytes": len(payload),
                        "file": output_name,
                        "lane": current.lane,
                        "sha256": _sha256(payload),
                        "wall_seconds": time.perf_counter() - started_boundary,
                    }
                )

    usage = resource.getrusage(resource.RUSAGE_SELF)
    result = {
        "identity": "hcsn-n256-authentic-checkpoint-hex-20261122-c6bc-v2",
        "execution_key": EXECUTION_KEY,
        "status": "AUTHENTIC_INDEX128_RESOURCE_PROFILE_ONLY_HOLD",
        "inputs": {
            "profile_zip_sha256": PROFILE_SHA256,
            "detached_zip_sha256": DETACHED_SHA256,
            "parent_zip_sha256": PARENT_SHA256,
        },
        "checkpoints": rows,
        "cost": {
            "wall_seconds": time.perf_counter() - started_wall,
            "cpu_seconds": time.process_time() - started_cpu,
            "max_rss_kib": usage.ru_maxrss,
            "cursor_output_bytes": output_bytes,
        },
        "work": {
            "index_two_relation_recomputations": 30,
            "index32_source_replay_row_actions": 900,
            "warm_extension_row_actions": 960,
            "cold_extension_row_actions": 1280,
            "total_row_actions": 3140,
            "tail_checks": 0,
            "provider_outputs": 0,
            "dynamic_steps": 0,
            "exponential_actions": 0,
            "torch_calls": 0,
            "optimizer_steps": 0,
        },
        "scope": {
            "resource_gate_closed": False,
            "provider_completion": False,
            "unique_rounding_closed": False,
            "arbitrary_history_resume": False,
            "n256_qualified": False,
            "production_adoption": False,
            "all_closed": False,
            "cause_of_6901_red": "UNKNOWN",
            "c2_full_replay_completed_fits": 0,
            "hpca_status": "NoUpdate",
        },
    }
    (OUTPUT / "RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    host = {
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "github_sha": os.environ.get("GITHUB_SHA"),
        "platform": platform.platform(),
        "python": sys.version,
    }
    (OUTPUT / "HOST.json").write_text(
        json.dumps(host, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
