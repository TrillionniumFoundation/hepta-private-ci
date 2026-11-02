"""Real-process controls for the meter portions available without delegation.

These tests do not simulate a successful kernel cgroup measurement.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from experiments.hcsn_v10_followup_20261101.economics import cgroup_meter as meter


class GateControls(unittest.TestCase):
    def launch(self, temporary, payload=None):
        marker = Path(temporary) / "payload-ran"
        command = payload or [sys.executable, "-c", "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('ran')", str(marker)]
        read_fd, write_fd = os.pipe()
        child = subprocess.Popen(
            [sys.executable, meter.__file__, "--gate-fd", str(read_fd), "--", *command],
            pass_fds=(read_fd,), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        os.close(read_fd)
        def cleanup():
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=3)
        self.addCleanup(cleanup)
        return child, write_fd, marker

    def test_real_gate_blocks_then_releases_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            child, fd, marker = self.launch(temporary)
            try:
                time.sleep(0.15)
                self.assertIsNone(child.poll())
                self.assertFalse(marker.exists())
                os.write(fd, b"R")
            finally:
                os.close(fd)
            child.communicate(timeout=3)
            self.assertEqual((child.returncode, marker.read_text()), (0, "ran"))

    def test_parent_disappearance_refuses_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            child, fd, marker = self.launch(temporary)
            os.close(fd)
            child.communicate(timeout=3)
            self.assertEqual((child.returncode, marker.exists()), (125, False))

    def test_wrong_release_refuses_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            child, fd, marker = self.launch(temporary)
            os.write(fd, b"X")
            os.close(fd)
            child.communicate(timeout=3)
            self.assertEqual((child.returncode, marker.exists()), (125, False))

    def test_exec_failure_preserves_nonzero(self):
        with tempfile.TemporaryDirectory() as temporary:
            child, fd, _ = self.launch(temporary, [str(Path(temporary) / "missing-executable")])
            os.write(fd, b"R")
            os.close(fd)
            _, stderr = child.communicate(timeout=3)
            self.assertEqual(child.returncode, 127)
            self.assertIn(b"payload exec failed", stderr)

    def test_regular_filesystem_cannot_impersonate_kernel_cgroup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker, out = root / "payload-ran", root / "result"
            receipt = meter.run([sys.executable, "-c", "import sys; open(sys.argv[1],'w').write('ran')", str(marker)], out, root, 3)
            self.assertEqual((receipt["status"], receipt["payload_released"], marker.exists()), ("UNAVAILABLE", False, False))
            self.assertEqual(json.loads((out / "RECEIPT.json").read_text()), receipt)

    def test_malformed_counter_faults_refuse(self):
        for raw in ("usage_usec 1\nusage_usec 2", "usage_usec -1", "usage_usec nan", "usage_usec 3 4"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                meter.fields(raw)

    def test_real_mount_routing(self):
        self.assertTrue(meter.on_cgroup2(Path("/sys/fs/cgroup").resolve()))
        self.assertFalse(meter.on_cgroup2(Path(tempfile.gettempdir()).resolve()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
