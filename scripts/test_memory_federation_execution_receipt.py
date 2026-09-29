#!/usr/bin/env python3
"""Adversarial receipt tests using actual child-process outputs and exit status."""
import copy
import hashlib
import os
import pathlib
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import memory_federation_execution_receipt as execution
import memory_federation_full_attestation as full


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = pathlib.Path(self.directory.name)
        self.path = self.root / "execution.json"
        self.commands = ["printf actual-output"]
        self.candidate = {"sha": "a" * 40, "tree": "b" * 40}
        self.inputs = {"candidate": self.candidate, "sourceManifestSha256": "c" * 64}
        self.environment = mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "false"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        entry = execution.command_record(0, self.commands[0], self.commands[0], self.root, self.root)
        self.document = {
            "schema": execution.SCHEMA, "candidate": self.candidate,
            "inputs": self.inputs, "finalInputs": copy.deepcopy(self.inputs),
            "commandManifestSha256": hashlib.sha256(execution.canonical(self.commands)).hexdigest(),
            "commands": [entry], "conclusion": "success", "github": {},
        }
        self.write()

    def write(self):
        self.path.write_bytes(execution.canonical(self.document))

    def verify(self, success=True):
        return execution.validate(self.path, self.commands, self.candidate, self.inputs, success)

    def reject(self):
        self.write()
        with self.assertRaises(execution.ExecutionError):
            self.verify()

    def test_real_command_output_is_retained_and_verified(self):
        self.assertEqual((self.root / "command-000.log").read_bytes(), b"actual-output")
        self.assertEqual(self.verify()["conclusion"], "success")

    def test_changed_log_is_rejected(self):
        (self.root / "command-000.log").write_bytes(b"forged-output")
        with self.assertRaises(execution.ExecutionError):
            self.verify()

    def test_missing_log_is_rejected(self):
        (self.root / "command-000.log").unlink()
        with self.assertRaises(execution.ExecutionError):
            self.verify()

    def test_symlink_log_is_rejected_even_when_bytes_match(self):
        log = self.root / "command-000.log"
        other = self.root / "other"
        log.rename(other)
        log.symlink_to(other)
        with self.assertRaises(execution.ExecutionError):
            self.verify()

    def test_parent_traversal_is_rejected(self):
        self.document["commands"][0]["log"] = "../outside.log"
        self.reject()

    def test_reindexed_command_is_rejected(self):
        self.document["commands"][0]["index"] = 1
        self.reject()

    def test_duplicate_command_is_rejected(self):
        self.document["commands"].append(copy.deepcopy(self.document["commands"][0]))
        self.reject()

    def test_changed_command_is_rejected(self):
        self.document["commands"][0]["command"] = "true"
        self.reject()

    def test_changed_working_directory_is_rejected(self):
        self.document["commands"][0]["cwd"] = "codex-rs"
        self.reject()

    def test_partial_success_is_rejected(self):
        self.document["commands"] = []
        self.reject()

    def test_boolean_integer_fields_are_rejected(self):
        original = copy.deepcopy(self.document)
        for field in ("index", "exitCode", "elapsedNanos", "logBytes"):
            with self.subTest(field=field):
                self.document = copy.deepcopy(original)
                self.document["commands"][0][field] = False
                self.reject()

    def test_missing_post_execution_guard_is_rejected(self):
        del self.document["finalInputs"]
        self.reject()

    def test_changed_post_execution_inputs_are_rejected(self):
        self.document["finalInputs"]["sourceManifestSha256"] = "d" * 64
        self.reject()

    def test_wrong_source_candidate_is_rejected(self):
        self.document["candidate"] = {"sha": "d" * 40, "tree": "b" * 40}
        self.reject()

    def test_stale_command_manifest_is_rejected(self):
        self.document["commandManifestSha256"] = "d" * 64
        self.reject()

    def test_actual_nonzero_exit_is_diagnostic_not_success(self):
        out = self.root / "nonzero"
        out.mkdir()
        entry = execution.command_record(0, "exit 7", "exit 7", self.root, out)
        self.assertEqual(entry["exitCode"], 7)
        (self.root / "command-000.log").write_bytes((out / "command-000.log").read_bytes())
        self.commands = ["exit 7"]
        self.document["commands"] = [entry]
        self.document["commandManifestSha256"] = hashlib.sha256(execution.canonical(self.commands)).hexdigest()
        self.document["conclusion"] = "failure"
        self.write()
        self.assertEqual(self.verify(False)["conclusion"], "failure")
        with self.assertRaises(execution.ExecutionError):
            self.verify()
        self.document["conclusion"] = "success"
        self.reject()

    def test_actual_signal_exit_is_retained(self):
        out = self.root / "signal"
        out.mkdir()
        entry = execution.command_record(0, "kill -TERM $$", "kill -TERM $$", self.root, out)
        self.assertEqual(entry["exitCode"], -15)
        self.assertFalse(entry["timedOut"])

    def test_timeout_is_not_a_pass(self):
        out = self.root / "timeout"
        out.mkdir()
        entry = execution.command_record(0, "sleep 30", "sleep 30", self.root, out, timeout=0.03)
        self.assertTrue(entry["timedOut"])
        self.assertNotEqual(entry["exitCode"], 0)

    def test_duplicate_json_keys_are_rejected(self):
        self.path.write_text('{"conclusion":"failure","conclusion":"success"}')
        with self.assertRaises(execution.ExecutionError):
            self.verify()

    def test_nonfinite_json_is_rejected(self):
        for literal in ("NaN", "Infinity", "-Infinity"):
            self.path.write_text('{"value":' + literal + '}')
            with self.assertRaises(execution.ExecutionError):
                execution.strict_json(self.path)

    def test_capacity_measurement_is_bound_to_execution(self):
        metrics = self.root / "capacity.json"
        metrics.write_text('{"measured":true}')
        self.document["capacityMetricsSha256"] = execution.digest(metrics)
        self.write()
        self.verify()
        metrics.write_text('{"measured":false}')
        with self.assertRaises(execution.ExecutionError):
            self.verify()

    def test_wrong_workflow_attempt_is_rejected(self):
        with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true", **{
            env: f"current-{name}" for name, env in execution.GITHUB_FIELDS.items()
        }}):
            self.document["github"] = {key: os.environ[env] for key, env in execution.GITHUB_FIELDS.items()}
            self.write()
            self.verify()
            self.document["github"]["runAttempt"] = "old-attempt"
            self.reject()

    def test_running_transcript_cannot_be_accepted(self):
        self.document["conclusion"] = "running"
        self.reject()

    def test_atomic_writer_does_not_reuse_unfinished_staging(self):
        (self.root / "execution.pending").write_text("interrupted write")
        with self.assertRaises(FileExistsError):
            execution.atomic_write(self.path, self.document)

    def test_runner_records_real_command_prefix_and_stops_on_failure(self):
        import memory_federation_execution_guard as guard
        commands = ["printf first", "exit 9", "printf never-executed"]
        with mock.patch.object(full.base, "COMMANDS", tuple(commands)), \
                mock.patch.object(guard, "_candidate", return_value=self.candidate), \
                mock.patch.object(guard, "_snapshot", return_value=self.inputs), \
                mock.patch.dict(os.environ, {"RUNNER_TEMP": str(self.root)}):
            self.assertEqual(execution.run(), 1)
        path = self.root / execution.DIRECTORY / "execution.json"
        record = execution.validate(path, commands, self.candidate, self.inputs, False)
        self.assertEqual([row["exitCode"] for row in record["commands"]], [0, 9])
        self.assertFalse((path.parent / "command-002.log").exists())
        with self.assertRaises(execution.ExecutionError):
            execution.validate(path, commands, self.candidate, self.inputs, True)

    def test_evidence_parent_symlink_is_rejected(self):
        original = self.root / "actual"
        original.mkdir()
        (original / "source.json").write_text("[]")
        (self.root / "alias").symlink_to(original, target_is_directory=True)
        with self.assertRaises(full.base.AttestationError):
            full.resolve_evidence(self.path, "alias/source.json")

    def test_real_runner_never_reuses_a_prior_execution_directory(self):
        (self.root / execution.DIRECTORY).mkdir()
        with mock.patch.dict(os.environ, {"RUNNER_TEMP": str(self.root)}):
            with self.assertRaises(FileExistsError):
                execution.run()


