"""Byte-bound CPU qualification from two actual producers; no model execution."""

import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

STUDY_ID = "hcsn-regenerative-mechanisms-fv-pilot-20261107-1631115f163f-cpu-v1"
SOURCE_ROOT = Path(__file__).resolve().parents[3]
HEX = re.compile(r"[0-9a-f]{64}\Z")
ARTIFACTS = {"artifact-manifest.json", "execution.json", "outer-timing.json", "source-manifest.json", "suite-artifacts.zip"}
NATIVE_FILES = {"started.json", "owner-intent.json", "child.json", "exit.json", "exit.witness.json"}
SLOTS = {"unit": "evidence/mechanism-unit-result.json", "graph_cpu": "evidence/mechanism-graph-cpu.json",
         "sequence_cpu": "evidence/sequence-cpu/receipt.json", "resolution": "evidence/resolution-s81-fixed.json",
         "fixed_renewal": "evidence/fixed-renewal-audit-s81.json", "budget": "evidence/cpu-budget/result.json"}
ENV_KEYS = ("python", "numpy", "torch", "cuda_build", "device", "cpu_threads", "deterministic_algorithms")
ALLOWED_CHANGED = {"study_id", "frozen_at", "source_pins", "qualification_receipts", "numerical_resolution",
                   "execution_environment", "runtime_feasibility_policy", "resource_migration"}


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
    canonical(value)
    return value


def raw(path, limit=67108864):
    path = Path(path).absolute()
    require(not any(p.is_symlink() for p in (path, *path.parents)), "Symlink input")
    before = path.lstat()
    version = lambda x: (x.st_dev, x.st_ino, x.st_size, x.st_mtime_ns, x.st_ctime_ns)
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= limit, "Unsafe input")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        require(version(os.fstat(stream.fileno())) == version(before), "Input changed before read")
        blob = stream.read(limit + 1)
    require(len(blob) == before.st_size and version(path.lstat()) == version(before), "Input changed during read")
    return blob


def relative(name):
    require(isinstance(name, str) and name, "Missing relative path")
    path = PurePosixPath(name)
    require(not path.is_absolute() and ".." not in path.parts and "\\" not in name
            and path.as_posix() == name and not name.endswith("/"), "Unsafe relative path")
    return name


def pinned(root, pin):
    require(set(pin) == {"path", "bytes", "sha256"}, "Incomplete evidence byte pin")
    blob = raw(Path(root) / relative(pin["path"]))
    require(len(blob) == pin["bytes"] and digest(blob) == pin["sha256"], "Evidence bytes differ")
    return blob


def read(path, expected_sha256=None):
    blob = raw(path)
    require(expected_sha256 is None or digest(blob) == expected_sha256, "Expected file SHA differs")
    return parse(blob)


def registration():
    return read(Path(__file__).with_name("RESOURCE_AMENDMENT.json"))


def account_identity(value):
    require(value.get("authenticated") is True and value.get("verification") == "official_token_introspection"
            and isinstance(value.get("username"), str) and value["username"]
            and type(value.get("user_id")) is int and value["user_id"] > 0, "Unverified provider account")
    return {key: value[key] for key in ("authenticated", "username", "user_id", "method", "scope", "verification")}


def tool_object(document, predicate):
    found = {}
    def visit(value, depth=0):
        require(depth <= 12, "Excessive tool envelope nesting")
        if isinstance(value, dict):
            if predicate(value):
                found[canonical(value)] = value
                return  # Record contents are evidence, not nested MCP envelopes.
            for key, child in value.items():
                if isinstance(child, (dict, list)):
                    visit(child, depth + 1)
                elif key in ("text", "output") and isinstance(child, str):
                    try:
                        decoded = parse(child)
                    except (ValueError, TypeError):
                        continue
                    visit(decoded, depth + 1)
        elif isinstance(value, list):
            for child in value:
                visit(child, depth + 1)
    visit(document)
    require(len(found) == 1, "Missing or ambiguous actual tool record")
    return next(iter(found.values()))


