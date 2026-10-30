"""Linux tiny-process wiring tests; all scientific entrypoints are test doubles.

Actual child processes, wait4, file receipts, module scopes, and the production
wrapper code are exercised. Synthetic metadata never claims scientific work.
"""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

from operational.parameter_field_recovery06 import cwd_runner as cr
from operational.parameter_field_recovery06 import owned_children as owned
from operational.parameter_field_recovery06 import resource_backpressure as rb


class TinyTransport:
    """Record intended wrapper argv; spawn only this explicit tiny test program."""

    def __init__(self):
        self.calls = []
        self.processes = []

    def __getattr__(self, name):
        return getattr(subprocess, name)

    def Popen(self, argv, **kwargs):
        self.calls.append((deepcopy(argv), deepcopy(kwargs)))
        program = "import json,sys,time; print(json.dumps({'test_only_original_argv':sys.argv[1:]}),flush=True); time.sleep(.03)"
        child = subprocess.Popen([sys.executable, "-B", "-c", program, *argv], **kwargs)
        self.processes.append(child)
        return child


class CwdRunnerTests(unittest.TestCase):
    def setUp(self):
        output = os.environ.get("HEPTA_CWD_TEST_OUTPUT")
        if output:
            self.base = Path(output) / self._testMethodName
            self.base.mkdir(parents=True, exist_ok=False)
        else:
            self.temporary = tempfile.TemporaryDirectory(prefix="hepta-cwd06-")
            self.addCleanup(self.temporary.cleanup)
            self.base = Path(self.temporary.name)
        self.source = self.base / "fullstudy_recovery06_git"
        self.raw = self.base / "fullstudy_execution06_durable_raw"
        self.ops = self.base / "fullstudy_execution06_ops"
        self.empty = self.ops / "empty_cwd"
        for path in (self.source, self.raw, self.empty):
            path.mkdir(parents=True)
        self.policy = {"schema": cr.POLICY_SCHEMA, "execution_episode": cr.EPISODE,
            "source_root": str(self.source), "raw_root": str(self.raw), "ops_root": str(self.ops),
            "python": os.path.abspath(sys.executable), "empty_cwd": str(self.empty),
            "source_files": {}, "worker_modules": sorted(cr.WORKERS), "analysis_module": cr.ANALYSIS,
            "capacity_wait_seconds": 300}
        for index, name in enumerate(cr.RUNTIME_SOURCES):
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# static metadata fixture %d\n" % index)
            self.policy["source_files"][name] = cr.descriptor(path)["sha256"]
        self.policy["amendment"] = self.json_file("amendment.json", {
            "raw_root": str(self.raw), "concurrency": {"max_workers": 2, "memory_margin_bytes": rb.GiB,
                "worker_reservation_bytes": 768 * rb.MiB}, "proposed_resource_contract": {
                "global_raw_logical_bytes": 2 * rb.GiB, "minimum_private_allocatable_bytes": 256 * rb.MiB,
                "C_training_evidence_bytes": 350 * rb.MiB}})
        initial = self.json_file("initial.json", {"registered_commit": "a" * 40,
            "execution_episode": cr.EPISODE, "source_files": self.policy["source_files"]})
        self.producer_config = {"schema": "hepta.execution06.producer-config.1", "execution_episode": cr.EPISODE,
            "producer_map": self.json_file("map.json", {"fixture": "no scientific data"}),
            "import_receipt": self.json_file("import.json", {"fixture": "no scientific data"}),
            "fresh_registration": {"execution_episode": cr.EPISODE, "source_root": str(self.source),
                "raw_root": str(self.raw), "registered_commit": "a" * 40, "source_freeze": initial,
                "profile": self.policy["amendment"]}}
        self.policy["producer_config"] = self.json_file("producer.json", self.producer_config)
        self.policy_item = self.json_file("policy.json", self.policy)
        self.transport = TinyTransport()

    def json_file(self, name, value):
        path = self.ops / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True) + "\n")
        return cr.descriptor(path)

    def original_flags(self, phase="A", seed="29"):
        result = ["--root", str(self.raw), "--amendment", self.policy["amendment"]["path"],
                  "--amendment-sha256", self.policy["amendment"]["sha256"],
                  "--freeze", self.producer_config["fresh_registration"]["source_freeze"]["path"],
                  "--assets", str(self.base / "assets with spaces"), "--phase", phase]
        if phase != "W":
            result += ["--seed", seed]
        return [*result, "--execute"]

    def spawn_owned(self, original_module, original_flags, *, kind="controller", receipt="owner", write_failure=False):
        core = types.SimpleNamespace(subprocess=self.transport)
        received = []
        def callback():
            with cr.isolated_spawns(core, self.policy, self.policy_item["path"], self.policy_item["sha256"], kind, lambda: None):
                process = core.subprocess.Popen([sys.executable, "-B", "-m", original_module, *original_flags],
                    cwd=self.source, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    env={"SENTINEL": "unchanged", "PYTHONPATH": "old"})
                received.append(process)
                self.assertEqual(process.wait(timeout=3), 0)
                return json.loads(process.stdout.read())
        real_write = cr.write_new
        def write(path, value):
            if write_failure and Path(path).name == "STARTED.json":
                raise OSError("injected STARTED receipt failure")
            return real_write(path, value)
        with mock.patch.object(cr, "write_new", side_effect=write):
            result = owned.run_controller(core, callback, self.ops / receipt)
        self.assertIs(core.subprocess, self.transport)
        return result, received

    def start_policy(self, profile=None):
        if profile is None:
            profile = {"oom": 0, "oom_kill": 0}
        started = time.monotonic()
        value = {"schema": cr.START_SCHEMA, "execution_episode": cr.EPISODE,
            **{key: self.policy[key] for key in ("source_root", "raw_root", "ops_root")},
            "cwd_policy": self.policy_item, "supervisor_identity": cr.identity(os.getpid()),
            "started_monotonic": started, "deadline_monotonic": started + 43200,
            "oom_baseline": {key: profile[key] for key in ("oom", "oom_kill")}}
        return self.json_file("supervisor_run/START_POLICY.json", value)

    def test_policy_requires_exact_source_producer_and_initial_freeze_binding(self):
        with mock.patch.object(cr, "ROOT", self.source):
            self.assertEqual(cr.validate_policy(self.policy_item["path"], self.policy_item["sha256"]), self.policy)
            name = cr.RUNTIME_SOURCES[0]
            (self.source / name).write_text("changed source")
            with self.assertRaisesRegex(ValueError, "source binding differs"):
                cr.validate_policy(self.policy_item["path"], self.policy_item["sha256"])

    def test_policy_rejects_changed_producer_bytes_and_missing_runtime_closure(self):
        with mock.patch.object(cr, "ROOT", self.source):
            Path(self.policy["producer_config"]["path"]).write_text("{}\n")
            with self.assertRaisesRegex(ValueError, "descriptor bytes differ"):
                cr.validate_policy(self.policy_item["path"], self.policy_item["sha256"])
            self.policy["producer_config"] = self.json_file("producer.json", self.producer_config)
            self.policy["source_files"].pop(cr.RUNTIME_SOURCES[-1])
            changed = self.json_file("policy-changed.json", self.policy)
            with self.assertRaisesRegex(ValueError, "source closure is incomplete"):
                cr.validate_policy(changed["path"], changed["sha256"])

    def test_initial_source_freeze_cannot_omit_wrapper_sources(self):
        initial = self.producer_config["fresh_registration"]["source_freeze"]
        value = cr.read_json(initial)
        value["source_files"].pop(cr.RUNTIME_SOURCES[0])
        self.producer_config["fresh_registration"]["source_freeze"] = self.json_file("initial.json", value)
        self.policy["producer_config"] = self.json_file("producer.json", self.producer_config)
        changed = self.json_file("policy-changed.json", self.policy)
        with mock.patch.object(cr, "ROOT", self.source):
            with self.assertRaisesRegex(ValueError, "Initial producer source freeze"):
                cr.validate_policy(changed["path"], changed["sha256"])

    def test_shared_start_policy_preserves_actual_identity_baseline_and_deadline(self):
        start = self.start_policy({"oom": 4, "oom_kill": 4})
        actual = {"oom": 4, "oom_kill": 4, "effective_current": 123}
        guard = cr.SupervisorGuard(self.policy, self.policy_item["path"], self.policy_item["sha256"], lambda: dict(actual))
        before = deepcopy(guard.start)
        self.assertEqual(guard.initial_profile, actual)
        self.assertEqual(guard.own_identity, cr.identity(os.getpid()))
        self.assertEqual(guard.start_descriptor, start)
        self.assertEqual(guard.health(), actual)
        self.assertEqual(guard.start, before)
        actual["oom"] = 5
        with self.assertRaisesRegex(ValueError, "OOM counter increased"):
            guard.health()
        self.assertEqual(guard.start["oom_baseline"], {"oom": 4, "oom_kill": 4})

    def test_shared_start_policy_mutation_and_wrong_supervisor_identity_fail_closed(self):
        start = self.start_policy()
        guard = cr.SupervisorGuard(self.policy, self.policy_item["path"], self.policy_item["sha256"], lambda: {"oom": 0, "oom_kill": 0})
        Path(start["path"]).write_text(Path(start["path"]).read_text() + " ")
        with self.assertRaisesRegex(ValueError, "startup policy changed"):
            guard.health()
        value = cr.read_json(self.start_policy())
        value["supervisor_identity"]["start_ticks"] += 1
        self.json_file("supervisor_run/START_POLICY.json", value)
        with self.assertRaisesRegex(ValueError, "Supervisor process identity changed"):
            cr.SupervisorGuard(self.policy, self.policy_item["path"], self.policy_item["sha256"], lambda: {"oom": 0, "oom_kill": 0})

    def test_parent_identity_rejection_records_exact_expected_and_observed(self):
        value = cr.read_json(self.start_policy())
        actual = cr.identity(value["supervisor_identity"]["pid"])
        value["supervisor_identity"]["parent_pid"] += 1
        self.json_file("supervisor_run/START_POLICY.json", value)
        with self.assertRaisesRegex(ValueError, "Supervisor process identity changed") as caught:
            cr.SupervisorGuard(self.policy, self.policy_item["path"], self.policy_item["sha256"],
                               lambda: {"oom": 0, "oom_kill": 0})
        detail = json.loads(str(caught.exception).split(": ", 1)[1])
        self.assertEqual(detail, {"expected": value["supervisor_identity"], "observed": actual})

    def test_secondary_cleanup_exception_keeps_first_failure_in_bounded_receipt(self):
        try:
            try:
                raise RuntimeError("original supervisor parent changed")
            except RuntimeError:
                raise ValueError("poisoned stream refused a closing write")
        except ValueError as caught:
            self.assertEqual(cr.exception_chain(caught), {"errors": [
                {"error_type": "ValueError", "message": "poisoned stream refused a closing write"},
                {"error_type": "RuntimeError", "message": "original supervisor parent changed"}],
                "truncated_or_cyclic": False})

    def test_shared_deadline_is_not_reset_by_a_new_process_entry(self):
        value = cr.read_json(self.start_policy())
        value["started_monotonic"] = time.monotonic() - 43201
        value["deadline_monotonic"] = value["started_monotonic"] + 43200
        self.json_file("supervisor_run/START_POLICY.json", value)
        with self.assertRaisesRegex(ValueError, "absolute supervisor deadline exhausted"):
            cr.SupervisorGuard(self.policy, self.policy_item["path"], self.policy_item["sha256"], lambda: {"oom": 0, "oom_kill": 0})

    def test_controller_workers_all_reenter_wrapper_with_exact_original_arguments(self):
        choices = [
            (cr.PREFIX + "run_v2", self.original_flags(), "A-29"),
            (cr.PREFIX + "architecture_run_v2", ["--root", str(self.raw), "--amendment", self.policy["amendment"]["path"],
             "--amendment-sha256", self.policy["amendment"]["sha256"], "--freeze", "/fixture/c-freeze", "--execute"], "C"),
            (cr.PREFIX + "endpoint_v2", ["--root", str(self.raw), "--amendment", self.policy["amendment"]["path"],
             "--amendment-sha256", self.policy["amendment"]["sha256"], "--phase", "A", "--freeze", "/fixture/endpoint-freeze", "--execute"], "A_endpoint")]
        original_popen = subprocess.Popen
        for index, (module, arguments, token) in enumerate(choices):
            result, children = self.spawn_owned(module, arguments, receipt="owner-%d" % index)
            actual, options = self.transport.calls[-1]
            self.assertEqual(actual[actual.index("--") + 1:], arguments)
            self.assertEqual(actual[:6], [sys.executable, "-B", str(Path(cr.__file__).resolve()), "--kind", "worker", "--policy"])
            self.assertEqual(actual[actual.index("--original-module") + 1], module)
            self.assertEqual(options["cwd"], str(self.empty))
            self.assertEqual(options["env"], {"SENTINEL": "unchanged", "PYTHONPATH": str(self.source), "PYTHONDONTWRITEBYTECODE": "1"})
            self.assertEqual(result["test_only_original_argv"], actual)
            self.assertIsNotNone(children[0].wait4)
            record = json.loads((self.ops / "cwd_launches" / token / "STARTED.json").read_text())
            self.assertFalse(record["environment_values_disclosed"])
            self.assertNotIn("SENTINEL", json.dumps(record))
            closure = json.loads((self.ops / ("owner-%d" % index) / "CLOSURE.json").read_text())
            self.assertTrue(closure["accounting_complete_for_attempted_direct_workers"])
        self.assertIs(subprocess.Popen, original_popen)

    def test_analysis_child_reenters_wrapper_and_preserves_parent_binding(self):
        arguments = ["--root", str(self.raw), "--amendment", self.policy["amendment"]["path"],
            "--amendment-sha256", self.policy["amendment"]["sha256"], "--freeze", "/fixture/analysis", "--child", "--parent-pid", str(os.getpid())]
        self.spawn_owned(cr.ANALYSIS, arguments, kind="analysis")
        effective = self.transport.calls[0][0]
        self.assertEqual(effective[effective.index("--") + 1:], arguments)
        self.assertEqual(effective[effective.index("--kind") + 1], "analysis")
        self.assertNotIn("--original-module", effective)
        self.assertTrue((self.ops / "cwd_launches/ANALYSIS/STARTED.json").is_file())

    def test_started_receipt_failure_has_owned_wait4_and_preserves_original_error(self):
        with self.assertRaisesRegex(OSError, "STARTED receipt failure"):
            self.spawn_owned(cr.PREFIX + "run_v2", self.original_flags(), write_failure=True)
        closure = json.loads((self.ops / "owner/CLOSURE.json").read_text())
        self.assertEqual(closure["returned_children"], 1)
        self.assertTrue(closure["all_returned_direct_children_reaped"])
        self.assertTrue(closure["accounting_complete_for_attempted_direct_workers"])
        self.assertEqual(closure["original_exception"]["type"], "OSError")
        self.assertIsNotNone(closure["children"][0]["wait4"])
        self.assertIsNotNone(self.transport.processes[0].returncode)

    def test_constructor_failure_is_not_retried_or_given_invented_child_cost(self):
        with mock.patch.object(self.transport, "Popen", side_effect=OSError("constructor fixture failure")) as popen:
            with self.assertRaisesRegex(OSError, "constructor fixture failure"):
                self.spawn_owned(cr.PREFIX + "run_v2", self.original_flags())
        self.assertEqual(popen.call_count, 1)
        closure = json.loads((self.ops / "owner/CLOSURE.json").read_text())
        self.assertEqual(closure["returned_children"], 0)
        self.assertTrue(closure["construction_wait4_unavailable"])
        self.assertFalse(closure["accounting_complete_for_attempted_direct_workers"])
        self.assertTrue((self.ops / "cwd_launches/A-29/SPAWN_FAILED.json").is_file())

    def test_dirty_cwd_wrong_root_options_and_imported_a17_never_spawn(self):
        core = types.SimpleNamespace(subprocess=self.transport)
        arguments = self.original_flags()
        def callback():
            with cr.isolated_spawns(core, self.policy, self.policy_item["path"], self.policy_item["sha256"], "controller", lambda: None):
                command = [sys.executable, "-B", "-m", cr.PREFIX + "run_v2", *arguments]
                (self.empty / "unexpected").write_text("fixture")
                with self.assertRaisesRegex(ValueError, "not empty"):
                    core.subprocess.Popen(command, cwd=self.source, env={})
                (self.empty / "unexpected").unlink()
                with self.assertRaises(ValueError):
                    core.subprocess.Popen(command, cwd=self.source, env={}, shell=True)
                with self.assertRaises(ValueError):
                    core.subprocess.Popen(command, cwd=self.base, env={})
                a17 = [sys.executable, "-B", "-m", cr.PREFIX + "run_v2", *self.original_flags(seed="17")]
                with self.assertRaisesRegex(ValueError, "Imported A17"):
                    core.subprocess.Popen(a17, cwd=self.source, env={})
        owned.run_controller(core, callback, self.ops / "owner")
        self.assertEqual(self.transport.calls, [])
        self.assertIs(core.subprocess, self.transport)

    def test_unowned_proxy_and_legacy_resume_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Owned wait4 proxy"):
            cr.CwdSubprocess(subprocess, self.policy, self.policy_item["path"], self.policy_item["sha256"], "controller", health_check=lambda: None)
        for option in ("--resume-admission", "--recover-zero-work"):
            with self.assertRaisesRegex(ValueError, "legacy resume/recovery"):
                cr.invocation("controller", [*self.original_flags(), option])
        with self.assertRaisesRegex(ValueError, "Explicit registered worker"):
            cr.invocation("worker", self.original_flags(), "unregistered.module")
        with self.assertRaisesRegex(ValueError, "Only worker"):
            cr.invocation("finalizer", self.original_flags(), cr.PREFIX + "run_v2")

    def runtime_policy(self):
        """Bound real code; metadata/ProducerAdapter are explicit test fixtures."""
        self.policy["source_root"] = str(cr.ROOT)
        self.policy["source_files"] = {name: cr.descriptor(cr.ROOT / name)["sha256"] for name in cr.RUNTIME_SOURCES}
        initial = self.json_file("runtime-freeze.json", {"source_files": self.policy["source_files"]})
        self.producer_config["fresh_registration"].update(source_root=str(cr.ROOT), source_freeze=initial)
        self.policy["producer_config"] = self.json_file("runtime-producer.json", self.producer_config)
        self.policy_item = self.json_file("runtime-policy.json", self.policy)
        self.start_policy(rb.RESOURCE.memory_profile())
        return initial

    def test_dispatch_factories_see_installed_resources_and_scopes_restore(self):
        self.runtime_policy()
        events = []
        class Producer:
            import_receipt = {"fixture": True}
            def factory(self, label, module):
                # A/B/W/R import StorageBudget inside execute(), while
                # endpoint/finalizer also keep a module alias.
                resource = importlib.import_module(cr.PREFIX + "resource_v2")
                active = getattr(module, "StorageBudget", resource.StorageBudget)
                self_assert = issubclass(active, rb.BackpressureBudget)
                if label == "runner":
                    self_assert = self_assert and module.phase_budget_type.__module__ == rb.__name__
                events.append((label, self_assert))
                return types.SimpleNamespace(main=lambda: events.append((label + "_main", list(sys.argv))))
            def for_runner(self, module): return self.factory("runner", module)
            def for_endpoint(self, module): return self.factory("endpoint", module)
            def for_analysis_launcher(self, module): return self.factory("analysis", module)
            def for_finalizer(self, module): return self.factory("finalizer", module)
        p = rb.BackpressurePolicy(root=self.raw, journal_directory=self.ops / "fixture-capacity",
            source_root=cr.ROOT, expected_sources=self.policy["source_files"],
            deadline_monotonic=time.monotonic() + 30, oom_baseline={"oom": 0, "oom_kill": 0},
            health_check=lambda: None, max_wait_seconds=2, test_profile_reader=lambda: {
                "oom": 0, "oom_kill": 0, "effective_current": 0, "limit": 8 * rb.GiB})
        guard = types.SimpleNamespace(start_descriptor={"fixture": True}, health=lambda: None)
        previous_argv = sys.argv
        original_budget = rb.RESOURCE.StorageBudget
        with rb.installed(p, allow_test_policy=True) as install:
            for index, (kind, module, label) in enumerate((
                    ("worker", cr.PREFIX + "run_v2", "runner"),
                    ("worker", cr.PREFIX + "endpoint_v2", "endpoint"),
                    ("finalizer", cr.FINALIZER, "finalizer"))):
                cr.dispatch(kind, module, ["--fixture", str(index)], self.policy, self.policy_item["path"],
                    self.policy_item["sha256"], Producer(), install, guard, self.ops / ("dispatch-%d" % index))
                self.assertIn((label, True), events)
            architecture = importlib.import_module(cr.PREFIX + "architecture_run_v2")
            with mock.patch.object(architecture, "main", side_effect=lambda: events.append(("C_main", issubclass(rb.RESOURCE.StorageBudget, rb.BackpressureBudget) and architecture.store_type is rb.store_type))):
                cr.dispatch("worker", architecture.__name__, ["--fixture", "C"], self.policy, self.policy_item["path"],
                    self.policy_item["sha256"], Producer(), install, guard, self.ops / "dispatch-C")
            self.assertIn(("C_main", True), events)
        self.assertIs(sys.argv, previous_argv)
        self.assertIs(rb.RESOURCE.StorageBudget, original_budget)
        self.assertNotIn("torch", sys.modules)
        self.assertNotIn("numpy", sys.modules)

    def test_controller_owner_covers_entire_envelope_and_restores_core_after_failure(self):
        from operational.parameter_field_recovery06 import controller
        envelope = importlib.import_module(cr.PREFIX + "controller_envelope_v2")
        original_core, original_argv = envelope.core, sys.argv
        fake_core = types.SimpleNamespace(subprocess=self.transport, StorageBudget="original fixture budget")
        guard = types.SimpleNamespace(start_descriptor={"fixture": True}, health=lambda: None)
        producer = types.SimpleNamespace(import_receipt={"fixture": True})
        def fail_before_run():
            self.assertIs(envelope.core, fake_core)
            self.assertEqual(fake_core.StorageBudget, "bound fixture budget")
            self.assertIsInstance(fake_core.subprocess, cr.CwdSubprocess)
            self.assertIsInstance(fake_core.subprocess.original.owner, owned.OwnedChildren)
            raise RuntimeError("envelope validation fixture failure")
        with mock.patch.object(controller, "ControllerCore", return_value=fake_core), mock.patch.object(envelope, "main", side_effect=fail_before_run):
            with self.assertRaisesRegex(RuntimeError, "envelope validation fixture failure"):
                cr.dispatch("controller", envelope.__name__, ["--fixture", "yes"], self.policy, self.policy_item["path"],
                    self.policy_item["sha256"], producer, {"budget_type": "bound fixture budget"}, guard, self.ops / "controller-wrapper")
        self.assertIs(envelope.core, original_core)
        self.assertIs(fake_core.subprocess, self.transport)
        self.assertEqual(fake_core.StorageBudget, "original fixture budget")
        self.assertIs(sys.argv, original_argv)
        closure = json.loads((self.ops / "controller-wrapper/owned_children/CLOSURE.json").read_text())
        self.assertEqual(closure["attempt_count"], 0)
        self.assertEqual(closure["original_exception"]["message"], "envelope validation fixture failure")

    def test_analysis_parent_uses_factory_and_owned_scope_child_uses_new_cost_adapter(self):
        from operational.parameter_field_recovery06 import historical_costs
        events = []
        parent = types.SimpleNamespace(subprocess=self.transport)
        def parent_main():
            events.append("parent-main")
            self.assertIsInstance(parent.subprocess, cr.CwdSubprocess)
            self.assertIsInstance(parent.subprocess.original.owner, owned.OwnedChildren)
        parent.main = parent_main
        class Producer:
            def for_analysis_launcher(self, module):
                events.append("analysis-factory")
                return parent
        guard = types.SimpleNamespace(start_descriptor={"fixture": True}, health=lambda: None)
        cr.dispatch("analysis", cr.ANALYSIS, ["--fixture", "parent"], self.policy, self.policy_item["path"],
            self.policy_item["sha256"], Producer(), {}, guard, self.ops / "analysis-parent")
        self.assertIs(parent.subprocess, self.transport)
        inputs = self.json_file("inputs.json", {"fixture": True})
        @contextmanager
        def costs(item):
            self.assertEqual(item, inputs)
            events.append("new-cost-enter")
            try:
                yield
            finally:
                events.append("new-cost-exit")
        parent.main = lambda: events.append("child-main")
        with mock.patch.object(historical_costs, "apply_cost_adapter", side_effect=costs):
            cr.dispatch("analysis", cr.ANALYSIS, ["--child", "--inputs", inputs["path"], "--expected-sha256", inputs["sha256"]],
                self.policy, self.policy_item["path"], self.policy_item["sha256"], Producer(), {}, guard, self.ops / "analysis-child")
        self.assertEqual(events, ["analysis-factory", "parent-main", "analysis-factory", "new-cost-enter", "child-main", "new-cost-exit"])
        self.assertFalse((self.ops / "analysis-child/owned_children").exists())

    def test_fresh_exec_runs_wrapper_installation_and_preserves_original_numeric_argv(self):
        initial = self.runtime_policy()
        original = self.original_flags()
        original[original.index("--freeze") + 1] = initial["path"]
        proof = self.ops / "tiny-wrapper-proof.json"
        # This actual new Python process calls the real CLI with only explicit
        # test doubles for metadata trust, ProducerAdapter and memory sampling.
        # Its entrypoint is a tiny write, never a scientific function.
        program = r'''
import json,os,pathlib,sys,types
from unittest import mock
from operational.parameter_field_recovery06 import cwd_runner as cr,resource_backpressure as rb,producer_adapter as pa
policy_item=json.loads(sys.argv[1]); original=json.loads(sys.argv[2]); proof=pathlib.Path(sys.argv[3])
policy=cr.read_json(policy_item)
original_policy,original_install=rb.BackpressurePolicy,rb.installed
baseline=cr.read_json(cr.descriptor(pathlib.Path(policy['ops_root'])/'supervisor_run/START_POLICY.json'))['oom_baseline']
def make_policy(**kwargs):
    return original_policy(**kwargs,test_profile_reader=lambda:{**baseline,'effective_current':0,'limit':8*rb.GiB})
def install(policy):return original_install(policy,allow_test_policy=True)
class Producer:
    def __init__(self,*args):self.import_receipt=args[1]
    def for_runner(self,module):
        def tiny():
            registration=cr.read_json(policy['amendment'])
            from experiments.parameter_field_fullstudy_20261029.resource_v2 import StorageBudget
            storage=StorageBudget(policy['raw_root'],registration)
            storage.write_bytes('tiny-wiring-proof.bin',b'no scientific work')
            proof.write_text(json.dumps({'pid':os.getpid(),'argv':sys.argv[1:],'backpressure_installed':isinstance(storage,rb.BackpressureBudget),'torch_imported':'torch' in sys.modules,'numpy_imported':'numpy' in sys.modules,'test_only':True}))
        return types.SimpleNamespace(main=tiny)
with mock.patch.object(cr,'validate_policy',return_value=policy),mock.patch.object(pa,'ProducerAdapter',Producer),mock.patch.object(rb,'BackpressurePolicy',side_effect=make_policy),mock.patch.object(rb,'installed',side_effect=install):
    cr.main(['--kind','worker','--original-module',cr.PREFIX+'run_v2','--policy',policy_item['path'],'--expected-policy-sha256',policy_item['sha256'],'--',*original])
'''
        env = {**os.environ, "PYTHONPATH": str(cr.ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
        child = subprocess.run([sys.executable, "-B", "-c", program, json.dumps(self.policy_item), json.dumps(original), str(proof)],
                               cwd=self.empty, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        self.assertEqual(child.returncode, 0, child.stderr.decode())
        self.assertEqual((child.stdout, child.stderr), (b"", b""))
        value = json.loads(proof.read_text())
        self.assertNotEqual(value["pid"], os.getpid())
        self.assertEqual(value["argv"], original)
        self.assertTrue(value["backpressure_installed"])
        self.assertFalse(value["torch_imported"] or value["numpy_imported"])
        self.assertEqual((self.raw / "tiny-wiring-proof.bin").read_bytes(), b"no scientific work")
        directories = list((self.ops / "wrapper_runs/A-29").iterdir())
        self.assertEqual(len(directories), 1)
        complete = json.loads((directories[0] / "COMPLETE.json").read_text())
        self.assertTrue(complete["wrapper_call_returned_successfully"])
        self.assertFalse(complete["scientific_completion_claim"])
        start = cr.read_json(cr.descriptor(self.ops / "supervisor_run/START_POLICY.json"))
        self.assertEqual(complete["shared_deadline_monotonic"], start["deadline_monotonic"])
        self.assertEqual(complete["shared_oom_baseline"], start["oom_baseline"])
        journals = list((self.ops / "resource_backpressure/A-29").glob("*/CAPACITY_EVENTS.jsonl"))
        self.assertEqual(len(journals), 1)
        self.assertTrue(json.loads(journals[0].read_text().splitlines()[0])["test_only"])
        self.assertEqual(list(self.empty.iterdir()), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
