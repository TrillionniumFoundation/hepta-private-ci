"""Real child admission and callback gates; fixtures make no HIA capability claim."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from hepta_cells import joint_concurrency


class JointConcurrencyTests(unittest.TestCase):
    def setUp(self):
        retained = os.environ.get("HEPTA_JOINT_CONCURRENCY_ARTIFACT_ROOT")
        if retained:
            self.root = Path(retained) / self._testMethodName
            self.root.mkdir(parents=True, exist_ok=False)
        else:
            self.temp = tempfile.TemporaryDirectory()
            self.addCleanup(self.temp.cleanup)
            self.root = Path(self.temp.name)
        self.worker = self.root / "fixture.py"
        self.request = dict(operation="readback", request_id="original")

    def fixture(self, behavior):
        self.worker.write_text(
            """
import argparse,json,os,sys,time
from pathlib import Path
from hepta_cells.joint_concurrency import wait_joint_phase
p=argparse.ArgumentParser()
p.add_argument('--candidate');p.add_argument('--database')
p.add_argument('--admission-directory',type=Path)
a=p.parse_args();request=json.load(sys.stdin);gate=a.admission_directory
"""
            + behavior
        )

    def run_workers(self, *, timeout=2):
        with patch.object(joint_concurrency, "WORKER", self.worker):
            return joint_concurrency.run_joint_readbacks(
                self.root / "candidate",
                self.root / "database",
                self.request,
                self.root,
                timeout=timeout,
            )

    def test_both_real_children_reach_each_phase_before_release(self):
        self.fixture("""
wait_joint_phase(gate,'ADMITTED')
wait_joint_phase(gate,'READBACK')
print(json.dumps({'request':request,'pid':os.getpid(),'result':'retained'}))
""")
        expected_request = json.loads(json.dumps(self.request))
        popen = subprocess.Popen

        def launch(*args, **kwargs):
            child = popen(*args, **kwargs)
            self.request["request_id"] = "changed-after-launch"
            return child

        with patch.object(joint_concurrency.subprocess, "Popen", side_effect=launch):
            result = self.run_workers()
        self.assertIsNone(result["admission"]["error"])
        self.assertEqual([p["exit_code"] for p in result["processes"]], [0, 0])
        self.assertEqual(result["admission"]["launched_workers"], 2)
        gate = self.root / "joint-readback-admission"
        pids = [p["pid"] for p in result["processes"]]
        for phase, release in joint_concurrency.PHASES.items():
            row = json.loads((gate / (release + ".json")).read_text())
            self.assertEqual(row["pids"], pids)
            for pid in pids:
                ready = json.loads((gate / f"{phase}-{pid}.json").read_text())
                self.assertLessEqual(ready["ready_ns"], row["released_ns"])
        self.assertEqual(
            [json.loads(p["stdout"])["request"] for p in result["processes"]],
            [expected_request, expected_request],
        )
        self.assertEqual(
            [p["request"] for p in result["processes"]],
            [expected_request, expected_request],
        )

    def test_second_startup_failure_retains_first_and_never_releases(self):
        self.fixture("""
if list(gate.glob('ADMITTED-*.json')):
    print('second startup failed',file=sys.stderr);raise SystemExit(7)
wait_joint_phase(gate,'ADMITTED')
""")
        result = self.run_workers()
        self.assertEqual(result["admission"]["launched_workers"], 2)
        self.assertEqual(len(result["processes"]), 2)
        self.assertIsNotNone(result["admission"]["error"])
        self.assertFalse(result["admission"]["start_released"])
        self.assertFalse(result["admission"]["resume_released"])
        self.assertEqual(result["processes"][1]["exit_code"], 7)
        self.assertIn("second startup failed", result["processes"][1]["stderr"])
        self.assertTrue(all(p["exit_code"] is not None for p in result["processes"]))

    def test_missing_callback_retains_two_workers_and_no_resume(self):
        self.fixture("""
