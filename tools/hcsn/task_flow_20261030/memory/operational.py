"""Operational-only cache-aware admission; scientific source remains frozen."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from third.memory.execution import atomic_json
from task_flow_20261030.memory.freeze import verify, sha
from task_flow_20261030.memory import run


def observation():
    folder = Path("/sys/fs/cgroup")
    stats = {k: int(v) for k, v in (line.split() for line in (folder / "memory.stat").read_text().splitlines())}
    current = int((folder / "memory.current").read_text())
    maximum = int((folder / "memory.max").read_text())
    dirty = stats.get("file_dirty", 0) + stats.get("file_writeback", 0)
    inactive = max(0, stats.get("inactive_file", 0) - dirty)
    active = max(0, stats.get("active_file", 0) - dirty)
    slab = stats.get("slab_reclaimable", 0)
    floor = (stats.get("anon", 0) + max(0, stats.get("kernel", 0) - slab)
             + stats.get("shmem", 0) + stats.get("unevictable", 0) + dirty)
    estimated = max(floor, current - inactive - active // 2 - slab // 2)
    return dict(current_bytes=current, maximum_bytes=maximum, anon_bytes=stats.get("anon", 0),
                clean_inactive_bytes=inactive, clean_active_bytes=active,
                reclaimable_slab_bytes=slab, estimated_working_bytes=estimated,
                reserved_headroom_bytes=1500000000, admissible=estimated <= maximum - 1500000000)


def admission():
    began = time.perf_counter()
    while True:
        record = observation()
        record["wait_seconds"] = time.perf_counter() - began
        if record["admissible"]:
            return dict(operational_admission=record, policy="cache-aware-v1")
        atomic_json(HERE / "operational_resource_pause.json", record)
        print("OPERATIONAL_RESOURCE_PAUSE", record["estimated_working_bytes"], flush=True)
        time.sleep(10)


def main():
    verify()
    path = HERE / "operational_amendment.json"
    if path.exists():
        existing = json.loads(path.read_text())
        if existing["operational_source_sha256"] != sha(__file__):
            raise RuntimeError("Operational wrapper changed without separate record")
    else:
        result = json.loads((HERE / "results.json").read_text())
        atomic_json(path, dict(created_utc=datetime.now(timezone.utc).isoformat(),
            reason="Original conservative admission stalls on shared Rust build active-file/slab caches; first run own peak about504MB",
            original_freeze_sha256=sha(HERE / "freeze.json"),
            result_before_sha256=sha(HERE / "results.json"), completed_before=len(result["runs"]),
            operational_source_sha256=sha(__file__), observation=observation(),
            rule="Discount all clean inactive file, only half clean active file and half reclaimable slab; floor at anon+unreclaimable kernel+dirty+shmem+unevictable; reserve1.5GB",
            scientific_changes=False, data_changes=False, optimizer_or_quality_gate_changes=False,
            completed_run_repetition=False, concurrency=1))
    run.admission = admission
    run.main()


if __name__ == "__main__":
    main()
