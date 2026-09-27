from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).with_name("runtime_agentd_main_baseline.py")
SPEC = importlib.util.spec_from_file_location("runtime_agentd_main_baseline", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def run(run_id: int, run_number: int, sha_char: str, conclusion: str = "success") -> dict:
    return {
        "id": run_id,
        "run_number": run_number,
        "head_sha": sha_char * 40,
        "head_branch": "main",
        "event": "push",
        "status": "completed",
        "conclusion": conclusion,
    }


def jobs(run_id: int, conclusion: str = "success") -> list[dict]:
    return [
        {
            "id": run_id * 10,
            "name": "CI required",
            "status": "completed",
            "conclusion": conclusion,
        }
    ]


class MainBaselineTests(unittest.TestCase):
    def test_three_consecutive_candidates_succeed(self) -> None:
        runs = [run(30, 30, "a"), run(29, 29, "b"), run(28, 28, "c")]
        result = MODULE.evaluate_runs(
            runs,
            lambda run_id: jobs(run_id),
            "CI required",
            3,
            30,
            "a" * 40,
        )
        self.assertEqual(result["baseline_result"], "success")
        self.assertEqual(result["consecutive_successes"], 3)
        self.assertFalse(result["production_activation"])

    def test_latest_run_must_be_triggering_run(self) -> None:
        runs = [run(30, 30, "a"), run(29, 29, "b"), run(28, 28, "c")]
        with self.assertRaisesRegex(ValueError, "triggering run"):
            MODULE.evaluate_runs(
                runs,
                lambda run_id: jobs(run_id),
                "CI required",
                3,
                29,
                "b" * 40,
            )

    def test_failed_main_candidate_breaks_sequence(self) -> None:
        runs = [run(30, 30, "a"), run(29, 29, "b", "failure"), run(28, 28, "c")]
        with self.assertRaisesRegex(ValueError, "did not succeed"):
            MODULE.evaluate_runs(
                runs,
                lambda run_id: jobs(run_id),
                "CI required",
                3,
                30,
                "a" * 40,
            )

    def test_failed_required_job_breaks_sequence(self) -> None:
        runs = [run(30, 30, "a"), run(29, 29, "b"), run(28, 28, "c")]

        def loader(run_id: int) -> list[dict]:
            return jobs(run_id, "failure" if run_id == 29 else "success")

        with self.assertRaisesRegex(ValueError, "required job did not succeed"):
            MODULE.evaluate_runs(
                runs,
                loader,
                "CI required",
                3,
                30,
                "a" * 40,
            )

    def test_duplicate_candidate_sha_is_rejected(self) -> None:
        runs = [run(30, 30, "a"), run(29, 29, "a"), run(28, 28, "c")]
        with self.assertRaisesRegex(ValueError, "duplicate run or candidate SHA"):
            MODULE.evaluate_runs(
                runs,
                lambda run_id: jobs(run_id),
                "CI required",
                3,
                30,
                "a" * 40,
            )

    def test_non_main_or_non_push_runs_do_not_count(self) -> None:
        ignored = run(31, 31, "d")
        ignored["event"] = "workflow_dispatch"
        runs = [ignored, run(30, 30, "a"), run(29, 29, "b")]
        with self.assertRaisesRegex(ValueError, "not enough completed"):
            MODULE.evaluate_runs(
                runs,
                lambda run_id: jobs(run_id),
                "CI required",
                3,
                30,
                "a" * 40,
            )


if __name__ == "__main__":
    unittest.main()