def verify_native_bridge(root, bridge, expected_request_sha256, observer_blob=None):
    require(set(bridge) == {"request", "start", "terminal", "native_readback", "files"}
            and set(bridge["files"]) == NATIVE_FILES, "Incomplete native bridge")
    request_blob = pinned(root, bridge["request"])
    require(digest(request_blob) == expected_request_sha256, "Native launch request is not the reviewed request")
    request = parse(request_blob)
    start = tool_object(parse(pinned(root, bridge["start"])), lambda x: isinstance(x.get("job"), dict))["job"]
    terminal = tool_object(parse(pinned(root, bridge["terminal"])), lambda x: "job_id" in x and "state" in x)
    require(start["launch_state"] == "launched" and start["id"] == terminal["job_id"]
            and all(start[k] == request[k] for k in ("executable", "args", "host", "idempotency_key"))
            and start.get("env_keys") == [], "Actual native launch differs")
    require(terminal["state"] == "succeeded" and terminal["exit_code"] == 0
            and terminal["timed_out"] is False and terminal["cancelled"] is False
            and terminal["output_complete"] is True and terminal["output_durable"] is True
            and terminal["terminal_publication_confirmed"] is True, "Actual native terminal incomplete")
    snapshot = tool_object(parse(pinned(root, bridge["native_readback"])),
                           lambda x: isinstance(x.get("files"), list) and "snapshot_scope" in x)
    require(snapshot.get("truncated") is False, "Truncated native readback")
    rows = {row["path"]: row for row in snapshot["files"]}
    require(len(rows) == len(snapshot["files"]), "Duplicate native readback path")
    values, blobs = {}, {}
    for name, pin in bridge["files"].items():
        blob = pinned(root, pin)
        row = rows.get(start["remote_job_dir"].rstrip("/") + "/" + name, {})
        require(row.get("eof") is True and row.get("size") == len(blob)
                and row.get("sha256") == digest(blob) and row.get("text", "").encode() == blob,
                "Native five-file bytes lack their actual readback bridge")
        blobs[name], values[name] = blob, parse(blob)
    started, exit_, witness, child = (values[n] for n in ("started.json", "exit.json", "exit.witness.json", "child.json"))
    require(started == values["owner-intent.json"] and started["job_id"] == exit_["job_id"] == witness["job_id"] == start["id"]
            and started["launch_nonce"] == exit_["launch_nonce"] == witness["launch_nonce"] == terminal["launch_nonce"]
            and witness["exit_sha256"] == digest(blobs["exit.json"]), "Native owner/exit witness mismatch")
    require(exit_["exit_code"] == 0 and exit_["timed_out"] is False and exit_["cancelled"] is False
            and exit_["output_complete"] is True and exit_["output_durable"] is True
            and child["pid"] > 0 and child["identity"]["kind"] == "proc_start_ticks", "Native child/exit proof incomplete")
    if observer_blob is not None:
        require(any(row.get("eof") is True and row.get("size") == len(observer_blob)
                    and row.get("sha256") == digest(observer_blob) and row.get("text", "").encode() == observer_blob
                    for row in rows.values()), "Observer lacks an actual native byte readback")
    return {"request_sha256": digest(request_blob), "exit_sha256": digest(blobs["exit.json"])}


def archive_members(blob):
    result = {}
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)) <= 4096
                and sum(x.file_size for x in archive.infolist()) <= 67108864, "Duplicate or oversized archive")
        for info in archive.infolist():
            name = relative(info.filename)
            require(not info.is_dir() and not stat.S_ISLNK(info.external_attr >> 16), "Unsafe ZIP member")
            result[name] = archive.read(name)
        require(archive.testzip() is None, "Archive CRC failure")
    return result


