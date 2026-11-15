"""Targeted Colab control port tests: real pinned adapter, fake provider, zero training.

Set HCSN_COLAB_ADAPTER_SOURCE, HCSN_COLAB_RUNNER_SOURCE and
HCSN_COLAB_AUTHORIZER_SOURCE to the exact installed
source snapshots. They are external adapter dependencies, not scientific files.
No test instantiates OfficialSDKProvider or invokes a provider/network operation.
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    exec(compile(Path(path).read_bytes(), str(path), "exec"), module.__dict__)
    return module


owner = load("hcsn_colab_v3_test_owner", HERE / "native_owner.py")
cloud = load("hcsn_colab_v3_test_cloud", HERE / "cloud_batch.py")
finalizer = load("hcsn_colab_v3_test_finalizer", HERE / "finalize_mechanism.py")
capsule = load("hcsn_colab_v3_test_capsule", HERE / "capsule_contract.py")


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = value if isinstance(value, bytes) else owner.adapter_canonical(value)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


class FakeProvider:
    def __init__(self, fixture):
        self.fixture = fixture

    def execute(self, job, code, on_output):
        self.fixture.fake_dispatches += 1
        if self.fixture.unknown:
            raise ConnectionError("offline fixture lost response")
        self.publish_fixture_terminal(job)

    def publish_fixture_terminal(self, job):
        identity = {k: job[k] for k in ("job_id", "payload_sha256", "endpoint", "kernel_id", "session_id")}
        outputs = {name: b"{}\n" for name in owner.ARTIFACTS}
        declared = dict(schema="hepta-artifact-manifest-v1", request_id=job["idempotency_key"],
            files=[dict(path=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
                   for name, raw in sorted(outputs.items()) if name != "artifact-manifest.json"])
        outputs["artifact-manifest.json"] = owner.adapter_canonical(declared)
        entries = {}
        for name, raw in {**outputs, "stdout": b"", "stderr": b""}.items():
            suffix = {"stdout": "/stdout.bin", "stderr": "/stderr.bin"}.get(name, "/work/" + name)
            path = job["remote_dir"] + suffix
            self.fixture.remote_files[path] = raw
            entries[name] = dict(remote_path=path, size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        manifest = dict(identity, entries=entries, errors=[])
        manifest_raw = owner.adapter_canonical(manifest)
        receipt = dict(identity, state="succeeded", exit_code=0, cloud_execution_stopped=True,
            cloud_process_group_alive=False, artifact_manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
            artifact_manifest_size=len(manifest_raw))
        self.fixture.remote_files[job["remote_dir"] + "/artifacts.json"] = manifest_raw
        self.fixture.remote_files[job["remote_dir"] + "/status.json"] = owner.adapter_canonical(receipt)

    def read_bytes(self, path):
        if path.endswith("/status.json"):
            self.fixture.status_reads += 1
            if self.fixture.resolve_on_second_status and self.fixture.status_reads == 2:
                job_id = path.split("/")[-2]
                self.publish_fixture_terminal(self.fixture.adapter.engine.ledger.get(job_id))
        if path not in self.fixture.remote_files:
            raise FileNotFoundError("offline fixture absent")
        return self.fixture.remote_files[path]

    def write_bytes(self, path, raw):
        raise AssertionError("No control test may perform an upload")

    def close(self):
        pass


class Fixture:
    def __init__(self, root, adapter_source, runner_source, authorizer_source):
        self.root, self.remote_files, self.fake_dispatches, self.unknown = root, {}, 0, False
        self.status_reads, self.resolve_on_second_status = 0, False
        installed = root / "installed"
        write(installed / "hepta_colab.py", adapter_source)
        write(installed / "remote_runner.py", runner_source)
        write(installed / "authorize_colab.py", authorizer_source)
        self.module = load("hcsn_installed_adapter_fixture_" + root.name.replace("-", "_"), installed / "hepta_colab.py")
        original = dict(name="original-bound", session_name="owned-fixture", state_file=str(root / "session-state"),
            endpoint="gpu-fixture-owned", kernel_id="fixture-kernel", session_id="fixture-session",
            remote_root="/content/hepta_jobs", max_wall_seconds=600, max_artifact_bytes=33554432,
            max_output_bytes=8388608, auth_provider="oauth2", expected_account_email="fixture@example.invalid")
        profile = dict(original, name="colab-v3-execution", max_wall_seconds=3000, max_artifact_bytes=134217728)
        original_path, profile_path = root / "bound.json", root / "execution.json"
        original_sha, profile_sha = write(original_path, original), write(profile_path, profile)
        state_dir = root / "same-authoritative-adapter-ledger"
        outcome = dict(schema="hcsn-colab-bind-outcome-v1", status="BOUND_IDENTITY_VERIFIED", admitted=True,
            profile_raw_sha256=original_sha, manager_result=dict(phase="bound", owned_runtime=True, owned_kernel=True,
                runtime_submit_attempts=1, kernel_submit_attempts=1,
                profile_hash=hashlib.sha256(owner.adapter_canonical(original)).hexdigest(),
                profile_path=str(original_path), jobs_state_dir=str(state_dir), endpoint=profile["endpoint"],
                kernel_id=profile["kernel_id"], client_session_id=profile["session_id"],
                server_session_id="distinct-actual-server-session", session_name=profile["session_name"]))
        outcome_path = root / "outcome.json"
        outcome_sha = write(outcome_path, outcome)
        provider = dict(schema="hepta-colab-fixed-profile-v3", adapter_path=str(installed / "hepta_colab.py"),
            adapter_sha256=owner.ADAPTER_SHA, authorizer_sha256=owner.AUTHORIZER_SHA, runner_path=str(installed / "remote_runner.py"), runner_sha256=owner.RUNNER_SHA,
            profile_path=str(profile_path), profile_sha256=profile_sha,
            profile_fingerprint=hashlib.sha256(owner.adapter_canonical(profile)).hexdigest(),
            binding_profile_path=str(original_path), binding_profile_sha256=original_sha,
            binding_outcome_path=str(outcome_path), binding_outcome_sha256=outcome_sha,
            state_dir=str(state_dir), native_python=sys.executable, anchor_job_id="unused-offline-anchor")
        rows, groups = [], []
        for group_index in range(8):
            group_id = "fixture-group-" + str(group_index)
            ids = []
            for offset in range(20):
                index = len(rows)
                fit_id = f"fit-{index:03d}"
                ids.append(fit_id)
                rows.append(dict(index=index, fit_id=fit_id, group_id=group_id))
            groups.append(dict(group_id=group_id, fit_ids=ids))
        self.config = dict(provider=provider, ordered_roster=rows, groups=groups, identity={"study_id": "explicit-fixture-no-science"},
            control_pins={name: hashlib.sha256((HERE / name).read_bytes()).hexdigest() for name in owner.CONTROL_FILES})
        self.config["provider_binding"] = owner.provider_binding(self.config)
        self.profile = self.module.Profile.load(profile_path)
        self.adapter = owner.Adapter.__new__(owner.Adapter)
        self.adapter.config, self.adapter.root, self.adapter.module, self.adapter.profile = self.config, root / "owner", self.module, self.profile
        self.adapter.provider_factory = lambda _: FakeProvider(self)
        self.adapter.engine = self.module.Engine(self.profile, self.module.Ledger(state_dir),
                                                 provider_factory=lambda _: FakeProvider(self))
        self.code = "pass  # control fixture; no scientific imports or updates\n"
        self.request = "colab-v3-targeted-control-fixture"
        source_path = self.adapter.root / "provider-jobs" / self.request / "source.py"
        code_sha = write(source_path, self.code.encode())
        self.active = dict(request_id=self.request, code_sha256=code_sha, source_path=str(source_path),
            provider_binding=self.config["provider_binding"], group_id=groups[0]["group_id"], phase="fit",
            planned_fit_ids=groups[0]["fit_ids"], planned_evaluation_ids=[], producer=None,
            terminal_observation=None, adapter_registration=None, asset_upload_receipt={"status": "VERIFIED"},
            dispatch_requested=False, post_run_reconciliation=None, reserved_unix=0., ever_claimed_fit_ids=[], ever_claimed_evaluation_ids=[])

    def register(self):
        record = self.adapter.call("submit", self.request, self.code)
        self.active["producer"] = owner.validate_remote(record, self.active, self.config)
        self.active["adapter_registration"] = record
        return record

    def complete(self):
        registration = self.register()
        record = self.adapter.call("run", registration["job"]["job_id"])
        owner.validate_remote(record, self.active, self.config)
        self.active["terminal_observation"] = record
        return record


class ColabPortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter_bytes = Path(os.environ["HCSN_COLAB_ADAPTER_SOURCE"]).read_bytes()
        cls.runner_bytes = Path(os.environ["HCSN_COLAB_RUNNER_SOURCE"]).read_bytes()
        cls.authorizer_bytes = Path(os.environ["HCSN_COLAB_AUTHORIZER_SOURCE"]).read_bytes()
        if hashlib.sha256(cls.adapter_bytes).hexdigest() != owner.ADAPTER_SHA or hashlib.sha256(cls.runner_bytes).hexdigest() != owner.RUNNER_SHA or hashlib.sha256(cls.authorizer_bytes).hexdigest() != owner.AUTHORIZER_SHA:
            raise AssertionError("Exact installed external adapter dependencies are required; no skips")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.fixture = Fixture(self.root, self.adapter_bytes, self.runner_bytes, self.authorizer_bytes)

    def tearDown(self):
        self.tmp.cleanup()

    def test_actual_adapter_registration_and_fetch_preserve_identity(self):
        remote = self.fixture.complete()
        result = self.fixture.adapter.fetch_all(remote, self.fixture.active)
        self.assertEqual(owner.verified_artifacts(result, remote, self.fixture.active),
                         Path(self.fixture.active["source_path"]).parent / "artifacts")
        self.assertEqual(self.fixture.fake_dispatches, 1)
        self.assertEqual(remote["job"]["submit_attempts"], 1)
        self.assertEqual(set(remote["manifest"]["entries"]), set(owner.ARTIFACTS) | {"stdout", "stderr"})

    def test_original_payload_over_colab_limit_is_rejected_before_dispatch(self):
        with self.assertRaises(self.fixture.module.IntegrityError):
            self.fixture.adapter.engine.submit("too-large", "x" * 399295, [], 3000)
        self.assertEqual(self.fixture.fake_dispatches, 0)

    def test_new_profile_cannot_bypass_same_kernel_unknown_ledger(self):
        self.fixture.unknown = True
        registration = self.fixture.register()
        observed = self.fixture.adapter.call("run", registration["job"]["job_id"])
        self.assertEqual(observed["job"]["state"], "unknown")
        changed = self.fixture.module.Profile(**dict(self.fixture.profile.__dict__, name="another-fingerprint"))
        same_ledger = self.fixture.adapter.engine.ledger
        with self.assertRaises(self.fixture.module.SessionBusy):
            self.fixture.module.Engine(changed, same_ledger, provider_factory=lambda _: FakeProvider(self.fixture)).submit("new-id", "pass", [], 10)
        self.assertEqual(self.fixture.fake_dispatches, 1)

    def test_provider_rejects_different_ledger_or_changed_bound_identity(self):
        for field, value in (("state_dir", str(self.root / "fresh-wrong-ledger")), ("binding_profile_path", str(self.root / "missing"))):
            bad = copy.deepcopy(self.fixture.config)
            bad["provider"][field] = value
            with self.assertRaises((owner.OwnerHalt, FileNotFoundError)):
                owner.provider_binding(bad)
        profile_path = Path(self.fixture.config["provider"]["profile_path"])
        profile = json.loads(profile_path.read_text())
        profile["kernel_id"] = "another-kernel"
        self.fixture.config["provider"]["profile_sha256"] = write(profile_path, profile)
        self.fixture.config["provider"]["profile_fingerprint"] = hashlib.sha256(owner.adapter_canonical(profile)).hexdigest()
        with self.assertRaises(owner.OwnerHalt):
            owner.provider_binding(self.fixture.config)

    def test_profile_uses_actual_client_session_not_distinct_server_session(self):
        config = copy.deepcopy(self.fixture.config)
        outcome_path = Path(config["provider"]["binding_outcome_path"])
        outcome = json.loads(outcome_path.read_text())
        manager = outcome["manager_result"]
        self.assertNotEqual(manager["client_session_id"], manager["server_session_id"])
        self.assertEqual(owner.provider_binding(config)["session_id"], manager["client_session_id"])
        profile_path = Path(config["provider"]["profile_path"])
        profile = json.loads(profile_path.read_text())
        # Even a newly hashed derivative cannot substitute the server-side ID.
        profile["session_id"] = manager["server_session_id"]
        config["provider"]["profile_sha256"] = write(profile_path, profile)
        config["provider"]["profile_fingerprint"] = hashlib.sha256(owner.adapter_canonical(profile)).hexdigest()
        with self.assertRaises(owner.OwnerHalt):
            owner.provider_binding(config)

    def test_unowned_reused_runtime_is_rejected(self):
        config = copy.deepcopy(self.fixture.config)
        path = Path(config["provider"]["binding_outcome_path"])
        outcome = json.loads(path.read_text())
        outcome["manager_result"]["owned_runtime"] = False
        config["provider"]["binding_outcome_sha256"] = write(path, outcome)
        with self.assertRaises(owner.OwnerHalt):
            owner.provider_binding(config)

    def test_provider_schema_payload_and_terminal_stop_are_independent_guards(self):
        good = self.fixture.complete()
        for change in ("schema", "payload", "stop", "fake-kaggle"):
            bad = copy.deepcopy(good)
            if change == "schema":
                bad["schema"] = "self-reported-authenticated"
            elif change == "payload":
                bad["job"]["payload_sha256"] = "0" * 64
            elif change == "stop":
                bad["receipt"]["cloud_execution_stopped"] = False
                bad["job"]["cloud_receipt"] = bad["receipt"]
            else:
                bad = {"schema": "hepta-kaggle-job-v1", "remote_state": "COMPLETE", "identity_verified": True}
            with self.subTest(change=change), self.assertRaises(owner.OwnerHalt):
                owner.validate_remote(bad, self.fixture.active, self.fixture.config)

    def test_manifest_path_traversal_rejected_even_with_rehashed_manifest(self):
        bad = copy.deepcopy(self.fixture.complete())
        entry = bad["manifest"]["entries"].pop("execution.json")
        bad["manifest"]["entries"]["../foreign"] = entry
        raw = owner.adapter_canonical(bad["manifest"])
        bad["receipt"].update(artifact_manifest_sha256=hashlib.sha256(raw).hexdigest(), artifact_manifest_size=len(raw))
        bad["job"]["cloud_receipt"] = bad["receipt"]
        with self.assertRaises(owner.OwnerHalt):
            owner.validate_remote(bad, self.fixture.active, self.fixture.config)

    def test_full_native_download_rejects_loss_or_rewritten_bytes(self):
        remote = self.fixture.complete()
        result = self.fixture.adapter.fetch_all(remote, self.fixture.active)
        missing = copy.deepcopy(result)
        missing["files"] = [x for x in missing["files"] if x["path"] != "study-capsule.tar.gz"]
        with self.assertRaises(owner.OwnerHalt):
            owner.verified_artifacts(missing, remote, self.fixture.active)
        (Path(result["directory"]) / "study-capsule.tar.gz").write_bytes(b"changed")
        with self.assertRaises(owner.OwnerHalt):
            owner.verified_artifacts(result, remote, self.fixture.active)

    def test_unknown_owner_keeps_all_reserved_and_never_reruns(self):
        self.fixture.unknown = True
        registration = self.fixture.register()
        active = copy.deepcopy(self.fixture.active)
        ledger = owner.Ledger(self.root / "formal-ledger-fixture", self.fixture.config)
        state = ledger.copy()
        for fit_id in active["planned_fit_ids"]:
            state["fits"][fit_id] = dict(state="RESERVED", ever_claimed=False, request_id=active["request_id"])
        state["active"], state["batch_count"] = active, 1
        ledger.append("RESERVED_FIXTURE", state)
        controller = owner.Owner(self.fixture.config, {}, self.root, HERE, ledger, None,
                                 adapter=self.fixture.adapter, asset_module=object())
        try:
            with self.assertRaises(owner.OwnerHalt):
                controller.run()
            self.assertEqual(self.fixture.fake_dispatches, 1)
            calls = [json.loads(p.read_text())["operation"] for p in (self.fixture.adapter.root / "adapter-calls").glob("*.json")]
            self.assertEqual(calls.count("run"), 1)
            self.assertEqual(calls.count("status"), 1)
            self.assertEqual(ledger.state["active"]["post_run_reconciliation"]["attempts"], 1)
            self.assertEqual(ledger.state["active"]["post_run_reconciliation"]["first_run_observation"]["job"]["state"], "unknown")
            self.assertEqual(sum(v["state"] == "RESERVED" for v in ledger.state["fits"].values()), 20)
            self.assertEqual(len(ledger.state["fits"]), 160)
            self.assertFalse(ledger.state["execution_finished"])
            self.assertIsNotNone(ledger.state["halted"])
        finally:
            ledger.lock.close()

    def test_one_readonly_status_resolves_unknown_but_full_capsule_gate_still_applies(self):
        self.fixture.unknown, self.fixture.resolve_on_second_status = True, True
        self.fixture.register()
        active = copy.deepcopy(self.fixture.active)
        ledger = owner.Ledger(self.root / "resolved-ledger-fixture", self.fixture.config)
        state = ledger.copy()
        for fit_id in active["planned_fit_ids"]:
            state["fits"][fit_id] = dict(state="RESERVED", ever_claimed=False, request_id=active["request_id"])
        state["active"], state["batch_count"] = active, 1
        ledger.append("RESERVED_FIXTURE", state)
        controller = owner.Owner(self.fixture.config, {}, self.root, HERE, ledger, None,
                                 adapter=self.fixture.adapter, asset_module=object())
        try:
            with patch.object(owner, "verify_local_pins", return_value=None), self.assertRaisesRegex(owner.OwnerHalt, "Unsupported batch"):
                controller.run()
            observed = ledger.state["active"]
            self.assertEqual(observed["post_run_reconciliation"]["first_run_observation"]["job"]["state"], "unknown")
            self.assertEqual(observed["terminal_observation"]["job"]["state"], "succeeded")
            self.assertEqual(self.fixture.fake_dispatches, 1)
            calls = [json.loads(p.read_text())["operation"] for p in (self.fixture.adapter.root / "adapter-calls").glob("*.json")]
            self.assertEqual(calls.count("run"), 1)
            self.assertEqual(calls.count("status"), 1)
            self.assertEqual(sum(v["ever_claimed"] for v in ledger.state["fits"].values()), 0)
            self.assertFalse(ledger.state["execution_finished"])
        finally:
            ledger.lock.close()

    def test_selection_requires_twenty_known_terminals_and_native_verified_lock(self):
        group = [{"fit_id": f"fit-{i:03d}"} for i in range(20)]
        known = {r["fit_id"]: {"status": "COMPLETED"} for r in group}
        config = dict(phase="selection", group_id="fixture", planned_fit_ids=[], planned_evaluation_ids=[])
        known["fit-019"]["status"] = "UNSTARTED"
        with self.assertRaises(cloud.OwnerHalt):
            cloud.phase_dispatch(config, group, known, self.root, {}, {}, lambda *args: None)
        known["fit-019"]["status"] = "UNKNOWN"
        with self.assertRaises(cloud.OwnerHalt):
            cloud.phase_dispatch(config, group, known, self.root, {}, {}, lambda *args: None)

    def test_actual_execution_request_must_match_native_job(self):
        remote = self.fixture.complete()
        request = {k: remote["job"][k] for k in ("job_id", "payload_sha256", "code_sha256", "endpoint", "kernel_id", "session_id")}
        request["created_at"] = 1.
        execution = dict(provider_binding=self.fixture.active["provider_binding"], colab_request=request,
                         colab_request_sha256=hashlib.sha256(owner.adapter_canonical(request)).hexdigest())
        owner.validate_execution_producer(execution, remote, self.fixture.active)
        execution["colab_request"] = dict(request, kernel_id="foreign")
        execution["colab_request_sha256"] = hashlib.sha256(owner.adapter_canonical(execution["colab_request"])).hexdigest()
        with self.assertRaises(owner.OwnerHalt):
            owner.validate_execution_producer(execution, remote, self.fixture.active)

    def test_real_asset_packet_and_two_complete_capsules_preserve_loser_weights(self):
        """Actual serialization/CRC/restore with explicit nontraining worker fixtures."""
        import contextlib
        import io
        import time
        import types
        assets_path = Path(os.environ.get("HCSN_COLAB_ASSET_SOURCE", str(HERE.parent / "colab_qualification_v3/asset_transport.py")))
        assets = load("hcsn_colab_assets_port_fixture", assets_path)
        source = self.root / "fixture-source"
        controls = source / owner.CONTROL_RELATIVE
        pins, control_pins = {}, {}
        for name in owner.CONTROL_FILES:
            raw = (HERE / name).read_bytes()
            target = controls / name
            control_pins[name] = write(target, raw)
            pins[owner.CONTROL_RELATIVE + "/" + name] = control_pins[name]
        pins[owner.ASSET_RELATIVE] = write(source / owner.ASSET_RELATIVE, assets_path.read_bytes())
        roster = [dict(fit_id=f"fit-{i:03d}", group_id="fixture-group" if i < 20 else f"other-{i//20}") for i in range(160)]
        group = roster[:20]
        operator, metadata = b"EXPLICIT_NONTRAINED_FIXTURE_NOT_NPZ", b'{"fixture_only":true}'
        native_inputs = self.root / "fixture-native-inputs"
        write(native_inputs / "operators-s81.npz", operator)
        write(native_inputs / "operators-s81.json", metadata)
        plan = dict(source_pins=pins, runtime_feasibility_policy=dict(provider="colab",
            cloud_job_max_seconds=3000, minimum_remaining_before_operation_seconds=720), max_fit_wall_seconds=480)
        plan_path = source / "fixture-plan.json"
        plan_sha = write(plan_path, plan)
        identity = dict(study_id="EXPLICIT_CONTROL_FIXTURE_NO_TRAINING", source_pins=pins, plan_sha256=plan_sha,
            registered_fit_count=160, ordered_fit_roster_sha256=capsule._sha(capsule._canonical(roster)),
            bundle_sha256=hashlib.sha256(operator).hexdigest(), bundle_metadata_sha256=hashlib.sha256(metadata).hexdigest())
        binding = dict(self.fixture.config["provider_binding"], remote_root=str(self.root / "fixture-colab-jobs"))
        config = dict(formal_training_start_authorized=True, published_plan_commit="a" * 40,
            published_plan_ref=cloud.PUBLISHED_REF, phase="fit", group_id="fixture-group",
            planned_fit_ids=[r["fit_id"] for r in group], planned_evaluation_ids=[], expected_group_fit_ids=[r["fit_id"] for r in group],
            source_pins=pins, control_pins=control_pins, plan_relative_path="fixture-plan.json", plan_sha256=plan_sha,
            identity=identity, admission_epoch_unix=time.time(), ever_claimed_fit_ids=[], ever_claimed_evaluation_ids=[],
            prior_capsule=None, provider_binding=binding, verified_selection_lock_sha256=None,
            qualified_input=dict(bundle_path=str(native_inputs / "operators-s81.npz"),
                                 metadata_path=str(native_inputs / "operators-s81.json")))
        def read_attempt(study, fit, ident):
            path = study / "attempts" / fit["fit_id"]
            if not path.exists():
                return {"status": "UNSTARTED"}
            return cloud.read_json(path / "terminal.json") if (path / "terminal.json").exists() else {"status": "UNKNOWN"}
        fake_contract = types.ModuleType("qualification.hcsn_regenerative.mechanism_contract")
        fake_contract.load_contract = lambda *args: (plan, {}, {}, roster, identity)
        fake_training = types.ModuleType("qualification.hcsn_regenerative.mechanism_training")
        fake_training.read_attempt = read_attempt
        fake_training.validate_selection_lock = lambda *args: self.fail("Fit phase must not select/test")
        def fixture_process(argv, cwd, env, logs, label, timeout, attempt=None):
            if label == "environment-preflight":
                write(Path(argv[-1]), dict(environment={"fixture_only": True}, check={"matched": True}))
            else:
                fit = next(r for r in group if r["fit_id"] == argv[-1])
                attempt.mkdir(parents=True)
                checkpoint = write(attempt / "checkpoint.pt", b"NONTRAINED_FIXTURE_" + fit["fit_id"].encode())
                write(attempt / "started.json", dict(identity=identity, fit=fit, fixture_only=True))
                write(attempt / "terminal.json", dict(identity=identity, fit=fit, phase="fit", status="COMPLETED",
                    optimizer_updates_completed=400, validation={"mse": .2}, checkpoint_sha256=checkpoint,
                    frozen_environment_check={"matched": True}, source_and_input_pins_unchanged_at_completion=True, fixture_only=True))
                write(attempt / "process-completion.json", dict(returncode=0, timed_out=False, fixture_only=True))
            return dict(returncode=0, timed_out=False, worker_children_stopped=True, fixture_only=True)
        modules = {fake_contract.__name__: fake_contract, fake_training.__name__: fake_training, "capsule_contract": capsule}
        previous_manifest = None
        with patch.dict(sys.modules, modules), patch.object(cloud, "run_process", side_effect=fixture_process), \
             patch.object(cloud, "gpu_counters", return_value={"available": False, "devices": []}), contextlib.redirect_stdout(io.StringIO()):
            for index, expected_count in ((1, 2), (2, 3)):
                config["request_id"] = "explicit-offline-colab-fixture-" + str(index)
                payload = cloud.build_payload(config, source, plan_path, controls, asset_module=assets,
                    asset_output=self.root / ("prepared-" + str(index)), remote_root="/content/explicit-offline-fixture")
                self.assertLessEqual(payload["code_bytes"], 262144)
                compile(payload["source_text"], "nonexecuted-materializer-fixture", "exec")
                prepared = payload["prepared_assets"]
                manifest_raw = Path(prepared["manifest_path"]).read_bytes()
                manifest = assets.validate_manifest(manifest_raw, prepared["manifest_sha256"])
                self.assertIn("source/" + owner.ASSET_RELATIVE, manifest["files"])
                self.assertNotIn(owner.ASSET_RELATIVE, manifest["files"])
                path_map = {part["remote_path"]: Path(prepared["parts_dir"]) / part["local_name"] for part in manifest["parts"]}
                actual_reader = assets.regular_bytes
                def fixture_remote_read(path, limit=assets.MAX_ARCHIVE):
                    # Map only the explicitly synthetic /content namespace; byte/hash logic remains real.
                    return actual_reader(path_map.get(str(path), path), limit)
                job_id = "fixture-job-" + str(index)
                work = Path(binding["remote_root"]) / job_id / "work"
                work.mkdir(parents=True)
                destination = work / ("materialized-" + config["request_id"])
                with patch.object(assets, "regular_bytes", side_effect=fixture_remote_read):
                    materialized = assets.materialize_assets(manifest_raw, prepared["manifest_sha256"], destination)
                active_asset = dict(prepared_assets=prepared, request_id=config["request_id"])
                owner.validate_materialization(materialized, active_asset)
                incomplete_materialization = dict(materialized, files={})
                with self.assertRaises(owner.OwnerHalt):
                    owner.validate_materialization(incomplete_materialization, active_asset)
                write(work / "asset-materialization.json", materialized)
                request = dict(job_id=job_id, payload_sha256="e" * 64, code_sha256=payload["code_sha256"],
                    endpoint=binding["endpoint"], kernel_id=binding["kernel_id"], session_id=binding["session_id"], created_at=1.)
                write(work.parent / "request.json", request)
                cloud_config = json.loads((destination / "batch-config.json").read_text())
                cloud_config.update(source_root=str(destination / "source"),
                    control_root=str(destination / "source" / owner.CONTROL_RELATIVE),
                    temporary_root=str(destination / "state"), inputs_root=str(destination / "inputs"))
                Path(cloud_config["temporary_root"]).mkdir()
                budget = [720., 720., 719.999] if index == 1 else [720., 719.999]
                with patch.object(cloud, "remaining_budget", side_effect=budget):
                    self.assertEqual(cloud.run_batch(cloud_config, work_root=work), 0)
                execution = cloud.read_json(work / "execution.json")
                current_manifest = cloud.read_json(work / "capsule-manifest.json")
                self.assertEqual(execution["status"], "EXPORTED")
                self.assertEqual(current_manifest["claimed_fit_ids"], [f"fit-{i:03d}" for i in range(expected_count)])
                self.assertIn("attempts/fit-000/checkpoint.pt", current_manifest["files"])
                self.assertIn("attempts/fit-001/checkpoint.pt", current_manifest["files"])
                if previous_manifest is not None:
                    capsule.validate_transition(previous_manifest, current_manifest, config["ever_claimed_fit_ids"], [])
                    missing_loser = copy.deepcopy(current_manifest)
                    del missing_loser["files"]["attempts/fit-001/checkpoint.pt"]
                    with self.assertRaises(capsule.CapsuleError):
                        capsule.validate_transition(previous_manifest, missing_loser, config["ever_claimed_fit_ids"], [])
                previous_manifest = current_manifest
                config["prior_capsule"] = dict(colab_producer={"fixture_only": True},
                    archive_sha256=current_manifest["archive"]["sha256"], archive_bytes=current_manifest["archive"]["bytes"],
                    manifest_sha256=cloud.file_sha(work / "capsule-manifest.json"),
                    native_archive_path=str(work / "study-capsule.tar.gz"), native_manifest_path=str(work / "capsule-manifest.json"))
                config["ever_claimed_fit_ids"] = current_manifest["claimed_fit_ids"]
                config["planned_fit_ids"] = execution["unclaimed_remaining_planned_fit_ids"]


    def native_launch_fixture(self):
        """Role-bridge fixture only; it does not qualify or start a study."""
        config = copy.deepcopy(self.fixture.config)
        source_root, control_root = self.root / "scientific-source", self.root / "native-control"
        source = (HERE / "native_owner.py").read_bytes()
        write(control_root / "native_owner.py", source)
        logical = owner.CONTROL_RELATIVE + "/native_owner.py"
        write(source_root / logical, source)
        config.update(plan_relative_path="fixture-plan.json", published_plan_commit="a" * 40,
                      published_plan_ref=owner.REF, publication_receipt={"fixture_only": True})
        config["plan_sha256"] = write(source_root / config["plan_relative_path"],
            dict(status="FROZEN", source_pins={logical: config["control_pins"]["native_owner.py"]}, fixture_only=True))
        config_path = self.root / "fixture-config.json"
        config_sha = write(config_path, config)
        job_id = "fixture-native-job"
        script = "raise SystemExit('offline role-bridge fixture; never executed')\n"
        job = dict(id=job_id, host="fixture-host", remote_job_dir=str(self.root / "jobs" / job_id),
            unit="hepta-runtime-job-" + job_id, execution_mode="operator", launch_state="launched", launch_error=None,
            request_digest="b" * 64, idempotency_key="fixture-owner-key", executable="/usr/bin/python3",
            cwd=str(control_root), args=["-c", script])
        receipt = dict(job=job, launch=dict(backend="systemd", ok=True, unit=job["unit"]))
        receipt_path, admission_path = self.root / "actual-start.json", self.root / "actual-admission.json"
        binding = dict(source_root=str(source_root), control_root=str(control_root), config_path=str(config_path),
            config_sha256=config_sha, native_host="fixture-host", owner=dict(job_id=job_id, job_directory=job["remote_job_dir"]))
        expected = finalizer.expected_owner_launch(binding, config, owner)
        admission = dict(schema="hcsn-colab-native-formal-owner-launch-admission-v3",
            status="native_admission_verified_before_owner_exec", config_sha256=config_sha,
            config_canonical_sha256=owner.digest(config), owner_python=config["provider"]["native_python"],
            provider_binding=config["provider_binding"], registered_fits=160, updates_per_fit=400,
            fit_timeout_seconds=480, provider_limit_seconds=3000, **expected)
        for key in ("plan_sha256", "published_plan_commit", "published_plan_ref", "publication_receipt", "control_pins"):
            admission[key] = config[key]
        binding["native_launch"] = dict(receipt_path=str(receipt_path), receipt_sha256=write(receipt_path, receipt),
            request_digest=job["request_digest"], idempotency_key=job["idempotency_key"], wrapper_executable=job["executable"],
            launch_script_sha256=finalizer.sha(script.encode()), command_sha256=finalizer.sha(finalizer.canonical([job["executable"], *job["args"]])),
            admission_path=str(admission_path), admission_sha256=write(admission_path, admission))
        return binding, config, admission, expected

    def test_finalizer_exact_owner_command_and_source_bridge(self):
        binding, config, _, expected = self.native_launch_fixture()
        observed = finalizer.verify_launch_role(binding, config, owner)
        self.assertEqual(expected["owner_command"], [config["provider"]["native_python"], "-B",
            binding["control_root"] + "/native_owner.py", "--config", binding["config_path"],
            "--source-root", binding["source_root"], "--plan", binding["source_root"] + "/fixture-plan.json",
            "--control-root", binding["control_root"], "--published-plan-commit", "a" * 40,
            "--published-plan-ref", owner.REF])
        self.assertEqual(observed["owner_source_sha256"], config["control_pins"]["native_owner.py"])
        self.assertEqual(observed["owner_command_sha256"], owner.digest(expected["owner_command"]))
        self.assertEqual(self.fixture.fake_dispatches, 0)

    def test_finalizer_rejects_rehashed_wrong_command_paths_or_actual_source(self):
        binding, config, admission, expected = self.native_launch_fixture()
        wrong_command = list(expected["owner_command"])
        wrong_command[wrong_command.index("--config") + 1] = str(self.root / "other-config.json")
        for key, value in (("owner_command", wrong_command), ("owner_source_sha256", "0" * 64),
                           ("owner_source_path", str(self.root / "other-owner.py")),
                           ("plan_path", str(self.root / "other-plan.json")),
                           ("source_root", str(self.root / "other-source")),
                           ("control_root", str(self.root / "other-control"))):
            with self.subTest(field=key):
                changed = dict(admission, **{key: value})
                binding["native_launch"]["admission_sha256"] = write(Path(binding["native_launch"]["admission_path"]), changed)
                with self.assertRaisesRegex(finalizer.ClosureError, "command/source admission differs"):
                    finalizer.verify_launch_role(binding, config, owner)
        binding["native_launch"]["admission_sha256"] = write(Path(binding["native_launch"]["admission_path"]), admission)
        Path(expected["owner_source_path"]).write_bytes(b"# replaced same-path owner\n")
        with self.assertRaisesRegex(finalizer.ClosureError, "Actual owner source differs"):
            finalizer.verify_launch_role(binding, config, owner)
        self.assertEqual(self.fixture.fake_dispatches, 0)

    def test_finalizer_does_not_treat_unknown_as_closed_or_seed_episodes_as_fits(self):
        initial = owner.initial_state(self.fixture.config)
        self.assertEqual(finalizer.progress({"state": initial, "head": None})["registered_fit_count"], 160)
        initial["fits"]["fit-000"] = dict(state="UNKNOWN", ever_claimed=True)
        snapshot = {"state": initial, "head": None, "records": []}
        with self.assertRaises(finalizer.ClosureError):
            finalizer.validate_closure(self.fixture.config, snapshot, {}, self.root / "absent-handoff", self.root)


if __name__ == "__main__":
    unittest.main()
