"""Measurement-only V2: selected cgroups and process task children, not host scans.

V1 aggregation, PID pinning, PSS validation and result schema remain unchanged.
Only enumeration and explicit sampling cadence change. All selected process task
children are traversed, including non-main-thread forks and cross-cgroup children.
Missing permissions/capabilities trigger a reported V1 full-/proc fallback;
ordinary process/task exit is a coverage gap, not a reason to scan the host.
"""

from collections import Counter
import errno
import os
from pathlib import Path
import time

from process_metrics import CgroupScope
from process_metrics import ProcessMetrics as ProcessMetricsV1


class _FullProcFallback(Exception):
    pass


class ProcessMetrics(ProcessMetricsV1):
    def __init__(self, root_pids=None, *, sample_interval=0.1, **kwargs):
        super().__init__(root_pids, sample_interval=sample_interval, **kwargs)
        self._enumeration = Counter()
        self._phase_cpu = Counter()
        self._phase_wall = Counter()

    def _stat(self, pid):
        self._enumeration["proc_stat_read_attempts"] += 1
        return super()._stat(pid)

    @staticmethod
    def _missing(error):
        return isinstance(error, OSError) and error.errno in (errno.ENOENT, errno.ESRCH)

    def _pid_alive(self, pid):
        try:
            self._stat(pid)
            return True
        except (OSError, ValueError, IndexError) as error:
            if self._missing(error):
                return False
            raise _FullProcFallback("cannot_verify_live_pid:" + type(error).__name__) from error

    def _task_children(self, pid, gaps):
        task_root = self.proc_root / str(pid) / "task"
        try:
            tasks = [path for path in task_root.iterdir() if path.name.isdecimal()]
        except OSError as error:
            if self._missing(error) and not self._pid_alive(pid):
                gaps["pid_disappeared_during_enumeration"] += 1
                return []
            raise _FullProcFallback("task_directory:" + type(error).__name__) from error
        if not tasks:
            if not self._pid_alive(pid):
                gaps["pid_disappeared_during_enumeration"] += 1
                return []
            raise _FullProcFallback("live_pid_has_no_readable_task_directory")
        children = []
        for task in tasks:
            self._enumeration["task_children_read_attempts"] += 1
            try:
                values = [int(value) for value in (task / "children").read_text().split()]
                if any(value <= 0 for value in values):
                    raise ValueError("invalid child PID")
                children.extend(values)
            except (OSError, ValueError) as error:
                if self._missing(error):
                    # A live task without this file means the kernel/proc mount
                    # lacks the interface; an exited task is an ordinary race.
                    try:
                        (task / "stat").read_text()
                    except OSError as check_error:
                        if self._missing(check_error):
                            gaps["task_disappeared_during_enumeration"] += 1
                            continue
                        raise _FullProcFallback("task_liveness:" + type(check_error).__name__) from check_error
                    raise _FullProcFallback("live_task_children_interface_missing") from error
                raise _FullProcFallback("task_children:" + type(error).__name__) from error
        return children

    def _scoped_stats(self, seeds, gaps):
        stats, children, visited = {}, {}, set()
        queue = list(seeds)
        while queue:
            pid = queue.pop()
            if pid in visited:
                continue
            visited.add(pid)
            try:
                stat = self._stat(pid)
            except (OSError, ValueError, IndexError) as error:
                if self._missing(error):
                    gaps["pid_disappeared_during_enumeration"] += 1
                    continue
                # The full scan can still find children whose parent stat is
                # unreadable, so retain the V1 fallback rather than shrink scope.
                raise _FullProcFallback("selected_stat:" + type(error).__name__) from error
            stats[pid] = stat
            children.setdefault(stat["ppid"], []).append(pid)
            queue.extend(self._task_children(pid, gaps))
        return stats, children

    def _full_proc_stats(self, gaps):
        stats, children = {}, {}
        try:
            entries = list(self.proc_root.iterdir())
        except OSError as error:
            gaps["proc_scan:" + type(error).__name__] += 1
            entries = []
        for entry in entries:
            if not entry.name.isdecimal():
                continue
            pid = int(entry.name)
            try:
                stat = self._stat(pid)
                stats[pid] = stat
                children.setdefault(stat["ppid"], []).append(pid)
            except (OSError, ValueError, IndexError):
                pass
        return stats, children

    def _enumerate_stats(self, seeds, gaps):
        try:
            result = self._scoped_stats(seeds, gaps)
        except _FullProcFallback as error:
            self._enumeration["full_proc_fallback_samples"] += 1
            gaps["pid_enumeration_full_proc_fallback:" + str(error)] += 1
            return self._full_proc_stats(gaps)
        self._enumeration["scoped_samples"] += 1
        return result

    def _cgroups(self, gaps):
        samples, members = {}, set()
        # Keep polling every scope once requested: a callback may stop listing
        # a completed job just when its final retained cpu.stat is most useful.
        prior = [CgroupScope(Path(path), row["baseline"] == "caller_attested_new_cgroup_zero") for path, row in self._groups.items()]
        unique = {}
        for item in prior + self._values(self.cgroup_paths, "cgroup", gaps):
            scope = item if isinstance(item, CgroupScope) else CgroupScope(Path(item))
            path = Path(scope.path)
            if not path.is_absolute():
                path = self.cgroup_root / path
            path = Path(os.path.normpath(path))
            previous = unique.get(path)
            unique[path] = CgroupScope(path, scope.new_since_start or bool(previous and previous.new_since_start))
        for path, scope in unique.items():
            self._enumeration["cgroup_scopes_read"] += 1
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
                    self._enumeration["cgroup_procs_read_attempts"] += 1
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
        groups_wall, groups_cpu = time.monotonic(), time.thread_time()
        stats, children = self._enumerate_stats(roots | extras | group_members, gaps)
        enumeration_wall, enumeration_cpu = time.monotonic(), time.thread_time()
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
            self._phase_wall["cgroup_discovery"] += groups_wall - wall
            self._phase_cpu["cgroup_discovery"] += groups_cpu - cpu
            self._phase_wall["pid_enumeration"] += enumeration_wall - groups_wall
            self._phase_cpu["pid_enumeration"] += enumeration_cpu - groups_cpu
            self._phase_wall["pss_and_aggregation"] += time.monotonic() - enumeration_wall
            self._phase_cpu["pss_and_aggregation"] += time.thread_time() - enumeration_cpu
            self._sampler_wall += time.monotonic() - wall
            self._sampler_cpu += time.thread_time() - cpu

    def stop(self):
        result = super().stop()
        result["sampling"]["implementation"] = "hepta.process-metrics.linux.v2"
        result["sampling"]["cadence"] = "wait_after_sample"
        result["sampling"]["observer_stage_cpu_seconds"] = dict(self._phase_cpu)
        result["sampling"]["observer_stage_wall_seconds"] = dict(self._phase_wall)
        result["coverage"]["pid_enumeration"] = {
            "strategy": "explicit_cgroups_and_all_selected_task_children",
            "fallback": "full_proc_scan_on_permission_or_capability_failure",
            "normal_exits_are_recorded_without_global_fallback": True,
            **dict(self._enumeration),
        }
        return result
