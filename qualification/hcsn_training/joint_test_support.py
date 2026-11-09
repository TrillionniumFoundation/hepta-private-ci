"""Private synthetic filesystem fixtures; no owner, process, or training proof."""

from contextlib import ExitStack
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from qualification.hcsn_training import joint_lifecycle as lifecycle
from qualification.hcsn_training import joint_protocol as wire
from qualification.hcsn_training.joint_sources import HC_FILES, Sources
from qualification.hcsn_training.joint_store import Root
from scripts.test_joint_text_training_contract import synthetic_request

REPO = Path(__file__).resolve().parents[2]
RUNNER = dict(host_id="1" * 64, process_id=41001, incarnation="2" * 64)
WORKER = dict(host_id="1" * 64, process_id=41002, incarnation="3" * 64)
BOOT = "4" * 64
NOW = 1000000000


def private_file(path, raw):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)


class JournalFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="joint-journal-synthetic-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve() / "root"
        self.path.mkdir(mode=0o700)
        private_file(self.path / "layout.json", wire.LAYOUT)
        info = self.path.stat()
        self.expected = dict(device=info.st_dev, inode=info.st_ino, uid=info.st_uid)
        self.root = Root(self.path, self.expected)
        self.addCleanup(self.root.close)
        captured = {name: (REPO / name).read_bytes() for name in HC_FILES}
        self.sources = Sources(REPO, captured)
        self.request = synthetic_request()
        self.predecessor = b"not-a-model: synthetic custody bytes only"
        self.request.update(predecessor_sha256=wire.sha(self.predecessor),
                            predecessor_bytes=len(self.predecessor),
                            execution_source_digest=self.sources.h_digest())
        self.request_raw = self.sources.contract.json_bytes(self.request)
        manifest = dict(schema_version=1, profile=wire.PROFILE,
                        request_sha256=wire.sha(self.request_raw), request_bytes=len(self.request_raw),
                        request_binding_digest=self.sources.contract.request_binding_digest(self.request),
                        predecessor_sha256=wire.sha(self.predecessor), predecessor_bytes=len(self.predecessor),
                        worker_execution_source_digest=self.sources.h_digest())
        manifest_sha = wire.sha(wire.encoded(manifest))
        self.reference = dict(manifest=manifest, manifest_sha256=manifest_sha,
                              input_id=wire.sha(b"hepta.joint.text.input.v1\0" + manifest_sha.encode()))
        self.descriptor = wire.encoded(self.reference)
        self.target = wire.identity("provider-effect:v1:" + "5" * 64, wire.sha(self.descriptor))
        self.start = dict(schema_version=1, profile=wire.PROFILE, action="start",
                          dispatch=self.target, target=self.target, payload=self.descriptor.decode())
        custody = self.root.child("inputs", create=True).child(self.reference["input_id"], create=True)
        custody.write("manifest.json", wire.encoded(manifest))
        custody.write("request.json", self.request_raw)
        custody.write("predecessor.heptapk", self.predecessor)

    def command(self, action, dispatch=None):
        return wire.validate_command(wire.encoded(dict(schema_version=1, profile=wire.PROFILE,
            action=action, dispatch=dispatch or self.target, target=self.target, payload=None)))

    def cancellation(self):
        return self.command("cancel", wire.identity("provider-effect:v1:" + "6" * 64, "7" * 64))

    def reserve(self):
        with mock.patch.object(lifecycle.subprocess, "Popen") as spawn:
            lifecycle.dispatch(self.root, self.start, self.sources)
            spawn.assert_called_once()
        self.job = self.root.child("jobs").child(lifecycle.job_key(self.target))
        self.reservation = wire.decode(self.job.read("reservation.json"))
        return self.job

    def claim(self):
        claim = dict(schema_version=1, profile=wire.PROFILE, identity=self.target,
                     root=self.expected, runner=RUNNER, boot_id=BOOT, clock="CLOCK_BOOTTIME",
                     started_nanoseconds=NOW,
                     deadline_nanoseconds=NOW + self.request["maximum_training_milliseconds"] * 1000000,
                     budget_milliseconds=self.request["maximum_training_milliseconds"])
        self.job.write("claim.json", claim)
        return claim

    def clocks(self):
        from qualification.hcsn_training import joint_process, joint_runner
        stack = ExitStack()
        for module in (lifecycle, joint_process, joint_runner):
            stack.enter_context(mock.patch.object(module, "clock_ns", return_value=NOW + 1))
        stack.enter_context(mock.patch.object(joint_process, "boot_id", return_value=BOOT))
        stack.enter_context(mock.patch.object(joint_runner, "boot_id", return_value=BOOT))
        return stack

    def unsigned_output_fixture(self):
        """Wire/byte fixture only: does not claim model or gradient execution."""
        contract = self.sources.contract
        candidate = b"synthetic candidate bytes, intentionally not a loadable packet"
        groups = [dict(group=name, parameters=10, gradient_present_parameters=1,
                       gradient_nonzero_parameters=1, changed_parameters=1,
                       max_abs_gradient_f64_be=contract.encode_float(1.0),
                       max_abs_delta_f64_be=contract.encode_float(0.1))
                  for name in contract.PARAMETER_GROUPS]
        observed = dict(schema=contract.OBSERVATION_SCHEMA, profile=wire.PROFILE, status="candidate",
            authority="DENY_ALL", request_sha256=wire.sha(self.request_raw),
            request_binding_digest=contract.request_binding_digest(self.request),
            training_profile_digest=contract.PROFILE_DIGEST, update_rule_digest=contract.update_rule_digest(self.request),
            execution_source_digest=self.sources.h_digest(), execution_sources=self.sources.h_rows(),
            absent_source_paths=self.sources.h_absent(),
            predecessor=dict(sha256=wire.sha(self.predecessor), bytes=len(self.predecessor),
                             after_sha256=wire.sha(self.predecessor), roundtrip=True),
            candidate=dict(sha256=wire.sha(candidate), bytes=len(candidate), roundtrip=True, changed=True),
            training=dict(requested_steps=2, completed_steps=2, source_samples=1, source_record_count=3,
                dataset_observed_rows=7, dataset_observed_bytes=1000, prefix_bytes=8,
                continuation_bytes=4, continuation_scalars=1, losses_f64_be=[contract.encode_float(2.0)] * 3,
                parameter_groups=groups, core_gradient_nonzero=True, core_changed_parameters=1,
                effective_wall_limit_milliseconds=5000),
            runtime=dict(python_version="synthetic", torch_version="not imported", platform="fixture",
                         device="cpu", dtype="float64", threads=1),
            cost=dict(wall_nanoseconds=1, cpu_nanoseconds=0, scope=contract.COST_SCOPE,
                      physical_energy_joules=None, full_history_cost=None),
            claims=dict(content_loss_training=True, ndu_training=False, evaluation=False,
                        product_loading=False, selection=False, stage_advanced=False),
            input_files_unchanged=True, source_files_unchanged=True)
        raw_observed = contract.json_bytes(observed)
        contract.validate_observation(raw_observed, self.request)
        started = dict(schema="hepta.joint-text-worker.started.v1", profile=wire.PROFILE,
                       status="started", request_sha256=wire.sha(self.request_raw))
        completed = dict(schema="hepta.joint-text-worker.completed.v1", profile=wire.PROFILE,
                         status="complete", request_sha256=wire.sha(self.request_raw),
                         observation_sha256=wire.sha(raw_observed), candidate_sha256=wire.sha(candidate))
        directory = self.job.child(self.target["output_id"], create=True)
        for name, raw in (("candidate.heptapk", candidate), ("observation.json", raw_observed),
                          ("started.json", contract.json_bytes(started)),
                          ("completed.json", contract.json_bytes(completed))):
            directory.write(name, raw)
        return directory
