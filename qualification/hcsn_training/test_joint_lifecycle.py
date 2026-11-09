"""Journal transitions with mocked process contact; no real child or signal."""

from contextlib import contextmanager
import copy
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from qualification.hcsn_training import joint_lifecycle as lifecycle  # noqa: E402
from qualification.hcsn_training import joint_process  # noqa: E402
from qualification.hcsn_training import joint_protocol as wire  # noqa: E402
from qualification.hcsn_training.joint_outputs import validate_outputs  # noqa: E402
from qualification.hcsn_training.joint_store import Directory  # noqa: E402
from qualification.hcsn_training.joint_test_support import JournalFixture, WORKER  # noqa: E402


class JournalTransitions(JournalFixture):
    def test_lost_start_reply_never_launches_a_second_runner(self):
        with mock.patch.object(lifecycle.subprocess, "Popen") as spawn:
            first = lifecycle.dispatch(self.root, self.start, self.sources)
            repeat = lifecycle.dispatch(self.root, self.start, self.sources)
            status = lifecycle.dispatch(self.root, self.command("status"), self.sources)
        self.assertEqual(spawn.call_count, 1)
        self.assertEqual([item["state"] for item in (first, repeat, status)], ["unknown"] * 3)
        job = self.root.child("jobs").child(lifecycle.job_key(self.target))
        self.assertFalse(job.exists("claim.json"))
        self.assertFalse(job.exists("terminal.json"))

    def test_partial_reservation_is_unknown_and_not_repaired(self):
        jobs = self.root.child("jobs", create=True)
        job = jobs.child(lifecycle.job_key(self.target), create=True)
        job.write("reservation.json", b'{"schema_version":')
        with mock.patch.object(lifecycle.subprocess, "Popen") as spawn:
            answer = lifecycle.dispatch(self.root, self.start, self.sources)
        spawn.assert_not_called()
        self.assertEqual(answer["state"], "unknown")
        self.assertEqual(job.names(), ["reservation.json"])
        self.assertEqual(job.read("reservation.json"), b'{"schema_version":')

    def test_same_key_different_payload_cannot_rebind(self):
        self.reserve()
        before = self.job.read("reservation.json")
        changed = copy.deepcopy(self.reference)
        changed["manifest"]["request_sha256"] = "8" * 64
        changed["manifest_sha256"] = wire.sha(wire.encoded(changed["manifest"]))
        changed["input_id"] = wire.sha(b"hepta.joint.text.input.v1\0" + changed["manifest_sha256"].encode())
        payload = wire.encoded(changed)
        target = wire.identity(self.target["key"], wire.sha(payload))
        command = wire.validate_command(wire.encoded(dict(self.start, dispatch=target, target=target, payload=payload.decode())))
        with mock.patch.object(lifecycle.subprocess, "Popen") as spawn:
            answer = lifecycle.dispatch(self.root, command, self.sources)
        spawn.assert_not_called()
        self.assertEqual(answer["state"], "unknown")
        self.assertEqual(self.job.read("reservation.json"), before)

    def test_retained_cancel_before_start_launches_no_process(self):
        cancel = self.cancellation()
        with mock.patch.object(lifecycle.subprocess, "Popen") as spawn:
            first = lifecycle.dispatch(self.root, cancel, self.sources)
            answer = lifecycle.dispatch(self.root, self.start, self.sources)
            repeated = lifecycle.dispatch(self.root, self.start, self.sources)
        spawn.assert_not_called()
        self.assertEqual(first["state"], "unknown")
        self.assertEqual(answer, repeated)
        self.assertEqual(answer["state"], "cancelled")
        job = self.root.child("jobs").child(lifecycle.job_key(self.target))
        terminal = wire.decode(job.read("terminal.json"))
        self.assertEqual((terminal["returncode"], terminal["process"], terminal["claim_sha256"]), (None, None, None))
        self.assertEqual(self.root.child("cancellations").names(), [lifecycle.cancel_name(cancel["dispatch"])])
        self.assertFalse(job.exists("claim.json"))

    def test_cancel_identity_cannot_be_reused_for_a_different_target(self):
        cancel = self.cancellation()
        lifecycle.dispatch(self.root, cancel, self.sources)
        different = wire.identity("provider-effect:v1:" + "8" * 64, "9" * 64)
        command = wire.validate_command(wire.encoded(dict(cancel, target=different)))
        with mock.patch.object(lifecycle.subprocess, "Popen") as spawn, self.assertRaises(ValueError):
            lifecycle.dispatch(self.root, command, self.sources)
        spawn.assert_not_called()
        stored = self.root.child("cancellations").read(lifecycle.cancel_name(cancel["dispatch"]))
        self.assertEqual(wire.decode(stored), dict(dispatch=cancel["dispatch"], target=self.target))

    def test_custody_mutation_refuses_contact(self):
        path = self.path / "inputs" / self.reference["input_id"] / "request.json"
        path.write_bytes(self.request_raw.replace(b'"steps":2', b'"steps":3'))
        with mock.patch.object(lifecycle.subprocess, "Popen") as spawn, self.assertRaises(ValueError):
            lifecycle.dispatch(self.root, self.start, self.sources)
        spawn.assert_not_called()
        self.assertFalse(self.root.child("jobs").exists(lifecycle.job_key(self.target)))

    def test_post_contact_close_error_leaves_uncertainty(self):
        original = Directory.open_log

        @contextmanager
        def fail_after_contact(directory, name):
            with original(directory, name) as stream:
                yield stream
            if name == "runner.stderr":
                raise OSError("synthetic post-contact close error")

        with mock.patch.object(Directory, "open_log", fail_after_contact), mock.patch.object(lifecycle.subprocess, "Popen") as spawn:
            with self.assertRaises(OSError):
                lifecycle.dispatch(self.root, self.start, self.sources)
        spawn.assert_called_once()
        job = self.root.child("jobs").child(lifecycle.job_key(self.target))
        self.assertFalse(job.exists("terminal.json"))
        with mock.patch.object(lifecycle.subprocess, "Popen") as again:
            self.assertEqual(lifecycle.dispatch(self.root, self.start, self.sources)["state"], "unknown")
        again.assert_not_called()

    def test_observation_does_not_extend_the_original_deadline(self):
        self.reserve()
        claim = self.claim()
        self.job.write("worker.json", WORKER)
        raw_claim = self.job.read("claim.json")
        with self.clocks(), mock.patch.object(lifecycle, "liveness", return_value="live"):
            self.assertEqual(lifecycle.observe(self.root, self.command("status"), self.sources)["state"], "running")
            with mock.patch.object(joint_process, "clock_ns", return_value=claim["deadline_nanoseconds"]):
                answer = lifecycle.observe(self.root, self.command("status"), self.sources)
        self.assertEqual(answer["state"], "unknown")
        self.assertEqual(self.job.read("claim.json"), raw_claim)
        self.assertFalse(self.job.exists("terminal.json"))

    def test_validated_terminal_is_rechecked_against_physical_outputs(self):
        self.reserve()
        claim = self.claim()
        self.job.write("worker.json", WORKER)
        output = self.unsigned_output_fixture()
        with self.clocks():
            evidence = validate_outputs(self.root, self.job, self.reservation, self.sources)
            lifecycle.finish(self.root, self.job, self.reservation, "succeeded", WORKER, 0,
                             "worker_exit_zero_and_outputs_closed", claim, evidence, 0)
            answer = lifecycle.observe(self.root, self.command("status"), self.sources)
        self.assertEqual(answer["state"], "succeeded")
        self.assertEqual(answer["evidence"]["outputs"], evidence)
        # This synthetic unit fixture validates bytes, never model semantics or training.
        (output.path / "candidate.heptapk").write_bytes(b"mutated")
        self.assertEqual(lifecycle.observe(self.root, self.command("status"), self.sources)["state"], "unknown")

    def test_failed_marker_prevents_an_output_success(self):
        self.reserve()
        output = self.unsigned_output_fixture()
        output.write("failed.json", b"{}")
        with self.assertRaises(ValueError):
            validate_outputs(self.root, self.job, self.reservation, self.sources)
        self.assertTrue(output.exists("failed.json"))

    def test_retained_success_over_original_claim_budget_is_unknown(self):
        self.reserve()
        claim = self.claim()
        self.job.write("worker.json", WORKER)
        self.unsigned_output_fixture()
        with self.clocks():
            evidence = validate_outputs(self.root, self.job, self.reservation, self.sources)
            lifecycle.finish(self.root, self.job, self.reservation, "succeeded", WORKER, 0,
                             "worker_exit_zero_and_outputs_closed", claim, evidence, 0)
            self.assertEqual(lifecycle.observe(self.root, self.command("status"), self.sources)["state"], "succeeded")
        raw_claim = self.job.read("claim.json")
        changed = wire.decode(self.job.read("terminal.json"))
        changed["wall_nanoseconds"] = claim["budget_milliseconds"] * 1000000 + 1
        # Preserve canonical encoding, exact identity, outputs and original claim SHA.
        (self.job.path / "terminal.json").write_bytes(wire.encoded(changed))
        with mock.patch.object(lifecycle.subprocess, "Popen") as spawn:
            observed = lifecycle.observe(self.root, self.command("status"), self.sources)
        spawn.assert_not_called()
        self.assertEqual(observed["state"], "unknown")
        self.assertEqual(self.job.read("claim.json"), raw_claim)


if __name__ == "__main__":
    unittest.main(verbosity=2)
