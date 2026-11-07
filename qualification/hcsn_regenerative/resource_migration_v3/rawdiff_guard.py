"""Prospective Colab V3 provenance and exact scientific-diff admission.

Pure standard-library validation. No network, provider mutation, model, task
generation, lease recovery or training is performed by this module.
"""
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

PARENT_SHA = "cc2fe01594bd77721eda1f2a3130257ba5dbfa61c498a9f469f91195598c2550"
STUDY_ID = "hcsn-regenerative-mechanisms-fv-pilot-20261107-1631115f163f-v3"
SLOTS = ("unit", "graph_cpu", "graph_cuda", "sequence_cpu", "sequence_cuda", "resolution", "fixed_renewal", "budget")
ALLOWED_CHANGED = {"study_id", "frozen_at", "source_pins", "qualification_receipts", "numerical_resolution", "execution_environment", "runtime_feasibility_policy"}
HEX = re.compile(r"[0-9a-f]{64}")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

def require(condition, message):
    if not condition:
        raise ValueError(message)

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

def digest(data):
    return hashlib.sha256(data).hexdigest()

def raw(path, limit=268435456):
    path = Path(path).absolute()
    require(".." not in path.parts and not any(p.is_symlink() for p in (path, *path.parents)), "Unsafe input path")
    before = path.stat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= limit, "Unsafe or oversized input")
    data = path.read_bytes()
    after = path.stat()
    version = lambda x: (x.st_dev, x.st_ino, x.st_size, x.st_mtime_ns, x.st_ctime_ns)
    require(version(before) == version(after) and len(data) == before.st_size, "Input changed during read")
    return data

