"""Small controller checks; fake child work only, never a formal experiment."""

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import run_remaining as controller


class RemainingControllerTests(unittest.TestCase):
    def test_training_gate_requires_successful_receipt_and_no_current_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            study = Path(temp)
            spec = {"id": "stage/task/model/seed1"}
            seals = {"base": "base", "followup": "followup"}
            directory = study / spec["id"]
            cache = {}
            controller.write(
                directory / "RESULT.json", {"spec": spec, "source_seals": seals}
            )
            self.assertFalse(
                controller.training_ready(study, [spec], seals, cache)["ready"]
            )
            receipt = {"id": spec["id"], "exit_code": 0, "result_exists": True}
            controller.write(directory / "EXECUTION_01.json", receipt)
            self.assertTrue(
                controller.training_ready(study, [spec], seals, cache)["ready"]
            )
            controller.write(
                directory / "FAILED.json", {"error": "retained current failure"}
            )
            self.assertFalse(
                controller.training_ready(study, [spec], seals, cache)["ready"]
            )

    def test_exact_child_receipt_and_explicit_retry_preserve_failed_output(self):
        with tempfile.TemporaryDirectory() as temp:
            args = SimpleNamespace(
                study=Path(temp),
                package=Path(__file__).resolve().parents[3],
                retry_failed=False,
            )
            case = {
                "id": "boundary/seed1",
                "kind": "boundary",
                "seed": 1,
                "result_name": "RESULT.json",
            }
            seals = {"base": "base", "followup": "followup"}
            child = (
                "import json,pathlib,sys; p=pathlib.Path(sys.argv[1]); p.mkdir(parents=True); "
                "(p/sys.argv[2]).write_text(json.dumps({'seed':1,'source_seals':{'base':'base','followup':'followup'}})); "
                "sys.exit(int(sys.argv[3]))"
            )

            def command(name, code):
                return [
                    sys.executable,
                    "-c",
                    child,
                    str(args.study / case["id"]),
                    name,
                    str(code),
                ]

            with patch.object(
                controller, "build_command", return_value=command("FAILED.json", 3)
            ):
                failed = controller.execute(args, case, seals, 1, lambda _: None)
            self.assertEqual(failed["exit_code"], 3)
            self.assertTrue(failed["failed_marker_exists"])
            self.assertGreater(failed["child_cpu_seconds"], 0)
            self.assertEqual(
                failed["child_cpu_seconds"],
                failed["child_user_cpu_seconds"] + failed["child_system_cpu_seconds"],
            )
            with self.assertRaises(FileExistsError):
                controller.execute(args, case, seals, 2, lambda _: None)
            args.retry_failed = True
            with patch.object(
                controller, "build_command", return_value=command("RESULT.json", 0)
            ):
                passed = controller.execute(args, case, seals, 2, lambda _: None)
            self.assertEqual(passed["exit_code"], 0)
            self.assertTrue(controller.complete_case(args.study, case, seals))
            archive = (
                args.study / "failed_attempts/remaining/boundary/seed1/before_attempt02"
            )
            self.assertTrue((archive / "FAILED.json").exists())
            self.assertEqual(
                json.loads((archive / "EXECUTION_01.json").read_text()), failed
            )
            ledger = args.study / "remaining_execution" / case["id"]
            self.assertEqual(len(list(ledger.glob("EXECUTION_*.json"))), 2)


if __name__ == "__main__":
    unittest.main()
