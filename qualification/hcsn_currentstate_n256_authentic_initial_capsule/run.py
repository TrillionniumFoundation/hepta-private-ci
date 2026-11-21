"""One-shot authentic-input capsule readback with zero recurrence work."""

import hashlib
import json
import os
import platform
import resource
import struct
import sys
import time
from pathlib import Path

from qualification.hcsn_currentstate_n256_signed_adapter_review.adapter import (
    ARTIFACTS,
    ARTIFACT_SHA256,
    _artifact,
    adapt_lane,
)

from .capsule import build_initial_capsule, decode_initial_capsule, encode_initial_capsule


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = HERE / "RUN_OUTPUT"
COMPAT = ROOT / "qualification/hcsn_currentstate_n256_preexpm_provider_compat/REVIEW.json"
EXECUTION_KEY = "hcsn-n256-authentic-initial-capsule-20261121-c6bc-001"


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
        payload = encode_initial_capsule(capsule)
        decoded = decode_initial_capsule(payload)
        if (
            decoded.rows_hex != capsule.rows_hex
            or decoded.vectors_hex != capsule.vectors_hex
            or decoded.duration_hex != capsule.duration_hex
            or encode_initial_capsule(decoded) != payload
        ):
            raise SystemExit("authentic initial capsule round trip mismatch")
        (OUTPUT / f"{lane}.capsule.json").write_bytes(payload)
        lanes[lane] = {
            "capsule_bytes": len(payload),
            "capsule_sha256": _sha256(payload),
            "dimension": dimension,
            "duration_hex": duration_hex,
            "sparse_coordinates": sum(len(row) for row in capsule.rows_hex),
            "vectors": len(capsule.vectors_hex),
            "vector_coordinates": sum(map(len, capsule.vectors_hex)),
            "byte_exact_cold_decode": True,
        }

    usage = resource.getrusage(resource.RUSAGE_SELF)
    result = {
        "identity": "hcsn-n256-authentic-initial-capsule-20261121-c6bc-v1",
        "execution_key": EXECUTION_KEY,
        "status": "AUTHENTIC_INITIAL_CAPSULE_ONLY_RESOURCE_HOLD",
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
            "cold_decode_rebuilds": 2,
            "transition_builds": 4,
            "target_exact_input_conversions": 13135,
            "tail_checks": 0,
            "recurrence_row_actions": 0,
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
