"""Audit the immutable current desktop resource observation originals."""

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ORIGINALS = ROOT / "evidence" / "attempt001" / "ORIGINALS.json"
JOB_ID = "1a203764c26-ffbe-2724"
SOURCE_HEAD = "7dbc2da7ba0a951d0dce90b986e512e0f9e6c85d"
EXPECTED_SHA256 = {
    "request.json": "1e1ee187ae30a6054588eca4e00cd5219bbd9722e32061fb647c79826e6e0357",
    "exit.json": "9fe13e2d0b3048922a6f85ab33bb029229c23f599711bf946cb06244a99e5be3",
    "exit.witness.json": "5cd87828cec4952bdc314290df2092a147d477e093f20ecc8ff93b33cbd2b95e",
    "owner-intent.json": "c72f209f93e478fb2651ab6595355fa86e72316a384978b73200ec270375bab8",
    "started.json": "c72f209f93e478fb2651ab6595355fa86e72316a384978b73200ec270375bab8",
    "stdout.log": "351a36f0595bdb2febe93da8b9be32c753fdacc43e66afdfbaf8bfd853f5dd1e",
    "stderr.log": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
}


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _restore_originals():
    archive = json.loads(ORIGINALS.read_text())
    if archive["schema"] != "hcsn-index1159-resource-observation-originals-v1":
        raise SystemExit("original archive schema differs")
    if archive["job_id"] != JOB_ID or set(archive["files"]) != set(EXPECTED_SHA256):
        raise SystemExit("original archive identity differs")
    restored = {}
    for name, expected in EXPECTED_SHA256.items():
        record = archive["files"][name]
        raw = bytes.fromhex(record["hex"])
        if len(raw) != record["size"] or _sha256(raw) != expected:
            raise SystemExit(f"original bytes differ: {name}")
        if record["sha256"] != expected:
            raise SystemExit(f"recorded original digest differs: {name}")
        restored[name] = raw
    return restored


def _parse_stdout(raw):
    scalars = {}
    cgroups = {}
    current = None
    for line in raw.decode().splitlines():
        if line.startswith("cgroup_level="):
            prefix, path = line.split(" path=", 1)
            level = int(prefix.split("=", 1)[1])
            current = {"path": path, "fields": {}}
            cgroups[level] = current
        elif line.startswith("cgroup_field="):
            if current is None:
                raise SystemExit("cgroup field precedes its level")
            field, value = line.removeprefix("cgroup_field=").split(" value=", 1)
            current["fields"][field] = value.rstrip(";")
        else:
            name, value = line.split("=", 1)
            scalars[name] = value
    return scalars, cgroups


def _events(value):
    result = {}
    for entry in value.split(";"):
        if entry:
            name, count = entry.split()
            result[name] = int(count)
    return result


