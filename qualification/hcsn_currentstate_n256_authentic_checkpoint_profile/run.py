"""One-shot exact resource profile through fixed authentic N256 boundaries."""

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

from .checkpoint import (
    BOUNDARIES,
    advance_checkpoint,
    decode_checkpoint,
    encode_checkpoint,
    start_from_index_two,
)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DETACHED_ZIP = ROOT / "qualification/hcsn_ci_readbacks/6934/ORIGINAL.zip"
PARENT_PARTS = ROOT / "qualification/hcsn_ci_readbacks/6931"
OUTPUT = HERE / "RUN_OUTPUT"
EXECUTION_KEY = "hcsn-n256-authentic-checkpoint-profile-20261121-c6bc-001"
DETACHED_SHA256 = "5d745460761940b86add99436bcbf953a8c0111d4d97c49ba9d18db7c2b52444"
PARENT_SHA256 = "41f938e49dbebd6cdd4580285bed1cff9752b17633eb55a154f01ec34372e8ae"
MAX_OUTPUT_BYTES = 67_108_864
PARTS = ("ORIGINAL.zip.part000", "ORIGINAL.zip.part001", "ORIGINAL.zip.part002")


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    if os.environ.get("UNIQUE_EXECUTION_KEY") != EXECUTION_KEY:
        raise SystemExit("execution key mismatch")
    if os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
        raise SystemExit("rerun refused before authentic input read")
    if OUTPUT.exists():
        raise SystemExit("output already exists")
    detached_raw = DETACHED_ZIP.read_bytes()
    parent_raw = b"".join((PARENT_PARTS / name).read_bytes() for name in PARTS)
    if (
        _sha256(detached_raw) != DETACHED_SHA256
        or _sha256(parent_raw) != PARENT_SHA256
    ):
        raise SystemExit("authentic input digest mismatch")
    OUTPUT.mkdir()

    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    rows = []
    output_bytes = 0
    with (
        zipfile.ZipFile(io.BytesIO(detached_raw)) as detached_archive,
        zipfile.ZipFile(io.BytesIO(parent_raw)) as parent_archive,
    ):
        result = json.loads(detached_archive.read("RESULT.json"))
        if len(result["cursors"]) != 10:
            raise SystemExit("expected exactly ten authentic detached cursors")
        for item in result["cursors"]:
            source = detached_archive.read(item["file"])
            second = parent_archive.read(item["source_file"])
            second_body = json.loads(second)["body"]
            parent = second_body["parent_payload_ascii"].encode("ascii")
            if _sha256(parent) != item["parent_sha256"]:
                raise SystemExit("detached-to-parent binding mismatch")
            current = start_from_index_two(source, parent)
            for boundary in BOUNDARIES:
                started_boundary = time.perf_counter()
                current = advance_checkpoint(current, parent, boundary)
                payload = encode_checkpoint(current)
                cold = decode_checkpoint(payload, source, parent)
                if encode_checkpoint(cold) != payload:
                    raise SystemExit("warm/cold checkpoint bytes differ")
                output_name = item["file"].replace(
                    ".detached.cursor.json", f".index{boundary}.checkpoint.json"
                )
                (OUTPUT / output_name).write_bytes(payload)
                output_bytes += len(payload)
                if output_bytes > MAX_OUTPUT_BYTES:
                    raise SystemExit("checkpoint output byte cap exceeded")
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
        "identity": "hcsn-n256-authentic-checkpoint-profile-20261121-c6bc-v1",
        "execution_key": EXECUTION_KEY,
        "status": "AUTHENTIC_INDEX32_RESOURCE_PROFILE_ONLY_HOLD",
        "inputs": {
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
            "index_two_relation_recomputations": 50,
            "warm_row_actions": 300,
            "cold_validation_row_actions": 520,
            "total_row_actions": 870,
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
    (OUTPUT / "HOST.json").write_text(json.dumps(host, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