wait_joint_phase(gate,'ADMITTED')
time.sleep(5)
""")
        result = self.run_workers(timeout=2)
        self.assertEqual(result["admission"]["launched_workers"], 2)
        self.assertEqual(len(result["processes"]), 2)
        self.assertTrue(result["admission"]["start_released"])
        self.assertFalse(result["admission"]["resume_released"])
        self.assertIn("TimeoutError", result["admission"]["error"])
        self.assertFalse((self.root / "joint-readback-admission/RESUME.json").exists())
        self.assertTrue(all(p["exit_code"] != 0 for p in result["processes"]))

    @unittest.skipUnless(
        sys.platform.startswith("linux"), "Linux /proc process-state control"
    )
    def test_timeout_terminates_owned_descendants_and_reaps_workers(self):
        self.fixture("""
import subprocess
wait_joint_phase(gate,'ADMITTED')
descendant=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
stat=Path(f'/proc/{descendant.pid}/stat').read_text().rsplit(')',1)[1].split()
(gate/f'descendant-{os.getpid()}.json').write_text(json.dumps({
    'pid':descendant.pid,'group':os.getpgid(descendant.pid),'start_time':stat[19]}))
print('descendant launched',flush=True)
time.sleep(60)
""")
        result = self.run_workers(timeout=2)
        gate = self.root / "joint-readback-admission"
        self.assertEqual(len(result["processes"]), 2)
        self.assertEqual(
            [p["exit_code"] for p in result["processes"]], [-signal.SIGKILL] * 2
        )
        observations = []
        for process in result["processes"]:
            child = json.loads((gate / f"descendant-{process['pid']}.json").read_text())
            self.assertEqual(child["group"], process["pid"])
            deadline, alive, state = time.monotonic() + 2, True, None
            while time.monotonic() < deadline:
                try:
                    fields = (
                        Path(f"/proc/{child['pid']}/stat")
                        .read_text()
                        .rsplit(")", 1)[1]
                        .split()
                    )
                    state = fields[0]
                    alive = fields[19] == child["start_time"] and state not in {
                        "Z",
                        "X",
                    }
                except FileNotFoundError:
                    alive, state = False, "absent"
                if not alive:
                    break
                time.sleep(0.005)
            observations.append({**child, "alive": alive, "state": state})
            if alive:
                os.kill(child["pid"], signal.SIGKILL)
        (gate / "DESCENDANT-CHECK.json").write_text(
            json.dumps(observations, sort_keys=True)
        )
        self.assertTrue(all(not row["alive"] for row in observations))
        self.assertTrue(
            all(row["scope"] == "owned_process_group" for row in result["cleanup"])
        )
        self.assertFalse(result["detached_descendants_covered"])

    def test_ordinary_worker_import_preserves_cold_source_identity(self):
        program = """
import json
from hepta_cells.maintenance_cycle import run
from hepta_cells.maintenance_tasks import sources
cold = sources()
from hepta_cell_joint_worker import load_candidate
warm = sources()
assert warm == cold, {
    "added": sorted(warm.keys() - cold.keys()),
    "removed": sorted(cold.keys() - warm.keys()),
    "changed": sorted(k for k in cold.keys() & warm.keys() if cold[k] != warm[k]),
}
print(json.dumps({"source_count": len(cold), "equal": True}))
"""
        child = subprocess.run(
            [sys.executable, "-B", "-c", program],
            capture_output=True,
            text=True,
            timeout=15,
            env={
                **os.environ,
                "PYTHONPATH": str(
                    Path(joint_concurrency.__file__).resolve().parents[1]
                ),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        self.assertEqual(child.returncode, 0, child.stderr)
        result = json.loads(child.stdout)
        self.assertTrue(result["equal"])
        self.assertGreater(result["source_count"], 0)


if __name__ == "__main__":
    unittest.main()
