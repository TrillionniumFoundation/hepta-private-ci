"""Selection equivalence on real live processes; no model or runtime jobs run."""

from contextlib import contextmanager
import errno
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from process_metrics import CgroupScope
from process_metrics import ProcessMetrics as V1
from process_metrics_v2 import ProcessMetrics as V2


LEAF = "import os,sys; print(os.getpid(), flush=True); sys.stdin.readline()"
BRANCH = textwrap.dedent(f"""
    import json,os,subprocess,sys
    child = subprocess.Popen([sys.executable, '-u', '-c', {LEAF!r}], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, text=True)
    child_pid = int(child.stdout.readline())
    print(json.dumps({{'root':os.getpid(), 'descendants':[child_pid]}}), flush=True)
    try:
        sys.stdin.readline()
    finally:
        child.communicate('\\n', timeout=5)
""")
TREE = textwrap.dedent(f"""
    import json,os,subprocess,sys,threading
    children, ids = [], []
    def spawn():
        child = subprocess.Popen([sys.executable, '-u', '-c', {BRANCH!r}], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, text=True)
        description = json.loads(child.stdout.readline())
        children.append(child)
        ids.extend([description['root'], *description['descendants']])
    spawn()
    # The child must belong to a non-main live task while metrics are sampled.
    release = threading.Event()
    ready = threading.Event()
    def non_main_parent():
        spawn()
        ready.set()
        release.wait()
    worker = threading.Thread(target=non_main_parent)
    worker.start()
    ready.wait()
    print(json.dumps({{'root':os.getpid(), 'descendants':ids}}), flush=True)
    try:
        sys.stdin.readline()
    finally:
        release.set()
        worker.join()
        for child in children:
            child.communicate('\\n', timeout=5)
""")


@contextmanager
def live_process(source):
    process = subprocess.Popen([sys.executable, "-u", "-c", source], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, text=True)
    try:
        line = process.stdout.readline()
        if not line:
            raise RuntimeError("controlled process did not reach readiness")
        yield process, json.loads(line)
    finally:
        if process.poll() is None:
            process.communicate("\n", timeout=10)
        else:
            process.communicate(timeout=1)


def collect(implementation, **kwargs):
    collector = implementation(sample_interval=60, **kwargs).start()
    return collector.stop()


def identities(report):
    return {row["identity"] for row in report["processes"]}


class SelectionTests(unittest.TestCase):
    def test_live_tree_non_main_fork_extra_and_recursive_cgroup_seeds_match_v1(self):
        with live_process(TREE) as (_, tree), live_process(BRANCH) as (_, extra), \
                live_process(BRANCH) as (_, detached), tempfile.TemporaryDirectory() as temp:
            group = Path(temp) / "declared-group"
            nested = group / "child-group"
            nested.mkdir(parents=True)
            (group / "cpu.stat").write_text("usage_usec 0\n")
            (group / "memory.current").write_text("0\n")
            (group / "memory.peak").write_text("0\n")
            (group / "cgroup.procs").write_text("")
            # Synthetic membership files select real processes. This does not
            # claim a real kernel cgroup migration test in the scratch host.
            (nested / "cgroup.procs").write_text(str(detached["root"]) + "\n")
            kwargs = {"root_pids": [tree["root"]], "extra_pids": [extra["root"]],
                      "cgroup_paths": [CgroupScope(group), CgroupScope(group)]}
            v1 = collect(V1, **kwargs)
            v2 = collect(V2, **kwargs)
            expected = {tree["root"], *tree["descendants"], extra["root"],
                        *extra["descendants"], detached["root"], *detached["descendants"]}
            self.assertEqual({row["pid"] for row in v1["processes"]}, expected)
            self.assertEqual(identities(v2), identities(v1))
            enumeration = v2["coverage"]["pid_enumeration"]
            self.assertEqual(enumeration.get("full_proc_fallback_samples", 0), 0)
            self.assertEqual(enumeration["cgroup_scopes_read"], v2["sampling"]["samples"])
            self.assertGreater(enumeration["task_children_read_attempts"], 0)
            self.assertEqual(v2["memory"]["pss_incomplete_samples"], 0)

    def test_permission_failure_records_fallback_and_preserves_full_tree(self):
        with live_process(TREE) as (_, tree):
            v1 = collect(V1, root_pids=[tree["root"]])
            original = Path.read_text

            def deny_children(path, *args, **kwargs):
                if path.name == "children":
                    raise PermissionError(errno.EACCES, "controlled permission denial", str(path))
                return original(path, *args, **kwargs)

            with patch.object(Path, "read_text", deny_children):
                v2 = collect(V2, root_pids=[tree["root"]])
            self.assertEqual(identities(v2), identities(v1))
            self.assertEqual(v2["coverage"]["pid_enumeration"]["full_proc_fallback_samples"],
                             v2["sampling"]["samples"])
            self.assertTrue(any(key.startswith("pid_enumeration_full_proc_fallback:")
                                for key in v2["coverage"]["gaps"]))

    def test_disappearing_task_is_visible_without_global_fallback(self):
        with live_process(BRANCH) as (_, tree):
            original = Path.read_text
            task_prefix = Path("/proc") / str(tree["root"]) / "task"

            def disappeared_task(path, *args, **kwargs):
                if task_prefix in path.parents and path.name in ("children", "stat"):
                    raise FileNotFoundError(errno.ENOENT, "controlled task exit", str(path))
                return original(path, *args, **kwargs)

            with patch.object(Path, "read_text", disappeared_task):
                v2 = collect(V2, root_pids=[tree["root"]])
            self.assertEqual(v2["coverage"]["pid_enumeration"].get("full_proc_fallback_samples", 0), 0)
            self.assertGreater(v2["coverage"]["gaps"].get("task_disappeared_during_enumeration", 0), 0)

    def test_missing_children_interface_on_live_task_falls_back(self):
        with live_process(BRANCH) as (_, tree):
            v1 = collect(V1, root_pids=[tree["root"]])
            original = Path.read_text

            def missing_interface(path, *args, **kwargs):
                if path.name == "children":
                    raise FileNotFoundError(errno.ENOENT, "controlled missing interface", str(path))
                return original(path, *args, **kwargs)

            with patch.object(Path, "read_text", missing_interface):
                v2 = collect(V2, root_pids=[tree["root"]])
            self.assertEqual(identities(v2), identities(v1))
            self.assertGreater(v2["coverage"]["gaps"].get(
                "pid_enumeration_full_proc_fallback:live_task_children_interface_missing", 0), 0)

    def test_original_root_start_ticks_still_reject_reused_identity(self):
        with live_process(BRANCH) as (_, tree):
            metrics = V2(root_pids=[tree["root"]], sample_interval=60)
            # An existing pin to another start time represents a recycled PID.
            metrics._scope_identities[("root", tree["root"])] = -1
            result = metrics.start().stop()
            self.assertEqual(result["processes"], [])
            self.assertGreater(result["coverage"]["gaps"].get("root_pid_reused_scope_rejected", 0), 0)


if __name__ == "__main__":
    unittest.main()