class CapacityTests(unittest.TestCase):
    def test_real_workload_shape_is_accepted(self):
        full.require_metrics(full._self_test_metrics())

    def test_tiny_workload_cannot_impersonate_the_probe(self):
        metrics = full._self_test_metrics()
        metrics.update(peerCount=1, liveReplayEntries=1, liveCleanupRemoved=1,
                       livePartitionRejections=1, durableReplayEntries=1,
                       durableReplayPartitionRejections=1, durableAttemptEntries=1,
                       durableAttemptPartitionRejections=1, cancellationCount=1,
                       cancellationTotalNanos=1, cancellationAverageNanos=1)
        with self.assertRaises(full.base.AttestationError):
            full.require_metrics(metrics)

    def test_wrong_average_is_rejected(self):
        metrics = full._self_test_metrics()
        metrics["cancellationAverageNanos"] += 1
        with self.assertRaises(full.base.AttestationError):
            full.require_metrics(metrics)

    def test_boolean_measurements_are_rejected(self):
        metrics = full._self_test_metrics()
        metrics["liveFillNanos"] = True
        with self.assertRaises(full.base.AttestationError):
            full.require_metrics(metrics)

    def test_diagnostic_profile_cannot_claim_production_slo(self):
        metrics = full._self_test_metrics()
        metrics["profile"] = "production-slo"
        with self.assertRaises(full.base.AttestationError):
            full.require_metrics(metrics)


