"""Exercise caller persistence after an uncertain dispatch; no model is loaded."""

import contextlib
import io
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import run_replay
from loop_common import identity, read, write


class ReplayDispatchBoundary(unittest.TestCase):
    def test_dispatch_exception_preserves_phase_and_unknown_cpu(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            here = root / "replay"
            here.mkdir()
            origin = root / "original" / "evidence" / "run"
            origin.mkdir(parents=True)
            original_inventory = origin.parent.parent / "DELIVERY_INVENTORY.json"
            write(original_inventory, {"files": {}})
            before = identity(original_inventory)

            def prepare(unused_origin, output):
                inputs = output / "inputs"
                inputs.mkdir()
                shutil.copyfile(original_inventory, inputs / "original-inventory.json")
                write(output / "PROTOCOL.json",
                      {"child_wall_seconds": 60, "child_cleanup_seconds": 5})
                write(output / "INVENTORY.json", {
                    str(path.relative_to(output)): {"identity": identity(path)}
                    for path in sorted(output.rglob("*")) if path.is_file()})
                write(output / "LOCK.json", {name: identity(output / name)["sha256"]
                                            for name in ("PROTOCOL.json", "INVENTORY.json")})

            output = here / "run"
            args = SimpleNamespace(output=output, origin=origin)
            with patch.object(run_replay, "HERE", here), \
                    patch.object(run_replay, "prepare", prepare), \
                    patch.object(run_replay, "run_phase", side_effect=PermissionError("uncertain dispatch")) as dispatch, \
                    patch.object(run_replay, "worker") as model_worker, \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError, "post-run decision replay did not pass"):
                    run_replay.main(args)
                self.assertEqual(dispatch.call_count, 1)
                model_worker.assert_not_called()

            receipt = read(output / "decision.json")
            summary = read(output / "SUMMARY.json")
            self.assertEqual(summary["records"], [receipt])
            self.assertEqual(receipt["phase"], "decision")
            self.assertEqual(receipt["result"], {
                "engineering_passed": False,
                "error": {"type": "PermissionError", "message": "uncertain dispatch"},
            })
            self.assertEqual(summary["failure"], receipt["result"]["error"])
            self.assertEqual(summary["child_process_cpu"],
                             {"user_seconds": None, "system_seconds": None})
            self.assertFalse(summary["engineering_passed"])
            self.assertFalse(receipt["process_metrics"]["direct_child_reaped"])
            for key in ("pid", "exit_code", "cpu_user_seconds", "cpu_system_seconds", "peak_rss_bytes"):
                self.assertIsNone(receipt["process_metrics"][key])
            self.assertFalse((output / "cold_check.json").exists())
            self.assertEqual(identity(original_inventory), before)


if __name__ == "__main__":
    unittest.main()
