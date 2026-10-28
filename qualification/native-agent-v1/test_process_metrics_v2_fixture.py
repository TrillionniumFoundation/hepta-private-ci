"""Synthetic proc fixtures only; these do not replace the live-host scope gate.

The real /proc PID namespace guard remains untouched. Explicit temporary
proc_root input tests enumeration, fallback and identity logic in isolation.
"""

from contextlib import contextmanager
import errno
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from process_metrics import CgroupScope
from process_metrics import ProcessMetrics as V1
from process_metrics_v2 import ProcessMetrics as V2


def stat_text(pid, parent, start=None):
    fields = ["0"] * 22
    fields[0], fields[1] = "S", str(parent)
    fields[11], fields[12] = "20", "10"
    fields[19], fields[21] = str(start or pid * 10), "4"
    return f"{pid} (fixture process) " + " ".join(fields) + "\n"


@contextmanager
def fixture():
    with tempfile.TemporaryDirectory() as directory:
        proc = Path(directory) / "proc"
        proc.mkdir()
        (proc / "uptime").write_text("1000.0 0\n")
        # Task 102 is a thread of PID 100, not a separately selected process.
        parents = {100: 1, 101: 100, 103: 100, 104: 101,
                   200: 1, 201: 200, 300: 1, 301: 300, 900: 1}
        children = {100: [101], 101: [104], 200: [201], 300: [301]}
        for pid, parent in parents.items():
            target = proc / str(pid)
            (target / "task" / str(pid)).mkdir(parents=True)
            (target / "stat").write_text(stat_text(pid, parent))
            (target / "smaps_rollup").write_text("Pss: 8 kB\n")
            (target / "task" / str(pid) / "stat").write_text(stat_text(pid, parent))
            (target / "task" / str(pid) / "children").write_text(
                " ".join(map(str, children.get(pid, []))))
        worker = proc / "100" / "task" / "102"
        worker.mkdir()
        (worker / "stat").write_text(stat_text(102, 1))
        (worker / "children").write_text("103")
        group = Path(directory) / "cgroup"
        (group / "nested").mkdir(parents=True)
        for name, value in (("cpu.stat", "usage_usec 0\n"),
                            ("memory.current", "0\n"), ("memory.peak", "0\n"),
                            ("cgroup.procs", ""), ("nested/cgroup.procs", "300\n")):
            (group / name).write_text(value)
        yield proc, group


def collect(implementation, proc, group=None):
    return implementation(root_pids=[100], extra_pids=[200], proc_root=proc,
                          cgroup_paths=[CgroupScope(group), CgroupScope(group)] if group else [],
                          sample_interval=60).start().stop()


def identities(report):
    return {row["identity"] for row in report["processes"]}


class SyntheticEnumerationTests(unittest.TestCase):
    def test_non_main_task_extra_and_recursive_group_match_v1(self):
        with fixture() as (proc, group):
            previous = collect(V1, proc, group)
            result = collect(V2, proc, group)
            self.assertEqual(identities(result), identities(previous))
            self.assertEqual({row["pid"] for row in result["processes"]},
                             {100, 101, 103, 104, 200, 201, 300, 301})
            self.assertEqual(result["memory"], previous["memory"])
            self.assertEqual(result["cpu"], previous["cpu"])
            enumeration = result["coverage"]["pid_enumeration"]
            self.assertEqual(enumeration.get("full_proc_fallback_samples", 0), 0)
            self.assertEqual(enumeration["cgroup_scopes_read"], result["sampling"]["samples"])

    def test_permission_failure_preserves_selection_with_reported_fallback(self):
        with fixture() as (proc, group):
            previous = collect(V1, proc, group)
            original = Path.read_text

            def denied(path, *args, **kwargs):
                if path.name == "children":
                    raise PermissionError(errno.EACCES, "fixture permission denial", str(path))
                return original(path, *args, **kwargs)

            with patch.object(Path, "read_text", denied):
                result = collect(V2, proc, group)
            self.assertEqual(identities(result), identities(previous))
            self.assertEqual(result["coverage"]["pid_enumeration"]["full_proc_fallback_samples"],
                             result["sampling"]["samples"])

    def test_disappearing_known_pid_records_gap_without_host_scan(self):
        with fixture() as (proc, group):
            (proc / "103" / "stat").unlink()
            result = collect(V2, proc, group)
            self.assertEqual(result["coverage"]["pid_enumeration"].get("full_proc_fallback_samples", 0), 0)
            self.assertGreater(result["coverage"]["gaps"]["pid_disappeared_during_enumeration"], 0)
            self.assertNotIn("103:1030", identities(result))

    def test_live_task_missing_children_interface_requires_fallback(self):
        with fixture() as (proc, group):
            (proc / "100" / "task" / "102" / "children").unlink()
            previous = collect(V1, proc, group)
            result = collect(V2, proc, group)
            self.assertEqual(identities(result), identities(previous))
            self.assertGreater(result["coverage"]["gaps"][
                "pid_enumeration_full_proc_fallback:live_task_children_interface_missing"], 0)

    def test_pinned_root_reuse_rejects_its_unselected_descendants(self):
        with fixture() as (proc, _):
            metrics = V2(root_pids=[100], proc_root=proc, sample_interval=60)
            metrics._scope_identities[("root", 100)] = 1
            result = metrics.start().stop()
            self.assertEqual(result["processes"], [])
            self.assertGreater(result["coverage"]["gaps"]["root_pid_reused_scope_rejected"], 0)


if __name__ == "__main__":
    unittest.main()
