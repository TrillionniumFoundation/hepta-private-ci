"""Failure costs and integrity failures must survive an interrupted study."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from solver_accounting import model_observations
from solver_common import file_identity, save


class CostRecoveryTests(unittest.TestCase):
    def test_completed_response_is_charged_without_final_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            save(root / "generation-01/query-start.json", {"call": 1})
            save(
                root / "generation-01/response.json",
                {"usage": {"prompt_tokens": 80, "completion_tokens": 9}},
            )
            result = model_observations(root)
            self.assertEqual(
                (result["prompt_tokens"], result["generated_tokens"]), (80, 9)
            )
            self.assertEqual(result["model_queries_with_complete_receipts"], 0)
            self.assertFalse(result["token_totals_are_lower_bounds"])

    def test_interrupted_second_call_is_retained_and_cost_is_a_lower_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for call in (1, 2):
                save(root / f"generation-{call:02d}/query-start.json", {"call": call})
            save(
                root / "generation-01/response.json",
                {"usage": {"prompt_tokens": 80, "completion_tokens": 9}},
            )
            result = model_observations(root)
            self.assertEqual(result["model_queries_started"], 2)
            self.assertEqual(result["model_queries_returned"], 1)
            self.assertTrue(result["token_totals_are_lower_bounds"])

    def test_invalid_usage_cannot_reduce_recorded_cost(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            save(root / "generation-01/query-start.json", {"call": 1})
            save(
                root / "generation-01/response.json",
                {"usage": {"prompt_tokens": -1, "completion_tokens": 9}},
            )
            result = model_observations(root)
            self.assertEqual(result["responses_with_measured_tokens"], 0)
            self.assertTrue(result["token_totals_are_lower_bounds"])
            self.assertEqual(len(result["usage_errors"]), 1)


class TrajectoryIntegrityTests(unittest.TestCase):
    def run_case(self, root, close_error=False, generation_error=False):
        import repair_loop

        protocol = {
            "arms": ["no_history"],
            "task_order": ["ruff"],
            "generation": {"maximum_calls": 3},
            "trajectory_limits": {
                "wall_seconds": 900,
                "self_cpu_seconds": 1500,
                "per_file_bytes": 67108864,
                "retained_stop_threshold_bytes": 134217728,
            },
        }
        for name, value in (
            ("protocol", protocol),
            ("manifest", {}),
            ("retrieval", {"documents": []}),
        ):
            save(root / (name + ".json"), value)
        request = {
            "output": str(root / "trajectory"),
            "task": "ruff",
            "arm": "no_history",
            "protocol": str(root / "protocol.json"),
            "protocol_sha256": file_identity(root / "protocol.json")["sha256"],
            "model_manifest": str(root / "manifest.json"),
            "model_manifest_sha256": file_identity(root / "manifest.json")["sha256"],
            "retrieval": str(root / "retrieval.json"),
            "retrieval_sha256": file_identity(root / "retrieval.json")["sha256"],
            "model": "test-model-not-loaded",
            "fixture": "test-fixture",
            "runtime_profile": {},
        }

        class ControlledSolver:
            def __init__(self, _path, _manifest, _protocol, output):
                self.output = output

            def propose(self, *_args):
                save(self.output / "generation-01/query-start.json", {"call": 1})
                if generation_error:
                    raise RuntimeError("injected model execution loss")
                response = {"usage": {"prompt_tokens": 80, "completion_tokens": 9}}
                save(self.output / "generation-01/response.json", response)
                return json.dumps(
                    {
                        "schema": "hepta.memory-cell.code-edits.v1",
                        "edits": [{"path": "impl.py", "old": "a", "new": "b"}],
                    }
                ), response

            def close(self):
                if close_error:
                    raise RuntimeError("injected model byte drift")

        def gate(_task, _fixture, _candidate, output, _profile):
            result = {"accepted": True, "status": "passed"}
            save(output / "result.json", result)
            return result

        with (
            patch.object(
                repair_loop,
                "verify_request",
                return_value=({"allowed_paths": ["impl.py"]}, {"impl.py": "a"}),
            ),
            patch.object(repair_loop, "Solver", ControlledSolver),
            patch.object(repair_loop, "evaluate", gate),
            patch.object(repair_loop, "feedback", return_value="passed"),
            patch.object(repair_loop, "runtime", return_value={}),
            patch.object(repair_loop.resource, "setrlimit"),
        ):
            return repair_loop.run(request)

    def test_late_integrity_failure_invalidates_an_actual_gate_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = self.run_case(Path(temporary), close_error=True)
            self.assertTrue(result["attempts"][0]["accepted"])
            self.assertFalse(result["accepted"])
            self.assertFalse(result["execution_valid"])
            self.assertEqual(result["stop_reason"], "execution_failure")
            self.assertEqual(result["generated_tokens"], 9)

    def test_model_runtime_failure_is_not_retried_as_a_bad_proposal(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = self.run_case(Path(temporary), generation_error=True)
            self.assertEqual(len(result["attempts"]), 1)
            self.assertFalse(result["execution_valid"])
            self.assertEqual(result["model_queries_started"], 1)
            self.assertTrue(result["token_totals_are_lower_bounds"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
