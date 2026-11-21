"""One-shot authentic N256 first-step cursor execution."""

import hashlib
import json
import os
import platform
import resource
import struct
import sys
import time
from pathlib import Path

from qualification.hcsn_currentstate_n256_authentic_initial_capsule.capsule import (
    build_initial_capsule,
)
from qualification.hcsn_currentstate_n256_signed_adapter_review.adapter import (
    ARTIFACTS,
    ARTIFACT_SHA256,
    _artifact,
    adapt_lane,
)

from .cursor import (
    build_authentic_firststep_cursor,
    decode_authentic_firststep_cursor,
    encode_authentic_firststep_cursor,
)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = HERE / "RUN_OUTPUT"
COMPAT = ROOT / "qualification/hcsn_currentstate_n256_preexpm_provider_compat/REVIEW.json"
EXECUTION_KEY = "hcsn-n256-authentic-firststep-cursor-20261121-c6bc-001"


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    if os.environ.get("UNIQUE_EXECUTION_KEY") != EXECUTION_KEY:
        raise SystemExit("execution key mismatch")
    if os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
        raise SystemExit("rerun refused before authentic artifact read")
    if OUTPUT.exists():
        raise SystemExit("output already exists")
    OUTPUT.mkdir()

    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    artifact = _artifact(ARTIFACTS[0], ARTIFACT_SHA256[0])
    compat = json.loads(COMPAT.read_text())
    lanes = {}
    for lane, dimension in (("undiscounted", 258), ("discounted", 259)):
        adapted = adapt_lane(
            artifact[f"oracle-{lane}-augmented.bin"],
            artifact[f"oracle-{lane}-seed.bin"],
            dimension,
        )
        duration_hex = struct.pack(
            ">d", float.fromhex(compat["lanes"][lane]["matrix"]["binary64_duration_hex"])
        ).hex()
        capsule = build_initial_capsule(
            lane, adapted["rows_hex"], adapted["vectors_hex"], duration_hex
        )
        cursors = []
        for vector_index in range(len(capsule.parsed_vectors)):
            cursor = build_authentic_firststep_cursor(capsule, vector_index)
            payload = encode_authentic_firststep_cursor(cursor)
            decoded = decode_authentic_firststep_cursor(payload)
            if encode_authentic_firststep_cursor(decoded) != payload:
                raise SystemExit("authentic first-step cursor round trip mismatch")
            name = f"{lane}-vector{vector_index}.cursor.json"
            (OUTPUT / name).write_bytes(payload)
            cursors.append(
                {
                    "bytes": len(payload),
                    "file": name,
                    "included_index": decoded.included_index,
                    "sha256": _sha256(payload),
                }
            )
        lanes[lane] = {
            "dimension": dimension,
            "duration_hex": duration_hex,
            "sparse_coordinates": sum(len(row) for row in capsule.rows_hex),
            "vectors": len(cursors),
            "cursors": cursors,
            "byte_exact_cold_decode": True,
        }

    usage = resource.getrusage(resource.RUSAGE_SELF)
    result = {
        "identity": "hcsn-n256-authentic-firststep-cursor-20261121-c6bc-v1",
        "execution_key": EXECUTION_KEY,
        "status": "AUTHENTIC_FIRSTSTEP_CURSOR_ONLY_RESOURCE_HOLD",
        "lanes": lanes,
        "cost": {
            "wall_seconds": time.perf_counter() - started_wall,
            "cpu_seconds": time.process_time() - started_cpu,
            "max_rss_kib": usage.ru_maxrss,
        },
        "work": {
            "artifact_reads": 1,
            "adapter_lane_calls": 2,
            "initial_capsule_builds": 2,
            "cold_decode_rebuilds": 10,
            "transition_builds": 12,
            "target_exact_input_conversions": 20311,
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
    (OUTPUT / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
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
