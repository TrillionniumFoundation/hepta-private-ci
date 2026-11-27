"""Read-only Linux counters; sequential snapshots, not causal attribution.

Call inside the build CPU boundary: reading and GC instrumentation have real
cost. Container counters include other processes. GC CPU spans callback times
and can include other threads; it is not exclusive collector CPU.
"""

from collections import deque
import gc
import hashlib
import os
from pathlib import Path
import resource
import sys
import threading
import time


SCHEMA = "hepta.resource-snapshot.v1"
CONTAINER_SCOPE = "container, not process; deltas do not establish causation"


def _stamp():
    return time.process_time_ns(), time.perf_counter_ns()


def _counter_file(path):
    result = {}
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        key, value = line.split()
        if key in result or not value.isdecimal():
            raise ValueError("duplicate or invalid nonnegative counter")
        result[key] = int(value)
    if not result:
        raise ValueError("empty counter file")
    return result


def numerical_runtime():
    """Observe the actual numerical process once inside charged shared CPU.

    This does not configure threads, affinity, NumPy or the loaded libraries.
    Optional discovery failures stay visible rather than breaking model work.
    Boundary task counts do not measure transient thread peaks.
    """
    import numpy as np

    started = _stamp()
    errors, libraries = {}, []
    try:
        from threadpoolctl import threadpool_info
        pools = threadpool_info()
        for index, pool in enumerate(pools[:16]):
            row = {key: pool.get(key) for key in ("user_api", "internal_api", "prefix", "filepath",
                "version", "num_threads", "threading_layer", "architecture")}
            try:
                checksum = hashlib.sha256()
                with Path(pool["filepath"]).open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        checksum.update(chunk)
                row["sha256"] = checksum.hexdigest()
            except (OSError, ValueError, KeyError, TypeError) as error:
                errors["library_" + str(index)] = repr(error)
            libraries.append(row)
        truncated = len(pools) > 16
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        errors["threadpool_discovery"] = repr(error)
        truncated = False
    try:
        affinity = sorted(os.sched_getaffinity(0))
        tasks = len(list(Path("/proc/self/task").iterdir()))
    except (OSError, AttributeError) as error:
        affinity, tasks = None, None
        errors["process_observation"] = repr(error)
    result = {"schema": "hepta.numerical-runtime.v1", "python": sys.version,
        "python_executable": sys.executable, "numpy_version": np.__version__,
        "numpy_path": np.__file__, "numpy_geterr": np.geterr(),
        "threadpools": libraries, "threadpools_truncated": truncated,
        "cpu_affinity": affinity, "observed_process_threads": tasks,
        "trace_active": sys.gettrace() is not None, "profile_active": sys.getprofile() is not None,
        "thread_environment": {key: os.environ.get(key) for key in
            ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "PYTHONDONTWRITEBYTECODE")},
        "errors": errors, "scope": "same-process boundary observation; no configuration changes or peak-thread claim"}
    ended = _stamp()
    result["sampling"] = {"cpu_ns": ended[0] - started[0], "wall_ns": ended[1] - started[1]}
    return result


def capture():
    """Return JSON values; unavailable optional observations remain None/errors."""
    errors = {}

    def read(key, operation):
        try:
            return operation()
        except (OSError, ValueError, AttributeError, NotImplementedError) as error:
            errors[key] = type(error).__name__ + ": " + str(error)
            return None

    cpu, wall = _stamp()
    usage = read("rusage", lambda: resource.getrusage(resource.RUSAGE_SELF))
    fields = {"minor_faults": "ru_minflt", "major_faults": "ru_majflt",
              "voluntary_context_switches": "ru_nvcsw", "involuntary_context_switches": "ru_nivcsw"}
    rusage = None if usage is None else {key: int(getattr(usage, name)) for key, name in fields.items()}
    if rusage is not None:
        rusage.update(user_cpu_ns=round(usage.ru_utime * 1e9), system_cpu_ns=round(usage.ru_stime * 1e9))
    out = {"schema": SCHEMA, "process_cpu_ns": cpu, "wall_ns": wall,
            "identity": {"pid": os.getpid(), "thread_id": threading.get_native_id(),
                "start_ticks": read("identity.start_ticks", lambda: int(Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()[19]))},
            "thread_cpu_ns": read("thread_cpu_ns", lambda: time.thread_time_ns()),
            "process_threads": read("process_threads", lambda: len(list(Path("/proc/self/task").iterdir()))),
            "rusage": rusage, "container": {"scope": CONTAINER_SCOPE,
                "cpu_stat": read("container.cpu_stat", lambda: _counter_file("/sys/fs/cgroup/cpu.stat")),
                "memory_events": read("container.memory_events", lambda: _counter_file("/sys/fs/cgroup/memory.events"))},
            "errors": errors}
    end_cpu, end_wall = _stamp()
    out["sampling"] = {"cpu_ns": end_cpu - cpu, "wall_ns": end_wall - wall}
    return out


