"""Focused metadata fixtures; no scientific task, model, data or endpoint is run."""

from copy import deepcopy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from . import analysis_worker, common as c, initialize, registration


class RegistrationTests(unittest.TestCase):
    def test_actual_actions_identity_is_bound_without_recording_credentials(self):
        values = {
            "GITHUB_REPOSITORY": "TrillionniumFoundation/hepta-private-ci",
            "GITHUB_SHA": "a" * 40,
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_JOB": "synthetic-fixture",
            "ACTIONS_RUNTIME_TOKEN": "synthetic-placeholder",
            "ACTIONS_RESULTS_URL": "https://fixture.invalid",
        }
        with patch.dict(initialize.os.environ, values, clear=True):
            result = initialize.actions_identity("a" * 40)
            self.assertEqual(
                set(result), {"repository", "run_id", "run_attempt", "head_sha", "job"}
            )
            self.assertNotIn("synthetic-placeholder", str(result))
            with self.assertRaises(ValueError):
                initialize.actions_identity("b" * 40)
            del initialize.os.environ["ACTIONS_RUNTIME_TOKEN"]
            with self.assertRaises(ValueError):
                initialize.actions_identity("a" * 40)

    def test_exact_committed_source_and_extra_file_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for args in (
                ("init", "-q"),
                ("config", "user.name", "Synthetic Fixture"),
                ("config", "user.email", "fixture@example.invalid"),
            ):
                c.git(root, *args)
            target = root / "fixed.py"
            target.write_text("# synthetic source identity\n")
            c.git(root, "add", "fixed.py")
            c.git(root, "commit", "-qm", "Synthetic identity fixture")
            commit = c.git(root, "rev-parse", "HEAD").decode().strip()
            sources = {"fixed.py": c.descriptor(target)["sha256"]}
            c.committed_sources(root, commit, sources)
            (root / "shadow.py").write_text("# unregistered\n")
            with self.assertRaisesRegex(ValueError, "uncommitted or untracked"):
                c.committed_sources(root, commit, sources)
            (root / "shadow.py").unlink()
            target.write_text("# changed bytes\n")
            with self.assertRaises(ValueError):
                c.committed_sources(root, commit, sources)

    def test_initial_queue_is_fresh_complete_prefix(self):
        old = {
            "schema": "hepta.fullstudy.queue.2",
            "attempt_id": "attempt02",
            "finalize": False,
            "jobs": [
                {
                    "id": key,
                    "phase": "C" if key == "C" else "A",
                    "requires": [],
                    "argv": [
                        "-B",
                        "-m",
                        "fixed",
                        "--root",
                        "/old",
                        "--freeze",
                        "/old/freeze",
                        "--amendment",
                        "/old/amend",
                        "--amendment-sha256",
                        "old",
                    ],
                }
                for key in c.ORDER[:4]
            ],
        }
        before = deepcopy(old)
        with patch.object(c, "read", return_value=old):
            queue = initialize.initial_queue(
                {"path": "/new/A", "sha256": "a"},
                {"path": "/new/C", "sha256": "c"},
                {"path": "/new/profile", "sha256": "p"},
                {"raw_root": "/new/raw", "assets_root": "/new/assets"},
            )
        self.assertEqual(old, before)
        self.assertEqual([j["id"] for j in queue["jobs"]], list(c.ORDER[:4]))
        self.assertFalse(queue["finalize"])
        self.assertEqual(queue["execution_episode"], c.EPISODE)
        for index, job in enumerate(queue["jobs"]):
            self.assertEqual(job["requires"], [] if not index else [c.ORDER[index - 1]])
            self.assertEqual(job["freeze_sha256"], "c" if job["phase"] == "C" else "a")
            self.assertNotIn("/old", job["argv"])

    def test_followup_serialization_preserves_all_previous_jobs_and_dependencies(self):
        queue = {
            "jobs": [
                {"id": name, "requires": list(c.ORDER[:i])}
                for i, name in enumerate(c.ORDER[:4])
            ]
        }
        additions = [
            {"id": name, "requires": list(c.ORDER[:3])} for name in c.ORDER[4:11]
        ]
        before = deepcopy(queue), deepcopy(additions)

        def original(q, added, root, final):
            return {"jobs": q["jobs"] + added, "finalize": final}

        result = registration.serial_extension(original, queue, additions, None, False)
        self.assertEqual((queue, additions), before)
        self.assertEqual(result["jobs"][:4], queue["jobs"])
        for index in range(4, 11):
            self.assertEqual(
                set(result["jobs"][index]["requires"]),
                set(c.ORDER[:3]) | {c.ORDER[index - 1]},
            )
        with self.assertRaisesRegex(ValueError, "queue order"):
            registration.serial_extension(original, queue, additions[:-1], None, False)

    def test_bundle_cost_and_payload_are_jointly_bound(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            member = c.write_new(directory / "QUEUE_EXTENDED.json", {"synthetic": True})
            bundle = c.write_new(
                directory / "BUNDLE.json",
                {
                    "workers_started": 0,
                    "files": {
                        "QUEUE_EXTENDED.json": {
                            k: member[k] for k in ("bytes", "sha256")
                        }
                    },
                },
            )
            c.write_new(directory / "REGISTRATION_COST.json", {"bundle": bundle})
            self.assertEqual(
                registration.verified_bundle(directory)["QUEUE_EXTENDED.json"], member
            )
            (directory / "QUEUE_EXTENDED.json").write_text("{}\n")
            with self.assertRaisesRegex(ValueError, "member differs"):
                registration.verified_bundle(directory)

    def test_historical_projection_does_not_manufacture_receipts(self):
        value, item = analysis_worker.history()
        spec = {
            "execution07_historical_costs": {
                "schema": "hepta.execution07.cost-adapter-binding.1",
                "projection": item,
                "adapter_source": c.descriptor(
                    Path(analysis_worker.__file__).resolve()
                ),
            },
            "integrity": value["original_integrity"],
            "engineering_preflights": [],
            "failed_attempts": [],
        }
        result = analysis_worker.prior_costs(spec)
        self.assertEqual(result["gradient_microsteps_known_lower_bound"], 253328)
        self.assertTrue(result["unknown_partial_work"])
        self.assertFalse(result["whole_history_cpu_or_wall_total_known"])
        self.assertEqual(result["engineering_receipts"], [])
        self.assertTrue(
            spec["integrity"]["historical_exact_regression_gate"].startswith("FAIL")
        )
        self.assertEqual(
            sum(
                r["episode"] == "execution04_completed_A17"
                for r in result["previous_episode_cost_rows"]
            ),
            1,
        )
        corrupted = deepcopy(spec)
        corrupted["integrity"]["historical_exact_regression_gate"] = "PASS"
        with self.assertRaises(ValueError):
            analysis_worker.prior_costs(corrupted)

    def test_cost_adapter_restores_scientific_module_and_counts_current_once(self):
        value, item = analysis_worker.history()
        spec = {
            "execution07_historical_costs": {
                "schema": "hepta.execution07.cost-adapter-binding.1",
                "projection": item,
                "adapter_source": c.descriptor(
                    Path(analysis_worker.__file__).resolve()
                ),
            },
            "integrity": value["original_integrity"],
            "engineering_preflights": [],
            "failed_attempts": [],
        }
        untouched = object()
        module = SimpleNamespace(
            __file__=analysis_worker.__file__,
            prior_costs=untouched,
            cost_rows=untouched,
            render=lambda result: "original scientific report",
            microsteps=lambda ledger: ledger["steps"],
            scientific_thresholds=untouched,
        )
        original = module.prior_costs, module.cost_rows, module.render
        config = {
            "source_files": {
                "experiments/parameter_field_fullstudy_20261029/report_results.py": c.descriptor(
                    module.__file__
                )["sha256"]
            }
        }
        with patch.object(
            analysis_worker.importlib, "import_module", return_value=module
        ):
            with self.assertRaisesRegex(RuntimeError, "synthetic interruption"):
                with analysis_worker.installed(spec, config):
                    result = module.cost_rows(
                        {
                            ("A", 17): {
                                "costs": {
                                    "steps": 7,
                                    "wall_seconds": 1,
                                    "cpu_seconds": 2,
                                }
                            }
                        },
                        {("A", 17): {"process_peak_rss_bytes": 99}},
                        {
                            "A": {
                                "scoring_costs": {
                                    "steps": 0,
                                    "wall_seconds": 3,
                                    "cpu_seconds": 4,
                                }
                            }
                        },
                        spec,
                    )
                    self.assertEqual(result["completed_receipt_gradient_microsteps"], 7)
                    self.assertEqual(
                        result["all_attempts_gradient_microsteps_known_lower_bound"],
                        253335,
                    )
                    self.assertEqual(len(result["rows"]), 2)
                    self.assertIs(module.scientific_thresholds, untouched)
                    raise RuntimeError("synthetic interruption")
        self.assertEqual(
            (module.prior_costs, module.cost_rows, module.render), original
        )
        self.assertFalse(hasattr(module, "_execution07_cost_adapter"))

    def test_destination_runtime_accepts_only_actual_finite_limit_schema(self):
        executable = Path(sys.executable).resolve()
        info = c.descriptor(executable)
        contract = {
            "python": str(Path(sys.executable).absolute()),
            "python_base": str(executable.parent),
            "public_python_files": [
                {
                    "name": "python/" + executable.name,
                    "size": info["bytes"],
                    "sha256": info["sha256"],
                }
            ],
            "runtime_expected": {
                "descriptor": {"python": sys.version},
                "runtime_sha256": "fixed",
            },
            "docker_memory_max_bytes": 8 * 1024**3,
        }
        module = SimpleNamespace(
            capacity=lambda path: {"original_joint_pass": True},
            runtime_probe=lambda expected: {
                "exact_match": True,
                "runtime_sha256": "fixed",
                "model_created": False,
                "scientific_inputs_opened": False,
            },
            memory_node=lambda path: {"finite_limit": 8 * 1024**3},
            process_probe=lambda: {"supported": True},
            filesystem_probe=lambda path: {
                k: True
                for k in ("fsync", "atomic_rename", "flock", "xattr", "byte_readback")
            },
        )
        fake_spec = SimpleNamespace(
            loader=SimpleNamespace(exec_module=lambda value: None)
        )
        with (
            patch.object(
                initialize.importlib.util,
                "spec_from_file_location",
                return_value=fake_spec,
            ),
            patch.object(
                initialize.importlib.util, "module_from_spec", return_value=module
            ),
            patch.object(initialize.time, "sleep"),
        ):
            result = initialize.destination_runtime(
                contract, Path(tempfile.gettempdir()), "1" * 40
            )
            self.assertEqual(len(result["capacity_samples"]), 3)
            self.assertFalse(result["old_host_receipt_reused"])
            module.memory_node = lambda path: {"limit": 8 * 1024**3}
            with self.assertRaisesRegex(ValueError, "finite 8GiB"):
                initialize.destination_runtime(
                    contract, Path(tempfile.gettempdir()), "1" * 40
                )

    def test_actual_executor_memory_node_reports_finite_limit(self):
        from tools.parameter_field_executor import diagnose

        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for filename, contents in {
                "memory.max": str(8 * 1024**3),
                "memory.current": "1048576",
                "memory.stat": "inactive_file 0\nfile_dirty 0\nfile_writeback 0\n",
                "memory.events": "oom 0\noom_kill 0\n",
            }.items():
                (root / filename).write_text(contents)
            value = diagnose.memory_node(root)
            self.assertEqual(value["finite_limit"], 8 * 1024**3)
            self.assertNotIn("limit", value)

    def test_static_profile_has_no_inherited_measurement_or_relaxed_numbers(self):
        profile = c.read(c.OWN / "OPS_EXECUTION07.json")
        for name in (
            "capacity_at_registration",
            "archive_reservation_note",
            "supersedes",
            "mandatory_disclosure",
        ):
            self.assertNotIn(name, profile)
        self.assertEqual(profile["concurrency"]["max_workers"], 2)
        self.assertEqual(
            profile["concurrency"]["worker_reservation_bytes"], 768 * 1024**2
        )
        self.assertEqual(profile["concurrency"]["memory_margin_bytes"], 1024**3)
        self.assertEqual(
            profile["durable_execution"]["canonical_job_order"], list(c.ORDER)
        )
        self.assertEqual(profile["durable_execution"]["imported_jobs"], [])


if __name__ == "__main__":
    unittest.main()
