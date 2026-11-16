"""Observed process resources; parent/child identities prevent double counting."""

import os
from pathlib import Path
import sys
import time

from .coding_sft import write_new

try:
    import resource
except ImportError:
    resource = None


class StageResources:
    def __init__(self, root, operation, name):
        self.path = (
            Path(root)
            / "stage_resources"
            / (operation + "-" + (name or "all") + ".json")
        )
        self.operation, self.name = operation, name
        self.started = time.perf_counter()
        self.started_at_ns = time.time_ns()

    def finish(self, status):
        usage, children = (
            (
                resource.getrusage(resource.RUSAGE_SELF),
                resource.getrusage(resource.RUSAGE_CHILDREN),
            )
            if resource
            else (None, None)
        )
        scale = 1 if sys.platform == "darwin" else 1024
        result = {
            "schema": "hepta.process-resources.v2",
            "operation": self.operation,
            "name": self.name,
            "pid": os.getpid(),
            "ppid": os.getppid(),
            "status": status,
            "started_at_ns": self.started_at_ns,
            "completed_at_ns": time.time_ns(),
            "wall_seconds": time.perf_counter() - self.started,
            "self_cpu_seconds": usage.ru_utime + usage.ru_stime if usage else None,
            "waited_children_cpu_seconds": children.ru_utime + children.ru_stime
            if children
            else None,
            "self_peak_rss_bytes": usage.ru_maxrss * scale if usage else None,
            "waited_child_peak_rss_bytes": children.ru_maxrss * scale
            if children
            else None,
            "cpu_scope": "OS cumulative process and waited-child usage; includes imports before timer",
            "wall_scope": "CLI dispatch after imports; outer sequence records full child lifetime",
            "memory_scope": "separate process high-water marks; not concurrent aggregate memory",
            "aggregation": "sum only stages with sequence supervisor as ppid; nested cold costs already belong to their waiting stage",
            "energy_joules": None,
            "full_system_cost_known": False,
        }
        write_new(self.path, result)
        return result
