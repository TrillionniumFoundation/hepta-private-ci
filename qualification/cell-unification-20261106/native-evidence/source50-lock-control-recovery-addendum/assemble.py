#!/usr/bin/env python3
"""Offline, create-only attachment of late source50 lock/tool controller originals."""
from __future__ import annotations
import argparse
import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath

def require(value, message):
    if not value:
        raise ValueError(message)

def pin(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }

def json_bytes(obj):
    return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode()

def safe_path(root, relative):
    path = PurePosixPath(relative)
    require(not path.is_absolute() and all(x not in ("", ".", "..") for x in path.parts), "unsafe path")
    result = root.joinpath(*path.parts)
    for ancestor in [result, *result.parents]:
        if ancestor == root:
            break
        require(not ancestor.is_symlink(), "symlink path")
    return result

def unpack_tool(obj):
    require(not obj.get("isError", False), "tool error")
    if obj.get("structuredContent") is not None:
        return obj["structuredContent"]
    texts = [x["text"] for x in obj["content"] if x["type"] == "text"]
    require(len(texts) == 1, "ambiguous tool text")
    return json.loads(texts[0])

def terminal(obj, job, code, state, timed_out):
    require(obj["job_id"] == job and obj["exit_code"] == code and obj["state"] == state, "terminal identity/result")
    require(obj["timed_out"] is timed_out, "timeout mismatch")
    for field in ("audit_recorded", "output_complete", "output_durable", "terminal_publication_confirmed"):
        require(obj[field] is True, "incomplete terminal " + field)
    for field in ("automatic_retry", "cancelled"):
        require(obj[field] is False, "unexpected terminal flag " + field)
    for stream in ("stdout", "stderr"):
        require(obj["log_errors"][stream] is None, "log error")
        require(obj["log_truncated"][stream] is False and obj["log_synced"][stream] is True, "log not closed")
        require(obj["log_bytes"][stream]["seen"] == obj["log_bytes"][stream]["stored"], "log byte loss")