CANDIDATE = {"sha": "a" * 40, "tree": "b" * 40}
INPUTS = {"fixture": "recorder-only"}


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.environment = mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "false"})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def transcript(self, entry, commands):
        document = {
            "schema": execution.SCHEMA, "candidate": CANDIDATE,
            "inputs": INPUTS, "finalInputs": INPUTS,
            "commandManifestSha256": hashlib.sha256(execution.canonical(commands)).hexdigest(),
            "commands": [entry], "conclusion": "failure", "github": {},
        }
        path = self.root / "execution.json"
        path.write_bytes(execution.canonical(document))
        return path, document

    def interrupt_runner(self, signum, child_exits_zero=False):
        marker = self.root / "ready"
        program = (
            "import os,pathlib,signal,sys,time; "
            f"signal.signal({int(signum)}, "
            + ("lambda *_: sys.exit(0)); " if child_exits_zero else "signal.SIG_DFL); ")
            + f"pathlib.Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(30)"
        )
        command = shlex.join([sys.executable, "-c", program])
        commands = [command, "printf should-not-run"]
        harness = (
            "import sys,types; "
            f"sys.path.insert(0, {str(pathlib.Path(execution.__file__).parent)!r}); "
            "import memory_federation_execution_receipt as execution; "
            f"candidate={CANDIDATE!r}; inputs={INPUTS!r}; "
            "sys.modules['memory_federation_execution_guard']=types.SimpleNamespace("
            "_candidate=lambda: candidate, _snapshot=lambda *_: inputs); "
            "sys.modules['memory_federation_full_attestation']=types.SimpleNamespace("
            f"base=types.SimpleNamespace(COMMANDS={commands!r})); "
            "raise SystemExit(execution.run())"
        )
        env = dict(os.environ, RUNNER_TEMP=str(self.root), GITHUB_ACTIONS="false")
        with (self.root / "runner.log").open("wb") as log:
            process = subprocess.Popen([sys.executable, "-c", harness], env=env,
                                       stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 5
                while not marker.exists() and time.monotonic() < deadline:
                    if process.poll() is not None:
                        self.fail((self.root / "runner.log").read_text())
                    time.sleep(0.01)
                self.assertTrue(marker.exists(), "child never reached ready boundary")
                process.send_signal(signum)
                self.assertEqual(process.wait(timeout=8), 1)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                if marker.exists():
                    try:
                        os.kill(int(marker.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        path = self.root / execution.DIRECTORY / "execution.json"
        record = execution.validate(path, commands, CANDIDATE, INPUTS, False)
        self.assertEqual(record["conclusion"], "failure")
        self.assertEqual(len(record["commands"]), 1)
        self.assertEqual(record["commands"][0]["interruptedSignal"], signum)
        self.assertFalse(record["commands"][0]["timedOut"])
        self.assertFalse((path.parent / "command-001.log").exists())
        with self.assertRaises(execution.ExecutionError):
            execution.validate(path, commands, CANDIDATE, INPUTS, True)
        return record

    def test_term_retains_failure_and_stops_the_matrix(self):
        self.interrupt_runner(signal.SIGTERM)

    def test_int_retains_failure_and_stops_the_matrix(self):
        self.interrupt_runner(signal.SIGINT)

    def test_trapped_signal_exit_zero_is_still_failure(self):
        record = self.interrupt_runner(signal.SIGTERM, child_exits_zero=True)
        self.assertEqual(record["commands"][0]["exitCode"], 0)

    def test_successful_leader_cannot_leave_a_live_descendant(self):
        program = (
            "import subprocess,sys; "
            "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
            "print(p.pid, flush=True)"
        )
        command = shlex.join([sys.executable, "-c", program])
        entry = execution.command_record(0, command, command, self.root, self.root)
        self.assertEqual(entry["exitCode"], 0)
        self.assertTrue(entry["orphanedChildren"])
        self.assertTrue(execution.command_failed(entry))
        path, document = self.transcript(entry, [command])
        execution.validate(path, [command], CANDIDATE, INPUTS, False)
        document["conclusion"] = "success"
        path.write_bytes(execution.canonical(document))
        with self.assertRaises(execution.ExecutionError):
            execution.validate(path, [command], CANDIDATE, INPUTS, True)

    def test_normal_command_remains_a_pass(self):
        entry = execution.command_record(0, "printf real-output", "printf real-output",
                                         self.root, self.root)
        self.assertFalse(execution.command_failed(entry))
        self.assertIsNone(entry["interruptedSignal"])
        self.assertFalse(entry["orphanedChildren"])
        path, document = self.transcript(entry, ["printf real-output"])
        document["conclusion"] = "success"
        path.write_bytes(execution.canonical(document))
        execution.validate(path, ["printf real-output"], CANDIDATE, INPUTS, True)

    def test_nonzero_exit_is_not_a_pass(self):
        entry = execution.command_record(0, "exit 7", "exit 7", self.root, self.root)
        self.assertEqual(entry["exitCode"], 7)
        self.assertTrue(execution.command_failed(entry))

    def test_child_signal_is_distinct_from_recorder_interruption(self):
        entry = execution.command_record(0, "kill -TERM $$", "kill -TERM $$", self.root, self.root)
        self.assertEqual(entry["exitCode"], -signal.SIGTERM)
        self.assertIsNone(entry["interruptedSignal"])

    def test_timeout_is_distinct_from_recorder_interruption(self):
        entry = execution.command_record(0, "sleep 30", "sleep 30", self.root, self.root, timeout=0.03)
        self.assertTrue(entry["timedOut"])
        self.assertIsNone(entry["interruptedSignal"])
        self.assertTrue(execution.command_failed(entry))

    def test_invalid_interruption_and_descendant_fields_are_rejected(self):
        entry = execution.command_record(0, "true", "true", self.root, self.root)
        path, original = self.transcript(entry, ["true"])
        for field, invalid in (("interruptedSignal", True), ("interruptedSignal", 9),
                               ("interruptedSignal", "15"), ("orphanedChildren", 0)):
            with self.subTest(field=field, invalid=invalid):
                document = copy.deepcopy(original)
                document["commands"][0][field] = invalid
                path.write_bytes(execution.canonical(document))
                with self.assertRaises(execution.ExecutionError):
                    execution.validate(path, ["true"], CANDIDATE, INPUTS, False)

    def test_legacy_record_without_new_fields_remains_readable(self):
        entry = execution.command_record(0, "true", "true", self.root, self.root)
        del entry["interruptedSignal"]
        del entry["orphanedChildren"]
        path, document = self.transcript(entry, ["true"])
        document["conclusion"] = "success"
        path.write_bytes(execution.canonical(document))
        execution.validate(path, ["true"], CANDIDATE, INPUTS, True)


if __name__ == "__main__":
    unittest.main()
