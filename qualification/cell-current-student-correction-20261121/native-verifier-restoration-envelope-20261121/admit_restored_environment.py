"""Pure-data admission of one actual PTY restoration; never launches or imports it."""
import hashlib
import json
import os
from pathlib import Path
import sys


PHASES = ("create_venv_without_pip", "bootstrap_exact_pip24", "install_exact_original9", "pip_check", "installed_metadata_and_pytest_import_identity")
SCOPE = "complete venv tree plus explicitly hashed external symlink file targets; host /usr,/lib,/lib64 dependency closure is not fully inventoried"


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_bound(binding, as_json=True):
    path = Path(binding["path"])
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 8388608, "bounded local original required")
    raw = path.read_bytes()
    require(len(raw) == binding["bytes"] and sha(raw) == binding["sha256"], "local original bytes changed")
    return json.loads(raw) if as_json else raw


def unwrap(value):
    if "content" not in value:
        return value
    require(value.get("isError") is not True, "MCP response is an error")
    structured = value.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    texts = [row["text"] for row in value["content"] if row["type"] == "text"]
    require(len(texts) == 1, "one original response object required")
    return json.loads(texts[0])


def write_new(path, value):
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(raw)
        while view:
            size = os.write(descriptor, view)
            require(size > 0, "short admission write")
            view = view[size:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return {"path": str(path), "bytes": len(raw), "sha256": sha(raw)}


def admit(request):
    require(request["schema"] == "hepta.native-verifier-actual-pty-admission-request.v1", "unknown admission request")
    plan_raw = read_bound(request["input_plan"], False)
    plan = json.loads(plan_raw)
    plan_sha = sha(plan_raw)
    launch = read_bound(request["frozen_launch_arguments"])
    start = unwrap(read_bound(request["actual_pty_start_raw"]))
    terminal = unwrap(read_bound(request["actual_pty_read_raw"]))
    output_info = unwrap(read_bound(request["actual_terminal_output_info_raw"]))
    stream = read_bound(request["actual_merged_stream"], False)
    require(plan["status"] == "FROZEN_READY_FOR_ROOT_SINGLE_EXECUTION" and plan["actual_launch_transport"] == "H_PERSISTENT_OPERATOR_PTY", "plan was not frozen for this transport")
    expected_argv = [plan["timeout_binary"]["path"], "--signal=TERM", "--kill-after=5s", "235s", plan["python_identity"]["path"], "-I", "-B", plan["runner_source_path"], plan["input_plan_path"], plan_sha]
    require(launch["host"] == "desktop" and [launch["executable"], *launch["args"]] == expected_argv, "frozen actual launch differs")
    require(start["host"] == terminal["host"] == "desktop" and start["session_id"] == terminal["session_id"], "actual PTY session differs")
    require(start["audit_recorded"] is True and start["automatic_retry"] is False and start["reused"] is False, "actual unique audited launch required")
    require(start["persistent_across_runtime_restart"] is True and terminal["persistent_across_runtime_restart"] is True, "actual archived PTY required")
    initial, ended = start["status"], terminal["status"]
    require(initial["state"] == "running" and ended["state"] == "exited" and ended["exit_code"] == 0, "actual PTY is not a successful terminal")
    for key in ("boot", "created_unix_ms", "owner_pid", "pid"):
        require(initial[key] == ended[key], "PTY process identity changed")
    require(terminal["storage"] == "target_archive" and terminal["output_complete"] is True and ended["output_complete"] is True and ended["capture_error"] is None, "actual PTY output incomplete")
    require(terminal["offset"] == 0 and terminal["next_offset"] == terminal["available_end"] == ended["bytes_seen"] == ended["bytes_stored"] == len(stream), "actual PTY full byte accounting differs")
    require(terminal["truncated_before_offset"] is False and terminal["text_is_lossy"] is False and terminal["utf8_pending"] is False, "actual PTY stream lost bytes")
    require(bytes.fromhex(terminal["bytes_hex"]) == stream and terminal["chunk_sha256"] == sha(stream) and terminal["text"] == stream.decode(), "actual PTY raw/text/SHA disagree")
    require(output_info["path"] == terminal["archive_path"] and output_info["size"] == len(stream) and output_info["sha256"] == sha(stream) and bool(output_info["version"]), "independent whole terminal archive size/SHA differs")
    artifacts = request["owner_originals"]
    needed = {"CLAIM.json", "PLAN.json", "EXECUTION_CONTEXT.json", "INPUTS_BEFORE.json", "INPUTS_AFTER.json", "TREE_BEFORE.json", "TREE_AFTER.json", "NATIVE_ENVIRONMENT_CANDIDATE.json", "RESULT.json", "POST_FSYNC.json"}
    require(needed <= set(artifacts), "missing primary owner originals")
    values = {name: read_bound(binding, not name.endswith((".log", ".jsonl"))) for name, binding in artifacts.items()}
    raw_owner_plan = read_bound(artifacts["PLAN.json"], False)
    require(raw_owner_plan == plan_raw, "actual owner plan differs from frozen input")
    owner = Path(plan["owner"])
    claim, context, result, post, candidate = [values[name] for name in ("CLAIM.json", "EXECUTION_CONTEXT.json", "RESULT.json", "POST_FSYNC.json", "NATIVE_ENVIRONMENT_CANDIDATE.json")]
    require(claim["outer_timeout_parent_argv"] == expected_argv and claim["identity"]["ppid"] == ended["pid"] and claim["identity"]["boot_id"] == ended["boot"], "actual runner does not belong to launched outer timeout")
    require(result["identity"] == claim["identity"] and result["owner"] == str(owner), "result belongs to another process or owner")
    require(claim["plan_sha256"] == context["plan_sha256"] == result["plan_sha256"] == post["plan_sha256"] == candidate["restoration_plan_sha256"] == plan_sha, "actual plan chain differs")
    context_sha = artifacts["EXECUTION_CONTEXT.json"]["sha256"]
    require(result["context_sha256"] == post["context_sha256"] == candidate["restoration_context_sha256"] == context_sha, "actual shared clock context differs")
    require(context["owner"] == str(owner) and context["work_deadline_monotonic"] == context["started_monotonic"] + 180 and context["final_deadline_monotonic"] == context["started_monotonic"] + 210, "shared global clock changed")
    require(int(post["after_result_fsync_unix_ns"]) >= int(claim["started_at_ns"]) >= int(ended["created_unix_ms"]) * 1000000, "actual timing order differs")
    require(post["result"] == {"path": str(owner / "RESULT.json"), "bytes": artifacts["RESULT.json"]["bytes"], "sha256": artifacts["RESULT.json"]["sha256"]}, "post does not bind actual result bytes/path")
    printed = json.dumps(post, sort_keys=True)
    require(stream in ((printed + "\n").encode(), (printed + "\r\n").encode()), "complete actual terminal does not equal printed post-fsync receipt")
    require(post["success_pending_outer"] is True and post["automatic_next_phase"] is False and post["transport_kind"] == "H_PERSISTENT_OPERATOR_PTY", "inner terminal failed")
    require(result["status"] == "OFFLINE_VERIFIER_RESTORED_PENDING_ACTUAL_PTY_TERMINAL" and result["error"] is None and result["inputs_unchanged"] is True, "restoration inner result incomplete")
    require(result["qualified_C_changes"] == result["network_http_requests"] == 0 and all(value == 0 for value in result["scientific_calls"].values()), "restoration scope changed")
    require(values["INPUTS_BEFORE.json"] == values["INPUTS_AFTER.json"], "original inputs drifted")
    require(values["TREE_BEFORE.json"] == values["TREE_AFTER.json"] and candidate["files"] == values["TREE_BEFORE.json"]["files"], "candidate seal lacks two identical complete inventories")
    require(candidate["schema"] == "hepta.readonly-native-environment.v1" and candidate["root"] == plan["venv"] and candidate["inventory_scope"] == SCOPE and candidate["host_mount_closure_complete"] is False, "candidate environment schema/scope differs")
    require(candidate["python_binary_sha256"] == plan["python_identity"]["sha256"] and candidate["two_full_passes_equal"] is True, "candidate interpreter/inventory differs")
    candidate_binding = {"path": str(owner / "NATIVE_ENVIRONMENT_CANDIDATE.json"), "bytes": artifacts["NATIVE_ENVIRONMENT_CANDIDATE.json"]["bytes"], "sha256": artifacts["NATIVE_ENVIRONMENT_CANDIDATE.json"]["sha256"]}
    require(result["environment_candidate"] == candidate_binding, "actual result does not bind candidate seal")
    require([row["phase"] for row in result["phases"]] == list(PHASES), "missing or additional installation phase")
    for phase_record in result["phases"]:
        phase = phase_record["phase"]
        prefix = "phases/" + phase + "/"
        needed_phase = {prefix + name for name in ("PARENT_RESULT.json", "CHILD_RESULT.json", "CHILD_POST_FSYNC.json", "STDOUT.log", "STDERR.log")}
        require(needed_phase <= set(artifacts), "missing actual phase originals: " + phase)
        require(values[prefix + "PARENT_RESULT.json"] == phase_record, "phase summary differs from actual parent result")
        require(phase_record["successful"] is True and phase_record["actual_wait_returncode"] == 0 and phase_record["error"] is None and phase_record["owned_group_absent_after_wait"] is True, "phase actual terminal failed or residual group unknown")
        child_post = values[prefix + "CHILD_POST_FSYNC.json"]
        child_result = values[prefix + "CHILD_RESULT.json"]
        child_binding = artifacts[prefix + "CHILD_RESULT.json"]
        require(child_post["result"] == {"path": str(owner / prefix / "CHILD_RESULT.json"), "bytes": child_binding["bytes"], "sha256": child_binding["sha256"]}, "child result binding differs")
        require(child_post["phase"] == child_result["phase"] == phase and child_post["plan_sha256"] == child_result["plan_sha256"] == plan_sha and child_post["context_sha256"] == child_result["context_sha256"] == context_sha, "child plan/clock identity differs")
        require(child_result["identity"]["ppid"] == phase_record["identity"]["pid"] and child_result["identity"]["pgrp"] == phase_record["identity"]["pgrp"] == phase_record["identity"]["pid"] and child_result["identity"]["boot_id"] == ended["boot"], "child does not belong to its actual owned timeout group")
        for key, filename in (("child_post", "CHILD_POST_FSYNC.json"), ("child_result", "CHILD_RESULT.json")):
            stored = phase_record[key]
            original = artifacts[prefix + filename]
            require(stored["path"] == str(owner / prefix / filename) and stored["bytes"] == original["bytes"] and stored["sha256"] == original["sha256"], "parent phase does not bind actual child original")
        require(child_post["success_pending_parent"] is True and child_result["status"] == "COMPLETE_PENDING_PARENT" and child_result["error"] is None, "child inner success absent")
        for name in ("stdout", "stderr"):
            raw = values[prefix + name.upper() + ".log"]
            recorded = phase_record["streams"][name]
            require(recorded["complete"] is True and len(raw) == recorded["bytes_observed"] == recorded["bytes_retained"] <= 262144 and sha(raw) == recorded["sha256"], "phase stream incomplete")
        require(values[prefix + "STDOUT.log"].endswith((json.dumps(child_post, sort_keys=True) + "\n").encode()), "actual child stdout is not bound to child post")
        if phase == PHASES[-1]:
            require(child_result["metadata_before_import"] == child_result["metadata_after_import"], "package metadata changed during identity import")
            expected = {row["package"].casefold().replace("_", "-"): (row["package_version"], row["metadata_sha256"]) for row in plan["wheels"]}
            expected["pip"] = ("24.0", plan["bootstrap_pip"]["metadata_sha256"])
            observed = {row["package"]: (row["version"], row["metadata"]["sha256"]) for row in child_result["metadata_before_import"]}
            require(len(child_result["metadata_before_import"]) == 10 and observed == expected and child_result["pytest_import"]["version"] == "9.2.0" and child_result["pytest_import"]["native_cases_executed"] == 0, "actual installed dependency closure or import-only gate differs")
    inventory_by_path = {row["path"]: row for row in result["original_artifacts"]}
    for name, binding in artifacts.items():
        if name in ("RESULT.json", "POST_FSYNC.json"):
            continue
        expected = inventory_by_path.get(str(owner / name))
        require(expected is not None and expected["bytes"] == binding["bytes"] and expected["sha256"] == binding["sha256"], "artifact differs from actual inventory: " + name)
    final = dict(candidate)
    final["qualification_status"] = "ACTUAL_RESTORATION_AND_COMPLETE_PTY_CHAIN_VERIFIED"
    final["restoration_execution"] = {"actual_transport": "H persistent operator PTY; merged terminal stream, not process_job H",
                                    "host": "desktop", "session_id": start["session_id"], "terminal_status": ended,
                                    "actual_complete_stream_sha256": sha(stream), "actual_complete_stream_bytes": len(stream),
                                    "actual_terminal_archive_full_info": output_info,
                                    "plan_sha256": plan_sha, "candidate_original": candidate_binding,
                                    "result_original": post["result"], "post_fsync_sha256": artifacts["POST_FSYNC.json"]["sha256"],
                                    "source_proof_bindings": {key: request[key] for key in ("input_plan", "frozen_launch_arguments", "actual_pty_start_raw", "actual_pty_read_raw", "actual_terminal_output_info_raw", "actual_merged_stream")},
                                    "owner_original_bindings": artifacts,
                                    "power_loss_durability": "New owner parent, evidence files/directories, venv files/directories and final receipt explicitly fsynced; terminal archive completeness observed from actual PTY. No process_job terminal flags inferred."}
    return final


if __name__ == "__main__":
    require(len(sys.argv) == 3, "expected actual admission request and new output path")
    source = Path(sys.argv[1])
    require(source.is_file() and not source.is_symlink() and source.stat().st_size <= 8388608, "bounded request file required")
    request = json.loads(source.read_bytes())
    value = admit(request)
    binding = write_new(Path(sys.argv[2]), value)
    print(json.dumps({"status": "ACTUAL_PTY_CHAIN_VERIFIED_NO_NEW_EXECUTION", "environment": binding}, sort_keys=True))
