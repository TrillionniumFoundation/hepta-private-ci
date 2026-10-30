"""Real subprocess coverage for successful, failed and terminated research work."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

from .process_meter_v2 import meter_command


@unittest.skipUnless(sys.platform == "linux", "Linux-specific wait4 resource meter")
class ProcessMeterTests(unittest.TestCase):
    def test_exit_and_failed_work_are_metered_and_receipted(self):
        for code in (0, 7):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "run"
                command = [sys.executable, "-c", f"print(sum(i*i for i in range(100000))); raise SystemExit({code})"]
                result = meter_command(command, root, timeout_seconds=10)
                self.assertEqual(result["exit_code"], code)
                self.assertTrue(result["child_reaped"])
                self.assertGreater(result["child_cpu_seconds"], 0)
                self.assertGreater(result["measured_process_tariff_cost"], 0)
                self.assertEqual(json.loads((root / "PROCESS_RECEIPT.json").read_text()), result)
                with self.assertRaises(FileExistsError):
                    meter_command(command, root, timeout_seconds=10)

    def test_deadline_reaps_owned_process_and_retains_work(self):
        with tempfile.TemporaryDirectory() as directory:
            result = meter_command([sys.executable, "-c", "import time; time.sleep(20)"],
                                   Path(directory) / "run", timeout_seconds=0.1)
            self.assertTrue(result["timed_out"])
            self.assertTrue(result["child_reaped"])
            self.assertLess(result["exit_code"], 0)
            self.assertGreater(result["wall_seconds"], 0.1)


if __name__ == "__main__":
    unittest.main()
