"""Verify the immutable read-only N256 resource observation originals."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).parent
ORIGINAL = ROOT / "original_job"
JOB_ID = "1a1d4587885-392-376"
RAW_SHA256 = {
    "exit.json": "e7ed5af107c7d3e2a42133bb237f7e92d541f942ca0fc1198d0589a76c770faf",
    "exit.witness.json": "4816d6773ce3f58e050e5d5c57f49e1a8d3612430e475447de504140e0fd506a",
    "owner-intent.json": "075d3a66c470d41ea221d5c0a5b303175394a0267f7b4d78d7208d5158bc3256",
    "request.json": "7b7cf7f3ae3bf65a239ccd618b612bd5668d939e747065355ba28d84b001313a",
    "started.json": "075d3a66c470d41ea221d5c0a5b303175394a0267f7b4d78d7208d5158bc3256",
    "stderr.log": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "stdout.log": "8bd513b54e92ed326892276b72c50d31d838b06cb46e0058138fdf653fbdae4f",
}


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _events(value):
    result = {}
    for entry in value.rstrip(";").split(";"):
        if entry:
            name, count = entry.split()
            result[name] = int(count)
    return result


def _parse_stdout(text):
    scalars = {}
    cgroups = {}
    current = None
    for line in text.splitlines():
        if line.startswith("cgroup_level="):
            prefix, path = line.split(" path=", 1)
            level = int(prefix.split("=", 1)[1])
            current = {"path": path, "fields": {}}
            cgroups[level] = current
        elif line.startswith("cgroup_field="):
            if current is None:
                raise ValueError("cgroup field before level")
            field, value = line.removeprefix("cgroup_field=").split(" value=", 1)
            current["fields"][field] = value.rstrip(";")
        else:
            name, value = line.split("=", 1)
            scalars[name] = value
    return scalars, cgroups


def audit():
    for name, expected in RAW_SHA256.items():
        if _sha256(ORIGINAL / name) != expected:
            raise ValueError(f"original SHA-256 mismatch: {name}")

    request = json.loads((ORIGINAL / "request.json").read_text())
    exit_record = json.loads((ORIGINAL / "exit.json").read_text())
    witness = json.loads((ORIGINAL / "exit.witness.json").read_text())
    if {request["job_id"], exit_record["job_id"], witness["job_id"]} != {JOB_ID}:
        raise ValueError("job identity mismatch")
    if request["request_digest"] != "87dbe88d49a46c377a7c5cd0a33aae20436b745b6e71588fd6ffebfdfb3ca8f8":
        raise ValueError("request digest mismatch")
    if exit_record["exit_code"] != 0 or exit_record["timed_out"] or exit_record["cancelled"]:
        raise ValueError("snapshot job was not a clean terminal success")
    if not exit_record["output_complete"] or not exit_record["output_durable"]:
        raise ValueError("snapshot output is incomplete")
    if witness["exit_sha256"] != RAW_SHA256["exit.json"]:
        raise ValueError("exit witness mismatch")

    scalars, cgroups = _parse_stdout((ORIGINAL / "stdout.log").read_text())
    if scalars["schema"] != "hcsn-n256-resource-snapshot-v1":
        raise ValueError("snapshot schema mismatch")
    if set(cgroups) != set(range(6)):
        raise ValueError("ancestor cgroup chain is incomplete")
    if not cgroups[0]["path"].endswith(f"hepta-runtime-job-{JOB_ID}.service"):
        raise ValueError("snapshot does not identify its job cgroup")
    app_events = _events(cgroups[1]["fields"]["memory.events"])
    if app_events["oom"] != 315 or app_events["oom_kill"] != 15:
        raise ValueError("historical app.slice OOM evidence changed")
    finite_max = [
        level for level, item in cgroups.items()
        if item["fields"].get("memory.max") not in (None, "max")
    ]
    if finite_max:
        raise ValueError("unexpected finite memory.max in sampled chain")

    return {
        "schema": "hcsn-n256-resource-snapshot-audit-v1",
        "source_commit": "de254b3dfd7bc607ee3f829d4f8acf3e8ff20129",
        "job_id": JOB_ID,
        "sample_utc": scalars["sample_utc"],
        "boot_id": scalars["boot_id"],
        "observation": {
            "mem_total_kib": int(scalars["meminfo_MemTotal:"].split()[0]),
            "mem_available_kib": int(scalars["meminfo_MemAvailable:"].split()[0]),
            "swap_total_kib": int(scalars["meminfo_SwapTotal:"].split()[0]),
            "swap_free_kib": int(scalars["meminfo_SwapFree:"].split()[0]),
            "ancestor_levels": len(cgroups),
            "app_slice_memory_current_bytes": int(cgroups[1]["fields"]["memory.current"]),
            "app_slice_memory_peak_bytes": int(cgroups[1]["fields"]["memory.peak"]),
            "app_slice_swap_current_bytes": int(cgroups[1]["fields"]["memory.swap.current"]),
            "app_slice_oom_events": app_events["oom"],
            "app_slice_oom_kills": app_events["oom_kill"],
            "finite_memory_max_levels": len(finite_max),
        },
        "status": "PASS_OBSERVATION_HOLD_ADMISSION",
        "historical_resource_red_6295_unchanged": True,
        "allocation_frozen": False,
        "calendar_frozen": False,
        "resource_admitted": False,
        "counts": {
            "n256_dynamic_runs": 0,
            "matrix_exponential_actions": 0,
            "candidate_oracle_calls": 0,
            "n256_serializer_calls": 0,
            "torch_calls": 0,
            "optimizer_steps": 0,
        },
        "all_closed": False,
    }


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2, sort_keys=True))