def read_stream(obj, stream, job, offset, end):
    require(obj["audit_recorded"] is True and obj["job_id"] == job, "read identity")
    row = obj[stream]
    raw = bytes.fromhex(row["bytes_hex"])
    require(raw.decode("utf-8") == row["text"], "hex/text mismatch")
    require(row["offset"] == offset and row["next_offset"] == end and len(raw) == end - offset, "stream range")
    require(row["eof"] is True, "read EOF missing")
    if "size" in row:
        require(row["size"] == end, "read size mismatch")
    return raw

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--inputs", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    inputs_path = safe_path(workspace, args.inputs)
    inputs_raw = inputs_path.read_bytes()
    inputs = json.loads(inputs_raw)
    require(inputs["schema"] == "hepta.source50-lock-control-addendum-inputs.v1", "schema")
    output = safe_path(workspace, args.output)
    require(not output.exists(), "output must be new")
    previous = safe_path(workspace, inputs["previous_group"])
    manifest_raw = (previous / "ATTACHMENT-MANIFEST.json").read_bytes()
    previous_report_raw = (previous / "INDEPENDENT-READBACK.json").read_bytes()
    require(pin(manifest_raw)["sha256"] == inputs["previous_attachment_manifest_sha256"], "previous manifest changed")
    require(pin(previous_report_raw)["sha256"] == inputs["previous_readback_sha256"], "previous readback changed")
    previous_snapshot = {str(p.relative_to(previous)): pin(p.read_bytes()) for p in previous.rglob("*") if p.is_file()}
    require(len(previous_snapshot) == 63, "previous group count")
    raw = {}
    closure = []
    destinations = set()
    for row in inputs["files"]:
        data = safe_path(workspace, row["path"]).read_bytes()
        data.decode("utf-8")
        info = pin(data)
        require(info["bytes"] == row["bytes"] and info["sha256"] == row["sha256"], "input bytes changed")
        require(row["destination"] not in destinations, "duplicate destination")
        safe_path(output, row["destination"])
        destinations.add(row["destination"])
        raw[row["destination"]] = data
        closure.append({"origin": row["path"], "destination": row["destination"], "encoding": "identity", **info})
    require(len(raw) == 18, "unexpected input set")
    def load(name):
        return json.loads(raw[name])
    base = "original/tool-recovered-control/"
    export = "original/export-v2-control/"
    statuses = {}
    expected = {
        "v1": ("1a1b13d4104-fc05-772d", 124, "timed_out", True),
        "v2": ("1a1b155b661-fc05-77d1", 1, "failed", False),
        "v3": ("1a1b15f7cc1-fc05-781c", 1, "failed", False),
    }
    for attempt, values in expected.items():
        obj = load(base + attempt + "/terminal-process-status.json")
        terminal(obj, *values)
        statuses[attempt] = obj
    v1_read = load(base + "v1/terminal-process-read.json")
    for stream in ("stdout", "stderr"):
        require(read_stream(v1_read, stream, expected["v1"][0], 0, 0) == raw[base + "v1/" + stream + ".txt"], "v1 stream")
        require(statuses["v1"]["log_bytes"][stream]["stored"] == 0, "v1 nonempty stream")
    v1_recovery = load(base + "v1/RECOVERY-READBACK.json")
    require(v1_recovery["status"] == "RECOVERED_FROM_ORIGINAL_DURABLE_CONTROLLER_RECORD", "v1 recovery semantics")
    require(v1_recovery["job_id"] == expected["v1"][0] and v1_recovery["new_execution"] is False, "v1 rerun")
    require(v1_recovery["not_reconstructed_from_summary"] is True, "v1 approximation")
    require(v1_recovery["original_terminal_at_unix_ms"] == statuses["v1"]["at_unix_ms"], "v1 original timestamp")
    query_time = datetime.datetime.fromisoformat(v1_recovery["retrieved_again_utc"]).timestamp()
    require(query_time * 1000 > statuses["v1"]["at_unix_ms"], "v1 query timestamp")
    for row in v1_recovery["files"]:
        info = pin(raw[base + "v1/" + row["path"]])
        require(info["bytes"] == row["bytes"] and info["sha256"] == row["sha256"], "v1 recovery inventory")
    recovery_index = load(base + "RECOVERY-INDEX.json")
    for row in recovery_index["files"]:
        info = pin(raw[base + row["path"]])
        require(info["bytes"] == row["bytes"] and info["sha256"] == row["sha256"], "v2/v3 recovery inventory")
    captures = {}
    outputs = {}
    for attempt in ("v2", "v3"):
        cap = load(base + attempt + "/full-original-capture.json")
        launch = unpack_tool(cap["launch"])
        require(launch["job"]["id"] == expected[attempt][0] and launch["launch"]["ok"] is True, "capture launch")
        status_tool = unpack_tool(cap["terminal_raw_tool"] if attempt == "v2" else cap["raw_status"])
        require(status_tool == statuses[attempt], "captured status differs")
        text = cap["terminal_text"] if attempt == "v2" else cap["terminal"]
        require(text.encode() == raw[base + attempt + "/terminal-process-status.json"], "terminal original bytes")
        if attempt == "v2":
            first, last = cap["first_read"], cap["last_read"]
            first_end = first["stdout"]["next_offset"]
            last_end = last["stdout"]["next_offset"]
            stdout = read_stream(first, "stdout", expected[attempt][0], 0, first_end)
            stdout += read_stream(last, "stdout", expected[attempt][0], first_end, last_end)
            require(read_stream(first, "stderr", expected[attempt][0], 0, 0) == b"", "v2 first stderr")
            require(read_stream(last, "stderr", expected[attempt][0], 0, 0) == b"", "v2 last stderr")
        else:
            read = load(base + "v3/terminal-process-read.json")
            require(unpack_tool(cap["raw_read"]) == read, "v3 raw read differs")
            stdout = read_stream(read, "stdout", expected[attempt][0], 0, statuses[attempt]["log_bytes"]["stdout"]["stored"])
            require(stdout == raw[base + "v3/stdout.txt"] == bytes.fromhex(cap["stdout_hex"]), "v3 stdout original")
            require(read_stream(read, "stderr", expected[attempt][0], 0, 0) == b"", "v3 stderr")
        require(len(stdout) == statuses[attempt]["log_bytes"]["stdout"]["stored"], "terminal/stream size")
        receipt = json.loads(stdout.decode().splitlines()[-1])
        original_receipt = previous / "tool-history/original/evidence" / ("native-r24-bazel-tool-preparation-" + attempt + ".json")
        require(receipt == json.loads(original_receipt.read_bytes()), "original tool receipt differs")
        require(receipt["exit_code"] == 1 and receipt["version_probe"] is None and receipt["binary"] is None, "failed preparation published binary")
        require(receipt["rust_tests_started"] is False, "tool attempt unexpectedly ran Rust")
        for side in ("source_before", "source_after"):
            require(receipt[side]["tree"] == "be34ab1afe622ad3b8f030c8c5018f4f54fbc304" and receipt[side]["guard_pass"] is True, "tool source guard")
        outputs[attempt] = pin(stdout)
        captures[attempt] = receipt
    require(captures["v2"]["prior_job_id"] == expected["v1"][0] and captures["v2"]["prior_terminal_exit_code"] == 124, "v1 to v2")
    require(captures["v3"]["prior_job_id"] == expected["v2"][0], "v2 to v3")
    require(captures["v3"]["prior_terminal_sha256"] == pin(raw[base + "v2/terminal-process-status.json"])["sha256"], "v2 terminal pin")
    v4_path = previous / "tool-history/original/evidence/native-r24-bazel-tool-preparation-v4.json"
    v4 = json.loads(v4_path.read_bytes())
    require(v4["prior_job_id"] == expected["v3"][0] and v4["exit_code"] == 0, "v3 to v4")
    require(v4["prior_terminal_sha256"] == pin(raw[base + "v3/terminal-process-status.json"])["sha256"], "v3 terminal pin")
    export_status = load(export + "v2-terminal-process-status.json")
    export_job = "1a1b175f5dc-fc05-78e2"
    terminal(export_status, export_job, 0, "succeeded", False)
    export_launch = load(export + "v2-original-launch.json")
    require(export_launch["job"]["id"] == export_job and export_launch["launch"]["ok"] is True, "export launch")
    export_read = load(export + "v2-original-process-read.json")
    for stream in ("stdout", "stderr"):
        stream_data = raw[export + "v2-" + stream + ".txt"]
        require(read_stream(export_read, stream, export_job, 0, len(stream_data)) == stream_data, "export stream")
        require(export_status["log_bytes"][stream]["stored"] == len(stream_data), "export terminal stream")
    exported = json.loads(raw[export + "v2-stdout.txt"])
    file_info = load(export + "v2-archive-file-info.json")
    archive = (previous / "checkpoint-source50-lock-update-v2.tar.gz").read_bytes()
    archive_pin = pin(archive)
    require(archive_pin["bytes"] == 787385 and archive_pin["sha256"] == "7dbb64599c8986628e494536e0e0af4895e0d78f36ed8ea89153b94371fbb47c", "archive identity")
    require(exported["bytes"] == file_info["size"] == archive_pin["bytes"], "export archive size")
    require(exported["sha256"] == file_info["sha256"] == archive_pin["sha256"], "export archive hash")
    require(exported["git_blob"] == archive_pin["git_blob"] and exported["members"] == 29, "export archive Git/member pin")
    require(exported["source_tree"] == "ea48acf562499192a25e05ae28926a32632dee62" and exported["source_count"] == 194, "export source")
    require(exported["lock_update_exit_code"] == 0 and exported["rust_tests_started"] is False, "export scope")
    report = {
        "schema": "hepta.source50-lock-control-recovery-independent-readback.v1",
        "status": "CLOSED_CONTROLLER_INTEGRITY_ADDENDUM_NOT_RUST_QUALIFICATION",
        "original_files": len(raw),
        "original_bytes": sum(len(data) for data in raw.values()),
        "previous_group": {
            "path": "../source50-lock-update-checkpoint",
            "attachment_manifest": pin(manifest_raw),
            "independent_readback": pin(previous_report_raw),
            "original_file_count": len(previous_snapshot),
            "unchanged": True,
            "historical_missing_list_not_rewritten": True,
        },
        "tool_controller_results": {
            attempt: {"job_id": obj["job_id"], "state": obj["state"], "exit_code": obj["exit_code"],
                      "at_unix_ms": obj["at_unix_ms"], "timed_out": obj["timed_out"],
                      "output_complete": obj["output_complete"], "output_durable": obj["output_durable"],
                      "automatic_retry": obj["automatic_retry"], "cancelled": obj["cancelled"]}
            for attempt, obj in statuses.items()
        },
        "v1_recovery_boundary": {
            "retrieved_again_utc": v1_recovery["retrieved_again_utc"],
            "original_terminal_at_unix_ms": v1_recovery["original_terminal_at_unix_ms"],
            "new_execution": False,
            "description": "New read of the same original durable controller record. Not a reconstruction of a lost query envelope and not a repeated download or lock invocation.",
        },
        "v2_v3_stream_reconstruction": outputs,
        "failed_preparation_receipts_match_previously_frozen_originals": True,
        "v1_to_v2_to_v3_to_v4_job_and_terminal_pin_chain": True,
        "v4_success_reference": {"path": "../source50-lock-update-checkpoint/tool-history/original/evidence/native-r24-bazel-tool-preparation-v4.json", **pin(v4_path.read_bytes())},
        "export_v2": {"job_id": export_job, "state": export_status["state"], "exit_code": export_status["exit_code"],
                      "outer_output_complete": True, "outer_output_durable": True, "archive": archive_pin, "members": 29,
                      "full_original_launch_and_read_preserved": True},
        "resolved_late_original_sets": ["export-v2 controller 6 files", "tool v2/v3 full original captures and recovered records", "tool v1 newly queried old durable terminal/read/empty streams"],
        "still_missing_originals": [{"path": "source50-preparation/ROOT-R24-LAUNCH-AUTHORIZATION.json",
                                    "historically_observed_bytes": 1100,
                                    "historically_observed_sha256": "745751d4ce09bb7034d7ef6bf5b48594dade47bff4549acb22b6286d4ad191bf",
                                    "not_recreated": True}],
        "qualification_boundary": "This addendum closes custody of tool preparation and lock-export controllers. It does not change the original lock command result, run or qualify Rust, authorize r25, or replace the closed r24 test failure.",
        "execution": {"offline_standard_library_only": True, "network": False, "native_process": False, "rust": False, "source_mutation": False},
    }
    output.mkdir(parents=True)
    for name, data in raw.items():
        destination = safe_path(output, name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        destination.chmod(0o644)
    derived = {
        "INDEPENDENT-READBACK.json": json_bytes(report),
        "CLOSURE-MAPPING.json": json_bytes({"schema": "hepta.exact-source50-controller-closure.v1", "entries": closure}),
        "INPUTS.json": inputs_raw,
        "assemble.py": Path(__file__).read_bytes(),
        "BINARY-PLAN.json": json_bytes({"schema": "hepta.binary-upload-plan.v1", "files": [], "reason": "All 18 original controller files and new reports are UTF-8; existing archive is referenced without duplication."}),
        "README.md": ("# Source50 lock controller recovery addendum\n\n"
                      "This new group preserves controller originals recovered after the main 63-file lock checkpoint was frozen. "
                      "That checkpoint and its historical missing list remain byte-identical.\n\n"
                      "Tool attempts 1/2/3 remain timed out 124 / failed 1 / failed 1. "
                      "The existing v4 success receipt closes their exact job/terminal chain. "
                      "The lock export v2 controller succeeded 0 and binds the existing 787,385-byte archive.\n\n"
                      "The v1 controller record was queried again at the recorded recovery time; no attempt was re-executed. "
                      "No source, Rust, tests, formatter, or remote controller was modified or invoked by this assembler. "
                      "These integrity checks do not grant Rust qualification or erase r24's failed test result.\n").encode(),
    }
    for name, data in derived.items():
        (output / name).write_bytes(data)
        (output / name).chmod(0o644)
    now = {str(p.relative_to(previous)): pin(p.read_bytes()) for p in previous.rglob("*") if p.is_file()}
    require(now == previous_snapshot, "previous frozen group changed")
    members = [{"path": str(p.relative_to(output)), "mode": "100644", **pin(p.read_bytes())}
               for p in sorted(output.rglob("*")) if p.is_file()]
    attachment = json_bytes({"schema": "hepta.frozen-attachment-manifest.v1", "status": "FROZEN_EXACT_LATE_CONTROLLER_ADDENDUM",
                             "self_excluded": True, "files": members})
    (output / "ATTACHMENT-MANIFEST.json").write_bytes(attachment)
    (output / "ATTACHMENT-MANIFEST.json").chmod(0o644)
    print(json.dumps({"output": args.output, "files_including_manifest": len(members) + 1,
                      "readback": pin(derived["INDEPENDENT-READBACK.json"]), "manifest": pin(attachment)}))

if __name__ == "__main__":
    main()
