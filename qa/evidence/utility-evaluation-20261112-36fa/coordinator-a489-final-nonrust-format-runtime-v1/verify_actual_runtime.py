import base64
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONTROL = "/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-nonrust-format-v1/"
RUN = CONTROL + "run/"
JOB = "1a1d4a979d9-392-50f"
KEY = "hepta-utility-36fa-provider-coordinator-a489-final-nonrust-format-v1"
PIN_KEYS = ("bytes", "sha256", "git_blob")


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def jread(name):
    return json.loads((ROOT / name).read_bytes())


def save(name, raw):
    p = ROOT / name
    if p.exists():
        assert p.read_bytes() == raw, name
    else:
        with p.open("xb") as out:
            out.write(raw)


def sdk_body(name):
    outer = jread(name)
    assert not outer.get("isError"), name
    texts = [x["text"] for x in outer["content"] if x.get("type") == "text"]
    assert len(texts) == 1
    return json.loads(texts[0])


artifacts = jread("ARTIFACTS.json")
assert len(artifacts["files"]) == len({x["name"] for x in artifacts["files"]}) == 210
expected = {RUN + x["name"]: (x["name"], x) for x in artifacts["files"]}
core_index = {x["name"]: x for x in jread("CORE_PUBLISH_INDEX.json")["files"]}
for name in ("RESULT.json", "ARTIFACTS.json"):
    expected[RUN + name] = (name, core_index[name])
expected[CONTROL + "STAGING_READBACK.json"] = ("STAGING_READBACK.json", core_index["STAGING_READBACK.json"])
staging = jread("STAGING_READBACK.json")
assert staging["format"] == "hepta-final-nonrust-format-bootstrap-readback-v1"
assert staging["qualification"] is False and staging["source_writes_during_staging"] is False
assert len(staging["files"]) == 7
for item in staging["files"]:
    assert item["path"].startswith(CONTROL) and "/" not in item["path"][len(CONTROL):]
    expected[item["path"]] = (item["path"][len(CONTROL):], item)

groups = defaultdict(list)
sdk_names = sorted(x.name for x in ROOT.iterdir()
                   if re.fullmatch(r".+\.READ_[0-9]+\.original\.json", x.name))
for name in sdk_names:
    response = sdk_body(name)
    assert response["path"] in expected, name
    chunk = base64.b64decode(response["data_base64"], validate=True)
    assert len(chunk) == response["next_offset"] - response["offset"]
    assert hashlib.sha256(chunk).hexdigest() == response["chunk_sha256"]
    groups[response["path"]].append((response["offset"], response, chunk, name))

reads = []
for path, observations in sorted(groups.items()):
    name, identity = expected[path]
    observations.sort(key=lambda x: x[0])
    offset = 0
    version = observations[0][1]["version"]
    chunks = []
    identities = []
    for number, (start, response, chunk, sdk_name) in enumerate(observations):
        assert start == offset and response["version"] == version
        assert response["size"] == identity["bytes"]
        offset = response["next_offset"]
        assert response["eof"] == (number == len(observations) - 1 and offset == identity["bytes"])
        chunks.append(chunk)
        identities.append({"sdk": sdk_name, "sdk_identity": pin((ROOT / sdk_name).read_bytes()),
                           "offset": start, "next_offset": offset, "chunk_sha256": response["chunk_sha256"],
                           "version": version, "eof": response["eof"]})
    raw = b"".join(chunks)
    assert offset == identity["bytes"]
    assert pin(raw) == {k: identity[k] for k in PIN_KEYS}, name
    save(name, raw)
    reads.append({"native_path": path, "local_name": name, **pin(raw),
                  "native_full_file_read": True, "version": version, "observations": identities})

approval = jread("ROOT_EXACT_APPROVAL.original.json")
request_raw = (ROOT / "ACTUAL_PROCESS_INPUT.original.json").read_bytes()
request = json.loads(request_raw)
assert pin(request_raw) == {k: approval["exact_request"][k] for k in PIN_KEYS}
assert set(request) == {"args", "cwd", "executable", "host", "idempotency_key", "stdin", "timeout_seconds"}
assert request["host"] == "desktop" and request["cwd"] == "/home/qian-qi"
assert request["executable"] == "/usr/bin/python3" and request["timeout_seconds"] == 2100
assert request["idempotency_key"] == KEY and request["args"][:2] == ["-B", "-c"]
assert len(request["args"]) == 3
assert request["args"][2].encode() == (ROOT / "ACTUAL_BOOTSTRAP.py").read_bytes()
argv = jread("ACTUAL_BOOTSTRAP_ARGV.json")
assert argv == [request["executable"], *request["args"]]
for item in staging["files"]:
    if item["path"] == CONTROL + "ACTUAL_BOOTSTRAP_PAYLOAD.json":
        assert pin(request["stdin"].encode()) == {k: item[k] for k in PIN_KEYS}