def audit():
    original = _restore_originals()
    request = json.loads(original["request.json"])
    exit_record = json.loads(original["exit.json"])
    witness = json.loads(original["exit.witness.json"])
    started = json.loads(original["started.json"])
    owner = json.loads(original["owner-intent.json"])
    if {request["job_id"], exit_record["job_id"], witness["job_id"]} != {JOB_ID}:
        raise SystemExit("job identity differs")
    if started != owner or started["job_id"] != JOB_ID:
        raise SystemExit("start/owner identity differs")
    if request["args"] != ["-c", (ROOT / "snapshot_source.sh").read_text()]:
        raise SystemExit("executed shell source differs from frozen Git source")
    if request["request_digest"] != "4d39d97a638ee55caa50013f763cce23e4e783ca1d1c1eb3dd84e67cf2e1888b":
        raise SystemExit("runtime request digest differs")
    if request["memory_max_bytes"] is not None or request["timeout_seconds"] != 30:
        raise SystemExit("runtime launch limits differ")
    if exit_record["exit_code"] != 0 or exit_record["timed_out"] or exit_record["cancelled"]:
        raise SystemExit("resource observation did not terminate cleanly")
    if not exit_record["output_complete"] or not exit_record["output_durable"]:
        raise SystemExit("resource observation output is incomplete")
    if exit_record["log_truncated"] != {"stderr": False, "stdout": False}:
        raise SystemExit("resource observation log was truncated")
    if witness["exit_sha256"] != EXPECTED_SHA256["exit.json"]:
        raise SystemExit("exit witness differs")
    if original["stderr.log"]:
        raise SystemExit("resource observation stderr is nonempty")

    scalars, cgroups = _parse_stdout(original["stdout.log"])
    if scalars["schema"] != "hcsn-index1159-current-resource-observation-v1":
        raise SystemExit("resource observation schema differs")
    if set(cgroups) != set(range(6)):
        raise SystemExit("ancestor cgroup chain is incomplete")
    if not cgroups[0]["path"].endswith(f"hepta-runtime-job-{JOB_ID}.service"):
        raise SystemExit("job cgroup identity differs")
    finite_max = [
        level
        for level, item in cgroups.items()
        if item["fields"].get("memory.max") not in (None, "max")
    ]
    if finite_max:
        raise SystemExit("sampled ancestor chain contains a finite memory.max")
    app_events = _events(cgroups[1]["fields"]["memory.events"])
    return {
        "identity": "hcsn-index1159-current-resource-observation-20261122-c6bc-v1",
        "status": "PASS_CURRENT_OBSERVATION_HOLD_ADMISSION",
        "source_head": SOURCE_HEAD,
        "job_id": JOB_ID,
        "runtime_request_digest": request["request_digest"],
        "sample_utc": scalars["sample_utc"],
        "boot_id": scalars["boot_id"],
        "observation": {
            "mem_total_kib": int(scalars["meminfo_MemTotal:"].split()[0]),
            "mem_available_kib": int(scalars["meminfo_MemAvailable:"].split()[0]),
            "swap_total_kib": int(scalars["meminfo_SwapTotal:"].split()[0]),
            "swap_free_kib": int(scalars["meminfo_SwapFree:"].split()[0]),
            "ancestor_levels": len(cgroups),
            "finite_memory_max_levels": len(finite_max),
            "app_slice_memory_current_bytes": int(cgroups[1]["fields"]["memory.current"]),
            "app_slice_memory_peak_bytes": int(cgroups[1]["fields"]["memory.peak"]),
            "app_slice_memory_max_events": app_events["max"],
            "app_slice_oom_events": app_events["oom"],
            "app_slice_oom_kills": app_events["oom_kill"],
            "effective_cpus": cgroups[4]["fields"]["cpuset.cpus.effective"],
            "nproc": int(scalars["nproc"]),
        },
        "scope": {
            "current_host_ancestor_observation_complete": True,
            "allocation_frozen": False,
            "calendar_frozen": False,
            "controlled_concurrency_frozen": False,
            "index1159_execution_authorized": False,
            "index1159_checkpoint_profile_complete": False,
            "index1159_runtime_bound_complete": False,
            "tail_termination_closed": False,
            "n256_qualified": False,
            "all_closed": False,
        },
        "work": {
            "remote_jobs": 1,
            "checkpoint_decodes": 0,
            "recurrence_row_actions": 0,
            "candidate_tail_checks": 0,
            "provider_calls": 0,
            "dynamic_steps": 0,
            "exponential_actions": 0,
            "torch_calls": 0,
            "optimizer_steps": 0,
            "model_calls": 0,
            "training_calls": 0,
        },
        "historical_state": {
            "pr6901": "UNKNOWN",
            "pr6939": "RED",
            "pr6942": "RED_TIMEOUT_COMPLETED_ACTIONS_UNKNOWN",
            "pr6950": "RED",
            "hpca": "NoUpdate_EXTERNAL_CUSTODY_OPEN",
            "c2_full_replay_completed_fits": 0,
            "global": "HOLD_NOUPDATE",
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-expected", type=Path)
    args = parser.parse_args()
    encoded = json.dumps(audit(), indent=2, sort_keys=True) + "\n"
    if args.verify_expected is not None and args.verify_expected.read_text() != encoded:
        raise SystemExit("committed observation result differs")
    print(encoded, end="")


if __name__ == "__main__":
    main()
