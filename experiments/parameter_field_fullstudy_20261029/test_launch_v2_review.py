"""Independent controller guard tests; never spawn workers or read science."""
import copy
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from . import launch_v2 as launch


class QueueReviewTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.freeze = self.root / "fake-freeze.json"
        self.freeze.write_text("{}\n")
        digest = hashlib.sha256(self.freeze.read_bytes()).hexdigest()
        self.job = {"id": "A-17", "group": "training", "phase": "A", "seed": 17, "requires": [],
                    "completion": "operations/A-seed-17.COMPLETE.json",
                    "freeze_sha256": digest,
                    "argv": ["-B", "-m", "experiments.parameter_field_fullstudy_20261029.run_v2",
                             "--phase", "A", "--seed", "17", "--assets", "/synthetic/unused-assets",
                             "--root", str(self.root), "--freeze", str(self.freeze),
                             "--amendment", "/synthetic/unused-amendment.json", "--amendment-sha256", "a" * 64, "--execute"]}

    def check_bad(self, jobs, **extra):
        with self.assertRaises(ValueError):
            launch.validate_queue({"jobs": jobs, **extra}, self.root)

    def test_valid_nonfinal_training_queue(self):
        result = launch.validate_queue({"jobs": [self.job], "finalize": False}, self.root)
        self.assertEqual(result[0]["id"], "A-17")

    def test_unknown_or_nonlist_dependencies_are_rejected(self):
        job = copy.deepcopy(self.job)
        job["requires"] = ["missing"]
        self.check_bad([job])
        job["requires"] = "A-17"
        self.check_bad([job])

    def test_dependency_cycles_are_rejected(self):
        first, second = copy.deepcopy(self.job), copy.deepcopy(self.job)
        first["requires"] = ["A-29"]
        second.update(id="A-29", seed=29, requires=["A-17"], completion="operations/A-seed-29.COMPLETE.json")
        second["argv"][second["argv"].index("--seed") + 1] = "29"
        self.check_bad([first, second])

    def test_scientific_phase_must_match_controller_group(self):
        job = copy.deepcopy(self.job)
        job["group"] = "singleton"
        self.check_bad([job])

    def test_duplicate_flags_cannot_bypass_first_flag_validation(self):
        job = copy.deepcopy(self.job)
        job["argv"].extend(["--root", "/synthetic/other-root"])
        self.check_bad([job])

    def test_short_argv_raises_validation_error(self):
        job = copy.deepcopy(self.job)
        job["argv"] = ["-B", "-m"]
        self.check_bad([job])

    def test_empty_finalization_is_not_a_completed_study(self):
        self.check_bad([], finalize=True)

    def test_virtual_admission_timeout_starts_no_scientific_worker(self):
        queue = self.root / "queue.json"
        queue.write_text(json.dumps({"jobs": [self.job], "finalize": False}))
        registration = {"_sha256": "a" * 64, "raw_root": str(self.root),
                        "concurrency": {"worker_reservation_bytes": 768 * 1024 ** 2,
                                        "memory_margin_bytes": 1024 ** 3}}
        profile = {"current": 8 * 1024 ** 3, "effective_current": 8 * 1024 ** 3,
                   "limit": 8 * 1024 ** 3, "oom": 8, "oom_kill": 4, "allowed": False}
        args = SimpleNamespace(root=str(self.root), queue=str(queue), freeze=str(self.freeze),
                               amendment="/synthetic/unused-amendment", amendment_sha256="a" * 64,
                               resume_admission=False)

        class FakeStorage:
            def __init__(self, root, ignored):
                self.root = Path(root)

            def write_json(self, path, value, **kwargs):
                Path(path).write_text(json.dumps(value))

            def inventory(self):
                return {"logical_bytes": 0}

        class Selector:
            def select(self, timeout=0):
                return []

        clock = iter(range(0, 100000, 100))
        with ExitStack() as stack:
            stack.enter_context(patch.object(launch, "load_registration", return_value=registration))
            stack.enter_context(patch.object(launch, "verify_controller", return_value={"registered_commit": "b" * 40}))
            stack.enter_context(patch.object(launch, "StorageBudget", FakeStorage))
            stack.enter_context(patch.object(launch, "memory_profile", return_value=profile))
            stack.enter_context(patch.object(launch, "memory_admission", return_value=profile))
            stack.enter_context(patch.object(launch, "pending_growth", return_value=0))
            stack.enter_context(patch.object(launch.selectors, "DefaultSelector", return_value=Selector()))
            stack.enter_context(patch.object(launch.time, "monotonic", side_effect=lambda: next(clock)))
            stack.enter_context(patch.object(launch.time, "sleep"))
            stack.enter_context(patch("builtins.print"))
            process = stack.enter_context(patch.object(launch.subprocess, "Popen"))
            self.assertEqual(launch.run(args), 75)
            process.assert_not_called()
        receipt = json.loads((self.root / "controller/ADMISSION_FAILED.json").read_text())
        self.assertEqual(receipt["status"], "ADMISSION_BLOCKED")
        self.assertEqual(receipt["scientific_workers_started"], 0)
        self.assertEqual(receipt["gradient_work_during_admission_wait"], 0)
        self.assertFalse(receipt["scientific_outcome_claim"])
        self.assertGreaterEqual(receipt["admission_wait_seconds"], 300)
        self.assertEqual(receipt["pending"], ["A-17"])
        self.assertFalse((self.root / "controller/EXECUTION_FAILED.json").exists())
        self.assertFalse((self.root / "stage_A").exists())

    def test_controller_commit_must_be_real_sha_syntax(self):
        prefix = Path(launch.__file__).parent.relative_to(launch.ROOT)
        freeze = {"allowed_phases": ["OPS"], "attempt_id": "attempt02", "execution_kind": "controller",
                  "operational_amendment_sha256": "f" * 64, "registered_commit": "z" * 40,
                  "source_files": {(prefix / name).as_posix(): "a" * 64
                                   for name in ("launch_v2.py", "resource_v2.py", "run_v2.py")}}
        path = self.root / "controller-freeze.json"
        path.write_text(json.dumps(freeze))
        with patch.object(launch, "verify_files"):
            with self.assertRaises(ValueError):
                launch.verify_controller(SimpleNamespace(freeze=str(path)), {"_sha256": "f" * 64})


if __name__ == "__main__":
    unittest.main()