def difference(before, after):
    """Delta cumulative counters; preserve missing/reset errors and thread gauges."""
    if any(not isinstance(row, dict) or row.get("schema") != SCHEMA for row in (before, after)):
        raise ValueError("compatible resource snapshots required")
    errors = {side + "." + key: value for side, row in (("before", before), ("after", after))
              for key, value in row.get("errors", {}).items()}
    identities = [row.get("identity", {}) for row in (before, after)]
    same_process = all(identities[0].get(key) is not None and identities[0].get(key) == identities[1].get(key)
                       for key in ("pid", "start_ticks"))

    def delta(a, b, key):
        if not same_process and not key.startswith("container."):
            errors[key] = "process identity missing/changed; delta unavailable"
            return None
        if key == "thread_cpu_ns" and (identities[0].get("thread_id") is None
                or identities[0].get("thread_id") != identities[1].get("thread_id")):
            errors[key] = "native thread missing/changed; delta unavailable"
            return None
        if type(a) is not int or type(b) is not int or min(a, b) < 0:
            errors[key] = "missing or invalid cumulative counter"
            return None
        if b < a:
            errors[key] = "counter decreased/reset; delta unavailable"
            return None
        return b - a

    def group(a, b, prefix):
        if not isinstance(a, dict) or not isinstance(b, dict):
            errors[prefix] = "counter group unavailable"
            return None
        return {key: delta(a.get(key), b.get(key), prefix + "." + key) for key in sorted(a.keys() | b.keys())}

    out = {"schema": "hepta.resource-delta.v1", "errors": errors,
           "process_threads": {side: row.get("process_threads") for side, row in (("before", before), ("after", after))}}
    for key in ("process_cpu_ns", "wall_ns", "thread_cpu_ns"):
        out[key] = delta(before.get(key), after.get(key), key)
    out["rusage"] = group(before.get("rusage"), after.get("rusage"), "rusage")
    out["container"] = {"scope": CONTAINER_SCOPE}
    for key in ("cpu_stat", "memory_events"):
        out["container"][key] = group(before.get("container", {}).get(key), after.get("container", {}).get(key), "container." + key)
    return out


class GCMonitor:
    """Bounded GC callback intervals; always detach on normal/exceptional exit."""

    def __init__(self, max_events=32):
        if type(max_events) is not int or not 1 <= max_events <= 1024:
            raise ValueError("max_events must be an integer in [1,1024]")
        self.max_events = max_events
        self.events = deque(maxlen=max_events)
        self.active, self.pending = False, None
        self.count = self.unmatched_starts = self.unmatched_stops = 0
        self.cpu_ns_total = self.cpu_ns_max = self.wall_ns_total = self.wall_ns_max = 0
        self._callback = self._observe

    def __enter__(self):
        if self.active:
            raise RuntimeError("GCMonitor is already active")
        self.active = True
        gc.callbacks.append(self._callback)
        return self

    def __exit__(self, *exception):
        try:
            gc.callbacks.remove(self._callback)
        except ValueError:
            pass
        finally:
            self.active = False
            if self.pending is not None:
                self.unmatched_starts += 1
                self.pending = None
        return False

    def _observe(self, phase, info):
        if not self.active:
            return
        if phase == "start":
            if self.pending is not None:
                self.unmatched_starts += 1
                return
            self.pending = (*_stamp(), info.get("generation"))
        elif phase == "stop":
            if self.pending is None:
                self.unmatched_stops += 1
                return
            cpu, wall = _stamp()
            start_cpu, start_wall, generation = self.pending
            self.pending = None
            cpu, wall = cpu - start_cpu, wall - start_wall
            self.count += 1
            self.cpu_ns_total += cpu
            self.wall_ns_total += wall
            self.cpu_ns_max, self.wall_ns_max = max(self.cpu_ns_max, cpu), max(self.wall_ns_max, wall)
            self.events.append({"generation": generation, "cpu_ns": cpu, "wall_ns": wall})

    def snapshot(self):
        return {"scope": "GC callback intervals; process CPU may include other threads",
                "count": self.count, "cpu_ns_total": self.cpu_ns_total, "cpu_ns_max": self.cpu_ns_max,
                "wall_ns_total": self.wall_ns_total, "wall_ns_max": self.wall_ns_max,
                "events": [dict(event) for event in self.events], "dropped_events": max(0, self.count - self.max_events),
                "unmatched_starts": self.unmatched_starts, "unmatched_stops": self.unmatched_stops,
                "active": self.active, "pending": self.pending is not None}
