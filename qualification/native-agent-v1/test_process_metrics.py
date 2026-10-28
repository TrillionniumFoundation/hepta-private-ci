"""Focused metric-boundary checks; no privileged cgroup writes required."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from process_metrics import CgroupScope, ProcessMetrics


class ProcessMetricsTest(unittest.TestCase):
    @staticmethod
    def _fake_process(proc, pid, parent, start, cpu=0, pss=1024):
        directory = proc / str(pid)
        directory.mkdir(exist_ok=True, parents=True)
        fields = ["0"] * 22
        fields[0], fields[1] = "S", str(parent)
        fields[11], fields[19], fields[21] = str(cpu), str(start), "2"
        (directory / "stat").write_text(f"{pid} (test) " + " ".join(fields))
        (directory / "smaps_rollup").write_text(f"Pss: {pss} kB\n")

    def test_real_child_lifetime_and_observer_coverage(self):
        if int(Path("/proc/self/stat").read_text().split("(", 1)[0]) != os.getpid():
            with self.assertRaisesRegex(RuntimeError, "PID namespace differs"):
                ProcessMetrics(root_pids=[os.getpid()]).start()
            self.skipTest("caller and /proc PID namespaces differ; collector correctly refuses this environment")
        meter = ProcessMetrics(root_pids=[os.getpid()], sample_interval=0.02).start()
        child = subprocess.Popen([sys.executable, "-c", "import time\nend=time.monotonic()+0.18\nwhile time.monotonic()<end: pass"])
        child.wait(timeout=5)
        result = meter.stop()
        self.assertTrue(result["coverage"]["observer_process_included"])
        child_rows = [row for row in result["processes"] if row["pid"] == child.pid]
        self.assertEqual(len(child_rows), 1)
        self.assertGreater(child_rows[0]["observed_cpu_seconds"], 0)
        self.assertTrue(child_rows[0]["exit_cpu_endpoint_missing"])
        self.assertIsNone(result["cpu"]["cgroup_nonoverlap_observed_seconds"])
        self.assertFalse(result["coverage"]["global_total_memory_or_cpu_claim_supported"])
        self.assertIs(meter.stop(), result)

    def test_missing_pss_and_completed_job_cgroup_counter(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc, group = root / "proc", root / "job"
            (proc / "42").mkdir(parents=True)
            group.mkdir()
            (proc / "uptime").write_text("100.0 10.0\n")
            fields = ["0"] * 22
            fields[0], fields[1], fields[19], fields[21] = "S", "1", "100", "2"
            (proc / "42" / "stat").write_text("42 (test with parentheses ()) " + " ".join(fields))
            (group / "cgroup.procs").write_text("42\n")
            (group / "cpu.stat").write_text("usage_usec 1000\n")
            (group / "memory.current").write_text("2000\n")
            (group / "memory.peak").write_text("3000\n")
            scopes = [CgroupScope(group, new_since_start=True)]
            meter = ProcessMetrics(root_pids=[42], cgroup_paths=lambda: scopes, proc_root=proc).start()
            scopes.clear()  # A completed job drops out of the runtime callback.
            (group / "cpu.stat").write_text("usage_usec 7300\n")
            result = meter.stop()
            self.assertIsNone(result["memory"]["pss_peak_complete_sample_bytes"])
            self.assertIsNone(result["memory"]["pss_peak_observed_partial_bytes"])
            self.assertGreater(result["coverage"]["gaps"]["pss_missing:FileNotFoundError"], 0)
            self.assertAlmostEqual(result["cpu"]["cgroup_nonoverlap_observed_seconds"], 0.0073)
            self.assertEqual(result["cgroups"][0]["baseline"], "caller_attested_new_cgroup_zero")

    def test_reused_root_is_rejected_but_child_lifetimes_are_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            (proc / "uptime").write_text("100.0 10.0\n")
            self._fake_process(proc, 10, 1, 100, cpu=5)
            self._fake_process(proc, 11, 10, 110, cpu=3)
            meter = ProcessMetrics(root_pids=[10], proc_root=proc).start()
            self._fake_process(proc, 11, 10, 120, cpu=4)
            meter._sample()
            self._fake_process(proc, 10, 1, 200, cpu=1000)
            self._fake_process(proc, 12, 10, 210, cpu=1000)
            result = meter.stop()
            self.assertEqual({row["identity"] for row in result["processes"]}, {"10:100", "11:110", "11:120"})
            self.assertGreater(result["coverage"]["gaps"]["root_pid_reused_scope_rejected"], 0)

    def test_nested_cgroup_cpu_is_not_double_counted_and_members_are_recursive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc, group = root / "proc", root / "group"
            proc.mkdir()
            (proc / "uptime").write_text("100.0 10.0\n")
            self._fake_process(proc, 20, 1, 100, cpu=5)
            child_group = group / "child"
            child_group.mkdir(parents=True)
            for path, cpu, pids in [(group, 1000, ""), (child_group, 400, "20\n")]:
                (path / "cpu.stat").write_text(f"usage_usec {cpu}\n")
                (path / "cgroup.procs").write_text(pids)
                (path / "memory.current").write_text("1000\n")
                (path / "memory.peak").write_text("1000\n")
            meter = ProcessMetrics(root_pids=[], proc_root=proc, cgroup_paths=[
                CgroupScope(group, new_since_start=True),
                CgroupScope(child_group, new_since_start=True),
            ]).start()
            result = meter.stop()
            self.assertEqual([row["identity"] for row in result["processes"]], ["20:100"])
            self.assertEqual(result["cpu"]["cgroup_nonoverlap_paths"], [str(group)])
            self.assertAlmostEqual(result["cpu"]["cgroup_nonoverlap_observed_seconds"], 0.001)
            self.assertTrue(result["cpu"]["process_and_cgroup_totals_overlap_do_not_add"])

    def test_reset_cgroup_cpu_counter_is_unknown_not_clamped_to_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc, group = root / "proc", root / "group"
            proc.mkdir()
            group.mkdir()
            (proc / "uptime").write_text("100.0 10.0\n")
            (group / "cpu.stat").write_text("usage_usec 9000\n")
            (group / "cgroup.procs").write_text("")
            (group / "memory.current").write_text("0\n")
            (group / "memory.peak").write_text("0\n")
            meter = ProcessMetrics(root_pids=[], proc_root=proc, cgroup_paths=[group]).start()
            (group / "cpu.stat").write_text("usage_usec 100\n")
            result = meter.stop()
            self.assertTrue(result["cgroups"][0]["cpu_counter_reset"])
            self.assertIsNone(result["cgroups"][0]["observed_cpu_seconds"])
            self.assertIsNone(result["cpu"]["cgroup_nonoverlap_observed_seconds"])


if __name__ == "__main__":
    unittest.main()
