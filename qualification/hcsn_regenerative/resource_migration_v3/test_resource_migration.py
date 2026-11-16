"""Targeted, provider-free tests for the new Colab provenance boundary."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from . import rawdiff_guard as g

def fixture_parent():
    path = Path(__file__).parents[1] / "studies/s81-20261107/plan.json"
    return g.read(path, g.PARENT_SHA)

def fixture_child():
    parent = fixture_parent()
    child = copy.deepcopy(parent)
    child.update(study_id=g.STUDY_ID, frozen_at="FIXTURE_ONLY_NEVER_EXECUTED")
    child["runtime_feasibility_policy"]["provider"] = "colab"
    child["execution_environment"]["gpu"]["total_memory"] += 1024
    for name in g.SLOTS:
        child["qualification_receipts"][name]["sha256"] = g.digest(("fixture:" + name).encode())
    for name in g.amendment()["additional_source_paths"]:
        child["source_pins"][name] = g.digest(("fixture:" + name).encode())
    lineage = dict(provider="colab", parent_plan_sha256=g.PARENT_SHA, parent_study_id=parent["study_id"],
                   prior_ledgers_policy="immutable", v1_fit_completion_credit=0, v2_fit_completion_credit=0,
                   qualification_request_id=g.amendment()["qualification_request_id"],
                   qualification_job_id="00000000-0000-4000-8000-000000000001")
    for name in ("fresh_qualification_native_receipt_sha256", "qualification_identity_sha256",
                 "qualification_code_sha256", "qualification_adapter_payload_sha256",
                 "qualification_manifest_sha256", "qualification_profile_sha256",
                 "qualification_profile_fingerprint", "binding_proof_sha256",
                 "adapter_source_sha256", "remote_runner_source_sha256", "authorizer_source_sha256", "fixed_kernel_provider_sha256", "amendment_sha256"):
        lineage[name] = g.digest(("fixture:" + name).encode())
    child["resource_migration"] = lineage
    return parent, child

def native_fixture(root):
    registration = g.amendment()
    bound = dict(name="fixture-bound", session_name="fixture-session", state_file="/fixture/state.json",
                 endpoint="fixture-endpoint", kernel_id="00000000-0000-4000-8000-000000000002",
                 session_id="00000000-0000-4000-8000-000000000003", remote_root="/content/fixture",
                 max_wall_seconds=600, max_artifact_bytes=33554432, max_output_bytes=8388608,
                 auth_provider="oauth2", expected_account_email="fixture@example.invalid")
    profile = dict(bound, name="fixture-execution", max_wall_seconds=3000, max_artifact_bytes=134217728)
    code = 'print("offline fixture never executed")\n'
    names = sorted(registration["fresh_qualification"]["requested_artifacts"])
    profile_text, bound_text = json.dumps(profile), json.dumps(bound)
    job = dict(job_id="00000000-0000-4000-8000-000000000004", idempotency_key=registration["qualification_request_id"],
               state="succeeded", submit_attempts=1, wall_seconds=3000, profile=profile,
               profile_hash=g.digest(g.canonical(profile)), code=code, code_sha256=g.digest(code.encode()),
               runner_sha256=registration["resource_selection"]["remote_runner_source_sha256"],
               artifacts=names, endpoint=profile["endpoint"], kernel_id=profile["kernel_id"],
               session_id=profile["session_id"],
               remote_dir="/content/fixture/00000000-0000-4000-8000-000000000004", dispatched_at=1.0,
               worker_pid=4242, worker_start_ticks="12345")
    job["payload_sha256"] = g.digest(g.canonical(dict(profile_hash=job["profile_hash"], code=code, artifacts=names,
        wall_seconds=3000, runner_sha256=job["runner_sha256"], adapter_schema=1)))
    ident = {k: job[k] for k in ("job_id", "payload_sha256", "endpoint", "kernel_id", "session_id")}
    entries, fetches = {}, []
    for name in [*names, "stdout", "stderr"]:
        data = ("OFFLINE FIXTURE " + name).encode()
        (root / name).write_bytes(data)
        suffix = {"stdout": "/stdout.bin", "stderr": "/stderr.bin"}.get(name, "/work/" + name)
        entries[name] = dict(remote_path=job["remote_dir"] + suffix, size=len(data), sha256=g.digest(data))
        fetches.append(dict(artifact=name, local_relative_path=name, job_id=job["job_id"],
                            size=len(data), sha256=g.digest(data), verified=True))
    cm = dict(ident, entries=entries, errors=[])
    cm_text = g.canonical(cm).decode()
    receipt = dict(ident, state="succeeded", exit_code=0, cloud_execution_stopped=True, cloud_process_group_alive=False,
                   artifact_manifest_sha256=g.digest(cm_text.encode()), artifact_manifest_size=len(cm_text.encode()))
    job.update(receipt=receipt, manifest=cm)
    public = {k: job[k] for k in ("job_id", "state", "payload_sha256", "code_sha256", "endpoint", "kernel_id",
                                  "session_id", "remote_dir", "submit_attempts", "dispatched_at")}
    public.update(cloud_receipt=receipt, cloud_execution_stopped=True, artifacts=entries)
    proof = dict(admitted=True, status="BOUND_IDENTITY_VERIFIED", post_delegate_calls=1, automatic_retry=False,
                 profile_raw_sha256=g.digest(bound_text.encode()),
                 manager_result=dict(owned_runtime=True, owned_kernel=True, runtime_submit_attempts=1, kernel_submit_attempts=1,
                     endpoint=bound["endpoint"], kernel_id=bound["kernel_id"], client_session_id=bound["session_id"]),
                 admission=dict(profile_fingerprint=g.digest(g.canonical(bound))))
    worker_source = 'print("offline native fixture never executed")\n'
    command = dict(schema="hcsn-colab-v3-qualification-launch-contract", request_id=registration["qualification_request_id"],
                   host="rog", executable="/fixture/venv/bin/python", args=["-B", "-c", worker_source],
                   idempotency_key="offline-fixture-native", timeout_seconds=3600,
                   worker_source_sha256=g.digest(worker_source.encode()), cwd=None, env={})
    contract_text = g.canonical(command).decode()
    registration["resource_selection"]["native_qualification_launch_contract_sha256"] = g.digest(contract_text.encode())
    native_id, nonce, invocation = "OFFLINE_FIXTURE_NATIVE", "a" * 32, "b" * 32
    job_directory = "/fixture/native/jobs/" + native_id
    boot = "00000000-0000-4000-8000-000000000005"
    started = dict(job_id=native_id, launch_nonce=nonce, invocation_id=invocation)
    documents = {"started.json": started, "owner-intent.json": started,
                 "child.json": dict(pid=4242, identity=dict(kind="proc_start_ticks", value=boot + ":12345")),
                 "exit.json": dict(job_id=native_id, launch_nonce=nonce, exit_code=0, terminal_publication_protocol=1)}
    documents["exit.witness.json"] = dict(job_id=native_id, launch_nonce=nonce, terminal_publication_protocol=1,
                                        exit_sha256=g.digest(g.canonical(documents["exit.json"])))
    native_files = {}
    for name, document in documents.items():
        data = g.canonical(document)
        native_files[name] = dict(path=job_directory + "/" + name, text=data.decode(), bytes=len(data), sha256=g.digest(data))
    native = dict(schema="hcsn-colab-qualification-native-evidence-v3", request_id=registration["qualification_request_id"],
                  native_start=dict(job=dict(id=native_id, host="rog", launch_state="launched", launch_error=None,
                      execution_mode="operator", executable=command["executable"], args=command["args"],
                      idempotency_key=command["idempotency_key"], cwd=None, env_keys=[],
                      remote_job_dir=job_directory, unit="hepta-runtime-job-" + native_id, request_digest="c" * 64),
                      launch=dict(backend="systemd", ok=True, unit="hepta-runtime-job-" + native_id)),
                  native_terminal=dict(job_id="OFFLINE_FIXTURE_NATIVE", state="succeeded", exit_code=0, output_complete=True,
                      output_durable=True, terminal_publication_confirmed=True, timed_out=False, cancelled=False,
                      launch_nonce=nonce),
                  launch_contract_text=contract_text, native_files=native_files,
                  worker_identity=dict(pid=4242, start_ticks="12345", boot_id=boot,
                                       cmdline=[command["executable"], *command["args"]]),
                  ledger_job=job, public_job=public, execution_profile_text=profile_text,
                  execution_profile_sha256=g.digest(profile_text.encode()), binding_profile_text=bound_text,
                  binding_outcome_text=json.dumps(proof), adapter_source_sha256=registration["resource_selection"]["adapter_source_sha256"],
                  authorizer_source_sha256=registration["resource_selection"]["authorizer_source_sha256"],
                  cloud_artifact_manifest_text=cm_text, fetches=fetches, fixture_only=True)
    return native, dict(payload_sha256=job["code_sha256"]), registration

class ColabDiffTests(unittest.TestCase):
    def test_declared_resource_diff_and_fresh_driver_memory_allowed(self):
        parent, child = fixture_child()
        result = g.audit_diff(parent, child)
        self.assertEqual(result["unchanged_parent_source_files"], 42)
        self.assertEqual(result["added_source_files"], 18)

    def test_no_scientific_budget_threshold_or_source_changes(self):
        parent, child = fixture_child()
        variants = []
        for key, value in (("train_updates", 399), ("training_seeds", [1103]), ("state_count", 25)):
            c = copy.deepcopy(child); c[key] = value; variants.append(c)
        c = copy.deepcopy(child); c["statistical_contract"]["primary_mud_absolute_mse"] = 0.0; variants.append(c)
        c = copy.deepcopy(child); c["source_pins"][next(iter(parent["source_pins"]))] = "0" * 64; variants.append(c)
        for c in variants:
            with self.subTest(change=c):
                with self.assertRaises(ValueError): g.audit_diff(parent, c)

    def test_old_qualification_and_changed_provider_budget_rejected(self):
        parent, child = fixture_child()
        c = copy.deepcopy(child); c["qualification_receipts"]["unit"] = parent["qualification_receipts"]["unit"]
        with self.assertRaises(ValueError): g.audit_diff(parent, c)
        c = copy.deepcopy(child); c["runtime_feasibility_policy"]["cloud_job_max_seconds"] = 600
        with self.assertRaises(ValueError): g.audit_diff(parent, c)

    def test_no_private_identity_or_fake_kaggle_lineage(self):
        parent, child = fixture_child()
        for key in ("notebook_ref", "kernel_id", "expected_account_email"):
            c = copy.deepcopy(child); c["resource_migration"][key] = "fixture"
            with self.assertRaises(ValueError): g.audit_diff(parent, c)

class ColabNativeProofTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.native, self.manifest, self.registration = native_fixture(self.root)

    def tearDown(self): self.tmp.cleanup()

    def check(self, value):
        return g.verify_native(value, self.manifest, self.registration, self.root)

    def test_complete_fixture_shape_is_admitted_without_any_execution(self):
        job, _, _, files = self.check(self.native)
        self.assertEqual(job["submit_attempts"], 1)
        self.assertEqual(len(files), 7)

    def test_queued_unknown_or_duplicate_dispatch_cannot_pass(self):
        for state, attempts in (("queued", 0), ("unknown", 1), ("succeeded", 2)):
            value = copy.deepcopy(self.native); value["ledger_job"].update(state=state, submit_attempts=attempts)
            with self.assertRaises(ValueError): self.check(value)

    def test_native_success_does_not_replace_cloud_stop(self):
        value = copy.deepcopy(self.native)
        value["ledger_job"]["receipt"]["cloud_execution_stopped"] = False
        with self.assertRaises(ValueError): self.check(value)
        value = copy.deepcopy(self.native); value["native_terminal"]["output_complete"] = False
        with self.assertRaises(ValueError): self.check(value)

    def test_native_launch_is_the_previously_sealed_exact_source(self):
        value = copy.deepcopy(self.native)
        value["native_start"]["job"]["args"] = ["-B", "-c", "print('another worker')"]
        with self.assertRaisesRegex(ValueError, "launch command differs"):
            self.check(value)
        value = copy.deepcopy(self.native)
        value["launch_contract_text"] += " "
        with self.assertRaisesRegex(ValueError, "prospectively sealed"):
            self.check(value)

    def test_another_native_child_cannot_attest_the_adapter_worker(self):
        value = copy.deepcopy(self.native)
        row = value["native_files"]["child.json"]
        document = g.parse(row["text"])
        document["pid"] += 1
        data = g.canonical(document)
        row.update(text=data.decode(), bytes=len(data), sha256=g.digest(data))
        with self.assertRaisesRegex(ValueError, "actual adapter dispatcher"):
            self.check(value)

    def test_terminal_must_have_the_actual_exit_witness_and_nonce(self):
        value = copy.deepcopy(self.native)
        row = value["native_files"]["exit.witness.json"]
        document = g.parse(row["text"])
        document["exit_sha256"] = "0" * 64
        data = g.canonical(document)
        row.update(text=data.decode(), bytes=len(data), sha256=g.digest(data))
        with self.assertRaisesRegex(ValueError, "witnessed successful terminal"):
            self.check(value)
        value = copy.deepcopy(self.native)
        value["native_terminal"]["launch_nonce"] = "d" * 32
        with self.assertRaisesRegex(ValueError, "nonce or invocation"):
            self.check(value)

    def test_profile_kernel_identity_change_rejected(self):
        value = copy.deepcopy(self.native); value["ledger_job"]["profile"]["kernel_id"] = "different"
        with self.assertRaises(ValueError): self.check(value)

    def test_self_consistent_foreign_cloud_directory_rejected(self):
        value = copy.deepcopy(self.native)
        job, public = value["ledger_job"], value["public_job"]
        old = job["remote_dir"]
        job["remote_dir"] = public["remote_dir"] = "/content/fixture/foreign-job"
        for entry in job["manifest"]["entries"].values():
            entry["remote_path"] = entry["remote_path"].replace(old, job["remote_dir"], 1)
        manifest = g.canonical(job["manifest"])
        value["cloud_artifact_manifest_text"] = manifest.decode()
        job["receipt"]["artifact_manifest_sha256"] = g.digest(manifest)
        job["receipt"]["artifact_manifest_size"] = len(manifest)
        with self.assertRaisesRegex(ValueError, "exact bound job namespace"):
            self.check(value)

    def test_code_payload_or_raw_manifest_change_rejected(self):
        for field in ("code_sha256", "payload_sha256"):
            value = copy.deepcopy(self.native); value["ledger_job"][field] = "0" * 64
            with self.assertRaises(ValueError): self.check(value)
        value = copy.deepcopy(self.native); value["cloud_artifact_manifest_text"] += " "
        with self.assertRaises(ValueError): self.check(value)

    def test_missing_fetch_and_changed_actual_bytes_rejected(self):
        value = copy.deepcopy(self.native); value["fetches"].pop()
        with self.assertRaises(ValueError): self.check(value)
        (self.root / "execution.json").write_bytes(b"DIFFERENT")
        with self.assertRaises(ValueError): self.check(self.native)

    def test_duplicate_json_key_and_path_escape_rejected(self):
        with self.assertRaises(ValueError): g.parse('{"a":1,"a":2}')
        for name in ("../escape", "/absolute", "a//b", "a/./b"):
            with self.assertRaises(ValueError): g.safe_relative(name)

if __name__ == "__main__":
    unittest.main()