admission = sdk_body("MAIN_ADMISSION.original.json")
assert admission["audit_recorded"] and not admission["local_record_pending"] and not admission["reused"]
assert admission["launch"]["ok"] is True
job = admission["job"]
assert job["id"] == JOB and job["launch_state"] == "launched" and job["launch_error"] is None
for field in ("args", "cwd", "executable", "host", "idempotency_key"):
    assert job[field] == request[field]
assert job["env_keys"] == []
normal = sdk_body("STATUS_02.original.json")
assert normal["job_id"] == JOB and normal["state"] == "succeeded" and normal["exit_code"] == 0
assert all(normal[x] is False for x in ("automatic_retry", "cancelled", "timed_out"))
assert all(normal[x] is True for x in ("output_complete", "output_durable", "terminal_publication_confirmed"))
assert normal["log_errors"] == {"stdout": None, "stderr": None}
assert normal["log_synced"] == {"stdout": True, "stderr": True}
assert normal["log_truncated"] == {"stdout": False, "stderr": False}
stream = sdk_body("STREAM_01.original.json")
assert stream["job_id"] == JOB
stream_rows = []
for name, size in (("stdout", 1298), ("stderr", 0)):
    row = stream[name]
    raw = bytes.fromhex(row["bytes_hex"])
    assert raw == row["text"].encode() and len(raw) == size
    assert row["offset"] == 0 and row["next_offset"] == row["size"] == size and row["eof"]
    assert normal["log_bytes"][name] == {"seen": size, "stored": size}
    assert raw == (ROOT / (name.upper() + ".complete.original.txt")).read_bytes()
    stream_rows.append({"stream": name, **pin(raw), "complete_offset_coverage": [0, size]})

result = jread("RESULT.json")
assert result["format"] == "hepta-reviewed-nonrust-final-format-result-v1"
assert result["status"] == "APPLIED_AND_FORMATTED_REVIEW_REQUIRED"
assert result["actual_maintenance_job"] == "1a1d47cebc8-392-41e"
assert result["source_commit"] == "d25675445c39f76db69a7bd8e71a1a72e1cd5b9f"
assert result["source_tree"] == "a489b394666b8141840275128a780605b024cde0"
assert result["parents"] == ["cc57c7198db6293ccca562253c42fffbe2a04633"]
assert result["fix_dispatched"] is False and result["test_commands_dispatched"] == 0
assert result["qualification"] is False and result["source_ref_updates"] is False
assert result["automatic_retry"] is False and result["freeze_approved"] is False
assert result["attempted_commands"] == ["fmt"] and result["not_run_commands"] == []
assert result["formatter_changed_paths"] == [] and result["format_source_stable"]
assert result["requires_fence_refresh_review"] is False
assert result["git_metadata_unchanged"] and result["nonrust_application_complete"]
assert len(result["stages"]) == 1
stage = result["stages"][0]
assert stage == jread("fmt.terminal.json")
assert stage["argv"] == ["just", "fmt", "--base", "c0f78493f815780f68b9bf5e390a21314d79311f"]
assert stage["name"] == "fmt" and stage["timeout_seconds"] == 900 and stage["test_command"] is False
assert stage["command_returned"] and stage["maximum_log_bytes"] == 67108864
execution = jread("fmt.execute_logged.original.json")
assert stage["execution"] == execution
assert execution["returncode"] == 0 and execution["timed_out"] is False
assert execution["output_limit_exceeded"] is False and execution["log_bytes"] == 0
assert execution["log_sha256"] == hashlib.sha256((ROOT / "fmt.raw.log").read_bytes()).hexdigest()
empty = jread("fmt.after.postimages.json")
assert empty["changes"] == []
assert empty["base_inventory_sha256"] == empty["after_inventory_sha256"] == result["actual_final_source"]["inventory"]["sha256"]
assert result["application"] == result["actual_final_source"]
assert result["actual_final_source"]["complete"]
assert result["actual_final_source"]["postimages"]["all_actual_physical_tree"] == "8ebb37e523ad3932a58cf016af0a9f4e0eeb6638"
assert result["actual_final_source"]["postimages"]["all_actual_physical_leaf_count"] == 15243
assert result["actual_final_source"]["postimages"]["change_count"] == 4
audits = {x["check"]: x for x in result["final_audits"]}
assert set(audits) == {"actual_complete_source_and_git", "original_inputs", "same_source_coordination_lock"}
assert all(x["status"] == "verified" for x in audits.values())
assert audits["actual_complete_source_and_git"]["complete_final_source"] == result["actual_final_source"]
assert audits["original_inputs"]["unchanged"] and audits["original_inputs"]["input_count"] == 28