def verify_provider_source(root, source, role, reg, control_manifest):
    require(set(source) == {"prepared_manifest", "observer", "artifacts", "native"}
            and set(source["artifacts"]) == ARTIFACTS and set(source["native"]) == {"submit", "observer"}, "Source inventory differs")
    manifest_blob, observer_blob = pinned(root, source["prepared_manifest"]), pinned(root, source["observer"])
    manifest, observer = parse(manifest_blob), parse(observer_blob)
    if role == "budget":
        expected = reg["external_budget"]
        require(digest(manifest_blob) == expected["prepared_manifest_sha256"]
                and digest(observer_blob) == expected["observer_sha256"], "Original budget identity differs")
        launch_pins = expected["native_launch_request_sha256"]
        schema = "hcsn-kaggle-cpu-feasibility-native-observer-v1"
    else:
        require(digest(manifest_blob) == control_manifest["qualification_prepared_manifest_sha256"], "Qualification manifest differs")
        launch_pins = control_manifest["qualification_launch_request_sha256"]
        schema = "hcsn-kaggle-cpu-qualification-native-observer-v1"
    expected_request = reg["external_budget"]["request_id_sha256"] if role == "budget" else reg["qualification_request_id_sha256"]
    require(digest(manifest["request_id"].encode()) == expected_request, "Unregistered qualification request")
    require(observer["schema"] == schema and observer["status"] == "terminal_artifact_readback_verified"
            and observer["no_new_submission"] is True and observer["remote_terminal_observed"] is True
            and observer["payload_sha256"] == manifest["payload"]["sha256"]
            and observer["prepared_manifest_sha256"] == digest(manifest_blob), "Incomplete actual provider observation")
    native = {phase: verify_native_bridge(root, source["native"][phase], launch_pins[phase],
                                        observer_blob if phase == "observer" else None) for phase in ("submit", "observer")}
    latest, producer = observer["latest_remote"], observer["bound_producer"]
    account_identity(latest["account"])
    require(latest["request_id"] == observer["request_id"] == manifest["request_id"]
            and latest["remote_state"] == "COMPLETE" and latest["submission_state"] == "ACCEPTED"
            and latest["identity_verified"] is True and latest["remote_effect_unknown"] is False
            and {k: latest[k] for k in producer} == producer and producer["notebook_version"] == 1, "Actual producer is not fixed and complete")
    intent = latest["intent"]
    require(intent["source_sha256"] == manifest["payload"]["sha256"] and intent["accelerator"] == "cpu"
            and intent["timeout_seconds"] == 3000 and intent["internet"] is False
            and all(intent[k] == [] for k in ("dataset_sources", "model_sources", "competition_sources")), "Unexpected actual provider inputs or budget")
    require(manifest["source_files"] == reg["scientific_source_files"]
            and manifest["source_set_sha256"] == reg["scientific_source_set_sha256"]
            and manifest["input_files"] == reg["fixed_input_files"], "Original source/input identity changed")
    artifact = observer["artifacts"]
    require(artifact["remote_manifest_verified"] is True and artifact["request_id"] == latest["request_id"]
            and all(artifact[k] == producer[k] for k in ("input_digest", "notebook_ref", "notebook_version")), "Artifacts belong to another producer")
    rows = {row["path"]: row for row in artifact["files"]}
    require(len(rows) == len(artifact["files"]) and set(rows) == ARTIFACTS, "Incomplete actual artifact inventory")
    blobs = {}
    for name in ARTIFACTS:
        blob, row = pinned(root, source["artifacts"][name]), rows[name]
        require(len(blob) == row["bytes"] == row["http_content_length"] and digest(blob) == row["sha256"]
                and row["http_content_length_verified"] is True, "Artifact bytes/HTTP length differ")
        blobs[name] = blob
    raw_manifest = parse(blobs["artifact-manifest.json"])
    declared = {row["path"]: row for row in raw_manifest["files"]}
    require(raw_manifest["request_id"] == latest["request_id"] and len(declared) == len(raw_manifest["files"])
            and set(declared) == ARTIFACTS - {"artifact-manifest.json"}, "Actual cloud artifact manifest differs")
    for name, pin in declared.items():
        require(pin["bytes"] == len(blobs[name]) and pin["sha256"] == digest(blobs[name]), "Cloud artifact manifest hash mismatch")
    members = archive_members(blobs["suite-artifacts.zip"])
    require(observer["artifact_sha256"] == digest(blobs["suite-artifacts.zip"])
            and observer["artifact_bytes"] == len(blobs["suite-artifacts.zip"])
            and observer["archive_members"] == {k: {"bytes": len(v), "sha256": digest(v)} for k, v in members.items()}, "Archive member readback differs")
    for name in ("execution.json", "source-manifest.json"):
        require(members[name] == blobs[name], "Separate and archived evidence differ")
    execution, sources = parse(blobs["execution.json"]), parse(blobs["source-manifest.json"])
    require(execution == observer["execution"] and execution["request_id"] == latest["request_id"]
            and execution["status"] == "pass" and execution["source_unchanged"] is True
            and execution["fixed_input_unchanged"] is True and execution["formal_training_fits"] == 0
            and execution["formal_task_optimizer_updates"] == 0 and execution["task_datasets_read"] is False,
            "Provider completion is not a successful scientific execution")
    source_key = "files" if role == "budget" else "source_files"
    require(execution["source_files"] == sources[source_key] == reg["scientific_source_files"]
            and execution["source_set_sha256"] == sources["source_set_sha256"] == reg["scientific_source_set_sha256"], "Actual source map differs")
    for name, pin in reg["fixed_input_files"].items():
        require(len(members[name]) == pin["bytes"] and digest(members[name]) == pin["sha256"], "Actual fixed input bytes differ")
    commitment = digest(canonical({"producer": producer, "account": latest["account"]}))
    public = {"producer_commitment_sha256": commitment, "request_id_sha256": digest(latest["request_id"].encode()),
              "payload_sha256": manifest["payload"]["sha256"], "prepared_manifest_sha256": digest(manifest_blob),
              "native_observer_sha256": digest(observer_blob), "native_bridges": native,
              "archive": {"bytes": len(blobs["suite-artifacts.zip"]), "sha256": digest(blobs["suite-artifacts.zip"])} }
    return {"manifest": manifest, "observer": observer, "execution": execution, "members": members,
            "producer": producer, "account": latest["account"], "intent": intent, "public": public}


