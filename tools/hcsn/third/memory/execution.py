"""Atomic evidence writes and a shared-host memory-pressure pause."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

import numpy as np


def numpy_scalar(value):
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError("Unsupported evidence value: "+type(value).__name__)


def atomic_json(path, payload):
    path = Path(path)
    temporary = path.with_name(path.name+".pending")
    with temporary.open("w") as handle:
        json.dump(payload, handle, indent=2, default=numpy_scalar)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def atomic_checkpoint(path, params):
    path = Path(path)
    temporary = path.with_name(path.name+".pending")
    with temporary.open("wb") as handle:
        np.savez_compressed(handle, **{k: np.asarray(v) for k, v in params.items()})
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def memory_current():
    path = Path("/sys/fs/cgroup/memory.current")
    return int(path.read_text()) if path.exists() else None


def wait_for_capacity(folder, run_id):
    started = time.perf_counter()
    pauses = []
    while True:
        used = memory_current()
        if used is None or used <= 7500000000:
            break
        record = dict(run=run_id, status="paused_before_training", reason="Shared cgroup memory exceeds7.5GB",
                      memory_current_bytes=used, utc=datetime.now(timezone.utc).isoformat(),
                      pause_seconds=time.perf_counter()-started)
        pauses.append(record)
        atomic_json(Path(folder)/"resource_pause.json", dict(pauses=pauses, resumed=False))
        print("RESOURCE_PAUSE", json.dumps(record), flush=True)
        time.sleep(10)
    if pauses:
        atomic_json(Path(folder)/"resource_pause.json", dict(pauses=pauses, resumed=True,
                    total_pause_seconds=time.perf_counter()-started))
    return dict(seconds=time.perf_counter()-started, observations=pauses, memory_at_start_bytes=used)
