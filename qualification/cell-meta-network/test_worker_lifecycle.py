"""Local direct-child lifecycle checks; no Runtime/cgroup qualification claims."""
import base64
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest

HELPER = Path(__file__).with_name("worker_lifecycle.py")
PYTHON = Path(sys.executable).resolve()
PYTHON_SHA = hashlib.sha256(PYTHON.read_bytes()).hexdigest()
READY = b'{ "ready" : true, "identity" : "local-test" }\n'
PREFIX = '''import os,signal,sys,time
memory=bytearray(12*1024*1024)
for index in range(0,len(memory),4096): memory[index]=1
sum(index*index for index in range(200000))
'''


class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hepta-worker-life-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.receipt = self.root / "lifecycle.json"
        self.children = []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for child in self.children:
            if child.returncode is None:
                child.terminate()
                try:
                    child.communicate(timeout=4)
                except subprocess.TimeoutExpired:
                    child.kill(); child.communicate(timeout=2)

    def start(self, source, *extra):
        command = [str(PYTHON), "-I", "-S", str(HELPER), "--receipt", str(self.receipt),
                   "--worker-sha256", PYTHON_SHA, "--terminate-grace-seconds", "0.15",
                   "--kill-wait-seconds", "1", *extra, "--", str(PYTHON), "-I", "-S", "-c", source]
        child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 start_new_session=True)
        self.children.append(child)
        return child

    def ready(self, wrapper):
        self.assertTrue(select.select([wrapper.stdout], [], [], 5)[0], "ready deadline")
        self.assertEqual(wrapper.stdout.readline(), READY)
        current = json.loads(self.receipt.read_text())
        self.assertEqual(base64.b64decode(current["ready"]["raw_base64"]), READY)

    def resource_receipt(self):
        record = json.loads(self.receipt.read_text())
        self.assertTrue(record["complete"])
        self.assertTrue(record["child_reaped"])
        self.assertGreater(record["wait4_usage"]["peak_rss_kib"], 0)
        self.assertGreater(sum(record["rusage_children_cpu_delta_seconds"].values()), 0)
        for key in ("user_cpu_seconds", "system_cpu_seconds"):
            self.assertAlmostEqual(record["wait4_usage"][key],
                                   record["rusage_children_cpu_delta_seconds"][key], places=6)
        self.assertTrue(all(record["inherited_scope_observed"].values()))
        self.assertFalse(record["scope"]["external_cleanup_verified"])
        self.assertFalse(record["scope"]["descendants_reaped_or_cleaned_by_wrapper"])
        return record

    def test_natural_exit_preserves_exact_ready_and_collects_actual_usage(self):
        child = self.start(PREFIX + "os.write(1," + repr(READY) + ")\n")
        output, error = child.communicate(timeout=5)
        self.assertEqual(child.returncode, 0, error)
        self.assertEqual(output, READY)
        record = self.resource_receipt()
        self.assertEqual(record["classification"], "normal")
        self.assertEqual(record["child_returncode"], 0)
        self.assertEqual(record["signals_sent"], [])
        self.assertEqual(base64.b64decode(record["ready"]["raw_base64"]), READY)

    def test_sigterm_reaps_owned_child_and_keeps_cpu_evidence(self):
        source = PREFIX + '''stop=False
def term(signum, frame):
    global stop
    stop=True
signal.signal(signal.SIGTERM,term)
os.write(1,''' + repr(READY) + ''')
while not stop: time.sleep(.01)
'''
        child = self.start(source)
        self.ready(child)
        child.send_signal(signal.SIGTERM)
        child.communicate(timeout=5)
        self.assertEqual(child.returncode, 143)
        record = self.resource_receipt()
        self.assertEqual(record["classification"], "cancelled")
        self.assertEqual(record["child_returncode"], 0)
        self.assertEqual([row["name"] for row in record["signals_sent"]], ["SIGTERM"])
        self.assertTrue(all(row["child_unreaped"] for row in record["signals_sent"]))

    def test_ignored_term_is_killed_before_reap_with_bounded_accounting(self):
        source = PREFIX + "signal.signal(signal.SIGTERM,signal.SIG_IGN)\nos.write(1," + repr(READY) + ")\nwhile True: time.sleep(.01)\n"
        child = self.start(source)
        self.ready(child)
        child.send_signal(signal.SIGTERM)
        child.communicate(timeout=5)
        record = self.resource_receipt()
        self.assertEqual(record["classification"], "cancelled")
        self.assertEqual(record["child_returncode"], -signal.SIGKILL)
        self.assertEqual([row["name"] for row in record["signals_sent"]], ["SIGTERM", "SIGKILL"])
        self.assertTrue(all(row["child_unreaped"] for row in record["signals_sent"]))

    def test_nonzero_worker_exit_keeps_failure_resources(self):
        child = self.start(PREFIX + "os.write(1," + repr(READY) + ")\nraise SystemExit(7)\n")
        child.communicate(timeout=5)
        self.assertNotEqual(child.returncode, 0)
        record = self.resource_receipt()
        self.assertEqual(record["classification"], "failed")
        self.assertEqual(record["child_returncode"], 7)

    def test_full_stdout_pipe_cannot_block_cancel_and_wait4(self):
        source = PREFIX + "signal.signal(signal.SIGTERM,signal.SIG_IGN)\nos.write(1," + repr(READY) + ")\nwhile True: os.write(1,b'x'*65536)\n"
        child = self.start(source)
        self.ready(child)
        time.sleep(.15)  # Stop consuming stdout so the actual pipe fills.
        child.send_signal(signal.SIGTERM)
        child.wait(timeout=3)  # Deliberately do not communicate/drain before exit.
        child.communicate(timeout=2)
        record = self.resource_receipt()
        self.assertEqual(record["classification"], "cancelled")
        self.assertEqual(record["child_returncode"], -signal.SIGKILL)
        self.assertGreater(record["stdout_pending_bytes_at_exit"], 0)
        self.assertFalse(record["stdout_transport_complete"])

    def test_existing_receipt_refuses_a_second_child_without_rewriting_evidence(self):
        marker = self.root / "executions"
        source = PREFIX + "open(" + repr(str(marker)) + ", 'a').write('one\\n')\nos.write(1," + repr(READY) + ")\n"
        first = self.start(source)
        first.communicate(timeout=5)
        original = self.receipt.read_bytes()
        second = self.start(source)
        second.communicate(timeout=5)
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual(self.receipt.read_bytes(), original)
        self.assertEqual(marker.read_text(), "one\n")


if __name__ == "__main__":
    unittest.main()
