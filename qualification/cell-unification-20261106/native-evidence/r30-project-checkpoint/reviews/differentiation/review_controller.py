"""Read the already closed local R30 controller originals; no subprocesses."""
from pathlib import Path
import hashlib
import json
import re

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
DATA = WORK / "native-validation-results/r30-closed-input"
E = DATA / "evidence"
C = DATA / "controller"
PREFIX = "native-source53-project-r30"
JOB = "1a1b25b399f-fc05-7daa"
AUTH = WORK / "source53-r30-root-review/ROOT-EXECUTION-AUTHORIZATION.json"
RUNNER = WORK / "source53-r30-binding/native-run-r30.py"


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def save(name, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    with (HERE / name).open("xb") as out:
        out.write(raw)
    return {"path": name, **pin(raw)}


authorization_raw = AUTH.read_bytes()
assert pin(authorization_raw)["sha256"] == "c08c972a98f8951637e6525e18cbf8c944cfddf23d87a9388f27761d52583f02"
authorization = json.loads(authorization_raw)
runner_raw = RUNNER.read_bytes()
assert len(runner_raw) == 61214
assert pin(runner_raw)["sha256"] == authorization["runner"]["sha256"] == "b72407252efdaf81d8e3bc5280c3fa7ad9afb36fa398869e8023daaa392ff3c8"
launch_raw = (C / "r30-controller-closed-launch.json").read_bytes()
launch = json.loads(launch_raw)
assert launch["job"]["id"] == JOB and launch["job"]["launch_state"] == "launched"
assert launch["job"]["executable"] == "/usr/bin/python3"
assert launch["job"]["args"] == ["/home/alex/work/hepta-cell-unified-20261106-a/native-run-r30.py"]
assert launch["job"]["idempotency_key"] == authorization["unique_launch_key"]
assert launch["reused"] is False and launch["local_record_pending"] is False
terminal_raw = (C / "r30-controller-closed-terminal-process-status.json").read_bytes()
assert terminal_raw == (E / (PREFIX + "-terminal-process-status.json")).read_bytes()
assert pin(terminal_raw)["sha256"] == "714f22dd64a60d5d9abb932c94c30803d081f365d1dd8ef06afc45d2ea7ede1d"
terminal = json.loads(terminal_raw)
assert terminal["state"] == "succeeded" and terminal["exit_code"] == 0 and terminal["job_id"] == JOB
assembled = {"stdout": b"", "stderr": b""}
readbacks = []
for index in range(3):
    path = C / ("r30-controller-closed-read-" + str(index) + ".json")
    raw = path.read_bytes()
    value = json.loads(raw)
    assert value["job_id"] == JOB
    streams = {}
    for stream in assembled:
        observed = value[stream]
        data = bytes.fromhex(observed["bytes_hex"])
        assert observed["offset"] == len(assembled[stream])
        assert len(data) == observed["next_offset"] - observed["offset"]
        assert observed["size"] >= observed["next_offset"]
        assert observed["text"].encode() == data
        assembled[stream] += data
        streams[stream] = {key: observed[key] for key in ("offset", "next_offset", "size", "eof")}
        streams[stream]["chunk"] = pin(data)
    readbacks.append({"original": {"path": str(path.relative_to(WORK)), **pin(raw)}, "streams": streams})
for stream, raw in assembled.items():
    assert raw == (C / ("original-" + stream + ".log")).read_bytes()
    assert len(raw) == terminal["log_bytes"][stream]["seen"] == terminal["log_bytes"][stream]["stored"]
assert len(assembled["stdout"]) == 5097 and assembled["stderr"] == b""
events = [json.loads(line) for line in assembled["stdout"].splitlines()]
assert len(events) == 6
for phase, offset in (("strict", 0), ("tests", 3)):
    start, process, receipt = events[offset:offset + 3]
    original_raw = json.loads((E / (PREFIX + "-" + phase + "-raw-process-result.json")).read_bytes())
    original_receipt = json.loads((E / (PREFIX + "-" + phase + "-receipt.json")).read_bytes())
    assert start["phase"] == phase + "-start"
    assert start["command"] == original_raw["command"] and start["source_tree"] == original_raw["source_tree"]
    assert process == {**original_raw, "event": phase + "-raw-process-return"}
    assert receipt == original_receipt
    assert launch["job"]["created_unix_ms"] / 1000 <= original_raw["start_unix"]
    assert terminal["at_unix_ms"] / 1000 >= original_raw["end_unix"]
controller = {
    "schema": "hepta.source53-r30-independent-controller-readback.v1",
    "job": JOB, "root_authorization": {"path": str(AUTH.relative_to(WORK)), **pin(authorization_raw)},
    "actual_direct_file_runner": {"path": str(RUNNER.relative_to(WORK)), **pin(runner_raw)},
    "launch": {"path": "controller/r30-controller-closed-launch.json", **pin(launch_raw)},
    "terminal": {"path": "controller/r30-controller-closed-terminal-process-status.json", **pin(terminal_raw)},
    "stream_readbacks": readbacks,
    "stream_size_is_total_at_read_not_chunk_size": True,
    "original_stdout": pin(assembled["stdout"]), "original_stderr": pin(assembled["stderr"]),
    "all_six_original_start_raw_return_and_receipt_announcements_match_phase_originals": True,
    "natural_outer": {"state": "succeeded", "exit_code": 0, "timed_out": False, "cancelled": False},
    "runner_imported_or_executed": False, "native_or_Rust_executed": False,
}
controller_pin = save("CONTROLLER-READBACK.json", controller)
report_path = HERE / "closed-readback-v1/INDEPENDENT-READBACK.json"
report_raw = report_path.read_bytes()
assert pin(report_raw)["sha256"] == "f03be158c3bc5a305c763fce7d4783eea23f6e0fdfd306cd2ae76d6fc33a7225"
report = json.loads(report_raw)
execution = report["execution"]
match = re.fullmatch(r"\s*Starting (\d+) tests across (\d+) binaries \((\d+) tests skipped\)", execution["starting"]["text"])
assert match and int(match[1]) == 1345 and int(match[2]) == 6 and int(match[3]) == 2
summary = {
    "schema": "hepta.source53-r30-independent-closure-summary.v1",
    "classification": "CLOSED_ENGINEERING_PROJECT_PASS_DIAGNOSTIC_SOURCE",
    "independent_report": {"path": "closed-readback-v1/INDEPENDENT-READBACK.json", **pin(report_raw)},
    "controller_readback": controller_pin,
    "source_commit": report["source_commit"], "source_tree": report["source_tree"],
    "actual_native_HEAD": report["native_HEAD"], "registered_manifest_rows": 197,
    "source_byte_boundary": report["source_readback"],
    "strict_raw_and_effective_exit": 0, "tests_raw_and_effective_exit": 0, "outer_exit": 0,
    "strict_wall_seconds": 189.01348495483398, "tests_wall_seconds": 972.5199975967407,
    "nextest_execution_seconds": execution["summary"]["seconds"],
    "counts": execution["terminal_counts"], "unique_test_count": execution["terminal_unique_test_count"],
    "reported_skipped": execution["reported_skipped"], "skip_identities_inferred": False,
    "announced_binary_count": int(match[2]), "binary_groups_with_executed_rows": len(execution["per_binary"]),
    "executed_row_groups": execution["per_binary"],
    "announced_binaries_not_conflated_with_executed_row_groups": True,
    "missing_test_ids": execution["baseline_missing"], "additional_test_ids": execution["additional_test_ids"],
    "footer_rows_excluded_count": len(execution["footer_rows_excluded"]),
    "actual_19_successful_originals_plus_terminal_rehashed": 20,
    "original_R29_failure_and_current_R30_observation": report["original_R29_failed_observation_not_relabelled"],
    "diagnostic_only": True, "behavior_repair_claimed": False,
    "project_result_substitutes_for_workspace_or_finalizer": False,
    "native_Rust_metadata_fix_fmt_or_tool_queries_executed_by_reader": False,
    "host_free_space_readings_are_not_exclusive_test_resource_cost": True,
}
summary_pin = save("CLOSURE-SUMMARY.json", summary)
print(json.dumps({"controller": controller_pin, "summary": summary_pin, "result": "READBACK_PASS"}))