def verify_budget_record(result, stage, journal, checkpoint, reg):
    expected = {"status": "completed", "device": "cpu", "optimizer_updates_completed": 400, "updates_registered": 400,
                "state_count": 81, "expected_parameter_count": 2890, "sequence_length": 64, "batch_size": 64,
                "data_seed": 931117, "initialization_seed": 931119, "validation_seed": 931123, "batch_order_seed": 931127,
                "learning_rate": .003, "formal_training_fits": 0, "task_datasets_read": False, "task_gain_established": False}
    require(all(result.get(k) == v for k, v in expected.items()), "Original full400 non-task budget definition changed")
    wall = result.get("wall_seconds")
    require(type(wall) in (int, float) and math.isfinite(wall) and 0 <= wall < 450
            and result["within_480_second_probe_window"] is True, "Original budget time gate failed")
    require(stage["returncode"] == 0 and stage["timed_out"] is False and stage["timeout_seconds"] == 540
            and stage["child_wait_completed"] is True and stage["owned_process_group_alive"] is False
            and stage["worker_children_stopped"] is True and stage["pid"] == stage["pgid"], "Budget child is not proven stopped")
    require(result["source_pins"] == reg["external_budget"]["probe_source_pins"]
            and result["bundle_sha256"] == reg["bundle_sha256"] and result["bundle_metadata_sha256"] == reg["bundle_metadata_sha256"], "Budget source/input differs")
    require({k: result["environment"][k] for k in ENV_KEYS} == reg["cpu_execution_environment"], "CPU budget environment differs")
    events = [parse(line) for line in journal.splitlines()]
    updates = [x for x in events if x.get("event") == "non_task_optimizer_update_completed"]
    validation = [x for x in events if x.get("event") == "evaluation_batch_completed"]
    terminal = [x for x in events if x.get("event") == "non_task_probe_terminal"]
    require([x.get("update") for x in updates] == list(range(1, 401)) and all(x.get("examples") == 64 for x in updates), "Incomplete or duplicated budget updates")
    require(len(events) == 409 and len(validation) == 8 and all(x["count"] == 64 and x["phase"] == "non_task_validation" for x in validation)
            and [x["cumulative_examples"] for x in validation] == list(range(64, 513, 64))
            and result["validation"]["count"] == 512 and len(terminal) == 1 and events[-1] == terminal[0]
            and terminal[0]["status"] == "completed", "Budget validation/terminal journal differs")
    require(digest(checkpoint) == result["checkpoint_sha256"], "Budget checkpoint bytes differ")


