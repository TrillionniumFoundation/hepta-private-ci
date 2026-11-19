"""Draft unique native owner: fixed claims, verified whole capsules, no replay.

This control layer imports no training code. Root must pin all eight control
sources and the published plan before enabling this CLI. An unknown effect
halts the owner without cancelling, resubmitting, or declaring a fit unstarted.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time


STUDY_ID = "hcsn-regenerative-mechanisms-fv-pilot-20261107-1631115f163f-v3"
REF = "refs/heads/codex/hcsn-mechanisms-s81-colab-v3-20261107"
TERMINAL = {"COMPLETED", "FAILED", "TIMEOUT"}
PROVIDER_TERMINAL = {"succeeded", "failed", "cancelled", "timed_out"}
CONTROL_FILES = {"native_owner.py", "cloud_batch.py", "capsule_contract.py", "finalize_mechanism.py", "__init__.py", "test_colab_execution.py", "fixed_kernel_provider.py", "test_fixed_kernel_provider.py"}
CONTROL_RELATIVE = "qualification/hcsn_regenerative/colab_execution_v3"
ASSET_RELATIVE = "qualification/hcsn_regenerative/colab_qualification_v3/asset_transport.py"
ADAPTER_SHA = "55acb80ca2351b4aaafc16b04fb642100e52a9ddb021cb0551a6703513c068c2"
RUNNER_SHA = "56047c73774c5507ba150dca310aa87b432b344193d1c827310e56f689a43d68"
AUTHORIZER_SHA = "7c4a297f1c781701dd5d1ac23e63111b9f3d2976ba77cfe88ae2e9774998f40b"
ARTIFACTS = sorted(("execution.json", "capsule-manifest.json", "study-capsule.tar.gz", "artifact-manifest.json", "control-logs.zip", "outer-timing.json", "asset-materialization.json"))


class OwnerHalt(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise OwnerHalt(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(OwnerHalt("Nonfinite JSON")))
    try:
        canonical(value)  # Also reject exponent overflow, for example 1e999.
    except (ValueError, TypeError) as error:
        raise OwnerHalt("Nonfinite/invalid JSON") from error
    return value


def safe_path(path):
    path = Path(path).absolute()
    require(".." not in path.parts and not any(p.is_symlink() for p in (path, *path.parents)), "Symlink/traversal in evidence path")
    return path


def version(value):
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def file_bytes(path, limit=268435456):
    path = safe_path(path)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_size <= limit and before.st_nlink == 1, "Unsafe/oversized evidence file")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        require(version(os.fstat(stream.fileno())) == version(before), "Evidence changed before read")
        data = stream.read(limit + 1)
    require(len(data) == before.st_size and version(path.lstat()) == version(before), "Evidence changed during read")
    return data


def read(path, expected=None):
    raw = file_bytes(path)
    require(expected is None or hashlib.sha256(raw).hexdigest() == expected, "Evidence SHA256 mismatch")
    return parse(raw)


def exclusive(path, value):
    path = safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(value if isinstance(value, bytes) else canonical(value))
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def check_environment(expected, actual):
    for key, value in expected.items():
        if key in ("gpu_uuid_policy", "allowed_gpu_uuids"):
            continue
        if key == "gpu":
            require(all(actual.get("gpu", {}).get(k) == v for k, v in value.items()), "Execution GPU differs")
        else:
            require(actual.get(key) == value, "Execution environment differs: " + key)


def verify_local_pins(config, source_root, control_root):
    read(Path(source_root) / config["plan_relative_path"], config["plan_sha256"])
    for directory, pins in ((source_root, config["source_pins"]), (control_root, config["control_pins"])):
        for name, expected in pins.items():
            relative = Path(name)
            require(not relative.is_absolute() and ".." not in relative.parts and relative.as_posix() == name, "Unsafe source pin path")
            require(hashlib.sha256(file_bytes(Path(directory) / relative, 2 * 1024**2)).hexdigest() == expected, "Pinned source changed: " + name)


def load_control(name, root, expected):
    """Execute pinned source bytes directly, without trusting an old pyc cache."""
    path = Path(root) / (name + ".py")
    raw = file_bytes(path, 2 * 1024**2)
    require(hashlib.sha256(raw).hexdigest() == expected, "Control import source changed")
    module = importlib.util.module_from_spec(importlib.util.spec_from_file_location(name, path))
    sys.modules[name] = module
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module




def adapter_canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def load_module_path(name, path, expected):
    path = Path(path)
    raw = file_bytes(path, 2 * 1024**2)
    require(hashlib.sha256(raw).hexdigest() == expected, "Pinned module source changed")
    module = importlib.util.module_from_spec(importlib.util.spec_from_file_location(name, path))
    sys.modules[name] = module
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


def provider_binding(config):
    """Check exact actual bound profile, derivative profile and same native ledger."""
    p = config["provider"]
    require(p.get("schema") == "hepta-colab-fixed-profile-v3", "Unsupported Colab provider")
    require(p.get("adapter_sha256") == ADAPTER_SHA and p.get("runner_sha256") == RUNNER_SHA,
            "Installed adapter/runner source differs")
    require(p.get("authorizer_sha256") == AUTHORIZER_SHA
            and hashlib.sha256(file_bytes(Path(p["adapter_path"]).with_name("authorize_colab.py"))).hexdigest() == AUTHORIZER_SHA,
            "Exact installed authorization dependency differs")
    require(Path(p["adapter_path"]).parent / "remote_runner.py" == Path(p["runner_path"]),
            "Runner is not beside the exact installed adapter")
    for name in ("adapter", "runner"):
        require(hashlib.sha256(file_bytes(p[name + "_path"], 2 * 1024**2)).hexdigest() == p[name + "_sha256"],
                "Installed Colab source changed")
    profile_raw = file_bytes(p["profile_path"], 65536)
    original_raw = file_bytes(p["binding_profile_path"], 65536)
    profile, original = parse(profile_raw), parse(original_raw)
    require(hashlib.sha256(profile_raw).hexdigest() == p["profile_sha256"]
            and hashlib.sha256(original_raw).hexdigest() == p["binding_profile_sha256"],
            "Execution or original binding profile changed")
    fingerprint = hashlib.sha256(adapter_canonical(profile)).hexdigest()
    require(fingerprint == p["profile_fingerprint"], "Execution profile canonical fingerprint differs")
    fields = {"name", "session_name", "state_file", "endpoint", "kernel_id", "session_id", "remote_root",
              "max_wall_seconds", "max_artifact_bytes", "max_output_bytes", "auth_provider", "expected_account_email"}
    require(set(profile) == set(original) == fields, "Profile fields are not the actual adapter schema")
    require(Path(p["profile_path"]) != Path(p["binding_profile_path"]), "Never modify the manager binding profile")
    for key in fields - {"name", "max_wall_seconds", "max_artifact_bytes", "max_output_bytes"}:
        require(profile[key] == original[key], "Derived profile changed bound identity: " + key)
    require(profile["max_wall_seconds"] == 3000 and profile["max_artifact_bytes"] == 134217728
            and profile["max_output_bytes"] == original["max_output_bytes"] == 8388608,
            "Prospective execution profile limits differ")
    outcome = read(p["binding_outcome_path"], p["binding_outcome_sha256"])
    manager = outcome.get("manager_result", {})
    require(outcome.get("schema") == "hcsn-colab-bind-outcome-v1"
            and outcome.get("status") == "BOUND_IDENTITY_VERIFIED" and outcome.get("admitted") is True
            and manager.get("phase") == "bound" and manager.get("owned_runtime") is True
            and manager.get("owned_kernel") is True and manager.get("runtime_submit_attempts") == 1
            and manager.get("kernel_submit_attempts") == 1 and not manager.get("error"),
            "Actual binding outcome is not a new owned bound runtime/kernel")
    require(outcome.get("profile_raw_sha256") == p["binding_profile_sha256"]
            and manager.get("profile_hash") == hashlib.sha256(adapter_canonical(original)).hexdigest()
            and manager.get("profile_path") == p["binding_profile_path"],
            "Original binding evidence differs from profile")
    require(Path(p["state_dir"]) == Path(manager["jobs_state_dir"]), "New ledger would bypass the actual same-kernel UNKNOWN guard")
    for key, native_key in (("endpoint", "endpoint"), ("kernel_id", "kernel_id"), ("session_id", "client_session_id"), ("session_name", "session_name")):
        require(profile[key] == manager.get(native_key), "Binding outcome/profile identity differs")
    return dict(profile_fingerprint=fingerprint, profile_raw_sha256=p["profile_sha256"],
                endpoint=profile["endpoint"], kernel_id=profile["kernel_id"], session_id=profile["session_id"],
                remote_root=profile["remote_root"], max_wall_seconds=3000,
                max_artifact_bytes=profile["max_artifact_bytes"], max_output_bytes=profile["max_output_bytes"],
                adapter_sha256=ADAPTER_SHA, runner_sha256=RUNNER_SHA, authorizer_sha256=AUTHORIZER_SHA,
                fixed_kernel_provider_sha256=config["control_pins"]["fixed_kernel_provider.py"])


def validate_config(config, source_root, plan_path, control_root, commit, ref):
    require(config.get("schema") == "hcsn-colab-study-owner-config-v3" and config.get("formal_training_start_authorized") is True,
            "Formal Colab study is not authorized")
    require(re.fullmatch(r"[0-9a-f]{40}", commit or "") and ref == REF
            and config.get("published_plan_commit") == commit and config.get("published_plan_ref") == ref,
            "Explicit actual published Colab commit/ref required")
    plan_sha = config.get("plan_sha256")
    require(re.fullmatch(r"[0-9a-f]{64}", plan_sha or "") and Path(config["state_root"]).name == plan_sha,
            "Wrong prospective owner identity root")
    require(Path(plan_path).absolute() == (Path(source_root) / config["plan_relative_path"]).absolute(), "Plan path differs")
    plan = read(plan_path, plan_sha)
    require(plan.get("status") == "FROZEN" and plan.get("study_id") == STUDY_ID and plan.get("train_updates") == 400
            and plan.get("max_fit_wall_seconds") == 480 and plan.get("state_count") == 81
            and plan.get("expected_parameter_count") == 2890, "Frozen scientific identity differs")
    proof = config["publication_receipt"]
    receipt = read(proof["receipt_path"], proof["receipt_sha256"])
    readback = read(proof["readback_path"], proof["readback_sha256"])
    require(receipt.get("status") == "published_and_verified" and receipt.get("repo") == "TrillionniumFoundation/hepta-private-ci"
            and receipt.get("branch") == ref.removeprefix("refs/heads/") and receipt.get("commit") == commit,
            "Native publication receipt is not the declared commit")
    require(readback.get("commit") == commit and readback["files"][config["plan_relative_path"]]["sha256"] == plan_sha,
            "Published plan bytes not verified")
    pins = config["source_pins"]
    require(pins == config["identity"]["source_pins"] == plan["source_pins"], "Frozen source maps differ")
    require(all(readback["files"].get(name, {}).get("sha256") == value for name, value in pins.items()),
            "Published sources not all verified")
    require(set(config["control_pins"]) == CONTROL_FILES, "Complete Colab control pins required")
    for name, value in config["control_pins"].items():
        require(pins.get(CONTROL_RELATIVE + "/" + name) == value, "Control absent from frozen published source map")
    require(ASSET_RELATIVE in pins, "Shared immutable asset helper is unpinned")
    require(config["control_pins"]["fixed_kernel_provider.py"] == plan["resource_migration"]["fixed_kernel_provider_sha256"],
            "Formal provider guard differs from the exact qualified guard")
    verify_local_pins(config, source_root, control_root)
    rows, groups = config["ordered_roster"], config["groups"]
    require(len(rows) == 160 and len({r["fit_id"] for r in rows}) == 160 and [r["index"] for r in rows] == list(range(160)),
            "Wrong full 160-fit roster")
    require(len(groups) == 8 and all(len(g["fit_ids"]) == 20 for g in groups)
            and [i for g in groups for i in g["fit_ids"]] == [r["fit_id"] for r in rows], "Wrong eight twenty-fit groups")
    roster_sha = hashlib.sha256(canonical(rows)[:-1]).hexdigest()
    expected_identity = dict(study_id=STUDY_ID, plan_sha256=plan_sha, bundle_sha256=plan["bundle_sha256"],
        bundle_metadata_sha256=plan["bundle_metadata_sha256"], source_pins=pins, ordered_fit_roster_sha256=roster_sha,
        state_count=81, expected_parameter_count=2890, registered_fit_count=160, registered_training_updates=64000,
        original_campaign_completion_credit=0)
    require(roster_sha == plan["ordered_fit_roster_sha256"] and config["identity"] == expected_identity, "Roster/identity differs")
    require(len({g["group_id"] for g in groups}) == 8
            and all(g["fit_ids"] == [r["fit_id"] for r in rows if r["group_id"] == g["group_id"]] for g in groups),
            "Statistical group identities differ")
    require(config["runtime_policy"] == plan["runtime_feasibility_policy"] and config["runtime_policy"]["provider"] == "colab"
            and config["execution_environment"] == plan["execution_environment"], "Policy/environment differs")
    require(provider_binding(config) == config["provider_binding"], "Actual provider binding differs")
    qualified = config["qualified_input"]
    for key, expected in (("bundle_path", plan["bundle_sha256"]), ("metadata_path", plan["bundle_metadata_sha256"])):
        require(hashlib.sha256(file_bytes(qualified[key])).hexdigest() == expected, "Qualified operator bytes changed")
    # This private native proof is independently bound by the public prospective plan.
    require(qualified["qualification_proof_sha256"] == plan["resource_migration"]["fresh_qualification_native_receipt_sha256"],
            "Fresh native qualification proof is not frozen")
    read(qualified["qualification_proof_path"], qualified["qualification_proof_sha256"])
    require(config["provider"]["anchor_job_id"] == plan["resource_migration"]["qualification_job_id"], "Staging anchor differs from fresh qualified job")
    require(config["provider"]["binding_outcome_sha256"] == plan["resource_migration"]["binding_proof_sha256"],
            "Actual binding proof differs from frozen native qualification")
    lineage = plan["resource_migration"]
    require(lineage["authorizer_source_sha256"] == AUTHORIZER_SHA, "Frozen authorizer dependency differs")
    for private, public in (("anchor_code_sha256", "qualification_code_sha256"),
                            ("anchor_payload_sha256", "qualification_adapter_payload_sha256"),
                            ("profile_sha256", "qualification_profile_sha256"),
                            ("profile_fingerprint", "qualification_profile_fingerprint")):
        require(config["provider"][private] == lineage[public], "Qualified provider input differs: " + private)
    return plan


class Adapter:
    """Use the actual installed Engine; never invent Kaggle-shaped Colab receipts."""
    def __init__(self, config, root):
        self.config, self.root = config, Path(root)
        provider_binding(config)
        p = config["provider"]
        guard = load_control("fixed_kernel_provider", Path(__file__).resolve().parent,
                             config["control_pins"]["fixed_kernel_provider.py"])
        self.module = guard.load_pinned_adapter(p["adapter_path"], adapter_sha256=p["adapter_sha256"],
            runner_sha256=p["runner_sha256"], authorizer_sha256=p["authorizer_sha256"])
        self.profile = self.module.Profile.load(p["profile_path"])
        self.provider_factory = guard.guarded_provider_factory(self.module, lambda event: self._record("fixed-kernel-transport", event))
        self.engine = self.module.Engine(self.profile, self.module.Ledger(p["state_dir"]), provider_factory=self.provider_factory)

    def _record(self, operation, value, started_monotonic=None):
        path = self.root / "adapter-calls" / (str(time.time_ns()) + ".json")
        exclusive(path, dict(operation=operation, observed_utc=datetime.now(timezone.utc).isoformat(), result=value,
            wall_seconds=None if started_monotonic is None else time.monotonic()-started_monotonic,
            cost_scope="This native control call; cloud/worker/transfer timers are nested, never sum them blindly",
            full_physical_energy_joules=None, monetary_cost=None))
        return str(path)

    def _observe(self, operation, public, started_monotonic=None):
        require(provider_binding(self.config) == self.config["provider_binding"], "Profile/source changed during operation")
        row = self.engine.ledger.get(public["job_id"])
        require(row["profile_hash"] == self.profile.fingerprint and row["profile"] == self.profile.__dict__,
                "Actual registered profile differs")
        fields = ("job_id", "state", "payload_sha256", "code_sha256", "endpoint", "kernel_id", "session_id", "remote_dir", "submit_attempts")
        require(all(public.get(k) == row.get(k) for k in fields), "Public observation and authoritative ledger row differ")
        value = dict(schema="hcsn-colab-provider-observation-v3", job=public,
                     profile_fingerprint=row["profile_hash"], profile_raw_sha256=self.config["provider"]["profile_sha256"],
                     request_id=row["idempotency_key"], wall_seconds=row["wall_seconds"],
                     requested_artifacts=row["artifacts"], runner_sha256=row["runner_sha256"],
                     code_sha256=row["code_sha256"], payload_sha256=row["payload_sha256"],
                     adapter_sha256=ADAPTER_SHA, authorizer_sha256=AUTHORIZER_SHA,
                     fixed_kernel_provider_sha256=self.config["control_pins"]["fixed_kernel_provider.py"],
                     manifest=row.get("manifest"), receipt=row.get("receipt"),
                     observed_operation=operation, submission_replayed=False)
        value["native_observation_path"] = self._record(operation, value, started_monotonic)
        return value

    def call(self, operation, *args):
        started = time.monotonic()
        try:
            if operation == "submit":
                request, code = args
                result = self.engine.submit(request, code, ARTIFACTS, 3000)
            elif operation == "run":
                result = self.engine.run(args[0])
            elif operation == "status":
                result = self.engine.status(args[0], refresh=True)
            else:
                raise OwnerHalt("Unsupported bounded Engine operation")
            return self._observe(operation, result, started)
        except BaseException as error:
            self._record(operation + "-error", dict(error_type=type(error).__name__, unknown_effect=True, automatic_retry=False), started)
            raise OwnerHalt("Colab operation unresolved; same-job read-only reconciliation only") from None

    def stage(self, active, asset_module):
        started = time.monotonic()
        require(provider_binding(self.config) == active["provider_binding"], "Staging profile changed")
        prepared = active["prepared_assets"]
        manifest = file_bytes(prepared["manifest_path"], 16 * 1024**2)
        require(hashlib.sha256(manifest).hexdigest() == prepared["manifest_sha256"], "Prepared manifest changed")
        try:
            provider = self.provider_factory(self.profile)
            try:
                receipt = asset_module.stage_assets(provider, manifest, prepared["manifest_sha256"], prepared["parts_dir"],
                    self.root / "provider-jobs" / active["request_id"] / "asset-upload-journal.json",
                    self.profile.fingerprint, reconcile_only=False, adapter_ledger=self.engine.ledger,
                    expected_ledger_root=self.config["provider"]["state_dir"], anchor_job_id=self.config["provider"]["anchor_job_id"])
            finally:
                provider.close()
        except BaseException as error:
            self._record("stage-assets-error", dict(error_type=type(error).__name__, unknown_effect=True, automatic_retry=False))
            raise OwnerHalt("Asset transport unresolved; only exact-path read-only reconciliation is allowed") from None
        self._record("stage-assets", receipt, started)
        return receipt

    def fetch_all(self, remote, active):
        started = time.monotonic()
        job = remote["job"]
        manifest = remote.get("manifest")
        require(job["state"] in PROVIDER_TERMINAL and isinstance(manifest, dict), "Artifact fetch requires explicit terminal manifest")
        root = self.root / "provider-jobs" / active["request_id"] / "artifacts"
        root.mkdir(parents=True, exist_ok=True)
        files = []
        for name, entry in sorted(manifest["entries"].items()):
            artifact = name
            local_name = {"stdout": "stdout.bin", "stderr": "stderr.bin"}.get(name, name)
            path = root / local_name
            if path.exists():
                raw = file_bytes(path)
                require(len(raw) == entry["size"] and hashlib.sha256(raw).hexdigest() == entry["sha256"], "Existing retained artifact changed")
                result = dict(job_id=job["job_id"], artifact=artifact, path=str(path), sha256=entry["sha256"],
                              size=entry["size"], verified=True, source="previous_native_retained_bytes")
            else:
                try:
                    result = self.engine.fetch(job["job_id"], artifact, str(path))
                except BaseException as error:
                    self._record("fetch-error", dict(job_id=job["job_id"], artifact=artifact, error_type=type(error).__name__))
                    raise OwnerHalt("Artifact readback unresolved; no next job") from None
            require(result.get("verified") is True and result.get("job_id") == job["job_id"], "Actual Engine fetch was not verified")
            files.append(dict(path=local_name, artifact_name=artifact, bytes=entry["size"], sha256=entry["sha256"], fetch_receipt=result))
        receipt = dict(schema="hcsn-colab-native-artifact-readback-v3", job_id=job["job_id"], request_id=active["request_id"],
                       directory=str(root), profile_fingerprint=self.profile.fingerprint, payload_sha256=job["payload_sha256"],
                       cloud_manifest=manifest, files=files)
        self._record("fetch-all", receipt, started)
        return receipt


def validate_remote(remote, active, config):
    require(remote.get("schema") == "hcsn-colab-provider-observation-v3" and remote.get("request_id") == active["request_id"],
            "Wrong raw Colab observation identity")
    binding = config["provider_binding"]
    for key in ("profile_fingerprint", "profile_raw_sha256", "adapter_sha256", "runner_sha256", "authorizer_sha256", "fixed_kernel_provider_sha256"):
        require(remote.get(key) == binding[key], "Colab observed source/profile differs: " + key)
    job = remote.get("job", {})
    require(re.fullmatch(r"[0-9a-f-]{36}", job.get("job_id", "")) and job.get("state") in
            {"queued", "dispatched", "running", "cancel_requested", "unknown"} | PROVIDER_TERMINAL, "Unknown Colab job/state")
    require(job.get("code_sha256") == active["code_sha256"] == remote.get("code_sha256"), "Colab code bytes differ")
    require(remote.get("wall_seconds") == 3000 and remote.get("requested_artifacts") == sorted(ARTIFACTS), "Colab budget/artifact contract differs")
    require(job.get("submit_attempts") in (0, 1) and type(job.get("submit_attempts")) is int, "Colab dispatch count differs")
    for key in ("endpoint", "kernel_id", "session_id"):
        require(job.get(key) == binding[key], "Actual Colab kernel/session changed")
    require(job.get("remote_dir") == binding["remote_root"] + "/" + job["job_id"], "Actual remote job path differs")
    code = file_bytes(active["source_path"], 262144).decode()
    expected_payload = hashlib.sha256(adapter_canonical(dict(profile_hash=binding["profile_fingerprint"], code=code,
        artifacts=sorted(ARTIFACTS), wall_seconds=3000, runner_sha256=RUNNER_SHA, adapter_schema=1))).hexdigest()
    require(job.get("payload_sha256") == remote.get("payload_sha256") == expected_payload, "Actual Colab payload differs")
    producer = {k: job[k] for k in ("job_id", "payload_sha256", "code_sha256", "endpoint", "kernel_id", "session_id", "remote_dir")}
    producer.update(profile_fingerprint=binding["profile_fingerprint"], runner_sha256=RUNNER_SHA)
    require(active.get("producer") in (None, producer), "Actual Colab producer changed")
    registration = active.get("adapter_registration")
    if registration is not None:
        require(registration["job"]["job_id"] == job["job_id"] and registration["job"]["payload_sha256"] == expected_payload,
                "Native registered UUID/payload changed")
    if job["state"] in PROVIDER_TERMINAL:
        receipt, manifest = remote.get("receipt"), remote.get("manifest")
        require(isinstance(receipt, dict) and isinstance(manifest, dict) and job.get("cloud_receipt") == receipt,
                "Terminal lacks actual ledger/cloud receipts")
        for value in (receipt, manifest):
            require(all(value.get(k) == job[k] for k in ("job_id", "payload_sha256", "endpoint", "kernel_id", "session_id")),
                    "Cloud receipt/manifest identity differs")
        require(receipt.get("state") == job["state"] and receipt.get("cloud_execution_stopped") is True
                and receipt.get("cloud_process_group_alive") is False and job.get("cloud_execution_stopped") is True,
                "Colab terminal does not prove its process group stopped")
        entries = manifest.get("entries", {})
        require(isinstance(entries, dict) and set(entries) <= set(ARTIFACTS) | {"stdout", "stderr"}, "Unexpected artifact name")
        for name, entry in entries.items():
            suffix = {"stdout": "/stdout.bin", "stderr": "/stderr.bin"}.get(name, "/work/" + name)
            require(entry.get("remote_path") == job["remote_dir"] + suffix
                    and type(entry.get("size")) is int and 0 <= entry["size"] <= binding["max_artifact_bytes"]
                    and re.fullmatch(r"[0-9a-f]{64}", entry.get("sha256", "")), "Unsafe cloud artifact entry")
        raw = adapter_canonical(manifest)
        require(len(raw) == receipt.get("artifact_manifest_size") and hashlib.sha256(raw).hexdigest() == receipt.get("artifact_manifest_sha256"),
                "Actual remote artifact manifest bytes differ")
        if job["state"] == "succeeded":
            require(receipt.get("exit_code") == 0 and type(receipt.get("exit_code")) is int
                    and not manifest.get("errors") and set(ARTIFACTS) <= set(manifest.get("entries", {})),
                    "Colab success lacks a complete exact artifact contract")
    return producer


def validate_staged_assets(receipt, active, config):
    prepared = active["prepared_assets"]
    manifest = read(prepared["manifest_path"], prepared["manifest_sha256"])
    require(receipt.get("schema") == "hcsn-colab-asset-upload-journal-v3" and receipt.get("status") == "VERIFIED"
            and receipt.get("request_id") == active["request_id"]
            and receipt.get("manifest_sha256") == prepared["manifest_sha256"]
            and receipt.get("archive") == manifest["archive"]
            and receipt.get("unknown_put_replayed") is False, "Staged asset identity or completion differs")
    identity = receipt.get("identity", {})
    for key in ("profile_fingerprint", "endpoint", "kernel_id", "session_id", "remote_root"):
        require(identity.get(key) == active["provider_binding"][key], "Staged asset provider identity differs")
    p = config["provider"]
    require(identity.get("anchor_job_id") == p["anchor_job_id"]
            and identity.get("anchor_code_sha256") == p["anchor_code_sha256"]
            and identity.get("anchor_payload_sha256") == p["anchor_payload_sha256"]
            and identity.get("authoritative_ledger_root_sha256") == hashlib.sha256(str(Path(p["state_dir"]).absolute()).encode()).hexdigest(),
            "Staged asset anchor is not the actual frozen qualification")
    require(manifest["remote_root"] == active["provider_binding"]["remote_root"], "Native asset remote root differs")
    rows = receipt.get("parts", [])
    require(len(rows) == len(manifest["parts"]), "Staged part denominator differs")
    for row, expected in zip(rows, manifest["parts"]):
        require(all(row.get(k) == expected[k] for k in ("index", "remote_path", "bytes", "sha256"))
                and row.get("put_attempts") == 1 and type(row.get("put_attempts")) is int
                and row.get("phase") == "VERIFIED" and row.get("readback_sha256") == expected["sha256"]
                and row.get("readback_bytes") == expected["bytes"], "An input part lacks unique PUT/readback proof")


def validate_materialization(receipt, active):
    prepared = active["prepared_assets"]
    manifest = read(prepared["manifest_path"], prepared["manifest_sha256"])
    require(receipt.get("schema") == "hcsn-colab-asset-materialization-v3" and receipt.get("status") == "VERIFIED"
            and receipt.get("request_id") == active["request_id"] and receipt.get("manifest_sha256") == prepared["manifest_sha256"]
            and receipt.get("archive") == manifest["archive"] and receipt.get("files") == manifest["files"]
            and receipt.get("member_crc_verified") is True
            and receipt.get("destination_name") == "materialized-" + active["request_id"],
            "Actual cloud input materialization differs from the native full asset manifest")


def validate_execution_producer(execution, remote, active):
    require(execution.get("provider_binding") == active["provider_binding"], "Execution profile binding differs")
    request = execution.get("colab_request", {})
    job = remote["job"]
    for key in ("job_id", "payload_sha256", "code_sha256", "endpoint", "kernel_id", "session_id"):
        require(request.get(key) == job[key], "Actual cloud request differs: " + key)
    require(hashlib.sha256(adapter_canonical(request)).hexdigest() == execution.get("colab_request_sha256"),
            "Actual cloud request raw hash differs")


def verified_artifacts(result, remote, active):
    job, manifest = remote["job"], remote["manifest"]
    require(result.get("schema") == "hcsn-colab-native-artifact-readback-v3"
            and result.get("job_id") == job["job_id"] and result.get("request_id") == active["request_id"]
            and result.get("payload_sha256") == job["payload_sha256"]
            and result.get("profile_fingerprint") == remote["profile_fingerprint"]
            and result.get("cloud_manifest") == manifest, "Native artifact producer differs")
    root, records = safe_path(result["directory"]), result["files"]
    expected_root = Path(active["source_path"]).parent / "artifacts"
    require(root == expected_root and len(records) == len({r["path"] for r in records}) <= 34,
            "Wrong artifact root/duplicate inventory")
    expected = {{"stdout": "stdout.bin", "stderr": "stderr.bin"}.get(k, k): (k, v) for k, v in manifest["entries"].items()}
    require(set(expected) == {r["path"] for r in records} and set(ARTIFACTS) <= set(expected), "Incomplete native artifacts")
    require(sum(r["bytes"] for r in records) <= 512 * 1024**2, "Full artifact bound exceeded; never truncate")
    for row in records:
        name, entry = expected[row["path"]]
        require(row["artifact_name"] == name and row["bytes"] == entry["size"] and row["sha256"] == entry["sha256"],
                "Cloud/native inventory differs")
        raw = file_bytes(root / row["path"], active["provider_binding"]["max_artifact_bytes"])
        require(len(raw) == row["bytes"] and hashlib.sha256(raw).hexdigest() == row["sha256"], "Native artifact bytes differ")
        fetch = row["fetch_receipt"]
        require(fetch.get("verified") is True and fetch.get("job_id") == job["job_id"] and fetch.get("artifact") == name
                and fetch.get("size") == row["bytes"] and fetch.get("sha256") == row["sha256"],
                "Actual Engine fetch receipt differs")
    declared = read(root / "artifact-manifest.json")
    require(declared.get("schema") == "hepta-artifact-manifest-v1" and declared.get("request_id") == active["request_id"],
            "Control output manifest identity differs")
    records_by_name = {r["path"]: r for r in records}
    intended = {name: dict(bytes=records_by_name[name]["bytes"], sha256=records_by_name[name]["sha256"])
                for name in ARTIFACTS if name != "artifact-manifest.json"}
    require(len(declared["files"]) == len(intended)
            and {r["path"]: dict(bytes=r["bytes"], sha256=r["sha256"]) for r in declared["files"]} == intended,
            "Complete control output manifest differs")
    return root



def initial_state(config):
    return dict(config_sha256=digest(config), fits={r["fit_id"]: dict(state="UNSTARTED", ever_claimed=False) for r in config["ordered_roster"]},
                groups={g["group_id"]: dict(fit_ids=g["fit_ids"], phase="fit", prior_capsule=None, ever_claimed_fit_ids=[], ever_claimed_evaluation_ids=[], evaluations={}, selected_ids=[], verified_selection_lock_sha256=None) for g in config["groups"]},
                active=None, batch_count=0, halted=None, execution_finished=False)


def validate_state_transition(before, after, kind, evidence=None):
    require(before["config_sha256"] == after["config_sha256"] and before["fits"].keys() == after["fits"].keys() and before["groups"].keys() == after["groups"].keys(), "Global roster/config changed")
    for fit_id, old in before["fits"].items():
        new = after["fits"][fit_id]
        require(new["state"] in TERMINAL | {"UNKNOWN", "UNSTARTED", "RESERVED", "CLAIMED_PENDING"} and new["ever_claimed"] is (new["state"] not in {"UNSTARTED", "RESERVED"}), "Invalid native fit state/claim flag")
        require(not old["ever_claimed"] or new["ever_claimed"], "A native ever-claimed fit disappeared")
        if old["state"] in TERMINAL | {"UNKNOWN"}:
            require(new == old, "A terminal/unknown fit was changed or replayed")
        if old["state"] == "RESERVED" and new["state"] == "UNSTARTED":
            require(kind == "CAPSULE_ACCEPTED" and not new["ever_claimed"] and all((evidence or {}).get(k) is True for k in ("provider_terminal_verified", "full_capsule_verified", "final_state_attested")), "Reservation released without verified terminal capsule")
    for name, old in before["groups"].items():
        new = after["groups"][name]
        require(new["fit_ids"] == old["fit_ids"] and {"fit": 0, "selection": 1, "evaluation": 2, "done": 3}[new["phase"]] >= {"fit": 0, "selection": 1, "evaluation": 2, "done": 3}[old["phase"]], "Group identity/phase regressed")
        for key in ("ever_claimed_fit_ids", "ever_claimed_evaluation_ids"):
            require(set(old[key]) <= set(new[key]) <= set(new["fit_ids"]) and len(new[key]) == len(set(new[key])), "Native claim history contracted/escaped group")
        for fit_id, value in old["evaluations"].items():
            require(fit_id in new["evaluations"] and (value["state"] not in TERMINAL | {"UNKNOWN"} or new["evaluations"][fit_id] == value), "Evaluation disappeared or was replayed")
        require(set(new["evaluations"]) == set(new["ever_claimed_evaluation_ids"]), "Evaluation claim ledger is incomplete")
        if old["verified_selection_lock_sha256"] is not None:
            require(new["verified_selection_lock_sha256"] == old["verified_selection_lock_sha256"] and new["selected_ids"] == old["selected_ids"], "Verified selection was changed")
    if before["active"] and after["active"]:
        require(all(after["active"].get(k) == v for k, v in before["active"].items() if k not in ("producer", "terminal_observation", "asset_upload_receipt", "adapter_registration", "dispatch_requested", "post_run_reconciliation")), "Active dispatch identity changed")
        for key in ("producer", "terminal_observation", "asset_upload_receipt", "adapter_registration", "post_run_reconciliation"):
            if before["active"].get(key) is not None:
                require(after["active"].get(key) == before["active"][key], "Provider producer/terminal identity changed")
        require(not before["active"].get("dispatch_requested") or after["active"].get("dispatch_requested") is True, "Dispatch intent regressed")
    claims = {i for g in after["groups"].values() for i in g["ever_claimed_fit_ids"]}
    require(claims == {i for i, value in after["fits"].items() if value["ever_claimed"]}, "Global and group claim ledgers differ")


class Ledger:
    def __init__(self, root, config):
        self.root = safe_path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        require(not self.root.is_symlink(), "Owner root is a symlink")
        self.lock = os.fdopen(os.open(self.root / "owner.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600), "w")
        lock_stat = os.fstat(self.lock.fileno())
        require(stat.S_ISREG(lock_stat.st_mode) and lock_stat.st_nlink == 1, "Unsafe owner lock")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            self.lock.close()
            raise
        self.state, self.number, self.previous = initial_state(config), 0, None
        for path in sorted((self.root / "events").glob("*.json")):
            raw = file_bytes(path)
            event = parse(raw)
            require(event["sequence"] == self.number + 1 and event["previous_sha256"] == self.previous and path.name == f"{self.number + 1:06d}.json", "Broken immutable native ledger chain")
            validate_state_transition(self.state, event["state"], event["kind"], event.get("evidence"))
            self.state, self.number, self.previous = event["state"], event["sequence"], hashlib.sha256(raw).hexdigest()
        self.config = config

    def append(self, kind, state, evidence=None):
        validate_state_transition(self.state, state, kind, evidence)
        event = dict(sequence=self.number + 1, previous_sha256=self.previous, kind=kind, at_utc=datetime.now(timezone.utc).isoformat(), evidence=evidence, state=state)
        raw = canonical(event)
        exclusive(self.root / "events" / f"{self.number + 1:06d}.json", raw)
        self.state, self.number, self.previous = parse(raw)["state"], self.number + 1, hashlib.sha256(raw).hexdigest()

    def copy(self):
        return parse(canonical(self.state))








def verify_selection(study, group, plan, config):
    """Independent stdlib reproduction of the frozen validation-only selection."""
    block = study / "blocks" / group["group_id"]
    lock, receipt = read(block / "selection-lock.json"), read(block / "selection-receipt.json")
    lock_sha = hashlib.sha256(file_bytes(block / "selection-lock.json")).hexdigest()
    require(receipt.get("identity") == config["identity"] and receipt.get("group_id") == group["group_id"] and receipt.get("phase") == "selection" and receipt.get("selection_lock_sha256") == lock_sha, "Original selection receipt/lock binding differs")
    fits = [r for r in config["ordered_roster"] if r["fit_id"] in group["fit_ids"]]
    terminals = {r["fit_id"]: read(study / "attempts" / r["fit_id"] / "terminal.json") for r in fits}
    require(all(t.get("status") in TERMINAL for t in terminals.values()), "Selection lacks twenty non-UNKNOWN terminals")
    for field, name in (("fit_terminal_file_sha256", "terminal.json"), ("fit_process_completion_file_sha256", "process-completion.json")):
        require(lock.get(field) == {r["fit_id"]: hashlib.sha256(file_bytes(study / "attempts" / r["fit_id"] / name)).hexdigest() for r in fits}, "Selection training-evidence file hash differs")
    selected, missing = {}, {}
    for arm in plan["arms"]:
        pair = sorted((r for r in fits if r["arm"] == arm), key=lambda r: r["lr_index"])
        valid = [r for r in pair if terminals[r["fit_id"]].get("status") == "COMPLETED" and terminals[r["fit_id"]].get("optimizer_updates_completed") == plan["train_updates"] and (terminals[r["fit_id"]].get("validation") or {}).get("count") == plan["validation_count"] and math.isfinite(terminals[r["fit_id"]]["validation"].get("mse", math.nan))]
        if len(pair) != len(plan["learning_rates"]) or len(valid) != len(pair):
            missing[arm] = [dict(fit_id=r["fit_id"], status=terminals[r["fit_id"]]["status"]) for r in pair]
            continue
        best = min(valid, key=lambda r: (terminals[r["fit_id"]]["validation"]["mse"], r["lr_index"]))
        terminal = terminals[best["fit_id"]]
        selected[arm] = dict(fit_id=best["fit_id"], learning_rate=best["learning_rate"], validation_mse=terminal["validation"]["mse"], checkpoint_sha256=terminal["checkpoint_sha256"], terminal_sha256=hashlib.sha256(canonical(terminal)[:-1]).hexdigest())
    others = [a for a in plan["arms"] if a != "regenerative_dual" and a in selected]
    best_other = min(others, key=lambda a: (selected[a]["validation_mse"], plan["arms"].index(a))) if others else None
    complete = not missing and len(selected) == len(plan["arms"])
    expected = dict(schema="hcsn-mechanism-selection-lock-v1", identity=config["identity"], group_id=group["group_id"], task=fits[0]["task"], training_seed=fits[0]["training_seed"], selected=selected, incomplete_tuning_pairs=missing, strongest_registered_comparator=best_other if complete else None, best_available_comparator=best_other, strongest_full_registered_set_eligible=complete, all_registered_arms_selected=complete, selection_basis="validation MSE only; ties: registered arm order, then LR order", episode_seeds=plan["test_episode_seeds"], test_has_started=False)
    require(all(lock.get(k) == v for k, v in expected.items()), "Selection choices differ from frozen validation evidence")
    require(receipt.get("selected_fit_ids") == [v["fit_id"] for v in selected.values()] and receipt.get("all_registered_arms_selected") == complete and receipt.get("strongest_full_registered_set_eligible") == complete, "Selection receipt choices differ")
    # Dispatch uses full roster order; the selection receipt uses registered arm order.
    return [r["fit_id"] for r in fits if r["fit_id"] in {v["fit_id"] for v in selected.values()}], lock_sha


def inspect_claims(study, manifest, config, phase, selected_ids, selection_sha=None):
    fits = {row["fit_id"]: row for row in config["ordered_roster"]}
    outcomes, evaluations = {}, {}
    for category, ids, output, expected_phase in (("attempts", manifest["claimed_fit_ids"], outcomes, "fit"), ("evaluations", manifest["claimed_evaluation_ids"], evaluations, "selected_test")):
        for fit_id in ids:
            path = study / category / fit_id
            terminal, completion = path / "terminal.json", path / "process-completion.json"
            if not terminal.exists() or not completion.exists():
                output[fit_id] = dict(state="UNKNOWN", ever_claimed=True, reason="Claimed without complete stopped-worker evidence")
                continue
            t, stop = read(terminal), read(completion)
            require(t.get("identity") == config["identity"] and t.get("fit") == fits[fit_id] and t.get("phase") == expected_phase, "Claimed operation identity differs")
            require(type(stop.get("returncode")) is int and type(stop.get("timed_out")) is bool, "Worker stopped status missing")
            status = t.get("status")
            require(status in TERMINAL | {"UNKNOWN"}, "Unrecognized fit/evaluation outcome")
            if t.get("environment") is not None:
                check_environment(config["execution_environment"], t["environment"])
            if status in {"COMPLETED", "FAILED"}:
                require(t.get("frozen_environment_check", {}).get("matched") is True, "Claim did not establish the frozen execution environment")
            error = t.get("error") or {}
            require(not any(word in str(error.get("message", "")).lower() for word in ("environment", "gpu mismatch", "source drift", "source pin", "identity", "checkpoint", "selection", "bundle", "frozen", "plan mismatch", "roster")), "Integrity failure requires owner halt, not an ordinary training failure")
            if status == "FAILED":
                require(stop["returncode"] == 2 and not stop["timed_out"], "Failed outcome lacks a matching stopped worker")
            if status == "TIMEOUT":
                require(stop["timed_out"] or (stop["returncode"] == 2 and error.get("type") == "TimeoutError" and t.get("frozen_environment_check", {}).get("matched") is True), "Timeout lacks a stopped-worker timeout receipt")
            if status == "COMPLETED":
                require(stop["returncode"] == 0 and not stop["timed_out"] and t.get("source_and_input_pins_unchanged_at_completion") is True and t.get("frozen_environment_check", {}).get("matched") is True, "Completed operation lacks execution proof")
                if category == "attempts":
                    require(t.get("optimizer_updates_completed") == 400 and t.get("training_examples_completed") == 25600, "Completed fit has incomplete fixed budget")
                    require((t.get("validation") or {}).get("count") == 512 and math.isfinite(t["validation"].get("mse", math.nan)), "Completed fit lacks finite complete validation")
                    require(manifest["files"][f"attempts/{fit_id}/checkpoint.pt"]["sha256"] == t.get("checkpoint_sha256"), "Completed checkpoint binding differs")
                else:
                    require(fit_id in selected_ids and t.get("selection_lock_sha256") == selection_sha, "Evaluation was not selected under the verified lock")
                    require([r["episode_seed"] for r in t.get("test", [])] == [4703, 5801] and all(r["count"] == 1024 for r in t["test"]) and t.get("independent_training_replicates_represented") == 1 and t.get("evaluation_episode_seeds_are_training_replicates") is False, "Evaluation episode/training-seed accounting differs")
            count = t.get("optimizer_updates_completed")
            require(count is None or (type(count) is int and 0 <= count <= 400), "Invalid actual optimizer update counter")
            output[fit_id] = dict(state=status, ever_claimed=True, terminal_sha256=hashlib.sha256(file_bytes(terminal)).hexdigest(), process_completion_sha256=hashlib.sha256(file_bytes(completion)).hexdigest(), optimizer_updates_completed=count, counters_are_lower_bounds=t.get("counters_are_lower_bounds", False))
    return outcomes, evaluations


class Owner:
    def __init__(self, config, plan, source_root, control_root, ledger, builder, adapter=None, asset_module=None):
        self.config, self.plan, self.source_root, self.control_root = config, plan, Path(source_root), Path(control_root)
        self.ledger, self.builder = ledger, builder
        self.adapter = adapter or Adapter(config, ledger.root)
        self.asset_module = asset_module or load_module_path("hcsn_s81_asset_transport_v3",
            self.source_root / ASSET_RELATIVE, config["source_pins"][ASSET_RELATIVE])


    def reserve(self, group):
        require(self.config.get("formal_training_start_authorized") is True, "Formal training is not authorized")
        verify_local_pins(self.config, self.source_root, self.control_root)
        require(provider_binding(self.config) == self.config["provider_binding"], "Actual provider changed")
        state = self.ledger.copy()
        require(state["active"] is None and state["halted"] is None and state["batch_count"] < 248,
                "Existing/unknown job or fixed job-count bound")
        group_state = state["groups"][group["group_id"]]
        phase = group_state["phase"]
        planned = [i for i in group["fit_ids"] if state["fits"][i]["state"] == "UNSTARTED"] if phase == "fit" else []
        planned_eval = [i for i in group_state["selected_ids"] if i not in group_state["ever_claimed_evaluation_ids"]] if phase == "evaluation" else []
        request = f"hcsn-s81-colab-{self.config['plan_sha256'][:12]}-g{self.config['groups'].index(group):02d}-{phase}-b{state['batch_count']:03d}"
        require(phase == "selection" or planned or planned_eval, "No unclaimed operation remains")
        batch = dict(request_id=request, group_id=group["group_id"], phase=phase, planned_fit_ids=planned,
            planned_evaluation_ids=planned_eval, formal_training_start_authorized=True, expected_group_fit_ids=group["fit_ids"],
            plan_relative_path=self.config["plan_relative_path"], admission_epoch_unix=time.time(),
            verified_selection_lock_sha256=group_state["verified_selection_lock_sha256"], prior_capsule=group_state["prior_capsule"],
            ever_claimed_fit_ids=group_state["ever_claimed_fit_ids"], ever_claimed_evaluation_ids=group_state["ever_claimed_evaluation_ids"],
            identity=self.config["identity"], plan_sha256=self.config["plan_sha256"], source_pins=self.config["source_pins"],
            control_pins=self.config["control_pins"], published_plan_commit=self.config["published_plan_commit"], published_plan_ref=REF,
            qualified_input=self.config["qualified_input"], provider_binding=self.config["provider_binding"],
            submission_not_before_utc=datetime.now(timezone.utc).isoformat())
        directory = self.ledger.root / "provider-jobs" / request
        payload = self.builder(batch, self.source_root, self.source_root / self.config["plan_relative_path"], self.control_root,
            asset_module=self.asset_module, asset_output=directory / "prepared-inputs", remote_root=self.config["provider_binding"]["remote_root"])
        code = payload["source_text"].encode()
        require(payload["request_id"] == request and payload["code_sha256"] == hashlib.sha256(code).hexdigest()
                and payload["code_bytes"] == len(code) <= 262144, "Colab bootstrap identity/size differs")
        exclusive(directory / "source.py", code)
        exclusive(directory / "batch-config.json", batch)
        prepared = {key: str(value) if isinstance(value, Path) else value for key, value in payload["prepared_assets"].items()}
        active = dict(batch, code_sha256=payload["code_sha256"], source_path=str(directory / "source.py"),
            prepared_assets=prepared, asset_upload_receipt=None, adapter_registration=None, dispatch_requested=False, post_run_reconciliation=None,
            reserved_unix=time.time(), producer=None, terminal_observation=None)
        for fit_id in planned:
            require(not state["fits"][fit_id]["ever_claimed"], "Cannot replay a claimed fit")
            state["fits"][fit_id] = dict(state="RESERVED", ever_claimed=False, request_id=request)
        state["active"], state["batch_count"] = active, state["batch_count"] + 1
        self.ledger.append("RESERVED_BEFORE_ASSET_OR_JOB_EFFECT", state, dict(request_id=request, code_sha256=payload["code_sha256"]))
        uploaded = self.adapter.stage(active, self.asset_module)
        validate_staged_assets(uploaded, active, self.config)
        state = self.ledger.copy()
        state["active"]["asset_upload_receipt"] = uploaded
        self.ledger.append("ASSETS_VERIFIED", state, uploaded)
        registration = self.adapter.call("submit", request, code.decode())
        producer = validate_remote(registration, self.ledger.state["active"], self.config)
        require(registration["job"]["state"] == "queued" and registration["job"]["submit_attempts"] == 0,
                "New request was not an unexecuted exact registration")
        state = self.ledger.copy()
        state["active"]["adapter_registration"], state["active"]["producer"] = registration, producer
        self.ledger.append("ADAPTER_JOB_REGISTERED", state, registration)
        return registration


    def accept(self, remote, artifacts):
        from capsule_contract import restore_capsule, validate_transition
        verify_local_pins(self.config, self.source_root, self.control_root)
        s = self.ledger.copy()
        active, group_id = s["active"], s["active"]["group_id"]
        validate_remote(remote, active, self.config)
        require(active.get("producer") is not None and active.get("terminal_observation") is not None and remote["job"]["state"] in PROVIDER_TERMINAL, "Complete native producer/terminal binding missing")
        g = s["groups"][group_id]
        root = verified_artifacts(artifacts, remote, active)
        execution = read(root / "execution.json")
        require(execution.get("schema") == "hcsn-mechanism-colab-batch-v3", "Unsupported batch receipt")
        validate_execution_producer(execution, remote, active)
        validate_materialization(read(root / "asset-materialization.json"), active)
        for key in ("request_id", "group_id", "phase", "identity", "source_pins", "control_pins", "plan_sha256", "published_plan_commit", "published_plan_ref", "planned_fit_ids", "planned_evaluation_ids"):
            require(execution.get(key) == active[key], "Batch receipt differs: " + key)
        require(execution.get("qualified_input") == active["qualified_input"] and execution.get("prior_capsule") == active["prior_capsule"], "Input producers differ from the native dispatch")
        cap = execution["capsule"]
        require(cap["archive_name"] == "study-capsule.tar.gz" and cap["manifest_name"] == "capsule-manifest.json", "Capsule artifact names differ")
        manifest = read(root / cap["manifest_name"], cap["manifest_sha256"])
        require(manifest["archive"] == dict(bytes=cap["archive_bytes"], sha256=cap["archive_sha256"]), "Capsule receipt/hash differs")
        prior = read(g["prior_capsule"]["native_manifest_path"], g["prior_capsule"]["manifest_sha256"]) if g["prior_capsule"] else None
        validate_transition(prior, manifest, g["ever_claimed_fit_ids"], g["ever_claimed_evaluation_ids"])
        group = next(x for x in self.config["groups"] if x["group_id"] == group_id)
        restored = self.ledger.root / "verified-capsules" / active["request_id"] / str(time.time_ns())
        restored.parent.mkdir(parents=True, exist_ok=True)
        restore_capsule(root / cap["archive_name"], manifest, restored, self.config["identity"], group_id, group["fit_ids"], g["ever_claimed_fit_ids"], g["ever_claimed_evaluation_ids"])
        fresh_fit = set(manifest["claimed_fit_ids"]) - set(active["ever_claimed_fit_ids"])
        fresh_eval = set(manifest["claimed_evaluation_ids"]) - set(active["ever_claimed_evaluation_ids"])
        require(fresh_fit <= set(active["planned_fit_ids"]) and fresh_eval <= set(active["planned_evaluation_ids"]), "Unregistered operation claimed by provider")
        for fit_id in fresh_fit:
            if not s["fits"][fit_id]["ever_claimed"]:
                s["fits"][fit_id] = dict(state="CLAIMED_PENDING", ever_claimed=True, request_id=active["request_id"])
        for fit_id in fresh_eval:
            g["evaluations"].setdefault(fit_id, dict(state="CLAIMED_PENDING", ever_claimed=True, request_id=active["request_id"]))
        g["ever_claimed_fit_ids"], g["ever_claimed_evaluation_ids"] = manifest["claimed_fit_ids"], manifest["claimed_evaluation_ids"]
        self.ledger.append("CLAIMS_OBSERVED", s, dict(manifest_sha256=cap["manifest_sha256"], producer=active["producer"], restored_path=str(restored), execution_path=str(root / "execution.json")))
        # This append precedes all terminal parsing and guard checks. A malformed
        # terminal can never erase the already authenticated physical claim.
        outcomes, evaluations = inspect_claims(restored, manifest, self.config, active["phase"], g["selected_ids"], g["verified_selection_lock_sha256"])
        s = self.ledger.copy()
        s["fits"].update(outcomes)
        s["groups"][group_id]["evaluations"] = evaluations
        self.ledger.append("OUTCOMES_OBSERVED", s)
        require(execution.get("status") == "EXPORTED" and execution.get("halt_owner") is False and remote["job"]["state"] == "succeeded", "Provider did not export an accepted bounded batch")
        require(all(execution.get(k) is True for k in ("source_unchanged", "environment_verified", "worker_children_stopped", "final_state_attested", "capsule_verified")), "End-of-job evidence incomplete")
        check_environment(self.config["execution_environment"], execution["observed_environment"]["environment"])
        require(execution["observed_environment"].get("check", {}).get("matched") is True, "Global environment preflight did not match")
        require(all(x["state"] in TERMINAL for x in list(outcomes.values()) + list(evaluations.values())), "Unknown claimed operation; never replay")
        require(active["phase"] == "selection" or fresh_fit or fresh_eval, "No progress; do not allocate a replacement provider job")
        s = self.ledger.copy()
        g = s["groups"][group_id]
        for planned_name, claimed_name in (("fit", "claimed_fit_ids"), ("evaluation", "claimed_evaluation_ids")):
            require(execution.get("unclaimed_remaining_planned_" + planned_name + "_ids") == [i for i in active["planned_" + planned_name + "_ids"] if i not in manifest[claimed_name]], "Final unclaimed reservation evidence differs")
        for fit_id in active["planned_fit_ids"]:
            if fit_id not in manifest["claimed_fit_ids"]:
                require(not s["fits"][fit_id]["ever_claimed"], "Claim omission cannot release reservation")
                s["fits"][fit_id] = dict(state="UNSTARTED", ever_claimed=False)
        g["prior_capsule"] = dict(colab_producer=active["producer"], archive_sha256=cap["archive_sha256"], archive_bytes=cap["archive_bytes"], manifest_sha256=cap["manifest_sha256"], native_manifest_path=str(root / cap["manifest_name"]), native_archive_path=str(root / cap["archive_name"]), native_restored_path=str(restored), request_id=active["request_id"], execution_path=str(root / "execution.json"), execution_sha256=hashlib.sha256(file_bytes(root / "execution.json")).hexdigest())
        if active["phase"] == "fit" and all(s["fits"][i]["state"] in TERMINAL for i in group["fit_ids"]):
            g["phase"] = "selection"
        elif active["phase"] == "selection":
            g["selected_ids"], g["verified_selection_lock_sha256"] = verify_selection(restored, group, self.plan, self.config)
            g["phase"] = "evaluation" if g["selected_ids"] else "done"
        elif active["phase"] == "evaluation" and set(g["selected_ids"]) <= set(evaluations):
            g["phase"] = "done"
        s["active"] = None
        self.ledger.append("CAPSULE_ACCEPTED", s, dict(provider_terminal_verified=True, full_capsule_verified=True, final_state_attested=True, producer=remote, artifact_verification=artifacts, execution_costs=execution.get("costs"), full_physical_energy_joules=None, nested_wall_not_added=True))

    def final_handoff(self):
        verify_local_pins(self.config, self.source_root, self.control_root)
        s, capsules, members, semantics = self.ledger.state, [], set(), set()
        require(s["active"] is None and all(v["state"] in TERMINAL for v in s["fits"].values()), "Final union requires all 160 non-UNKNOWN terminals")
        for group in self.config["groups"]:
            g = s["groups"][group["group_id"]]
            require(g["phase"] == "done" and set(g["ever_claimed_fit_ids"]) == set(group["fit_ids"]) and set(g["selected_ids"]) == set(g["evaluations"]) and all(v["state"] in TERMINAL for v in g["evaluations"].values()), "Group selection/evaluation closure missing")
            cap = g["prior_capsule"]
            manifest = read(cap["native_manifest_path"], cap["manifest_sha256"])
            require(manifest["identity"] == self.config["identity"] and manifest["group_id"] == group["group_id"] and manifest["expected_group_fit_ids"] == group["fit_ids"], "Final capsule identity differs")
            archive = file_bytes(cap["native_archive_path"])
            require(len(archive) == cap["archive_bytes"] and hashlib.sha256(archive).hexdigest() == cap["archive_sha256"] and not members.intersection(manifest["claimed_fit_ids"]), "Final capsule changed or groups overlap")
            for name, pin in manifest["files"].items():
                raw = file_bytes(Path(cap["native_restored_path"]) / name)
                require(len(raw) == pin["bytes"] and hashlib.sha256(raw).hexdigest() == pin["sha256"], "Final restored history changed")
            read(cap["execution_path"], cap["execution_sha256"])
            selected, lock_sha = verify_selection(Path(cap["native_restored_path"]), group, self.plan, self.config)
            require(selected == g["selected_ids"] and lock_sha == g["verified_selection_lock_sha256"], "Final selection binding differs")
            block = read(Path(cap["native_restored_path"]) / "blocks" / group["group_id"] / "terminal.json")
            require(block.get("identity") == self.config["identity"] and block.get("group_id") == group["group_id"] and block.get("selection_lock_sha256") == lock_sha and block.get("training_terminal_status") == {i: s["fits"][i]["state"] for i in group["fit_ids"]}, "Final group terminal differs from native ledger")
            members.update(manifest["claimed_fit_ids"])
            semantics.add(manifest["study_semantic_sha256"])
            capsules.append(dict(group_id=group["group_id"], fit_ids=group["fit_ids"], selected_ids=g["selected_ids"], selection_lock_sha256=g["verified_selection_lock_sha256"], capsule=cap))
        require(members == set(s["fits"]) and len(semantics) == 1, "Eight-group union does not represent the exact same full study")
        value = dict(schema="hcsn-mechanism-full-study-analysis-handoff-v1", status="EXECUTION_CLOSED_ANALYSIS_PENDING", identity=self.config["identity"],
            published_plan_commit=self.config["published_plan_commit"], published_plan_ref=REF, publication_receipt=self.config["publication_receipt"], control_pins=self.config["control_pins"],
            source_root=str(self.source_root), plan_path=str(self.source_root / self.config["plan_relative_path"]), qualified_input=self.config["qualified_input"], groups=capsules,
            ledger_head_before_closure=self.ledger.previous, ledger_events_directory=str(self.ledger.root / "events"), adapter_calls_directory=str(self.ledger.root / "adapter-calls"),
            progress=self.summary(), next_owner="root", next_action="Assemble all eight immutable group capsules into one fresh full-study tree; preserve all attempts, failures and losing LR checkpoints; then run the frozen mechanism_analysis.py in an independently recorded CPU analysis-only environment.",
            analysis_started=False, scientific_admission="HOLD", original_campaign_completion_credit=0, full_physical_energy_joules=None, monetary_cost=None,
            cost_rule="Retain every native adapter and provider receipt; payload, operation, worker and GPU intervals are nested scopes, never blindly added.")
        path = self.ledger.root / "final-handoff.json"
        raw = canonical(value)
        if path.exists():
            require(file_bytes(path) == raw, "Existing final handoff differs")
        else:
            exclusive(path, raw)
        return dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest())

    def run(self):
        require(self.ledger.state["halted"] is None, "Owner is halted; explicit read-only review required")
        try:
            if self.ledger.state["execution_finished"]:
                return self.summary()
            while not all(g["phase"] == "done" for g in self.ledger.state["groups"].values()):
                active = self.ledger.state["active"]
                if active is None:
                    group = next(g for g in self.config["groups"] if self.ledger.state["groups"][g["group_id"]]["phase"] != "done")
                    self.reserve(group)
                active = self.ledger.state["active"]
                require(active.get("adapter_registration") is not None and active.get("asset_upload_receipt", {}).get("status") == "VERIFIED",
                        "Incomplete preparation/registration: read-only reconciliation only")
                job_id = active["adapter_registration"]["job"]["job_id"]
                if not active["dispatch_requested"]:
                    state = self.ledger.copy()
                    state["active"]["dispatch_requested"] = True
                    self.ledger.append("SINGLE_DISPATCH_INTENT", state, dict(job_id=job_id, automatic_retry=False))
                    remote = self.adapter.call("run", job_id)
                    validate_remote(remote, self.ledger.state["active"], self.config)
                    if remote["job"]["state"] not in PROVIDER_TERMINAL:
                        state = self.ledger.copy()
                        require(state["active"].get("post_run_reconciliation") is None, "Post-run reconciliation already claimed")
                        state["active"]["post_run_reconciliation"] = dict(job_id=job_id, attempts=1,
                            first_run_observation=remote, reason="One fresh-provider status may refresh an expired proxy token; no execution replay")
                        self.ledger.append("ONE_READONLY_POST_RUN_RECONCILIATION_INTENT", state, remote)
                        remote = self.adapter.call("status", job_id)
                else:
                    if active["terminal_observation"] is None:
                        require(active.get("post_run_reconciliation") is None,
                                "A claimed post-run reconciliation needs external read-only review after interruption")
                        state = self.ledger.copy()
                        state["active"]["post_run_reconciliation"] = dict(job_id=job_id, attempts=1,
                            first_run_observation=None, reason="One read-only observation after interrupted native run; never run again")
                        self.ledger.append("ONE_READONLY_POST_RUN_RECONCILIATION_INTENT", state)
                    remote = self.adapter.call("status", job_id)
                while True:
                    active = self.ledger.state["active"]
                    validate_remote(remote, active, self.config)
                    observed_state = remote["job"]["state"]
                    if observed_state in PROVIDER_TERMINAL:
                        if active["terminal_observation"] is None:
                            state = self.ledger.copy()
                            state["active"]["terminal_observation"] = remote
                            self.ledger.append("PROVIDER_TERMINAL_OBSERVED", state, remote)
                        else:
                            old = active["terminal_observation"]
                            require(remote["job"] == old["job"] and remote["receipt"] == old["receipt"]
                                    and remote["manifest"] == old["manifest"], "Terminal receipt changed")
                            remote = old
                        break
                    require(observed_state in {"dispatched", "running"}, "UNKNOWN/queued after dispatch: no replay or replacement")
                    require(time.time() < active["reserved_unix"] + 3900, "Finite observation deadline; no stop inferred")
                    time.sleep(20)
                    remote = self.adapter.call("status", job_id)
                artifacts = self.adapter.fetch_all(remote, self.ledger.state["active"])
                self.accept(remote, artifacts)
                print(json.dumps(self.summary(), sort_keys=True, allow_nan=False), flush=True)
            handoff = self.final_handoff()
            state = self.ledger.copy()
            state["execution_finished"], state["final_handoff"] = True, handoff
            self.ledger.append("EXECUTION_CLOSED", state, self.summary())
            return self.summary()
        except BaseException as error:
            state = self.ledger.copy()
            state["halted"] = dict(type=type(error).__name__, reason=str(error),
                pending_provider_may_still_run=state["active"] is not None and state["active"].get("terminal_observation") is None,
                automatic_replay=False)
            self.ledger.append("HALTED", state)
            raise


    def summary(self):
        s = self.ledger.state
        known = [x.get("optimizer_updates_completed") for x in s["fits"].values() if x["ever_claimed"]]
        active = s["active"]
        unresolved = [dict(request_id=active["request_id"], phase=active["phase"], planned_fit_ids=active["planned_fit_ids"], planned_evaluation_ids=active["planned_evaluation_ids"], producer=active.get("producer"), native_terminal_observed=active.get("terminal_observation") is not None, complete_capsule_accepted=False)] if active else []
        return dict(schema="hcsn-global-160-owner-progress-v1", registered_fit_count=160, fit_counts=dict(Counter(x["state"] for x in s["fits"].values())),
                    ever_claimed_fit_count=sum(x["ever_claimed"] for x in s["fits"].values()), registered_optimizer_updates=64000,
                    known_optimizer_updates_lower_bound=sum(x for x in known if type(x) is int and x >= 0), missing_update_counter_count=sum(type(x) is not int for x in known),
                    statistical_groups=8, group_phases={k: v["phase"] for k, v in s["groups"].items()}, provider_jobs_reserved=s["batch_count"],
                    unresolved_provider_jobs=unresolved, unclaimed_reserved_fit_count=sum(v["state"] == "RESERVED" for v in s["fits"].values()), final_handoff=s.get("final_handoff"),
                    missing_cost_scope=["Full physical energy", "Provider monetary charges", "End-to-end external deployment cost"] + (["Unresolved provider effects and any unexported optimizer updates"] if unresolved else []),
                    original_campaign_completion_credit=0, scientific_admission="HOLD", full_physical_energy_joules=None, monetary_cost=None)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("config", "source-root", "plan", "control-root", "published-plan-commit", "published-plan-ref"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    config = read(args.config)
    require(Path(__file__).resolve() == (Path(args.control_root) / "native_owner.py").resolve(), "Running native owner is outside the declared control source root")
    plan = validate_config(config, args.source_root, args.plan, args.control_root, args.published_plan_commit, args.published_plan_ref)
    require(Path(sys.executable).resolve() == Path(config["provider"]["native_python"]).resolve(), "Actual owner interpreter differs")
    sys.path.insert(0, str(Path(args.control_root).resolve()))
    load_control("capsule_contract", args.control_root, config["control_pins"]["capsule_contract.py"])
    cloud = load_control("cloud_batch", args.control_root, config["control_pins"]["cloud_batch.py"])
    owner = Owner(config, plan, args.source_root, args.control_root, Ledger(config["state_root"], config), cloud.build_payload)
    print(json.dumps(owner.run(), sort_keys=True, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
