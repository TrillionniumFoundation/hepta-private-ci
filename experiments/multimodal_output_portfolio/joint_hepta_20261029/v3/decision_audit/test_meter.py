"""Meter real small subprocess success/failure, never synthetic model execution."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

from .meter import execute


class PhysicalCommandMeter(unittest.TestCase):
    def test_failed_command_keeps_its_physical_attempt_and_cost(self):
        with tempfile.TemporaryDirectory(dir="/dev/shm") as folder:
            path = Path(folder) / "cost.json"
            row = execute([sys.executable, "-c", "raise SystemExit(7)"], path)
            self.assertEqual(row["return_code"], 7)
            self.assertEqual(row["status"], "failed")
            self.assertEqual(json.loads(path.read_text()), row)
            self.assertGreater(row["wall_seconds"], 0)
            self.assertGreaterEqual(row["child_cpu_seconds"], 0)
            self.assertTrue(row["do_not_add_to_nested_costs"])
            with self.assertRaises(FileExistsError):
                execute([sys.executable, "-c", "pass"], path)

    def test_successful_command_is_separately_metered(self):
        with tempfile.TemporaryDirectory(dir="/dev/shm") as folder:
            row = execute([sys.executable, "-c", "sum(range(10000))"], Path(folder) / "cost.json")
            self.assertEqual(row["status"], "completed")
            self.assertEqual(row["return_code"], 0)


if __name__ == "__main__":
    unittest.main()
