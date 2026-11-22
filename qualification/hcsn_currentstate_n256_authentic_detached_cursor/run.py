"""One-shot authentic detached-parent validation from immutable #6931 bytes."""

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

from .cursor import (
    decode_authentic_detached_cursor,
    detach_authentic_secondstep_cursor,
    encode_authentic_detached_cursor,
)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
READBACK = ROOT / "qualification/hcsn_ci_readbacks/6931"
OUTPUT = HERE / "RUN_OUTPUT"
EXECUTION_KEY = "hcsn-n256-authentic-detached-cursor-20261121-c6bc-001"
ZIP_SHA256 = "41f938e49dbebd6cdd4580285bed1cff9752b17633eb55a154f01ec34372e8ae"
PARTS = (
    "ORIGINAL.zip.part000",
    "ORIGINAL.zip.part001",
    "ORIGINAL.zip.part002",
)


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    if os.environ.get("UNIQUE_EXECUTION_KEY") != EXECUTION_KEY:
        raise SystemExit("execution key mismatch")
    if os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
        raise SystemExit("rerun refused before original ZIP part read")
    if OUTPUT.exists():
        raise SystemExit("output already exists")
    raw_zip = b"".join((READBACK / name).read_bytes() for name in PARTS)
    if _sha256(raw_zip) != ZIP_SHA256:
        raise SystemExit("reconstructed #6931 ZIP digest mismatch")
    OUTPUT.mkdir()

    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    rows = []
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as archive:
        names = sorted(
            name for name in archive.namelist() if name.endswith(".cursor.json")
        )
        if len(names) != 10:
            raise SystemExit("expected exactly ten second-step cursors")
        for name in names:
            source_payload = archive.read(name)
            detached = detach_authentic_secondstep_cursor(source_payload)
            source_body = json.loads(source_payload)["body"]
            parent_payload = source_body["parent_payload_ascii"].encode("ascii")
            payload = encode_authentic_detached_cursor(detached)
            decoded = decode_authentic_detached_cursor(payload, parent_payload)
            if encode_authentic_detached_cursor(decoded) != payload:
                raise SystemExit("detached cursor round trip mismatch")
            if len(payload) >= len(source_payload):
                raise SystemExit("detached cursor did not reduce payload bytes")
            output_name = name.replace(
                ".secondstep.cursor.json", ".detached.cursor.json"
            )
            (OUTPUT / output_name).write_bytes(payload)
            rows.append(
                {
                    "bytes": len(payload),
                    "bytes_saved": len(source_payload) - len(payload),
                    "file": output_name,
                    "included_index": decoded.included_index,
                    "lane": decoded.lane,
                    "parent_sha256": _sha256(parent_payload),
                    "sha256": _sha256(payload),
                    "source_bytes": len(source_payload),
                    "source_file": name,
                    "source_sha256": _sha256(source_payload),
                }
            )

    usage = resource.getrusage(resource.RUSAGE_SELF)
    result = {
        "identity": "hcsn-n256-authentic-detached-cursor-20261121-c6bc-v1",
        "execution_key": EXECUTION_KEY,
        "status": "AUTHENTIC_INDEX_TWO_RELATION_VALIDATED_RESOURCE_HOLD",
        "input_zip_sha256": ZIP_SHA256,
        "cursors": rows,
        "cost": {
            "wall_seconds": time.perf_counter() - started_wall,
            "cpu_seconds": time.process_time() - started_cpu,
            "max_rss_kib": usage.ru_maxrss,
        },
        "work": {
            "original_zip_part_reads": 3,
            "secondstep_cursor_reads": 10,
            "secondstep_cold_decodes": 10,
            "parent_cold_decodes": 30,
            "row_action_relation_recomputations": 20,
            "recurrence_advancement_row_actions": 0,
            "tail_checks": 0,
            "provider_outputs": 0,
            "dynamic_steps": 0,
            "exponential_actions": 0,
            "torch_calls": 0,
            "optimizer_steps": 0,
        },
        "scope": {
            "arbitrary_history_resume": False,
            "resource_gate_closed": False,
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
