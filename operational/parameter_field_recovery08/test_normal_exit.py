"""Normal CLI exits and legacy receipts; synthetic workers, no scientific claims."""

from contextlib import nullcontext
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from operational.parameter_field_recovery06 import owned_children
from . import analysis_worker, common as c
from .postseal import review


class AnalysisExitTests(unittest.TestCase):
    def run_owned_analysis(self, root, status):
        inputs = c.write_new(root / "inputs.json", {"synthetic_only": True})
        module = SimpleNamespace(
            __name__="experiments.parameter_field_fullstudy_20261029.analysis_launch_v2",
            subprocess=subprocess,
        )

        def main():
            child = module.subprocess.Popen(
                [sys.executable, "-c", "pass"], cwd=root
            )
            self.assertEqual(child.wait(timeout=5), 0)
            raise SystemExit(status)

        module.main = main
        flags = ["--inputs", inputs["path"], "--expected-sha256", inputs["sha256"]]
        with patch.object(analysis_worker, "installed", return_value=nullcontext()):
            return owned_children.run_controller(
                module,
                lambda: analysis_worker.run(module, flags, {}),
                root / "owned",
                binding={"execution_episode": c.EPISODE},
            )

    def test_normal_cli_exit_is_recorded_as_a_return_after_real_wait4(self):
        for status in (None, 0):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                self.assertEqual(self.run_owned_analysis(root, status), 0)
                closure = c.read(root / "owned/CLOSURE.json")
                self.assertIsNone(closure["original_exception"])
                self.assertEqual(closure["return_value"], 0)
                result = review.wait4(review.Metadata(), root / "owned")
                self.assertEqual(result["exit_semantics"], "normal_return")

    def test_nonzero_or_noninteger_exit_remains_an_error_with_accounting(self):
        for status in (7, "0", False, 0.0):
            with self.subTest(status=repr(status)), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                with self.assertRaises(SystemExit):
                    self.run_owned_analysis(root, status)
                closure = c.read(root / "owned/CLOSURE.json")
                self.assertEqual(closure["original_exception"]["type"], "SystemExit")
                self.assertTrue(closure["all_returned_direct_children_reaped"])
                with self.assertRaises(ValueError):
                    review.wait4(review.Metadata(), root / "owned")


def legacy_fixture(root):
    waited = {
        "pid": 13, "exit_code": 0, "wait_status": 0,
        "wall_seconds": 1, "user_cpu_seconds": 0.2,
        "system_cpu_seconds": 0.3, "cpu_seconds": 0.5,
        "peak_rss_bytes": 1024,
        "identity": {"pid": 13, "parent_pid": 7, "start_ticks": 20},
    }
    item = c.write_new(root / "001.WAIT4.json", waited)
    closure = {
        "schema": "hepta.execution06.owned-children.closure.1",
        "all_returned_direct_children_reaped": True,
        "accounting_complete_for_attempted_direct_workers": True,
        "attempt_count": 1, "returned_children": 1,
        "attempts": [{
            "argv": ["/usr/bin/python3", "-B", "-m",
                     "experiments.parameter_field_fullstudy_20261029.analysis_launch_v2",
                     "--child", "--parent-pid", "7"],
            "executable": "/usr/bin/python3", "pid": 13,
            "returned_child": True, "construction_entered": True,
            "construction_wait4_unavailable": False,
        }],
        "children": [{
            "wait4": waited, "wait4_receipt": item,
            "pid": 13, "identity": waited["identity"],
            "signals": [], "wait4_unavailable": None,
        }],
        "controller_identity": {"pid": 7},
        "original_exception": {"type": "SystemExit", "system_exit_code": 0, "message": "0"},
        "return_value": None, "pending_signal": None,
        "receipt_errors": [], "cleanup_errors": [],
        "construction_wait4_unavailable": False,
        "binding": {"execution_episode": c.EPISODE},
    }
    return closure


class LegacyReceiptTests(unittest.TestCase):
    def test_legacy_zero_exit_requires_explicit_scope_and_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            closure = legacy_fixture(root)
            item = c.write_new(root / "CLOSURE.json", closure)
            with self.assertRaises(ValueError):
                review.wait4(review.Metadata(), root)
            metadata = review.Metadata()
            result = review.wait4(metadata, root, allow_analysis_exit=True)
            metadata.stable()
            self.assertEqual(result["exit_semantics"], "legacy_analysis_system_exit_zero")
            self.assertEqual(result["closure"], item)
            self.assertEqual(c.bound(item), closure)

    def test_failed_ambiguous_or_unaccounted_legacy_receipts_stay_rejected(self):
        changes = [
            ("original_exception", {"type": "SystemExit", "system_exit_code": 7, "message": "7"}),
            ("original_exception", {"type": "SystemExit", "system_exit_code": "0", "message": "0"}),
            ("original_exception", {"type": "SystemExit", "system_exit_code": False, "message": "0"}),
            ("original_exception", {"type": "SystemExit", "system_exit_code": 0.0, "message": "0"}),
            ("original_exception", {"type": "RuntimeError", "system_exit_code": 0, "message": "0"}),
            ("pending_signal", 15), ("return_value", 7),
            ("receipt_errors", ["write failed"]), ("cleanup_errors", ["unreaped"]),
            ("construction_wait4_unavailable", True),
            ("accounting_complete_for_attempted_direct_workers", False),
            ("all_returned_direct_children_reaped", False),
            ("binding", {"execution_episode": "another-episode"}),
            ("controller_identity", {"pid": 8}),
        ]
        for key, value in changes:
            with self.subTest(key=key, value=value), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                closure = legacy_fixture(root)
                closure[key] = value
                c.write_new(root / "CLOSURE.json", closure)
                with self.assertRaises(ValueError):
                    review.wait4(review.Metadata(), root, allow_analysis_exit=True)

    def test_other_child_wrong_receipt_and_failed_wait_status_are_rejected(self):
        for mode in ("other_program", "signal", "missing_receipt", "failed_child", "wrong_parent"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                closure = legacy_fixture(root)
                if mode == "other_program":
                    closure["attempts"][0]["argv"][3] = "unrelated.program"
                elif mode == "signal":
                    closure["children"][0]["signals"] = [{"signal": 15}]
                elif mode == "missing_receipt":
                    closure["children"][0]["wait4_receipt"] = None
                elif mode == "wrong_parent":
                    closure["attempts"][0]["argv"][6] = "8"
                else:
                    waited = closure["children"][0]["wait4"]
                    waited["exit_code"], waited["wait_status"] = 1, 256
                    (root / "001.WAIT4.json").write_bytes(c.encode(waited))
                    closure["children"][0]["wait4_receipt"] = c.descriptor(root / "001.WAIT4.json")
                c.write_new(root / "CLOSURE.json", closure)
                with self.assertRaises(ValueError):
                    review.wait4(review.Metadata(), root, allow_analysis_exit=True)


if __name__ == "__main__":
    unittest.main()
