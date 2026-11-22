"""One-shot cold-resume of ten archived authentic first-step cursors."""

import hashlib
import json
import os
import platform
import resource
import sys
import time
from pathlib import Path
import zipfile

from .cursor import (
    build_authentic_secondstep_cursor,
    decode_authentic_secondstep_cursor,
    encode_authentic_secondstep_cursor,
)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
INPUT = ROOT / "qualification/hcsn_ci_readbacks/6927/ORIGINAL.zip"
OUTPUT = HERE / "RUN_OUTPUT"
INPUT_SHA256 = "c82b34925f80ceb724bc9bf45d2097f07bc4a2a1b05ee0cb374421984082dc61"
EXECUTION_KEY = "hcsn-n256-authentic-secondstep-cursor-20261121-c6bc-001"


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    if os.environ.get("UNIQUE_EXECUTION_KEY") != EXECUTION_KEY:
        raise SystemExit("execution key mismatch")
    if os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
        raise SystemExit("rerun refused before archived cursor read")
    if OUTPUT.exists():
        raise SystemExit("output already exists")
    raw_zip = INPUT.read_bytes()
    if _sha256(raw_zip) != INPUT_SHA256:
        raise SystemExit("archived first-step ZIP digest mismatch")
    OUTPUT.mkdir()

    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    rows = []
    with zipfile.ZipFile(INPUT) as archive:
        names = sorted(
            name for name in archive.namelist() if name.endswith(".cursor.json")
        )
        if len(names) != 10:
            raise SystemExit("expected exactly ten archived first-step cursors")
        for name in names:
            parent_payload = archive.read(name)
            cursor = build_authentic_secondstep_cursor(parent_payload)
            payload = encode_authentic_secondstep_cursor(cursor)
            decoded = decode_authentic_secondstep_cursor(payload)
            if encode_authentic_secondstep_cursor(decoded) != payload:
                raise SystemExit("authentic second-step cursor round trip mismatch")
            output_name = name.replace(".cursor.json", ".secondstep.cursor.json")
            (OUTPUT / output_name).write_bytes(payload)
            rows.append(
                {
                    "bytes": len(payload),
                    "file": output_name,
                    "included_index": decoded.included_index,
                    "lane": decoded.lane,
                    "parent_file": name,
                    "parent_sha256": _sha256(parent_payload),
                    "sha256": _sha256(payload),
                }
            )

    usage = resource.getrusage(resource.RUSAGE_SELF)
    result = {
        "identity": "hcsn-n256-authentic-secondstep-cursor-20261121-c6bc-v1",
        "execution_key": EXECUTION_KEY,
        "status": "AUTHENTIC_SECONDSTEP_CURSOR_ONLY_RESOURCE_HOLD",
        "input_zip_sha256": INPUT_SHA256,
        "cursors": rows,
        "cost": {
            "wall_seconds": time.perf_counter() - started_wall,
            "cpu_seconds": time.process_time() - started_cpu,
            "max_rss_kib": usage.ru_maxrss,
        },
        "work": {
            "archived_zip_reads": 1,
            "parent_cursor_reads": 10,
            "parent_cold_decodes": 20,
            "secondstep_cold_decodes": 10,
            "tail_checks": 10,
            "recurrence_row_actions": 10,
            "provider_outputs": 0,
            "dynamic_steps": 0,
            "exponential_actions": 0,
            "torch_calls": 0,
            "optimizer_steps": 0,
        },
        "scope": {
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
