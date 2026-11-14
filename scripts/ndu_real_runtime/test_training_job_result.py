"""Synthetic protocol controls only; no trainer/model fit or production authority."""

import copy
from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from . import pipeline, training_job_result as bridge
from .controllers import ControlPlan
from .metering import Meter, atomic_json, canonical_sha, file_sha
from .test_recursive_contract import numerical_records
from .training_grid import fit_grid


class ResultAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        source = Path(__file__).resolve().parents[2]
        self.config = {
            "python": sys.executable,
            "scripts_root": str(source / "scripts"),
            "repository_root": str(source),
            "pillow_path": str(self.root / "empty"),
        }
        self.job = {
            "job_id": "engineering-fixture-only",
            "output": str(self.root / "output"),
            "command": {
                "executable": sys.executable,
                "args": [
                    "-m",
                    "ndu_real_runtime.training",
                    "--output",
                    str(self.root / "output"),
                    "--seed",
                    "7",
                    "--core",
                    "ordinary",
                    "--run-id",
                    "engineering-fixture-only",
                    "--bootstrap",
                ],
            },
        }

    def admission(self):
        return bridge.admit(self.job, self.config, "2026-11-08T00:00:00+00:00")

    def fixture_output(self, admission):
        """Consistent schema fixtures; deliberately not a fitted Tensor checkpoint."""
        output = Path(admission["output"])
        output.mkdir()
        receipt = copy.deepcopy(admission["expected_receipt"])
        atomic_json(
            output / "started.json",
            dict(admission["expected_started"], status="STARTED"),
        )
        (output / "weights.pt").write_bytes(
            b"explicit protocol fixture, not trained weights"
        )
        receipt.update(
            status={
                "bootstrap": "BOOTSTRAP_READY_NOT_A_FIT",
                "content": "CONTENT_PRETRAINED",
                "fit": "FITTED_NOT_ADOPTED",
            }[receipt["stage"]],
            weights_sha256=file_sha(output / "weights.pt"),
            checkpoint_parameter_replay_exact=True,
        )
        if admission["records"] is not None:
            receipt["records"] = {
                k: v for k, v in admission["records"].items() if k != "rows"
            }
            receipt["records"]["counts"] = {"rows": admission["records"]["rows"]}
        if admission["pretrained_lineage"] is not None:
            receipt["reused_content"] = admission["pretrained_lineage"]
        profile = {
            "schema": "ndu.real.deployment-profile.v1",
            "weights_sha256": receipt["weights_sha256"],
            "core": receipt["core"],
            "memory_mode": receipt["memory_mode"],
            "utility_profile_sha256": receipt["utility_profile_sha256"],
            "control_profile_sha256": receipt["control_profile_sha256"],
            "rubric_sha256": receipt.get("rubric_sha256"),
            "recursive_policy_trained": False,
        }
        receipt["deployment_profile_sha256"] = atomic_json(
            output / "deployment-profile.json", profile
        )
        meter = Meter(receipt["run_id"], journal_path=output / "training.meter.jsonl")
        with meter.stage("sync", "protocol fixture only"):
            pass
        receipt["meter"] = meter.finish("SUCCEEDED")
        atomic_json(output / "receipt.json", receipt)
        return receipt

    def fixture_executable(self, source):
        """Real child executable; its output is explicitly a protocol fixture."""
        executable = self.root / "fixture-python"
        executable.write_text("#!" + sys.executable + "\n" + source)
        executable.chmod(0o700)
        self.config["python"] = self.job["command"]["executable"] = str(executable)

    def test_actual_pipeline_callsite_and_readonly_reconciliation(self):
        logs = self.root / "jobs"
        directory = logs / canonical_sha(self.job["job_id"])[:32]
        self.fixture_executable(
            "import json\nfrom pathlib import Path\n"
            "from ndu_real_runtime.test_training_job_result import ResultAdmissionTests\n"
            f"admitted = json.loads(Path({str(directory / 'admission.json')!r}).read_text())\n"
            "ResultAdmissionTests().fixture_output(admitted)\n"
            "print('explicit protocol fixture stdout', flush=True)\n"
        )
        result = pipeline.run_training_job(self.job, self.config, logs)
        self.assertGreater(result["process_supervision"]["pid"], 0)
        self.assertTrue(result["process_supervision"]["cleanup_complete"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            result["artifact_validation"]["state"], "VALIDATED_UNAUTHENTICATED"
        )
        self.assertFalse(result["artifact_validation"]["production_stage_completed"])
        directory = logs / canonical_sha(self.job["job_id"])[:32]
        before = {str(p): file_sha(p) for p in self.root.rglob("*") if p.is_file()}
        with patch.object(
            pipeline,
            "run_logged",
            side_effect=AssertionError("reconciliation must not dispatch"),
        ):
            for _ in range(2):
                self.assertEqual(
                    bridge.reconcile(directory, result["admission_sha256"])["state"],
                    "VALIDATED_UNAUTHENTICATED",
                )
            with self.assertRaises(FileExistsError):
                pipeline.run_training_job(self.job, self.config, logs)
        self.assertEqual(
            before, {str(p): file_sha(p) for p in self.root.rglob("*") if p.is_file()}
        )
        environment = dict(
            os.environ,
            PYTHONPATH=self.config["scripts_root"],
            PYTHONDONTWRITEBYTECODE="1",
        )
        observed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "ndu_real_runtime.training_job_result",
                "--operation-directory",
                str(directory),
                "--expected-admission-sha256",
                result["admission_sha256"],
            ],
            env=environment,
            capture_output=True,
            timeout=10,
            check=True,
        )
        self.assertEqual(
            json.loads(observed.stdout)["state"], "VALIDATED_UNAUTHENTICATED"
        )
        self.assertEqual(
            before, {str(p): file_sha(p) for p in self.root.rglob("*") if p.is_file()}
        )
        legacy = self.root / "legacy-v2"
        legacy.mkdir()
        original = json.loads((directory / "admission.json").read_text())
        removed = original.pop("supervision")
        for name in removed["source_files"]:
            original["input_files"].pop(name)
        legacy_result = copy.deepcopy(result)
        legacy_result.pop("supervision")
        legacy_result.pop("process_supervision")
        legacy_result["admission_sha256"] = atomic_json(
            legacy / "admission.json", original
        )
        for name in ("stdout.log", "stderr.log"):
            shutil.copyfile(directory / name, legacy / name)
        atomic_json(legacy / "result.json", legacy_result)
        self.assertEqual(
            bridge.reconcile(legacy, legacy_result["admission_sha256"])["state"],
            "VALIDATED_UNAUTHENTICATED",
        )
        for field, value in (("cleanup_complete", False), ("returncode", None)):
            changed = copy.deepcopy(result)
            changed["process_supervision"][field] = value
            (directory / "result.json").write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, "conflicts with supervisor"):
                bridge.reconcile(directory, result["admission_sha256"])
        retained = json.loads((directory / "result.json").read_text())
        retained["error"] = {"type": "retained original failure"}
        (directory / "result.json").write_text(json.dumps(retained))
        with self.assertRaisesRegex(ValueError, "conflicts with retained"):
            bridge.reconcile(directory, result["admission_sha256"])

    def test_budget_duplicate_and_foreign_operation_rejected_before_dispatch(self):
        for extra in (
            ["--max-wall-seconds", "3600"],
            ["--seed", "8"],
            ["--run-id", "other"],
            ["--unknown", "value"],
        ):
            with self.subTest(extra=extra):
                original = copy.deepcopy(self.job)
                self.job["command"]["args"] += extra
                with self.assertRaises(ValueError):
                    self.admission()
                self.job = original
        for field, wrong in (
            ("core", "hepta"),
            ("seed", 8),
            ("phase", "fit"),
            ("controller", "ndu"),
            ("regime", "joint"),
            ("lr", 0.01),
            ("observation_policy", "matched_episodes"),
        ):
            with self.subTest(indexed_field=field):
                self.job[field] = wrong
                with self.assertRaisesRegex(ValueError, "Indexed job identity"):
                    self.admission()
                del self.job[field]
        self.job["command"]["args"] += ["--max-wall-seconds", "601"]
        with patch.object(
            pipeline,
            "run_logged",
            side_effect=AssertionError("invalid budget must not launch"),
        ):
            result = pipeline.run_training_job(
                self.job, self.config, self.root / "jobs"
            )
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["admission_sha256"])
        self.assertGreaterEqual(result["wall_seconds"], 0)

    def test_grid_source_memory_and_observation_bound_before_dispatch(self):
        self.job["command"]["args"] += [
            "--observation-policy",
            "matched_episodes",
        ]
        self.job.update(
            observation_policy="matched_episodes",
            memory_mode="reset",
            source_pins=bridge._source_pins(),
        )
        admission = self.admission()
        self.assertEqual(
            admission["expected_receipt"]["observation_policy"], "matched_episodes"
        )
        self.assertEqual(
            admission["expected_started"]["observation_policy"], "matched_episodes"
        )
        for field, wrong in (
            ("source_pins", {}),
            ("memory_mode", "persistent"),
            ("observation_policy", "legacy"),
        ):
            with self.subTest(field=field):
                original = self.job[field]
                self.job[field] = wrong
                with patch.object(
                    pipeline,
                    "run_logged",
                    side_effect=AssertionError("invalid identity must not launch"),
                ) as launch:
                    result = pipeline.run_training_job(
                        self.job, self.config, self.root / ("jobs-" + field)
                    )
                    launch.assert_not_called()
                self.assertEqual(result["status"], "failed")
                self.assertIsNone(result["admission_sha256"])
                self.job[field] = original

    def test_real_grid_rows_reject_changed_planned_source_before_dispatch(self):
        records = self.root / "records.jsonl"
        rows = numerical_records(ControlPlan(memory_mode="persistent"))
        records.write_text("".join(json.dumps(row) + "\n" for row in rows))
        plans = {}
        for mode in ("reset", "persistent"):
            path = self.root / (mode + ".json")
            atomic_json(path, {"control": asdict(ControlPlan(memory_mode=mode))})
            plans[mode] = path
        for paired in (False, True):
            with self.subTest(paired=paired):
                grid = fit_grid(
                    records,
                    file_sha(records),
                    self.root / ("paired" if paired else "legacy"),
                    python=sys.executable,
                    seeds=(7,),
                    head_lrs=(0.003,),
                    regimes=("frozen",),
                    controllers=("light",),
                    control_plans=plans if paired else None,
                    observation_policy="matched_episodes" if paired else "legacy",
                )
                for row in grid["jobs"]:
                    self.assertEqual(row["source_pins"], grid["intent"]["source_pins"])
                job = next(row for row in grid["jobs"] if row["phase"] == "content")
                admitted = bridge.admit(job, self.config, "2026-11-09T00:00:00+00:00")
                self.assertEqual(
                    admitted["expected_receipt"]["source_pins"],
                    grid["intent"]["source_pins"],
                )
                changed_source = dict(grid["intent"]["source_pins"])
                changed_source["scripts/ndu_real_runtime/training.py"] = "0" * 64
                with (
                    patch.object(bridge, "_source_pins", return_value=changed_source),
                    patch.object(pipeline, "run_logged") as launch,
                ):
                    result = pipeline.run_training_job(
                        job,
                        self.config,
                        self.root / ("jobs-paired" if paired else "jobs-legacy"),
                    )
                    launch.assert_not_called()
                self.assertEqual(result["status"], "failed")
                self.assertIsNone(result["admission_sha256"])
                self.assertIn("Indexed source pins", result["error"]["message"])

    def test_verification_time_is_charged_before_completed_status(self):
        def child(*args, **kwargs):
            self.fixture_output(self.admission())
            return {
                "returncode": 0,
                "error": None,
                "cleanup_complete": True,
                "policy": bridge.supervision_policy(),
            }

        with (
            patch.object(pipeline, "run_logged", child),
            patch.object(pipeline.time, "perf_counter", side_effect=[0, 1, 659, 661]),
        ):
            result = pipeline.run_training_job(
                self.job, self.config, self.root / "jobs"
            )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["wall_seconds"], 661)
        self.assertIsNone(result["weights_sha256"])

    def test_per_job_budget_controls_admission_launch_and_final_verification(self):
        self.job["command"]["args"] += ["--max-wall-seconds", "5"]
        for limit in (6.0, 10):
            self.job["timeout_seconds"] = limit
            budget = self.admission()["budget"]
            self.assertEqual(budget["supervisor_limit_seconds"], limit)
            self.assertEqual(budget["reserved_startup_and_io_seconds"], limit - 5)
        for index, limit in enumerate(
            (None, True, 0, -1, 5.9, 661, float("nan"), float("inf"))
        ):
            with self.subTest(limit=limit):
                self.job["timeout_seconds"] = limit
                with patch.object(pipeline, "run_logged") as launch:
                    result = pipeline.run_training_job(
                        self.job,
                        self.config,
                        self.root / ("invalid-budget-" + str(index)),
                    )
                    launch.assert_not_called()
                self.assertIsNone(result["admission_sha256"])
                self.assertEqual(result["status"], "failed")
        del self.job["timeout_seconds"]
        self.assertEqual(self.admission()["budget"]["supervisor_limit_seconds"], 660)
        self.job["timeout_seconds"] = 10

        def child(*args, **kwargs):
            self.assertEqual(kwargs["timeout"], 9)
            self.fixture_output(self.admission())
            return {
                "returncode": 0,
                "error": None,
                "cleanup_complete": True,
                "policy": bridge.supervision_policy(),
            }

        with (
            patch.object(pipeline, "run_logged", child),
            patch.object(pipeline.time, "perf_counter", side_effect=[0, 1, 9, 11]),
        ):
            result = pipeline.run_training_job(
                self.job, self.config, self.root / "short-job"
            )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["wall_seconds"], 11)
        self.assertIsNone(result["weights_sha256"])

    def test_short_job_reaps_real_child_inside_its_original_envelope(self):
        self.job["command"]["args"] += ["--max-wall-seconds", "1"]
        self.job["timeout_seconds"] = 2
        self.fixture_executable(
            "import time\nprint('started', flush=True)\ntime.sleep(30)\n"
        )
        result = pipeline.run_training_job(
            self.job, self.config, self.root / "short-real-job"
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["type"], "TimeoutExpired")
        self.assertTrue(result["process_supervision"]["child_reaped"])
        self.assertTrue(result["process_supervision"]["cleanup_complete"])
        self.assertLessEqual(result["process_supervision"]["timeout_seconds"], 2)
        self.assertEqual(result["budget"]["supervisor_limit_seconds"], 2)

    def test_real_child_zero_exit_does_not_bypass_artifact_validation(self):
        self.fixture_executable("print('partial stdout', flush=True)\n")
        result = pipeline.run_training_job(self.job, self.config, self.root / "jobs")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["type"], "FileNotFoundError")
        self.assertIsNone(result["artifact_validation"])

    def test_detached_pipe_holder_remains_unresolved_without_replaying_operation(self):
        self.fixture_executable(
            "import subprocess,sys\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)\n"
            "print(child.pid, flush=True)\n"
        )
        logs = self.root / "jobs"
        directory = logs / canonical_sha(self.job["job_id"])[:32]
        try:
            result = pipeline.run_training_job(self.job, self.config, logs)
            self.assertEqual(result["exit_code"], 0)
            self.assertEqual(result["status"], "unresolved")
            self.assertEqual(
                bridge.reconcile(directory, result["admission_sha256"])["state"],
                "UNRESOLVED",
            )
            with self.assertRaises(FileExistsError):
                pipeline.run_training_job(self.job, self.config, logs)
        finally:
            # This explicitly detached test child is outside supervisor scope.
            pid = int((directory / "stdout.log").read_text())
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def test_parent_supervision_is_bound_outside_model_lineage(self):
        admission = self.admission()
        supervision = admission["supervision"]
        self.assertLessEqual(
            supervision["policy"]["stream_limit_bytes"], 16 * 1024 * 1024
        )
        for name, pin in supervision["source_files"].items():
            self.assertEqual(pin, admission["input_files"][name])
            self.assertNotIn(
                str(Path(name).relative_to(self.config["repository_root"])),
                admission["expected_receipt"]["source_pins"],
            )
        self.fixture_output(admission)
        changed = copy.deepcopy(admission)
        name = next(iter(supervision["source_files"]))
        changed["input_files"][name]["sha256"] = "0" * 64
        with self.assertRaisesRegex(
            ValueError, "Admitted source/data/control/lineage changed"
        ):
            bridge.validate_output(changed, exit_code=0, supervisor_wall_seconds=1)

    def test_same_weights_cannot_hide_foreign_receipt_or_profile(self):
        admission = self.admission()
        receipt = self.fixture_output(admission)
        receipt["engineering_large_receipt"] = "x" * (bridge.JSON_LIMIT + 1)
        (self.root / "output/receipt.json").write_text(json.dumps(receipt))
        self.assertEqual(
            bridge.validate_output(admission, exit_code=0, supervisor_wall_seconds=1)[
                "state"
            ],
            "VALIDATED_UNAUTHENTICATED",
        )
        original = json.dumps(receipt)
        for field, value in (
            ("source_pins", {}),
            ("memory_mode", "persistent"),
            ("observation_policy", "matched_episodes"),
            ("schema", "foreign"),
            ("controller", "ndu"),
            ("config", {}),
            ("runtime_job_id", "foreign"),
            ("run_id", "foreign"),
        ):
            with self.subTest(field=field):
                bad = json.loads(original)
                bad[field] = value
                (self.root / "output/receipt.json").write_text(json.dumps(bad))
                with self.assertRaises(ValueError):
                    bridge.validate_output(
                        admission, exit_code=0, supervisor_wall_seconds=1
                    )
        (self.root / "output/receipt.json").write_text(original)
        started = self.root / "output/started.json"
        original_started = started.read_text()
        changed_started = json.loads(original_started)
        changed_started["observation_policy"] = "matched_episodes"
        started.write_text(json.dumps(changed_started))
        with self.assertRaisesRegex(ValueError, "Started identity"):
            bridge.validate_output(admission, exit_code=0, supervisor_wall_seconds=1)
        started.write_text(original_started)
        profile = self.root / "output/deployment-profile.json"
        bad = json.loads(profile.read_text())
        bad["memory_mode"] = "persistent"
        profile.write_text(json.dumps(bad))
        receipt["deployment_profile_sha256"] = file_sha(profile)
        (self.root / "output/receipt.json").write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, "Deployment profile fields"):
            bridge.validate_output(admission, exit_code=0, supervisor_wall_seconds=1)

    def test_persistent_record_schema_and_pretrained_lineage(self):
        records = self.root / "records.jsonl"
        rows = numerical_records(ControlPlan(memory_mode="persistent"))
        records.write_text("".join(json.dumps(row) + "\n" for row in rows))
        args = self.job["command"]["args"]
        args.remove("--bootstrap")
        args += [
            "--content-only",
            "--memory-mode",
            "persistent",
            "--records",
            str(records),
            "--expected-records-sha256",
            file_sha(records),
        ]
        admission = self.admission()
        self.fixture_output(admission)
        self.assertEqual(
            bridge.validate_output(admission, exit_code=0, supervisor_wall_seconds=1)[
                "state"
            ],
            "VALIDATED_UNAUTHENTICATED",
        )
        args.remove("--content-only")
        args[args.index("--output") + 1] = self.job["output"] = str(
            self.root / "fit-output"
        )
        args += ["--pretrained", str(self.root / "output")]
        fitted = self.admission()
        self.assertEqual(fitted["pretrained_lineage"]["run_id"], self.job["job_id"])
        self.job["depends_on"] = ["another-original-operation"]
        with self.assertRaisesRegex(ValueError, "dependency differs"):
            self.admission()
        del self.job["depends_on"]
        previous_path = self.root / "output/receipt.json"
        original_previous = previous_path.read_text()
        previous = json.loads(original_previous)
        previous["observation_policy"] = "matched_episodes"
        previous_path.write_text(json.dumps(previous))
        with self.assertRaisesRegex(ValueError, "Pretrained lineage"):
            self.admission()
        previous_path.write_text(original_previous)
        (self.root / "output/weights.pt").write_bytes(b"changed despite same receipt")
        with self.assertRaisesRegex(ValueError, "Pretrained lineage"):
            self.admission()

    def test_missing_outer_terminal_and_historical_admission_stay_unresolved(self):
        directory = self.root / "operation"
        directory.mkdir()
        admission = self.admission()
        self.fixture_output(admission)
        pin = atomic_json(directory / "admission.json", admission)
        self.assertEqual(bridge.reconcile(directory, pin)["state"], "UNRESOLVED")
        with self.assertRaisesRegex(ValueError, "original digest"):
            bridge.reconcile(directory, "0" * 64)
        old = self.root / "historical"
        old.mkdir()
        pin = atomic_json(
            old / "admission.json",
            {
                "schema": "ndu.real.training-job-admission.v1",
                "original_operation_id": "historical",
            },
        )
        self.assertEqual(bridge.reconcile(old, pin)["state"], "UNATTRIBUTED_HISTORICAL")

    def test_deadline_missing_exit_changed_input_and_partial_meter_rejected(self):
        if hasattr(os, "mkfifo"):
            fifo = self.root / "nonregular-input"
            os.mkfifo(fifo)
            with self.assertRaisesRegex(ValueError, "Nonregular"):
                bridge.bounded(fifo)
        admission = self.admission()
        receipt = self.fixture_output(admission)
        for code, wall in ((None, 1), (0, 661), (0, float("nan"))):
            with self.assertRaises(ValueError):
                bridge.validate_output(
                    admission, exit_code=code, supervisor_wall_seconds=wall
                )
        admission["input_files"][str(self.root / "missing-input")] = {
            "sha256": "a" * 64,
            "bytes": 1,
        }
        with self.assertRaises(OSError):
            bridge.validate_output(admission, exit_code=0, supervisor_wall_seconds=1)
        del admission["input_files"][str(self.root / "missing-input")]
        failed_meter = Meter(
            receipt["run_id"], journal_path=self.root / "failed-meter.jsonl"
        )
        failed_receipt = copy.deepcopy(receipt)
        failed_receipt["meter"] = failed_meter.finish("FAILED")
        (self.root / "output/receipt.json").write_text(json.dumps(failed_receipt))
        (self.root / "output/training.meter.jsonl").write_bytes(
            (self.root / "failed-meter.jsonl").read_bytes()
        )
        with self.assertRaisesRegex(ValueError, "Meter identity/terminal"):
            bridge.validate_output(admission, exit_code=0, supervisor_wall_seconds=1)
        receipt["meter"]["raw_spans"]["events"].pop()
        (self.root / "output/receipt.json").write_text(json.dumps(receipt))
        with self.assertRaises(ValueError):
            bridge.validate_output(admission, exit_code=0, supervisor_wall_seconds=1)


if __name__ == "__main__":
    unittest.main()
