"""Read-only hardware observations; unavailable energy is never imputed."""

import json
import os
from pathlib import Path
import platform
import shutil


def hardware_inventory():
    counters = []
    for path in sorted(Path("/sys/class/powercap").glob("**/energy_uj")):
        row = {"path": str(path), "readable": False}
        try:
            row["sample_microjoules"] = int(path.read_text())
            row["readable"] = True
        except (OSError, ValueError) as error:
            row["error_type"] = type(error).__name__
        counters.append(row)
    limits = {}
    for name in ("cpu.max", "memory.max", "memory.current"):
        path = Path("/sys/fs/cgroup") / name
        limits[name] = path.read_text().strip() if path.exists() else None
    return {
        "schema": "hcsn-hardware-observation.v1",
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "logical_cpus_visible": os.cpu_count(),
        "affinity_cpus": len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
        "cgroup_limits": limits,
        "nvidia_smi": shutil.which("nvidia-smi"),
        "nvidia_devices": [str(path) for path in sorted(Path("/dev").glob("nvidia*"))],
        "energy_counters": counters,
        "direct_energy_counter_available": any(row["readable"] for row in counters),
        "energy_scope": "A readable package counter alone would not isolate this process's energy.",
        "joules_measured": None,
        "gpu_experiment_executed": False,
    }


if __name__ == "__main__":
    print(json.dumps(hardware_inventory(), indent=2, sort_keys=True))
