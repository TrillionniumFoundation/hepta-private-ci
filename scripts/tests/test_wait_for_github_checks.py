import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "wait_for_github_checks.py"
SPEC = importlib.util.spec_from_file_location("wait_for_github_checks", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class CheckFanInTests(unittest.TestCase):
    def test_latest_check_run_wins(self) -> None:
        payload = {
            "check_runs": [
                {
                    "id": 10,
                    "name": "runtime.codex exact-head",
                    "status": "completed",
                    "conclusion": "failure",
                },
                {
                    "id": 12,
                    "name": "runtime.codex exact-head",
                    "status": "completed",
                    "conclusion": "success",
                    "details_url": "https://example.test/12",
                },
                {
                    "id": 11,
                    "name": "runtime.codex synthetic-merge",
                    "status": "in_progress",
                    "conclusion": None,
                },
            ]
        }
        states, pending = module.evaluate_check_runs(
            payload,
            ["runtime.codex exact-head", "runtime.codex synthetic-merge"],
        )
        self.assertEqual(states["runtime.codex exact-head"].conclusion, "success")
        self.assertEqual(pending, ["runtime.codex synthetic-merge"])

    def test_missing_check_is_pending_and_unknown_status_fails(self) -> None:
        states, pending = module.evaluate_check_runs(
            {"check_runs": []}, ["runtime.codex exact-head"]
        )
        self.assertEqual(states, {})
        self.assertEqual(pending, ["runtime.codex exact-head"])
        with self.assertRaises(module.CheckError):
            module.evaluate_check_runs(
                {
                    "check_runs": [
                        {
                            "id": 1,
                            "name": "runtime.codex exact-head",
                            "status": "mystery",
                            "conclusion": None,
                        }
                    ]
                },
                ["runtime.codex exact-head"],
            )


if __name__ == "__main__":
    unittest.main()
