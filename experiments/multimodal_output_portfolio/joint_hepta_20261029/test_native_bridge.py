"""No-torch adapter unit tests with an explicitly FAKE protocol transport.

These tests do NOT qualify an Agentd owner, native execution, calibration,
checkpoint recovery, or CPU measurements. The separately built Rust host and
native_bridge.lifecycle_probe provide that integration evidence in CI.
"""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import native_bridge as bridge


class ProtocolDouble:
    """Test-only response shape; not a neuron implementation or native host."""

    decline = False
    fail_phase = None
    exit_code = 0

    def __init__(self, binary):
        self.sequence, self.closed = 0, False
        self._protocol_failed, self.finished = False, False

    def call(self, request):
        command = request["command"]
        if command == "Tick":
            if request["phase"] == self.fail_phase:
                self._protocol_failed = True
                raise TimeoutError("TEST DOUBLE lost response")
            self.sequence += 1
            value = {"owner_authority": "DENY_ALL", "native_transition_executed": True,
                     "native_abstain": self.decline, "sequence": self.sequence,
                     "execution_micros": 0, "journal_bytes_written": 0,
                     "checkpoint_bytes": 0, "test_double_not_owner": True}
        else:
            self.closed = command == "Close"
            value = {"sequence": self.sequence, "test_double_not_owner": True}
        return {"ok": True, "result": value, "physical_receipt_processing_micros": 0}

    def finish(self, *, timeout=10, terminate_on_timeout=False):
        self.finished = True
        return {"user_seconds": 0.0, "system_seconds": 0.0, "cpu_seconds": 0.0,
                "returncode": self.exit_code, "stderr_tail": "TEST DOUBLE exit",
                "measurement": "TEST DOUBLE: no native process was executed"}


class NativeAdapterUnitTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hepta-native-adapter-unit-")
        self.root = Path(self.temporary.name)
        self.binary = self.root / "NOT_A_NATIVE_BINARY"
        self.binary.write_bytes(b"unit fixture only; never executed")
        self.build = self.root / "FAKE_BUILD_RECEIPT_FOR_UNIT_TEST.json"
        self.build.write_text(json.dumps({
            "schema": "hepta.joint-output.native-build.v1",
            "source_commit": bridge.SOURCE_COMMIT,
            "binary_sha256": bridge.file_sha(self.binary),
            "owner_and_three_crates_unmodified": True, "host_sources_unmodified": True,
            "all_dependencies_name_version_source_checksum_match": True,
            "test_double_fixture_not_qualification": True,
        }))
        ProtocolDouble.decline = False
        ProtocolDouble.fail_phase, ProtocolDouble.exit_code = None, 0
        self.patcher = patch.object(bridge, "_Process", ProtocolDouble)
        self.patcher.start()
        self.guard = None

    def tearDown(self):
        if self.guard is not None and not self.guard.finished:
            self.guard.stop(reason="unit_test_cleanup")
        self.patcher.stop()
        self.temporary.cleanup()

    def make_guard(self):
        self.guard = bridge.NativeGuard(
            binary=self.binary, build_receipt=self.build, directory=self.root / "episode",
            case="unit.fake", model_sha256=bridge.digest({"model": "unit"}),
            profile_sha256=bridge.digest({"profile": "unit"}),
        )
        return self.guard

    def delivery(self):
        path = self.root / "output.txt"
        path.write_text("unit test artifact\n")
        return {"artifact_refs": {"text": str(path)},
                "artifact_sha256": {"text": bridge.file_sha(path)}, "public_feedback": 1.0}

    def test_abstention_prevents_dispatch(self):
        guard = self.make_guard()
        ProtocolDouble.decline = True
        calls = []
        result = guard.perform("continue", {"chosen": "continue"}, lambda: calls.append(1))
        self.assertEqual(calls, [])
        self.assertEqual(result["reason"], "native_abstain_before_dispatch")
        self.assertTrue(guard.finished)

    def test_physical_output_digest_is_checked_before_feedback(self):
        guard = self.make_guard()

        def forged():
            delivered = self.delivery()
            delivered["artifact_sha256"]["text"] = bridge.digest({"wrong": "bytes"})
            return delivered

        with self.assertRaisesRegex(ValueError, "declared digest"):
            guard.perform("continue", {}, forged)
        phases = [row["request"]["phase"] for row in guard.transcript
                  if row["request"]["command"] == "Tick"]
        self.assertNotIn(1, phases)

    def test_action_and_model_profile_identity_enter_the_bound_evidence(self):
        guard = self.make_guard()
        guard.perform("continue", {"controller_step": 4, "state_sha256": "a" * 64}, self.delivery)
        rows = [row for row in guard.transcript if row["request"]["command"] == "Tick"]
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertEqual(row["request"]["receipt_digest"], bridge.digest(row["bound_evidence"]))
            self.assertEqual(row["bound_evidence"]["identity_sha256"], bridge.digest(guard.identity))
            self.assertEqual(row["bound_evidence"]["action_trace"]["controller_step"], 4)
        self.assertEqual(rows[1]["bound_evidence"]["artifact_sha256"]["text"],
                         bridge.file_sha(self.root / "output.txt"))

    def test_stop_prevents_all_future_dispatch(self):
        guard = self.make_guard()
        calls = []
        guard.perform("stop", {"reason": "selected"}, lambda: calls.append(1))
        with self.assertRaisesRegex(ValueError, "already stopped"):
            guard.perform("continue", {}, lambda: calls.append(2))
        self.assertEqual(calls, [])

    def test_binary_digest_mismatch_rejected_before_transport_creation(self):
        self.binary.write_bytes(b"modified after identity receipt")
        with self.assertRaisesRegex(ValueError, "qualified unchanged"):
            self.make_guard()

    def test_action_outside_permit_has_no_tick_or_dispatch(self):
        guard = self.make_guard()
        before = len(guard.transcript)
        with self.assertRaisesRegex(ValueError, "outside"):
            guard.perform("unregistered", {}, self.delivery)
        self.assertEqual(len(guard.transcript), before)

    def test_dispatch_failure_is_closed_reaped_and_retained(self):
        guard = self.make_guard()

        def failed():
            raise ValueError("TEST DOUBLE dispatcher failed after starting work")

        with self.assertRaisesRegex(ValueError, "dispatcher failed"):
            guard.perform("continue", {"step": 0}, failed)
        self.assertTrue(guard.finished)
        self.assertTrue(guard.process.finished)
        self.assertEqual(len(guard.native_process_cpu), 1)
        self.assertTrue(guard.history[0]["dispatch_entered"])
        self.assertFalse(guard.history[0]["dispatch_completed"])
        self.assertTrue(guard.history[0]["failed"])
        saved = json.loads((guard.directory / "NATIVE_FAILURE.json").read_text())
        self.assertTrue(saved["final"]["aborted"])
        self.assertTrue(saved["native_process_reaped"])
        self.assertEqual(saved["actual_dispatched_actions"], 1)
        with self.assertRaisesRegex(ValueError, "already stopped"):
            guard.perform("continue", {}, self.delivery)

    def test_lost_transport_reaps_without_claiming_acknowledged_stop(self):
        guard = self.make_guard()
        ProtocolDouble.fail_phase = 1
        with self.assertRaisesRegex(TimeoutError, "lost response"):
            guard.perform("continue", {}, self.delivery)
        self.assertTrue(guard.finished)
        self.assertTrue(guard.process.finished)
        self.assertIsNone(guard.final_record["native_stop_tick"])
        self.assertIsNone(guard.final_record["native_closed_status"])
        self.assertTrue(guard.final_record["native_process_reaped"])
        self.assertEqual(guard.receipt()["native_tick_count"], 1)

    def test_nonzero_child_exit_retains_usage_once(self):
        guard = self.make_guard()
        ProtocolDouble.exit_code = 7
        with self.assertRaisesRegex(RuntimeError, "exited unsuccessfully"):
            guard.stop()
        self.assertTrue(guard.final_record["aborted"])
        self.assertEqual(len(guard.native_process_cpu), 1)
        self.assertEqual(guard.native_process_cpu[0]["returncode"], 7)
        guard.abort("repeated cleanup")
        self.assertEqual(len(guard.native_process_cpu), 1)

    def test_external_abort_binds_error_and_real_protocol_shape(self):
        guard = self.make_guard()
        result = guard.abort("model_failed", action_trace={"step": 2}, error=RuntimeError("unit failure"))
        self.assertTrue(result["aborted"])
        self.assertEqual(result["failure"]["error_type"], "RuntimeError")
        ticks = [row for row in guard.transcript if row["request"]["command"] == "Tick"]
        self.assertEqual([row["request"]["phase"] for row in ticks], [3])
        self.assertEqual(ticks[0]["bound_evidence"]["terminal_failure"]["action_trace"], {"step": 2})

    def test_process_interrupts_are_not_swallowed(self):
        guard = self.make_guard()

        def interrupted():
            raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            guard.perform("continue", {}, interrupted)
        self.assertFalse(guard.finished)


if __name__ == "__main__":
    unittest.main()
