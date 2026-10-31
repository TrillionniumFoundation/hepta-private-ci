"""Small real processes and synthetic metadata; no scientific payload is opened."""

import copy
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from . import controller, process, supervisor, terminal, worker
from . import job_queue as queue


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.config = self.save("config.json", {"synthetic_only": True})

    def tearDown(self):
        self.temporary.cleanup()

    def save(self, name, value):
        return process.write(self.root / name, value)

    def ack(self, acks, done, mutate=None):
        index = len(acks)
        binding = {
            "execution_episode": process.EPISODE,
            "sequence": index + 1,
            "label": queue.LABELS[index],
            "pipeline_config": self.config,
            "completed_jobs": list(done),
            "previous_ack": acks[-1]["ack"] if acks else None,
        }
        manifest = self.save(f"manifest-{index}.json", {"synthetic_only": True})
        value = {
            "schema": "hepta.github-actions-archive-ack.v1",
            "binding": binding,
            "readback": {"all_sha256_and_bytes_match": True},
            "manifest": manifest,
            "logical_files": [{"path": "fixture.txt", "bytes": 1, "sha256": "0" * 64}],
            "items_verified": 1,
            "artifact": {"id": index + 1},
            "cost": {},
            "identity": {"run_id": "synthetic", "run_attempt": "1"},
        }
        if mutate:
            mutate(value)
        item = self.save(f"ack-{index}.json", value)
        result = {
            key: value[key]
            for key in (
                "binding",
                "manifest",
                "logical_files",
                "items_verified",
                "artifact",
                "cost",
            )
        }
        return {**result, "ack": item}

    def canonical(self, count):
        return queue.canonical(
            {
                "schema": "hepta.fullstudy.queue.2",
                "attempt_id": "attempt02",
                "finalize": False,
                "jobs": [
                    {"id": name, "requires": [] if i == 0 else [queue.ORDER[i - 1]]}
                    for i, name in enumerate(queue.ORDER[:count])
                ],
            },
            count,
        )

    def test_exact_fourteen_and_seventeen_sequence(self):
        done, acks, previous = [], [], None
        canonical = self.canonical(4)
        for index, name in enumerate(queue.ORDER):
            previous = queue.activate(canonical, index + 1, done, acks, previous)
            done.append(name)
            queue.accept_ack(acks, self.ack(acks, done), self.config, done)
            if index in (2, 10):
                canonical = self.canonical(11 if index == 2 else 14)
        final = queue.activate(canonical, 14, done, acks, previous, finalize=True)
        self.assertTrue(final["finalize"])
        for unused in range(3):
            queue.accept_ack(acks, self.ack(acks, done), self.config, done)
        self.assertEqual([row["binding"]["label"] for row in acks], queue.LABELS)
        with self.assertRaises(ValueError):
            queue.activate(canonical, 14, done, acks, final, finalize=True)

    def test_unacknowledged_or_redefined_job_cannot_advance(self):
        canonical = self.canonical(4)
        previous = queue.activate(canonical, 1, [], [])
        with self.assertRaises(ValueError):
            queue.activate(canonical, 2, ["A-17"], [], previous)
        acks = []
        queue.accept_ack(acks, self.ack(acks, ["A-17"]), self.config, ["A-17"])
        bad = copy.deepcopy(canonical)
        bad["jobs"][0]["changed"] = True
        with self.assertRaises(ValueError):
            queue.activate(bad, 2, ["A-17"], acks, previous)
        with self.assertRaises(ValueError):
            queue.activate(canonical, 3, ["A-17"], acks, previous)

    def test_bad_readback_and_changed_ack_are_rejected(self):
        result = self.ack(
            [],
            ["A-17"],
            lambda value: value["readback"].update(all_sha256_and_bytes_match=False),
        )
        with self.assertRaises(ValueError):
            queue.accept_ack([], result, self.config, ["A-17"])
        Path(result["ack"]["path"]).write_text("{}")
        with self.assertRaises(ValueError):
            queue.accept_ack([], result, self.config, ["A-17"])

    def test_no_cross_run_or_artifact_id_reuse(self):
        acks = []
        queue.accept_ack(acks, self.ack(acks, ["A-17"]), self.config, ["A-17"])
        result = self.ack(
            acks,
            queue.ORDER[:2],
            lambda value: value["identity"].update(run_id="other"),
        )
        with self.assertRaises(ValueError):
            queue.accept_ack(acks, result, self.config, queue.ORDER[:2])

    def test_real_wait4_exit_cpu_and_no_second_reaper(self):
        log = self.root / "process.log"
        log.touch()
        result = process.run_owned(
            [sys.executable, "-c", "print(sum(range(200000)))"],
            directory=self.root / "owned",
            cwd=str(self.root),
            env=os.environ.copy(),
            log=log,
            health=lambda: None,
            binding={"synthetic_only": True},
        )
        self.assertEqual(result["exit_code"], 0)
        self.assertGreater(result["cpu_seconds"], 0)
        self.assertGreater(result["peak_rss_bytes"], 0)
        self.assertEqual(log.read_text().strip(), str(sum(range(200000))))
        closure = json.loads((self.root / "owned/CLOSURE.json").read_text())
        self.assertTrue(closure["accounting_complete_for_attempted_direct_workers"])
        with self.assertRaises(ChildProcessError):
            os.wait4(result["pid"], os.WNOHANG)
        terminal.require_measurement(self.root / "owned")

    def test_nonzero_never_passes_measurement_gate(self):
        log = self.root / "nonzero.log"
        log.touch()
        result = process.run_owned(
            [sys.executable, "-c", "raise SystemExit(7)"],
            directory=self.root / "nonzero",
            cwd=str(self.root),
            env=os.environ.copy(),
            log=log,
            health=lambda: None,
            binding={"synthetic_only": True},
        )
        self.assertEqual(result["exit_code"], 7)
        with self.assertRaises(ValueError):
            terminal.require_measurement(self.root / "nonzero")

    def test_health_abort_reaps_child_and_preserves_failure(self):
        calls = 0

        def health():
            nonlocal calls
            calls += 1
            if calls > 1:
                raise ValueError("synthetic deadline")

        log = self.root / "abort.log"
        log.touch()
        with self.assertRaisesRegex(ValueError, "synthetic deadline"):
            process.run_owned(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                directory=self.root / "abort",
                cwd=str(self.root),
                env=os.environ.copy(),
                log=log,
                health=health,
                binding={"synthetic_only": True},
            )
        closure = process.read(self.root / "abort/CLOSURE.json")
        self.assertTrue(closure["all_returned_direct_children_reaped"])
        self.assertEqual(closure["original_exception"]["message"], "synthetic deadline")
        self.assertNotEqual(closure["children"][0]["wait4"]["exit_code"], 0)
        self.assertGreaterEqual(closure["direct_workers_cpu_seconds"], 0)

    def literal_fixture(self):
        raw, cas = self.root / "raw", self.root / "raw_cas"
        raw.mkdir()
        cas.mkdir()
        item = process.write(raw / "fixture.json", {"synthetic_only": True})
        frozen = self.save(
            "freeze.json",
            {
                "synthetic_only": True,
                "operational_amendment_sha256": "0" * 64,
                "registered_commit": "1" * 40,
            },
        )
        entries = {
            "fixture.json": {
                "bytes": item["bytes"],
                "sha256": item["sha256"],
                "storage": "direct",
                "blob": None,
            }
        }
        binding = {
            "attempt_id": "attempt02",
            "source_freeze_sha256": frozen["sha256"],
            "operational_amendment_sha256": "0" * 64,
            "registered_commit": "1" * 40,
        }
        manifest = process.write(
            raw / "evidence_v2/verification07/MANIFEST.json",
            {
                "schema": "hepta.fullstudy.cas-container-manifest.1",
                "binding": binding,
                "root": str(raw),
                "cas_root": str(cas),
                "logical_paths": entries,
                "logical_artifact_count": 1,
                "logical_artifact_bytes": item["bytes"],
            },
        )
        verified = {
            "archive_verification_complete": True,
            "binding": binding,
            "manifest": {
                **manifest,
                "path": "evidence_v2/verification07/MANIFEST.json",
            },
            "logical_files_restored": 1,
            "logical_bytes_restored": item["bytes"],
            "logical_paths_verified": ["fixture.json"],
            "temporary_directory_removed_after_success": True,
        }
        process.write(raw / "evidence_v2/verification07/VERIFIED.json", verified)
        return {"raw_root": str(raw), "cas_root": str(cas)}, frozen, verified

    def test_literal_gate_reads_content_identity_and_exact_counts(self):
        config, frozen, verified = self.literal_fixture()
        supervisor.verify_literal(config, frozen)
        verified["logical_paths_verified"] = ["fixture.json", "fixture.json"]
        process.write(
            Path(config["raw_root"]) / "evidence_v2/verification07/VERIFIED.json",
            verified,
            replace=True,
        )
        with self.assertRaises(ValueError):
            supervisor.verify_literal(config, frozen)

    def test_literal_tamper_is_not_promoted_to_closure(self):
        config, frozen, unused = self.literal_fixture()
        (Path(config["raw_root"]) / "fixture.json").write_text("changed")
        with self.assertRaises(ValueError):
            supervisor.verify_literal(config, frozen)

    def test_literal_inventory_cannot_omit_a_current_raw_path(self):
        config, frozen, unused = self.literal_fixture()
        (Path(config["raw_root"]) / "unlisted.bin").write_bytes(b"unlisted fixture")
        with self.assertRaisesRegex(ValueError, "omits or invents"):
            supervisor.verify_literal(config, frozen)

    def test_capacity_wait_closes_at_five_minutes_with_actual_samples(self):
        value = supervisor.Supervisor.__new__(supervisor.Supervisor)
        value.ops = self.root
        value.run_dir = self.root / "capacity"
        value.run_dir.mkdir()
        value.phase = "synthetic_admission"
        value.guard = mock.Mock()
        value.guard.health.return_value = {
            "limit": 8 * process.GIB,
            "effective_current": 8 * process.GIB,
        }
        value.status = lambda: None
        clock = [0.0]

        def advance(seconds):
            clock[0] += seconds

        with (
            mock.patch.object(
                supervisor.time, "monotonic", side_effect=lambda: clock[0]
            ),
            mock.patch.object(supervisor.time, "sleep", side_effect=advance),
        ):
            with self.assertRaisesRegex(RuntimeError, "five-minute"):
                value.gate()
        failure = process.read(
            value.run_dir / "synthetic_admission.ADMISSION_FAILED.json"
        )
        self.assertEqual(failure["capacity_wait_seconds"], 300)
        self.assertEqual(failure["fixed_capacity_wait_limit_seconds"], 300)
        self.assertFalse(failure["complete"])
        process.checked(failure["actual_samples"])
        self.assertEqual(
            len((value.run_dir / "ADMISSION.jsonl").read_text().splitlines()), 30
        )

    def test_all_seventeen_process_wrappers_are_required(self):
        value = supervisor.Supervisor.__new__(supervisor.Supervisor)
        value.ops = self.root
        directory = self.root / "wrapper_runs"
        directory.mkdir()
        for token in queue.ORDER:
            (directory / token).mkdir()
        with self.assertRaisesRegex(ValueError, "Wrapper population"):
            value.closed_wrappers()

    def controller_fixture(self, seal_seed):
        original = importlib.import_module(process.PREFIX + "launch_v2")
        raw, ops = self.root / "raw", self.root / "ops"
        (raw / "controller").mkdir(parents=True)
        ops.mkdir()
        amend = self.save("amendment.json", {"synthetic_only": True})
        protocol = process.descriptor(
            Path(original.__file__).with_name("PROTOCOL.json")
        )
        source = Path(original.__file__).resolve()
        frozen = self.save(
            "job-freeze.json",
            {
                "synthetic_only": True,
                "allowed_phases": ["A"],
                "attempt_id": "attempt02",
                "operational_amendment_sha256": amend["sha256"],
                "protocol_sha256": protocol["sha256"],
                "source_files": {
                    source.relative_to(original.ROOT).as_posix(): process.descriptor(
                        source
                    )["sha256"]
                },
            },
        )
        job = {
            "id": "A-17",
            "phase": "A",
            "seed": 17,
            "group": "training",
            "requires": [],
            "freeze_sha256": frozen["sha256"],
            "completion": "operations/A-seed-17.COMPLETE.json",
            "argv": [
                "-B",
                "-m",
                process.PREFIX + "run_v2",
                "--root",
                str(raw),
                "--phase",
                "A",
                "--seed",
                "17",
                "--freeze",
                frozen["path"],
                "--amendment",
                amend["path"],
                "--amendment-sha256",
                amend["sha256"],
                "--protocol",
                protocol["path"],
                "--execute",
            ],
        }

        def write_bytes(path, content):
            Path(path).write_bytes(content)

        def append_bytes(path, content):
            with Path(path).open("ab") as stream:
                stream.write(content)

        value = controller.Controller.__new__(controller.Controller)
        value.root, value.ops, value.state = raw, ops, raw / "controller"
        value.config = {"empty_cwd": str(self.root), "source_root": str(original.ROOT)}
        value.config_desc = self.config
        value.core = SimpleNamespace(
            validate_queue=original.validate_queue,
            verify_job=original.verify_job,
            completion_matches=original.completion_matches,
            memory_admission=lambda *args: {"allowed": True},
            pending_growth=lambda unused: 0,
        )
        value.guard = mock.Mock(policy={"oom_baseline": {"oom": 0, "oom_kill": 0}})
        value.storage = SimpleNamespace(
            check=lambda: None,
            write_json=lambda path, data, allow_replace=False, **kwargs: process.write(
                path, data, replace=allow_replace
            ),
            write_bytes=write_bytes,
            append_bytes=append_bytes,
        )
        value.registration = {
            "_sha256": amend["sha256"],
            "concurrency": {
                "worker_reservation_bytes": 768 * 1024**2,
                "memory_margin_bytes": process.GIB,
            },
        }
        value.results, value.definitions = {}, {}
        seal = {
            "synthetic_only": True,
            "complete": True,
            "phase": "A",
            "seed": seal_seed,
            "source_freeze_sha256": frozen["sha256"],
            "operational_amendment_sha256": amend["sha256"],
            "attempt_id": "attempt02",
            "post_execution_storage_check": True,
            "process_peak_rss_bytes": 1024,
        }
        code = "from pathlib import Path; import sys; p=Path(sys.argv[1]); p.parent.mkdir(parents=True); p.write_text(sys.argv[2])"
        argv = [
            sys.executable,
            "-B",
            "-c",
            code,
            str(raw / job["completion"]),
            json.dumps(seal),
        ]
        return value, {"jobs": [job], "finalize": False}, lambda unused: argv

    def test_controller_requires_original_seal_identity_after_actual_exit(self):
        value, active, command = self.controller_fixture(29)
        with self.assertRaisesRegex(ValueError, "original completion seal differs"):
            value.job(active, command)
        result = process.read(value.state / "A-17.RESULT.json")
        self.assertEqual(result["exit_code"], 0)
        self.assertFalse(result["complete"])
        self.assertIsNone(result["completion"])
        self.assertEqual(
            process.read(value.root / "ACTIVE_WORKERS.json")["workers"], []
        )
        self.assertFalse((value.state / "EXECUTION.json").exists())

    def test_controller_real_child_success_keeps_actual_wait4_and_original_completion(
        self,
    ):
        value, active, command = self.controller_fixture(17)
        result = value.job(active, command)
        self.assertTrue(result["complete"])
        self.assertFalse(result["imported"])
        self.assertGreater(result["owned_wait4"]["cpu_seconds"], 0)
        self.assertEqual(result["completion"]["path"], active["jobs"][0]["completion"])
        self.assertEqual(
            process.read(value.root / "ACTIVE_WORKERS.json")["workers"], []
        )

    def test_original_analysis_child_flags_are_preserved(self):
        original = mock.Mock()
        original.Popen.return_value = "actual-child"
        config = {
            "python": sys.executable,
            "source_root": str(self.root),
            "empty_cwd": str(self.root / "empty"),
        }
        proxy = worker.AnalysisSpawns(original, config, self.config)
        flags = ["--child", "--parent-pid", str(os.getpid()), "--root", "raw"]
        with mock.patch.object(worker, "validate_request") as validate:
            result = proxy.Popen(
                [sys.executable, "-B", "-m", worker.ANALYSIS, *flags], cwd=self.root
            )
        self.assertEqual(result, "actual-child")
        validate.assert_called_once_with(
            config, "ANALYSIS_CHILD", worker.ANALYSIS, flags, parent_pid=os.getpid()
        )
        argv = original.Popen.call_args.args[0]
        self.assertEqual(argv[argv.index("--") + 1 :], flags)
        self.assertEqual(original.Popen.call_args.kwargs["cwd"], config["empty_cwd"])
        with self.assertRaises(ValueError):
            proxy.Popen([sys.executable, "-c", "pass"], cwd=self.root)


if __name__ == "__main__":
    unittest.main()