def verify_cpu_stages(execution, manifest, reg):
    commands = parse(canonical(reg["qualification_commands"]).replace(b"{request_id}", manifest["request_id"].encode()))
    require(manifest["commands"] == commands and sum(x["timeout_seconds"] for x in commands) == 1440
            and manifest["provider_timeout_seconds"] == 3000, "CPU command roster or budget changed")
    require(execution["schema"] == "hcsn-kaggle-cpu-qualification-execution-v1" and execution["study_id"] == STUDY_ID
            and execution["worker_children_stopped"] is True and len(execution["stages"]) == 8
            and execution["external_budget_optimizer_updates_rerun"] == 0, "CPU qualification incomplete")
    for row, command in zip(execution["stages"], commands):
        require(row["name"] == command["name"] and row["argv"][1:] == ["-B", *command["args"]]
                and row["returncode"] == 0 and row["timeout"] is False and row["skipped"] is False
                and row["semantic_gate_pass"] is True and row["child_execution_stopped"] is True
                and row["timeout_seconds"] == command["timeout_seconds"], "CPU stage changed, failed, skipped or not stopped")


def compare_scientific_parent(parent, child):
    require(set(parent) == set(child), "Unregistered plan top-level field")
    for key in set(parent) - ALLOWED_CHANGED:
        require(parent[key] == child[key], "Scientific, statistical or fit-budget field changed: " + key)
    policy = dict(parent["runtime_feasibility_policy"], provider="kaggle", execution_gpu_index=None)
    require(child["runtime_feasibility_policy"] == policy, "Only declared CPU provider/device policy differences are allowed")