def parse(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result
    value = json.loads(data, object_pairs_hook=pairs)
    canonical(value)
    return value

def read(path, expected=None):
    data = raw(path)
    require(expected is None or digest(data) == expected, "Raw SHA256 mismatch")
    return parse(data)

def amendment():
    return read(Path(__file__).with_name("RESOURCE_AMENDMENT.json"))

def safe_relative(value):
    require(isinstance(value, str) and value and "\\" not in value and "\x00" not in value, "Unsafe relative path")
    parts = value.split("/")
    require(not value.startswith("/") and not any(x in ("", ".", "..") for x in parts), "Unsafe relative path")
    return value

def audit_diff(parent, child, registration=None):
    registration = registration or amendment()
    require(set(child) == set(parent) | {"resource_migration"}, "Undeclared top-level plan difference")
    for key in set(parent) - ALLOWED_CHANGED:
        require(child[key] == parent[key], "Scientific/budget/statistical field changed: " + key)
    require(child["study_id"] == STUDY_ID and child["frozen_at"] != parent["frozen_at"], "Distinct V3 study and actual new freeze required")
    original = parent["source_pins"]
    require(original == registration["preserved_parent_source_pins"] and len(original) == 42, "Original42 map differs")
    require(all(child["source_pins"].get(k) == v for k, v in original.items()), "Original scientific source changed")
    require(set(child["source_pins"]) - set(original) == set(registration["additional_source_paths"]), "Extra control roster differs")
    require(all(isinstance(v, str) and HEX.fullmatch(v) for v in child["source_pins"].values()), "Invalid source SHA")
    require(set(child["qualification_receipts"]) == set(SLOTS), "Eight fresh qualification slots required")
    for name in SLOTS:
        value, old = child["qualification_receipts"][name], parent["qualification_receipts"][name]
        require(value["sha256"] != old["sha256"], "Historical qualification reused: " + name)
        require(value["schema"] == old["schema"] and value["status"] == old["status"], "Qualification schema/status changed")
    policy = dict(parent["runtime_feasibility_policy"])
    require(policy.pop("provider") == "kaggle", "Unexpected scientific parent's provider")
    actual = dict(child["runtime_feasibility_policy"])
    require(actual.pop("provider") == "colab" and actual == policy, "Only provider label may change in runtime policy")
    numerical = child["numerical_resolution"]
    require(set(numerical) == set(parent["numerical_resolution"]) and numerical["active_cells"] == 64
            and numerical["phase_cells"] == 16 and numerical["eligible"] is True, "Fixed S81 grid changed")
    for key, ceiling in (("maximum_state_l1_error", .02), ("maximum_hit_relative_error", .03)):
        require(type(numerical[key]) in (int, float) and math.isfinite(numerical[key]) and 0 <= numerical[key] <= ceiling, "S81 numerical gate failed")
    env = child["execution_environment"]
    require(set(env) == set(parent["execution_environment"]) and env["device"] == "cuda"
            and env["cpu_threads"] == 1 and env["deterministic_algorithms"] is True
            and env["gpu_uuid_policy"] == "same_model_new_lease", "Execution policy changed")
    gpu = env["gpu"]
    require(set(gpu) == {"name", "compute_capability", "total_memory"} and gpu["name"] == "Tesla T4"
            and gpu["compute_capability"] == [7, 5] and type(gpu["total_memory"]) is int
            and gpu["total_memory"] > 0, "Fresh qualified T4 identity required")
    lineage = child["resource_migration"]
    require(lineage["provider"] == "colab" and lineage["parent_plan_sha256"] == PARENT_SHA
            and lineage["parent_study_id"] == parent["study_id"]
            and lineage["prior_ledgers_policy"] == "immutable"
            and lineage["v1_fit_completion_credit"] == lineage["v2_fit_completion_credit"] == 0, "Wrong resource lineage or historical credit")
    require(lineage["qualification_request_id"] == registration["qualification_request_id"]
            and UUID.fullmatch(lineage["qualification_job_id"]), "Colab qualification job identity absent")
    for name in ("fresh_qualification_native_receipt_sha256", "qualification_identity_sha256",
                 "qualification_code_sha256", "qualification_adapter_payload_sha256",
                 "qualification_manifest_sha256", "qualification_profile_sha256",
                 "qualification_profile_fingerprint", "binding_proof_sha256",
                 "adapter_source_sha256", "remote_runner_source_sha256", "authorizer_source_sha256", "fixed_kernel_provider_sha256", "amendment_sha256"):
        require(isinstance(lineage.get(name), str) and HEX.fullmatch(lineage[name]), "Missing resource proof SHA: " + name)
    require(not any(k in lineage for k in ("notebook_ref", "notebook_version", "kernel_id", "endpoint",
                                         "session_id", "profile_path", "expected_account_email")),
            "Public lineage must use typed Colab hashes, not raw private identity or Kaggle fields")
    return dict(schema="hcsn-s81-resource-rawdiff-v3", status="DECLARED_RESOURCE_DIFF_ONLY",
                unchanged_parent_source_files=42, added_source_files=len(registration["additional_source_paths"]),
                registered_training_attempts=160, registered_optimizer_updates=64000,
                independent_training_seeds_per_task_arm=4, statistical_family_size=20,
                original_campaign_completion_credit=0, v1_fit_completion_credit=0, v2_fit_completion_credit=0,
                full_physical_energy_joules=None, expansion_admission="HOLD")

def verify_launch(native, registration, ledger_job):
    """Bind the reviewed native command to actual supervisor and adapter worker records."""
    contract_raw = native["launch_contract_text"].encode()
    require(digest(contract_raw) == registration["resource_selection"]["native_qualification_launch_contract_sha256"],
            "Native launch contract is not the prospectively sealed bytes")
    contract = parse(contract_raw)
    require(contract["schema"] == "hcsn-colab-v3-qualification-launch-contract"
            and contract["request_id"] == registration["qualification_request_id"]
            and contract["host"] == "rog", "Native launch contract role differs")
    arguments = contract["args"]
    require(isinstance(arguments, list) and len(arguments) == 3 and arguments[:2] == ["-B", "-c"]
            and isinstance(arguments[2], str)
            and digest(arguments[2].encode()) == contract["worker_source_sha256"],
            "Native launch contract source differs")
    start, terminal = native["native_start"], native["native_terminal"]
    job, launch = start["job"], start["launch"]
    require(all(job.get(key) == contract[key] for key in ("host", "executable", "args", "idempotency_key"))
            and job.get("cwd") == contract.get("cwd")
            and contract.get("env", {}) == {} and job.get("env_keys") == [],
            "Actual native launch command differs from the reviewed contract")
    require(job.get("execution_mode") == "operator" and job.get("launch_error") is None
            and job.get("unit") == "hepta-runtime-job-" + job["id"]
            and launch.get("backend") == "systemd" and launch.get("ok") is True
            and launch.get("unit") == job["unit"] and HEX.fullmatch(job.get("request_digest", "")),
            "Native launch is not the exact successful systemd operation")
    files = native["native_files"]
    names = {"started.json", "owner-intent.json", "child.json", "exit.json", "exit.witness.json"}
    require(set(files) == names, "Native supervisor file roster differs")
    documents = {}
    for name, row in files.items():
        data = row["text"].encode()
        require(row["path"] == job["remote_job_dir"] + "/" + name
                and row["bytes"] == len(data) and row["sha256"] == digest(data),
                "Actual native supervisor bytes/path differ")
        documents[name] = parse(data)
    require(files["started.json"]["sha256"] == files["owner-intent.json"]["sha256"],
            "Native owner intent and start differ")
    started = documents["started.json"]
    require(started["job_id"] == job["id"] and started["launch_nonce"] == terminal["launch_nonce"]
            and isinstance(started.get("invocation_id"), str)
            and re.fullmatch(r"[0-9a-f]{32}", started["invocation_id"]),
            "Native start/terminal nonce or invocation differs")
    for name in ("exit.json", "exit.witness.json"):
        record = documents[name]
        require(record.get("job_id") == job["id"] and record.get("launch_nonce") == started["launch_nonce"]
                and record.get("invocation_id", started["invocation_id"]) == started["invocation_id"]
                and record.get("terminal_publication_protocol") == 1,
                "Native terminal file identity differs")
    require(documents["exit.witness.json"]["exit_sha256"] == files["exit.json"]["sha256"]
            and type(documents["exit.json"].get("exit_code")) is int
            and documents["exit.json"]["exit_code"] == terminal["exit_code"] == 0,
            "Native exit is not the exact witnessed successful terminal")
    worker, child = native["worker_identity"], documents["child.json"]
    require(type(worker.get("pid")) is int and worker["pid"] > 0
            and worker["pid"] == child.get("pid") == ledger_job.get("worker_pid")
            and isinstance(worker.get("start_ticks"), str) and worker["start_ticks"].isdigit()
            and worker["start_ticks"] == ledger_job.get("worker_start_ticks")
            and UUID.fullmatch(worker.get("boot_id", ""))
            and child.get("identity") == dict(kind="proc_start_ticks", value=worker["boot_id"] + ":" + worker["start_ticks"])
            and worker.get("cmdline") == [contract["executable"], *arguments],
            "Native launched worker is not the actual adapter dispatcher")


def verify_native(native, manifest, registration, artifact_root):
    """Validate exact actual native/tool/provider fields; no self-reported PASS shortcut."""
    require(native.get("schema") == "hcsn-colab-qualification-native-evidence-v3"
            and native.get("request_id") == registration["qualification_request_id"], "Native qualification identity differs")
    start, terminal = native["native_start"], native["native_terminal"]
    require(start["job"]["id"] == terminal["job_id"] and start["job"]["host"] == "rog"
            and start["job"].get("launch_state") == "launched", "Actual native launch/terminal mismatch")
    require(terminal.get("state") == "succeeded" and type(terminal.get("exit_code")) is int and terminal["exit_code"] == 0
            and terminal.get("output_complete") is True and terminal.get("output_durable") is True
            and terminal.get("terminal_publication_confirmed") is True and terminal.get("timed_out") is False
            and terminal.get("cancelled") is False, "Native qualification is not a complete successful terminal")
    job, public = native["ledger_job"], native["public_job"]
    require(UUID.fullmatch(job["job_id"]) and job["idempotency_key"] == registration["qualification_request_id"]
            and job["state"] == "succeeded" and job["submit_attempts"] == 1
            and job["wall_seconds"] == 3000, "Colab job is missing, failed, replayed or over budget")
    verify_launch(native, registration, job)
    for key in ("job_id", "state", "payload_sha256", "code_sha256", "endpoint", "kernel_id", "session_id",
                "remote_dir", "submit_attempts", "dispatched_at"):
        require(public.get(key) == job.get(key), "Public/authoritative job mismatch: " + key)
    profile_raw = native["execution_profile_text"].encode()
    profile = parse(profile_raw)
    require(job["profile"] == profile and job["profile_hash"] == digest(canonical(profile)), "Actual profile canonical identity differs")
    require(digest(profile_raw) == native["execution_profile_sha256"], "Actual execution profile bytes differ")
    bound_raw = native["binding_profile_text"].encode()
    bound = parse(bound_raw)
    proof_raw = native["binding_outcome_text"].encode()
    proof = parse(proof_raw)
    require(proof.get("admitted") is True and proof.get("status") == "BOUND_IDENTITY_VERIFIED"
            and proof.get("post_delegate_calls") == 1 and proof.get("automatic_retry") is False
            and proof["profile_raw_sha256"] == digest(bound_raw), "No actual owned BOUND proof")
    manager = proof["manager_result"]
    require(manager.get("owned_runtime") is True and manager.get("owned_kernel") is True
            and manager.get("runtime_submit_attempts") == manager.get("kernel_submit_attempts") == 1
            and proof["admission"]["profile_fingerprint"] == digest(canonical(bound)), "Binding ownership/attempt/profile mismatch")
    allowed = set(registration["resource_selection"]["profile_changes_allowed"])
    require(set(profile) == set(bound) and all(profile[k] == bound[k] for k in bound if k not in allowed)
            and profile["name"] != bound["name"], "Execution profile changed bound identity")
    require(profile["max_wall_seconds"] == 3000 and profile["max_artifact_bytes"] == 134217728
            and profile["max_output_bytes"] == 8388608, "Execution profile bounds differ")
    for key in ("endpoint", "kernel_id", "session_id"):
        require(job[key] == profile[key], "Profile/cloud job identity differs")
    require(job["remote_dir"] == profile["remote_root"] + "/" + job["job_id"],
            "Cloud directory is not the exact bound job namespace")
    require(manager["endpoint"] == bound["endpoint"] and manager["kernel_id"] == bound["kernel_id"]
            and manager["client_session_id"] == bound["session_id"], "Binding manager/profile identity differs")
    required_artifacts = sorted(registration["fresh_qualification"]["requested_artifacts"])
    require(job["artifacts"] == required_artifacts and len(job["code"].encode()) <= 262144
            and digest(job["code"].encode()) == job["code_sha256"] == manifest["payload_sha256"], "Code or artifact contract differs")
    pins = registration["resource_selection"]
    require(job["runner_sha256"] == pins["remote_runner_source_sha256"]
            and native["adapter_source_sha256"] == pins["adapter_source_sha256"]
            and native["authorizer_source_sha256"] == pins["authorizer_source_sha256"],
            "Installed adapter/runner/authorizer source differs")
    expected_payload = digest(canonical(dict(profile_hash=job["profile_hash"], code=job["code"],
        artifacts=job["artifacts"], wall_seconds=job["wall_seconds"], runner_sha256=job["runner_sha256"], adapter_schema=1)))
    require(job["payload_sha256"] == expected_payload, "Actual adapter payload formula mismatch")
    identity = {k: job[k] for k in ("job_id", "payload_sha256", "endpoint", "kernel_id", "session_id")}
    receipt, cloud_manifest = job["receipt"], job["manifest"]
    for record in (receipt, cloud_manifest):
        require(isinstance(record, dict) and all(record.get(k) == v for k, v in identity.items()), "Cloud receipt identity mismatch")
    require(public["cloud_receipt"] == receipt and public["cloud_execution_stopped"] is True
            and receipt.get("state") == "succeeded" and type(receipt.get("exit_code")) is int
            and receipt["exit_code"] == 0 and receipt.get("cloud_execution_stopped") is True
            and receipt.get("cloud_process_group_alive") is False, "No actual cloud stopped proof")
    cloud_bytes = native["cloud_artifact_manifest_text"].encode()
    require(parse(cloud_bytes) == cloud_manifest and digest(cloud_bytes) == receipt["artifact_manifest_sha256"]
            and len(cloud_bytes) == receipt["artifact_manifest_size"], "Raw cloud artifact manifest differs")
    entries = cloud_manifest["entries"]
    require(set(entries) == set(required_artifacts) | {"stdout", "stderr"} and not cloud_manifest["errors"]
            and public["artifacts"] == entries, "Incomplete cloud artifact set")
    fetches = native["fetches"]
    require(len(fetches) == len(entries) and {x["artifact"] for x in fetches} == set(entries), "Actual fetch roster differs")
    inventory = {}
    for fetch in fetches:
        name = safe_relative(fetch["artifact"])
        entry = entries[name]
        local = safe_relative(fetch["local_relative_path"])
        data = raw(Path(artifact_root) / local, 134217728)
        suffix = {"stdout": "/stdout.bin", "stderr": "/stderr.bin"}.get(name, "/work/" + name)
        require(entry["remote_path"] == job["remote_dir"] + suffix
                and fetch["job_id"] == job["job_id"] and fetch["verified"] is True
                and fetch["size"] == entry["size"] == len(data)
                and fetch["sha256"] == entry["sha256"] == digest(data), "Fetched artifact differs from actual manifest")
        inventory[name] = dict(bytes=len(data), sha256=digest(data), local_relative_path=local)
    return job, profile_raw, proof_raw, inventory

def verify_archive(archive, expected, paths, registration, parent):
    data = raw(archive, 134217728)
    require(len(data) == expected["bytes"] and digest(data) == expected["sha256"], "Qualification archive bytes differ")
    members = {}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        require(len(names) == len(set(names)) <= 1000 and sum(x.file_size for x in z.infolist()) <= 268435456, "Duplicate/oversized archive")
        for item in z.infolist():
            name = safe_relative(item.filename.rstrip("/") if item.is_dir() else item.filename)
            require(not stat.S_ISLNK(item.external_attr >> 16) and item.file_size <= 134217728, "Unsafe member")
            if not item.is_dir():
                blob = z.read(item)
                members[name] = dict(bytes=len(blob), sha256=digest(blob))
        require(z.testzip() is None, "Qualification archive CRC failed")
    fresh = registration["fresh_qualification"]
    mapping = dict(fresh["fresh_slots"], bundle=fresh["bundle_zip_member"], metadata=fresh["bundle_metadata_zip_member"])
    inputs = {name: paths[name] for name in (*SLOTS, "bundle")}
    inputs["metadata"] = paths["bundle"].with_suffix(".json")
    for name, path in inputs.items():
        data = raw(path, 134217728)
        require(members.get(mapping[name]) == dict(bytes=len(data), sha256=digest(data)), "Freezer input is not exact fresh named archive member: " + name)
        if name in SLOTS:
            require(digest(data) != parent["qualification_receipts"][name]["sha256"], "Historical slot relabelled fresh: " + name)
    return members

def preflight(args, paths):
    registration = amendment()
    parent = read(args.parent_plan, PARENT_SHA)
    require(parent["source_pins"] == registration["preserved_parent_source_pins"], "Wrong original42 source identity")
    manifest = read(args.qualification_manifest, args.qualification_manifest_sha256)
    fresh = registration["fresh_qualification"]
    require(manifest["request_id"] == registration["qualification_request_id"] and manifest["study_id"] == STUDY_ID
            and manifest["commands"] == fresh["commands"] and manifest["provider_timeout_seconds"] == 3000
            and sum(x["timeout_seconds"] for x in manifest["commands"]) == 2700, "Qualification commands/budget/identity differ")
    require(manifest["source_files"] == registration["qualification_source_files"]
            and manifest["source_set_sha256"] == registration["qualification_source_set_sha256"]
            and manifest["original42_source_pins"] == parent["source_pins"], "Original qualification sources changed")
    controls = manifest["control_source_files"]
    expected_controls = {x for x in registration["additional_source_paths"] if "/colab_qualification_v3/" in x}
    require(set(controls) == expected_controls, "Qualification control source roster differs")
    source_root = Path(__file__).parents[3]
    for name, row in controls.items():
        data = raw(source_root / name)
        require(row == dict(bytes=len(data), sha256=digest(data)), "Qualification control source drift")
    native = read(args.native_receipt, args.native_receipt_sha256)
    require(native["qualification_manifest_sha256"] == args.qualification_manifest_sha256, "Native/qualification manifest bridge differs")
    guard_path = registration["resource_selection"]["fixed_kernel_provider_source_path"]
    guard_sha = digest(raw(source_root / guard_path))
    require(native["fixed_kernel_provider_sha256"] == manifest["fixed_kernel_provider_sha256"] == guard_sha,
            "Native fixed-kernel provider guard differs from qualified source")
    job, profile_raw, proof_raw, inventory = verify_native(native, manifest, registration, args.artifact_root)
    root = Path(args.artifact_root)
    execution = read(root / inventory["execution.json"]["local_relative_path"])
    require(execution["schema"] == fresh["execution_schema"] and execution["request_id"] == registration["qualification_request_id"]
            and execution["status"] == "pass" and execution["source_unchanged"] is True
            and execution["worker_children_stopped"] is True
            and execution["formal_training_fits"] == 0 and execution["formal_task_dataset_reads"] == 0
            and execution["source_files"] == registration["qualification_source_files"]
            and execution["original42_source_pins"] == parent["source_pins"]
            and execution["control_source_files"] == controls, "Actual qualification execution/source differs")
    stages = execution["stages"]
    require([x["name"] for x in stages] == [x["name"] for x in fresh["commands"]], "Fresh stage roster differs")
    for stage, command in zip(stages, fresh["commands"]):
        require(stage.get("returncode") == 0 and stage.get("skipped") is False and stage.get("timeout") is False
                and stage.get("semantic_gate_pass") is True and stage.get("timeout_seconds") == command["timeout_seconds"]
                and stage.get("argv", [])[1:] == ["-B", *command["args"]], "Failed/skipped/changed actual qualification stage")
    verify_archive(root / inventory["suite-artifacts.zip"]["local_relative_path"], inventory["suite-artifacts.zip"],
                   paths, registration, parent)
    lineage = dict(provider="colab", parent_plan_sha256=PARENT_SHA, parent_study_id=parent["study_id"],
        prior_ledgers_policy="immutable", v1_fit_completion_credit=0, v2_fit_completion_credit=0,
        qualification_request_id=registration["qualification_request_id"], qualification_job_id=job["job_id"],
        fresh_qualification_native_receipt_sha256=args.native_receipt_sha256,
        qualification_identity_sha256=digest(canonical({k: job[k] for k in ("endpoint", "kernel_id", "session_id")})),
        qualification_code_sha256=job["code_sha256"], qualification_adapter_payload_sha256=job["payload_sha256"],
        qualification_manifest_sha256=args.qualification_manifest_sha256,
        qualification_profile_sha256=digest(profile_raw), qualification_profile_fingerprint=job["profile_hash"],
        binding_proof_sha256=digest(proof_raw), adapter_source_sha256=native["adapter_source_sha256"],
        authorizer_source_sha256=native["authorizer_source_sha256"],
        remote_runner_source_sha256=job["runner_sha256"], fixed_kernel_provider_sha256=guard_sha,
        amendment_sha256=digest(raw(Path(__file__).with_name("RESOURCE_AMENDMENT.json"))),
        qualification_archive={k: inventory["suite-artifacts.zip"][k] for k in ("bytes", "sha256")},
        reused_asset_only=dict(bundle_sha256=parent["bundle_sha256"], metadata_sha256=parent["bundle_metadata_sha256"], historical_qualification_credit=0),
        fresh_qualification_cost_scope="Actual fresh runtime only; retain all historical failures and costs, never sum nested intervals",
        full_physical_energy_joules=None)
    return parent, lineage

def add_prospective_pins(plan, source_root):
    for name in amendment()["additional_source_paths"]:
        require(name not in plan["source_pins"], "V3 control overwrites original source pin")
        plan["source_pins"][name] = digest(raw(Path(source_root) / safe_relative(name)))

