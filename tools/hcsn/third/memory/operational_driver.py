"""Authorized scheduling amendment; frozen model/training source is unchanged.

Only the capacity-wait callback and evidence-provenance wrapper are replaced.
The first completed run remains from the original raw-current admission rule.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from third.memory import development as engine
from third.memory.execution import atomic_json, wait_for_capacity
from third.memory.freeze import verify, sha


def snapshot():
    folder = Path("/sys/fs/cgroup")
    stat = {k: int(v) for k, v in (line.split() for line in (folder/"memory.stat").read_text().splitlines())}
    events = {k: int(v) for k, v in (line.split() for line in (folder/"memory.events").read_text().splitlines())}
    current = int((folder/"memory.current").read_text())
    maximum = int((folder/"memory.max").read_text())
    clean_inactive = max(0, stat["inactive_file"]-stat["file_dirty"]-stat["file_writeback"])
    working = max(0, current-clean_inactive)
    return dict(raw_current_bytes=current, cgroup_limit_bytes=maximum,
        clean_inactive_estimate_bytes=clean_inactive, conservative_working_set_bytes=working,
        estimated_headroom_bytes=maximum-working,
        components={k: stat[k] for k in ("anon", "file", "shmem", "inactive_file", "active_file",
                    "file_dirty", "file_writeback", "slab_reclaimable", "slab_unreclaimable")},
        oom_events=events, utc=datetime.now(timezone.utc).isoformat())


def capacity_wait(folder, run_id):
    started = time.perf_counter()
    observations = []
    while True:
        state = snapshot()
        if state["estimated_headroom_bytes"] >= 1500000000:
            break
        observations.append(state)
        record = dict(run=run_id, reason="Conservative working-set headroom below1.5GB",
                      pause_seconds=time.perf_counter()-started, observations=observations)
        atomic_json(Path(folder)/"operational_resource_pause.json", record)
        print("OPERATIONAL_RESOURCE_PAUSE", json.dumps(record), flush=True)
        time.sleep(10)
    return dict(seconds=time.perf_counter()-started, observations=observations,
                memory_at_start_bytes=state["raw_current_bytes"], admission_snapshot=state,
                admission_rule="current-max(0,inactive_file-dirty-writeback), reserve>=1.5GB",
                execution_driver_sha256=sha(Path(__file__)))


def main():
    verify()
    amendment_path = HERE/"operational_amendment.json"
    amendment = json.loads(amendment_path.read_text())
    if sha(Path(__file__)) != amendment["driver_sha256"]:
        raise RuntimeError("Operational driver source changed")
    if sha(HERE/"freeze.json") != amendment["scientific_freeze_sha256"]:
        raise RuntimeError("Scientific freeze changed")
    if sha(HERE/"numerical_validation.json") != amendment["numeric_receipt_sha256"]:
        raise RuntimeError("Numeric receipt changed")
    numerical = json.loads((HERE/"numerical_validation.json").read_text())
    if not numerical["passed"]:
        raise RuntimeError("A passed numerical receipt is required")
    original = json.loads((HERE/amendment["preserved_result_file"]).read_text())
    current = json.loads((HERE/"development_results.json").read_text())
    original_count = amendment["applies_after_completed_runs"]
    if current["runs"][:original_count] != original["runs"]:
        raise RuntimeError("Pre-amendment run changed")
    if engine.wait_for_capacity is not wait_for_capacity or engine.atomic_json is not atomic_json:
        raise RuntimeError("Unexpected execution callbacks before amendment")
    identity = dict(amendment_sha256=sha(amendment_path), driver_sha256=sha(Path(__file__)),
                    applies_after_completed_runs=original_count,
                    mathematical_sources_changed=False, scientific_protocol_changed=False)

    def recorded_write(path, payload):
        path = Path(path)
        if path.name == "development_results.json":
            payload["operational_amendment"] = identity
            if len(payload["runs"]) > original_count:
                payload["runs"][-1]["operational_driver"] = identity
                payload["runs"][-1]["resources_after_run"] = snapshot()
        elif path.name == "active_attempt.json":
            payload["operational_driver"] = identity
            payload["resources_observed"] = snapshot()
        atomic_json(path, payload)

    engine.wait_for_capacity = capacity_wait
    engine.atomic_json = recorded_write
    print("AUTHORIZED_OPERATIONAL_AMENDMENT", json.dumps(identity), flush=True)
    try:
        engine.main()
    except BaseException as error:
        path = HERE/"active_attempt.json"
        if path.exists():
            attempt = json.loads(path.read_text())
            if attempt["status"] == "running":
                attempt.update(status="interrupted", reason=type(error).__name__+": "+str(error),
                    elapsed_seconds=time.time()-attempt["started_epoch_seconds"],
                    resources_observed=snapshot())
                recorded_write(path, attempt)
                atomic_json(HERE/"operational_interruption.json", attempt)
        raise


if __name__ == "__main__":
    main()
