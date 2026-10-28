"""Linux process-tree and cgroup-v2 metrics with explicit coverage gaps.

Use ProcessMetrics(root_pids=[os.getpid()], cgroup_paths=callback).start(), then
stop(). The observer is included when it is in the requested process tree.
Callbacks must be fast local reads. cgroup CPU and per-process CPU overlap and
are reported separately; never add them. RSS sums double-count shared pages.
PSS is missing, never zero, when smaps_rollup cannot be read. Remote SSH/model
work is outside this host unless separately measured and reported.
Explicit root/extra PIDs are pinned to their first observed start ticks, so a
recycled PID cannot silently broaden the requested measurement scope.
"""

from collections import Counter
from dataclasses import dataclass
import math
import os
from pathlib import Path
import threading
import time


@dataclass(frozen=True)
class CgroupScope:
    path: Path
    # Only set when job/controller evidence proves this cgroup was created
    # during this measurement. This counts CPU before its first polling sample.
    new_since_start: bool = False


class ProcessMetrics:
    def __init__(self, root_pids=None, *, extra_pids=None, cgroup_paths=None,
                 sample_interval=0.05, external_work=None,
                 proc_root=Path("/proc"), cgroup_root=Path("/sys/fs/cgroup")):
        if sample_interval < 0.01:
            raise ValueError("sampling interval must be at least 10 ms")
        self.root_pids = [os.getpid()] if root_pids is None else root_pids
        self.extra_pids = [] if extra_pids is None else extra_pids
        self.cgroup_paths = [] if cgroup_paths is None else cgroup_paths
        self.interval = float(sample_interval)
        self.external_work = list(external_work or [])
        self.proc_root, self.cgroup_root = Path(proc_root), Path(cgroup_root)
        self.hz = os.sysconf("SC_CLK_TCK")
        self.page_size = os.sysconf("SC_PAGE_SIZE")
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._processes, self._groups = {}, {}
        self._gaps = Counter()
        self._active = set()
        self._roots_seen, self._extras_seen = set(), set()
        self._scope_identities = {}
        self._samples = 0
        self._rss_peak = 0
        self._pss_partial_peak = 0
        self._pss_observations = 0
        self._pss_complete_peak = None
        self._pss_complete_samples = 0
        self._pss_incomplete_samples = 0
        self._sampler_cpu = self._sampler_wall = 0.0
        self._largest_sample_gap = 0.0
        self._last_sample_time = None
        self._result = None
        self._thread = None

    def _values(self, value, name, gaps):
        try:
            return list(value() if callable(value) else value)
        except Exception as exc:
            gaps[name + "_callback:" + type(exc).__name__] += 1
            return []

    def _stat(self, pid):
        raw = (self.proc_root / str(pid) / "stat").read_text()
        left, right = raw.find("("), raw.rfind(")")
        if left < 0 or right < left:
            raise ValueError("invalid proc stat")
        fields = raw[right + 2:].split()
        return {"pid": pid, "name": raw[left + 1:right], "ppid": int(fields[1]),
                "start_ticks": int(fields[19]), "cpu_ticks": int(fields[11]) + int(fields[12]),
                "waited_child_ticks": int(fields[13]) + int(fields[14]),
                "rss_bytes": max(0, int(fields[21])) * self.page_size}

    @staticmethod
    def _integer(path):
        return int(path.read_text().strip())

    def _cgroups(self, gaps):
        samples, members = {}, set()
        # Keep polling every scope once requested: a callback may stop listing
        # a completed job just when its final retained cpu.stat is most useful.
        prior = [CgroupScope(Path(path), row["baseline"] == "caller_attested_new_cgroup_zero") for path, row in self._groups.items()]
        for item in prior + self._values(self.cgroup_paths, "cgroup", gaps):
            scope = item if isinstance(item, CgroupScope) else CgroupScope(Path(item))
            path = Path(scope.path)
            if not path.is_absolute():
                path = self.cgroup_root / path
            path = Path(os.path.normpath(path))
            sample = {"path": str(path), "new_since_start": scope.new_since_start,
                      "usage_usec": None, "memory_current_bytes": None,
                      "memory_peak_lifetime_bytes": None, "errors": []}
            try:
                fields = dict(line.split() for line in (path / "cpu.stat").read_text().splitlines())
                sample["usage_usec"] = int(fields["usage_usec"])
            except (OSError, ValueError, KeyError) as exc:
                sample["errors"].append("cpu.stat:" + type(exc).__name__)
            for filename, key in (("memory.current", "memory_current_bytes"), ("memory.peak", "memory_peak_lifetime_bytes")):
                try:
                    sample[key] = self._integer(path / filename)
                except (OSError, ValueError) as exc:
                    sample["errors"].append(filename + ":" + type(exc).__name__)
            # cgroup.procs is not recursive. Descendant cgroups must also be read.
            def walk_error(exc):
                sample["errors"].append("cgroup_walk:" + type(exc).__name__)
            visited = 0
            for directory, _, _ in os.walk(path, onerror=walk_error):
                visited += 1
                if visited > 4096:
                    sample["errors"].append("cgroup_descendant_limit")
                    break
                try:
                    members.update(int(value) for value in (Path(directory) / "cgroup.procs").read_text().split())
                except (OSError, ValueError) as exc:
                    sample["errors"].append("cgroup.procs:" + type(exc).__name__)
            if visited == 0:
                sample["errors"].append("cgroup_not_walkable")
            samples[str(path)] = sample
        return samples, members

    def _sample(self):
        wall, cpu = time.monotonic(), time.thread_time()
        gaps = Counter()
        roots = set(self._values(self.root_pids, "root_pids", gaps))
        extras = set(self._values(self.extra_pids, "extra_pids", gaps))
        if any(type(pid) is not int or pid <= 0 for pid in roots | extras):
            raise ValueError("process roots must be positive integer PIDs")
        groups, group_members = self._cgroups(gaps)
        stats, children = {}, {}
        try:
            entries = list(self.proc_root.iterdir())
        except OSError as exc:
            entries = []
            gaps["proc_scan:" + type(exc).__name__] += 1
        for entry in entries:
            if not entry.name.isdecimal():
                continue
            pid = int(entry.name)
            try:
                stat = self._stat(pid)
                stats[pid] = stat
                children.setdefault(stat["ppid"], []).append(pid)
            except (OSError, ValueError, IndexError):
                # Processes outside the selected scope may disappear during a
                # normal scan; only selected missing PIDs are counted below.
                pass
        scoped = set()
        for kind, pids in (("root", roots), ("extra", extras)):
            for pid in pids:
                if pid in stats:
                    key = (kind, pid)
                    start = stats[pid]["start_ticks"]
                    first = self._scope_identities.setdefault(key, start)
                    if start != first:
                        gaps[kind + "_pid_reused_scope_rejected"] += 1
                        continue
                scoped.add(pid)
        selected, queue = set(), list(scoped | group_members)
        while queue:
            pid = queue.pop()
            if pid not in selected:
                selected.add(pid)
                queue.extend(children.get(pid, ()))
        observed = []
        for pid in sorted(selected):
            if pid not in stats:
                gaps["selected_pid_stat_missing"] += 1
                continue
            stat = dict(stats[pid])
            stat["pss_bytes"] = None
            stat["pss_missing"] = None
            try:
                for line in (self.proc_root / str(pid) / "smaps_rollup").read_text().splitlines():
                    if line.startswith("Pss:"):
                        stat["pss_bytes"] = int(line.split()[1]) * 1024
                        break
                if stat["pss_bytes"] is None:
                    stat["pss_missing"] = "Pss_field_absent"
            except (OSError, ValueError) as exc:
                stat["pss_missing"] = type(exc).__name__
            try:
                if self._stat(pid)["start_ticks"] != stat["start_ticks"]:
                    gaps["pid_reused_during_sample"] += 1
                    continue
            except (OSError, ValueError, IndexError):
                gaps["pid_disappeared_during_sample"] += 1
                continue
            if stat["pss_missing"]:
                gaps["pss_missing:" + stat["pss_missing"]] += 1
            observed.append(stat)
        with self._lock:
            now = time.monotonic()
            if self._last_sample_time is not None:
                self._largest_sample_gap = max(self._largest_sample_gap, now - self._last_sample_time)
            self._last_sample_time = now
            self._samples += 1
            self._roots_seen.update(roots)
            self._extras_seen.update(extras)
            self._gaps.update(gaps)
            self._active = set()
            for stat in observed:
                key = f"{stat['pid']}:{stat['start_ticks']}"
                self._active.add(key)
                if key not in self._processes:
                    born_during_window = stat["start_ticks"] >= self._new_process_min_tick
                    self._processes[key] = {"pid": stat["pid"], "name": stat["name"], "start_ticks": stat["start_ticks"],
                        "first_seen_seconds": now - self.started_monotonic,
                        "cpu_baseline_ticks": 0 if born_during_window else stat["cpu_ticks"],
                        "cpu_baseline": "zero_for_process_born_during_window" if born_during_window else "first_observation",
                        "first_waited_child_ticks": stat["waited_child_ticks"], "rss_peak_bytes": 0,
                        "pss_peak_bytes": None, "pss_missing_samples": 0}
                record = self._processes[key]
                record.update(last_cpu_ticks=stat["cpu_ticks"], last_waited_child_ticks=stat["waited_child_ticks"], last_seen_seconds=now - self.started_monotonic)
                record["rss_peak_bytes"] = max(record["rss_peak_bytes"], stat["rss_bytes"])
                if stat["pss_bytes"] is None:
                    record["pss_missing_samples"] += 1
                else:
                    record["pss_peak_bytes"] = max(record["pss_peak_bytes"] or 0, stat["pss_bytes"])
                    self._pss_observations += 1
            rss = sum(stat["rss_bytes"] for stat in observed)
            pss = sum(stat["pss_bytes"] for stat in observed if stat["pss_bytes"] is not None)
            self._rss_peak = max(self._rss_peak, rss)
            self._pss_partial_peak = max(self._pss_partial_peak, pss)
            complete = len(observed) == len(selected) and all(stat["pss_bytes"] is not None for stat in observed)
            if complete and selected:
                self._pss_complete_samples += 1
                self._pss_complete_peak = max(self._pss_complete_peak or 0, pss)
            else:
                self._pss_incomplete_samples += 1
            for path, sample in groups.items():
                if path not in self._groups:
                    initial = 0 if sample["new_since_start"] else sample["usage_usec"]
                    self._groups[path] = {"path": path, "first_seen_seconds": now - self.started_monotonic,
                        "baseline_usage_usec": initial, "first_observed_usage_usec": sample["usage_usec"],
                        "baseline": "caller_attested_new_cgroup_zero" if sample["new_since_start"] else "first_observation",
                        "last_usage_usec": sample["usage_usec"], "cpu_counter_reset": False,
                        "memory_current_peak_bytes": None, "memory_peak_lifetime_bytes": None, "errors": Counter()}
                record = self._groups[path]
                usage = sample["usage_usec"]
                if usage is not None:
                    if record["baseline_usage_usec"] is None:
                        record["baseline_usage_usec"] = usage
                        record["first_observed_usage_usec"] = usage
                        record["baseline"] = "delayed_first_successful_observation"
                    if record["last_usage_usec"] is not None and usage < record["last_usage_usec"]:
                        record["cpu_counter_reset"] = True
                    record["last_usage_usec"] = usage
                record["cpu_available_last_sample"] = usage is not None
                record["last_seen_seconds"] = now - self.started_monotonic
                for input_key, output_key in (("memory_current_bytes", "memory_current_peak_bytes"), ("memory_peak_lifetime_bytes", "memory_peak_lifetime_bytes")):
                    value = sample[input_key]
                    if value is not None:
                        record[output_key] = max(record[output_key] or 0, value)
                record["errors"].update(sample["errors"])
            self._sampler_wall += time.monotonic() - wall
            self._sampler_cpu += time.thread_time() - cpu

    def _run(self):
        while not self._event.wait(self.interval):
            try:
                self._sample()
            except Exception as exc:
                with self._lock:
                    self._gaps["sampler_exception:" + type(exc).__name__] += 1

    def start(self):
        if self._thread is not None:
            raise RuntimeError("metrics collector has already started")
        if self.proc_root == Path("/proc"):
            observer_pid = int((self.proc_root / "self" / "stat").read_text().split("(", 1)[0])
            if observer_pid != os.getpid():
                raise RuntimeError("proc PID namespace differs from caller; refusing ambiguous process scope")
        self.started_wall_time_ns = time.time_ns()
        self.started_monotonic = time.monotonic()
        uptime = float((self.proc_root / "uptime").read_text().split()[0])
        self._new_process_min_tick = math.ceil(uptime * self.hz) + 1
        self._sample()
        self._thread = threading.Thread(target=self._run, name="process-metrics", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        if self._result is not None:
            return self._result
        if self._thread is None:
            raise RuntimeError("metrics collector has not started")
        self._event.set()
        self._thread.join(timeout=5)
        timed_out = self._thread.is_alive()
        if not timed_out:
            self._sample()
        with self._lock:
            processes = []
            for key, original in sorted(self._processes.items()):
                row = dict(original)
                row["identity"] = key
                row["present_at_final_sample"] = key in self._active
                row["observed_cpu_seconds"] = max(0, row["last_cpu_ticks"] - row["cpu_baseline_ticks"]) / self.hz
                row["waited_child_cpu_delta_seconds"] = max(0, row["last_waited_child_ticks"] - row["first_waited_child_ticks"]) / self.hz
                row["exit_cpu_endpoint_missing"] = key not in self._active
                row["cpu_before_first_observation_missing"] = row["cpu_baseline"] == "first_observation" and row["first_seen_seconds"] > self.interval
                processes.append(row)
            groups = []
            for original in self._groups.values():
                row = dict(original)
                row["errors"] = dict(row["errors"])
                baseline, last = row["baseline_usage_usec"], row["last_usage_usec"]
                row["observed_cpu_seconds"] = None if baseline is None or last is None or row["cpu_counter_reset"] else max(0, last - baseline) / 1e6
                row["cpu_before_first_observation_missing"] = row["baseline"] != "caller_attested_new_cgroup_zero" and row["first_seen_seconds"] > self.interval
                row["exit_cpu_endpoint_missing"] = not row.get("cpu_available_last_sample", False)
                groups.append(row)
            valid = [row for row in groups if row["observed_cpu_seconds"] is not None]
            nonoverlap = [row for row in valid if not any(row["path"].startswith(other["path"].rstrip("/") + "/") for other in valid if other is not row)]
            self._result = {"schema": "hepta.process-metrics.linux.v1", "elapsed_seconds": time.monotonic() - self.started_monotonic,
                "sampling": {"interval_seconds": self.interval, "samples": self._samples,
                    "largest_actual_gap_seconds": self._largest_sample_gap, "observer_cpu_seconds": self._sampler_cpu,
                    "observer_wall_seconds": self._sampler_wall, "observer_pid": os.getpid(), "stop_timeout": timed_out},
                "memory": {"rss_peak_sum_bytes": self._rss_peak if processes else None,
                    "rss_sum_double_counts_shared_pages": True, "pss_peak_complete_sample_bytes": self._pss_complete_peak,
                    "pss_peak_observed_partial_bytes": self._pss_partial_peak if self._pss_observations else None,
                    "pss_complete_samples": self._pss_complete_samples, "pss_incomplete_samples": self._pss_incomplete_samples,
                    "memory_peaks_are_sampled_lower_bounds": True},
                "cpu": {"process_lifecycle_observed_seconds": sum(row["observed_cpu_seconds"] for row in processes) if processes else None,
                    "cgroup_nonoverlap_observed_seconds": sum(row["observed_cpu_seconds"] for row in nonoverlap) if nonoverlap else None,
                    "cgroup_nonoverlap_paths": [row["path"] for row in nonoverlap],
                    "process_and_cgroup_totals_overlap_do_not_add": True,
                    "short_lived_unobserved_process_cpu": "missing unless included by a baselined, retained cgroup CPU counter; never assumed zero"},
                "coverage": {"root_pids_requested": sorted(self._roots_seen), "extra_pids_requested": sorted(self._extras_seen),
                    "explicit_pid_scope_pinned_to_first_start_ticks": True,
                    "cgroup_paths_requested": sorted(self._groups), "process_identities_observed": len(processes),
                    "observer_process_included": any(row["pid"] == os.getpid() for row in processes),
                    "process_exit_endpoints_missing": sum(row["exit_cpu_endpoint_missing"] for row in processes),
                    "polling_can_miss_short_lived_processes": True, "gaps": dict(self._gaps),
                    "remote_model_or_ssh_work": "Not included unless measured separately or represented by explicit local PID/cgroup scope. A local client/gateway alone does not measure remote inference.",
                    "external_work_declared": self.external_work, "global_total_memory_or_cpu_claim_supported": False},
                "processes": processes, "cgroups": groups}
            return self._result