def preflight(args):
    reg = registration()
    parent = read(args.parent_plan, reg["numerical_parent_plan_sha256"])
    require(parent["source_pins"] == reg["preserved_parent_source_pins"], "Wrong numerical parent source identity")
    controls = read(args.final_control_manifest, args.final_control_manifest_sha256)
    require(controls["schema"] == "hcsn-s81-cpu-final-controls-v1" and controls["status"] == "READY_FOR_FREEZE"
            and controls["study_id"] == STUDY_ID and set(controls["source_pins"]) == set(reg["additional_source_paths"])
            and controls["control_test_receipts"] and HEX.fullmatch(controls["independent_control_review_sha256"]), "Final reviewed CPU controls are not ready")
    require(all(HEX.fullmatch(x["sha256"]) for x in controls["control_test_receipts"]), "Missing control-test receipt identity")
    pins = dict(reg["retained_source_pins"], **controls["source_pins"])
    require(len(pins) == 93 and all(digest(raw(SOURCE_ROOT / relative(k))) == v for k, v in pins.items()), "Registered93 sources differ")
    index = read(args.evidence_index, args.evidence_index_sha256)
    require(index["schema"] == "hcsn-s81-cpu-qualification-evidence-index-v1" and index["study_id"] == STUDY_ID
            and set(index["sources"]) == {"budget", "qualification"} and set(index["slots"]) == set(SLOTS), "Two-producer six-slot evidence index required")
    sources = {role: verify_provider_source(args.artifact_root, index["sources"][role], role, reg, controls) for role in ("budget", "qualification")}
    budget, qualification = sources["budget"], sources["qualification"]
    require(digest(raw(args.qualification_manifest)) == args.qualification_manifest_sha256
            == controls["qualification_prepared_manifest_sha256"] == index["sources"]["qualification"]["prepared_manifest"]["sha256"], "Qualification manifest/index/final-control bridge differs")
    require(read(args.qualification_manifest) == qualification["manifest"], "Different qualification manifest supplied")
    require(account_identity(budget["account"]) == account_identity(qualification["account"]) and budget["intent"]["kernel_sources"] == []
            and qualification["intent"]["kernel_sources"] == [budget["producer"]["notebook_ref"]], "Unexpected external input producer")
    records, slot_pins = {}, {}
    for slot, member in SLOTS.items():
        binding, role = index["slots"][slot], "budget" if slot == "budget" else "qualification"
        require(set(binding) == {"source_id", "member", "bytes", "sha256"} and binding["source_id"] == role
                and binding["member"] == member, "Slot provenance or member changed")
        blob = sources[role]["members"][member]
        require(len(blob) == binding["bytes"] and digest(blob) == binding["sha256"], "Slot bytes differ from actual producer archive")
        records[slot], slot_pins[slot] = parse(blob), dict(binding)
    members, execution = budget["members"], budget["execution"]
    require(records["budget"] == execution["probe_result"] and digest(members[SLOTS["budget"]]) == reg["external_budget"]["result"]["sha256"]
            and budget["public"]["archive"] == reg["external_budget"]["archive"], "Budget original bytes relabelled")
    verify_budget_record(records["budget"], execution["stage"], members["evidence/cpu-budget/journal.jsonl"],
                         members["evidence/cpu-budget/probe-checkpoint.pt"], reg)
    manifest, execution = qualification["manifest"], qualification["execution"]
    verify_cpu_stages(execution, manifest, reg)
    for field, names in (("control_source_files", reg["qualification_source_paths"]),
                         ("reused_control_source_files", reg["reused_control_source_paths"])):
        expected = {p: {"bytes": len(raw(SOURCE_ROOT / p)), "sha256": pins[p]} for p in names}
        require(manifest[field] == execution[field] == expected, "CPU control dependency source map differs")
    require(execution["input_files"] == reg["fixed_input_files"], "CPU qualification inputs differ")
    external = manifest["external_budget"]
    require(execution["external_budget_reference"] == external
            and external["prepared_manifest_sha256"] == reg["external_budget"]["prepared_manifest_sha256"]
            and external["observer_sha256"] == reg["external_budget"]["observer_sha256"]
            and external["archive"] == reg["external_budget"]["archive"]
            and external["result"] == reg["external_budget"]["result"], "External fresh budget reference changed")
    mount = execution["mounted_external_budget_input"]
    require(mount["verified"] is True and mount["producer_ref"] == budget["producer"]["notebook_ref"]
            and mount["notebook_version"] == 1 and mount["bytes"] == reg["external_budget"]["archive"]["bytes"]
            and mount["sha256"] == reg["external_budget"]["archive"]["sha256"]
            and mount["members"] == budget["observer"]["archive_members"] and mount["repeated_optimizer_updates"] == 0,
            "Actual mounted external budget bytes/producer differ")
    cpu_provider = dict(account_selector=budget["manifest"]["account_selector"],
                        expected_username=budget["account"]["username"], expected_user_id=budget["account"]["user_id"],
                        accelerator="cpu", internet=False, is_private=True, mode="batch", timeout_seconds=3000)
    qualified_input = dict(request_id=manifest["request_id"], **qualification["producer"], archive_name="suite-artifacts.zip",
                           archive_bytes=qualification["public"]["archive"]["bytes"],
                           archive_sha256=qualification["public"]["archive"]["sha256"],
                           bundle_member=reg["bundle_member"], metadata_member=reg["metadata_member"])
    qualified_input.pop("input_digest")
    public = {"schema": "hcsn-s81-cpu-resource-lineage-v1", "provider": "kaggle",
              "parent_plan_sha256": reg["numerical_parent_plan_sha256"], "numerical_parent_plan_sha256": reg["numerical_parent_plan_sha256"],
              "qualification_manifest_sha256": args.qualification_manifest_sha256,
              "cpu_provider_commitment": digest(canonical(cpu_provider)), "qualified_input_commitment": digest(canonical(qualified_input)),
              "published_parent_commit": reg["published_parent_commit"], "registration_sha256": digest(raw(Path(__file__).with_name("RESOURCE_AMENDMENT.json"))),
              "final_control_manifest_sha256": args.final_control_manifest_sha256, "evidence_index_sha256": args.evidence_index_sha256,
              "sources": {k: v["public"] for k, v in sources.items()}, "slots": slot_pins,
              "external_budget_optimizer_updates": 400, "external_budget_wall_seconds": records["budget"]["wall_seconds"],
              "external_budget_repeated": False, "actual_new_qualification_stages": 8,
              "prior_failed_resource_attempts_preserved": True, "prior_fit_completion_credit": 0,
              "full_physical_energy_joules": None, "provider_charges": None,
              "cost_scope": "Two actual producers; the original budget400 is counted once. Do not add nested intervals."}
    return {"registration": reg, "parent": parent, "source_pins": pins, "records": records,
            "slot_pins": slot_pins, "sources": sources, "lineage": public}