packet = json.loads(Path("/tmp/hepta-36fa-a489-maintenance-nonrust-apply-packet-v1/NONRUST_PACKET.json").read_bytes())
assert result["applied_paths"] == [x["path"] for x in packet["changes"]]
applications = []
for number, change in enumerate(packet["changes"], 1):
    name = "APPLY.%03d" % number
    attempt = jread(name + ".attempt.json")
    temporary = jread(name + ".temporary.json")
    completed = jread(name + ".completed.json")
    assert attempt["path"] == completed["path"] == temporary["source"] == change["path"]
    assert attempt["before"] == change["before"] and attempt["after"] == completed["after"] == change["after"]
    assert attempt["status"] == "attempted" and attempt["rollback"] is False
    assert completed["status"] == "observed_complete"
    applications.append({"path": change["path"], "before": attempt["before"], "after": completed["after"],
                         "attempt": pin((ROOT / (name + ".attempt.json")).read_bytes()),
                         "temporary": pin((ROOT / (name + ".temporary.json")).read_bytes()),
                         "completed": pin((ROOT / (name + ".completed.json")).read_bytes())})

git_names = ["SOURCE_GIT_STATE.before.json", "apply.after.git-state.json", "fmt.after.git-state.json", "final.git-state.json"]
git_raw = (ROOT / git_names[0]).read_bytes()
assert all((ROOT / x).read_bytes() == git_raw for x in git_names)
metadata_names = ["SOURCE_GIT_METADATA.before.json", "SOURCE_GIT_METADATA.after.json"]
metadata_raw = (ROOT / metadata_names[0]).read_bytes()
assert (ROOT / metadata_names[1]).read_bytes() == metadata_raw
commands = jread("READONLY_COMMANDS.json")
assert len(commands) == 38 and all(x["returncode"] == 0 for x in commands)
inputs = jread("INPUT_IDENTITIES.json")
assert len(inputs) == 28
for item in staging["files"]:
    if item["path"] in inputs:
        assert inputs[item["path"]] == {k: item[k] for k in PIN_KEYS}
for name in ("BUILD_PROCESS_PREFLIGHT.json", "APPLY.process-preflight.json", "fmt.process-preflight.json"):
    guard = jread(name)
    assert guard["active_matching_processes"] == [] and guard["unreadable_matching_processes"] == []
lease = jread("SOURCE_COORDINATION_EX.json")
assert lease["lock_acquired"] == "LOCK_EX|LOCK_NB"
assert lease["device"] == 2050 and lease["inode"] == 50139448
assert lease["uid"] == 1000 and lease["mode"] == 384 and lease["nlink"] == 1

report = {
    "format": "actual-final-nonrust-format-receipt-closure-v1",
    "job_id": JOB, "idempotency_key": KEY, "engineering_approval": pin((ROOT / "ROOT_EXACT_APPROVAL.original.json").read_bytes()),
    "request": pin(request_raw), "supervisor": pin((ROOT / "STATUS_02.original.json").read_bytes()),
    "result": pin((ROOT / "RESULT.json").read_bytes()), "artifacts": pin((ROOT / "ARTIFACTS.json").read_bytes()),
    "sdk_count": len(sdk_names), "native_full_read_path_count": len(reads), "native_reads": reads,
    "streams": stream_rows, "source_applications": applications,
    "formatter_command_count": 1, "formatter_timeout_seconds": 900, "formatter_returncode": 0,
    "formatter_changed_paths": [], "source_git_state_four_paths_fullbytes_equal": {"paths": git_names, **pin(git_raw)},
    "source_git_metadata_before_after_fullbytes_equal": {"paths": metadata_names, **pin(metadata_raw)},
    "readonly_commands_observed_zero": 38, "final_input_identities": 28,
    "actual_final_source": result["actual_final_source"], "final_audits": result["final_audits"],
    "large_transition_and_inventory_scope": "Producer pins are actual. Full bytes recovered separately by ordinary_path against all raw/gzip/part identities; no second full native download claimed here.",
    "staging_large_input_scope": "Original exact request and producer full readback plus final input hashes bind the payload and NONRUST_PACKET; these two large staged files were not downloaded again.",
    "original_binary_read_errors_in_this_frozen_window": 0,
    "local_review_failure_preserved": "LOCAL_DECODE_CALL_FAILURE_01.original.json; exact-filename correction excludes Git SDK wrappers; no native operation repeated.",
    "qualification": False, "behavioral_tests": 0, "fix_dispatched": False,
    "canonical_alignment_dispatched": False, "source_ref_updated": False,
    "claim_boundary": "Receipt closure for this single engineering operation; not full source/native qualification or runtime authority."
}
raw = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
save("ACTUAL_RUNTIME_READBACK_REVIEW.json", raw)
print(json.dumps({"review": pin(raw), "sdk_count": len(sdk_names), "native_full_read_paths": len(reads), "qualification": False}))
