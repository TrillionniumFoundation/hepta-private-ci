"""One-shot exact N256 resource profile from index 128 to index 256."""

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

from .profile256 import (
    advance_to_index256,
    decode_index256,
    encode_index256,
    start_from_index128,
)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROFILE128_PARTS = ROOT / "qualification/hcsn_ci_readbacks/6940"
PROFILE32_PARTS = ROOT / "qualification/hcsn_ci_readbacks/6936"
DETACHED_ZIP = ROOT / "qualification/hcsn_ci_readbacks/6934/ORIGINAL.zip"
PARENT_PARTS = ROOT / "qualification/hcsn_ci_readbacks/6931"
OUTPUT = HERE / "RUN_OUTPUT"
EXECUTION_KEY = "hcsn-n256-authentic-checkpoint-profile256-20261122-c6bc-001"
PROFILE128_SHA256 = "2ecc44ac2d769105908e1b44b5bfabb99713c791b45c237da48913847af9de41"
PROFILE32_SHA256 = "e1775ee832acc431282bcca9b7b5f0e21b38ac5a0f3ac46c2228f787c0e8a0a8"
DETACHED_SHA256 = "5d745460761940b86add99436bcbf953a8c0111d4d97c49ba9d18db7c2b52444"
PARENT_SHA256 = "41f938e49dbebd6cdd4580285bed1cff9752b17633eb55a154f01ec34372e8ae"
PROFILE128_PART_COUNT = 28
PROFILE32_PART_COUNT = 31
PARENT_PART_NAMES = (
    "ORIGINAL.zip.part000",
    "ORIGINAL.zip.part001",
    "ORIGINAL.zip.part002",
)
MAX_OUTPUT_BYTES = 67_108_864


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _parts_raw(root, count):
    return b"".join(
        (root / f"ORIGINAL.zip.part{index:03d}").read_bytes()
        for index in range(count)
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
    profile128_raw = _parts_raw(PROFILE128_PARTS, PROFILE128_PART_COUNT)
    profile32_raw = _parts_raw(PROFILE32_PARTS, PROFILE32_PART_COUNT)
    detached_raw = DETACHED_ZIP.read_bytes()
    parent_raw = _parent_raw()
    if (
        _sha256(profile128_raw) != PROFILE128_SHA256
        or _sha256(profile32_raw) != PROFILE32_SHA256
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
        zipfile.ZipFile(io.BytesIO(profile128_raw)) as profile128_archive,
        zipfile.ZipFile(io.BytesIO(profile32_raw)) as profile32_archive,
        zipfile.ZipFile(io.BytesIO(detached_raw)) as detached_archive,
        zipfile.ZipFile(io.BytesIO(parent_raw)) as parent_archive,
    ):
        profile128_result = json.loads(profile128_archive.read("RESULT.json"))
        profile32_result = json.loads(profile32_archive.read("RESULT.json"))
        detached_result = json.loads(detached_archive.read("RESULT.json"))
        index128 = {
            item["file"].replace(".index128.checkpoint.json", ""): item
            for item in profile128_result["checkpoints"]
            if item["boundary"] == 128
        }
        index32 = {
            item["file"].replace(".index32.checkpoint.json", ""): item
            for item in profile32_result["checkpoints"]
            if item["boundary"] == 32
        }
        if (
            len(index128) != 10
            or len(index32) != 10
            or len(detached_result["cursors"]) != 10
        ):
            raise SystemExit("expected exactly ten authentic lanes")
        for item in detached_result["cursors"]:
            stem = item["file"].replace(".detached.cursor.json", "")
            item128 = index128.get(stem)
            item32 = index32.get(stem)
            if item128 is None or item32 is None:
                raise SystemExit("checkpoint lane roster mismatch")
            source = detached_archive.read(item["file"])
            second = parent_archive.read(item["source_file"])
            parent = json.loads(second)["body"]["parent_payload_ascii"].encode(
                "ascii"
            )
            checkpoint32 = profile32_archive.read(item32["file"])
            checkpoint128 = profile128_archive.read(item128["file"])
            if (
                _sha256(parent) != item["parent_sha256"]
                or _sha256(checkpoint32) != item32["sha256"]
                or _sha256(checkpoint128) != item128["sha256"]
            ):
                raise SystemExit("authentic lane binding mismatch")
            started_lane = time.perf_counter()
            current = start_from_index128(
                checkpoint128, checkpoint32, source, parent
            )
            current = advance_to_index256(current, parent)
            payload = encode_index256(current)
            cold = decode_index256(
                payload, checkpoint128, checkpoint32, source, parent
            )
            if encode_index256(cold) != payload:
                raise SystemExit("warm/cold index-256 bytes differ")
            if output_bytes + len(payload) > MAX_OUTPUT_BYTES:
                raise SystemExit("index-256 checkpoint output byte cap exceeded")
            output_name = f"{stem}.index256.checkpoint.json"
            (OUTPUT / output_name).write_bytes(payload)
            output_bytes += len(payload)
            rows.append(
                {
                    "boundary": 256,
                    "bytes": len(payload),
                    "file": output_name,
                    "lane": current.lane,
                    "sha256": _sha256(payload),
                    "wall_seconds": time.perf_counter() - started_lane,
                }
            )

    usage = resource.getrusage(resource.RUSAGE_SELF)
    result = {
        "identity": "hcsn-n256-authentic-checkpoint-profile256-20261122-c6bc-v1",
        "execution_key": EXECUTION_KEY,
        "status": "AUTHENTIC_INDEX256_RESOURCE_PROFILE_ONLY_HOLD",
        "inputs": {
            "profile128_zip_sha256": PROFILE128_SHA256,
            "profile32_zip_sha256": PROFILE32_SHA256,
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
            "index_two_relation_recomputations": 20,
            "index32_source_replay_row_actions": 600,
            "index128_source_replay_row_actions": 1920,
            "warm_extension_row_actions": 1280,
            "cold_extension_row_actions": 1280,
            "total_row_actions": 5080,
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
            "predecessor_6939": "RED_DECIMAL_INTEGER_DIGIT_LIMIT",
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
