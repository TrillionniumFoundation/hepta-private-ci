import collections
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent
BUNDLE = ROOT.parent / "ci-audit/recovered-20261105/app-parent-lifecycle-terminal.json"
OUT = ROOT / "inputs/app-parent-probe-root-decoded"
OUT.mkdir(exist_ok=False)


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "blob": hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()}


bundle_bytes = BUNDLE.read_bytes()
assert identity(bundle_bytes)["blob"] == "2f8ffc305f0e1d5814b9f838f8a3b4ad57bc21ab"
bundle = json.loads(bundle_bytes)
files = {}
for file in bundle["files"]:
    data = file["content"].encode()
    rec = identity(data)
    assert rec["bytes"] == file["bytes"] and rec["sha256"] == file["sha256"]
    assert Path(file["name"]).name == file["name"]
    path = OUT / file["name"]
    assert path.write_bytes(data) == len(data)
    assert path.read_bytes() == data
    files[file["name"]] = rec
assert len(files) == 6
terminal = json.loads((OUT / "terminal.json").read_bytes())
probes = json.loads((OUT / "parent-lifecycle-probe-observations.json").read_bytes())
restore = json.loads((OUT / "temporary-source-restoration.json").read_bytes())
summary = json.loads((OUT / "owned-process-observation-summary.json").read_bytes())
trace_bytes = (ROOT / "inputs/app-parent-lifecycle-owned-trace.jsonl").read_bytes()
assert identity(trace_bytes)["blob"] == "6f7132c44c5f83ffa1dd57c75721f0f2a01915a1"
assert identity(trace_bytes)["sha256"] == summary["trace"]["sha256"]
trace = [json.loads(line) for line in trace_bytes.splitlines()]
assert len(trace) == summary["events"] == 185 and summary["samples"] == 155
assert summary["observer_errors"] == [] and len(summary["known_fixture_markers"]) == 1
assert terminal["source"] == probes["source"] == summary["source"] == "1e936b1ca6df807d8928a4cc6c527f40f92808aa"
assert terminal["programs_before"] == terminal["programs_after"]
assert terminal["helpers_before"] == terminal["helpers_after"]
assert len(terminal["programs_before"]) == 1 and len(terminal["helpers_before"]) == 33
assert terminal["ordinary_index_before"] == terminal["ordinary_index_after"]
assert terminal["locks_before"] == terminal["locks_after"]
assert terminal["selected_count"] == 1 and terminal["retries"] == 0
assert terminal["original_just_exit"] == 100 and terminal["skip_notices"] == []
assert terminal["observation_complete"] and not terminal["test_passed"]
assert probes["all_probe_phases_complete"] and probes["pdeath_reads_succeeded"]
raw = (OUT / "app-disconnect-original-diagnostic.log").read_bytes()
observed = {row["phase"]: row for row in probes["observations"]}
assert len(observed) == 3
for row in observed.values():
    line = row["raw_line"].encode()
    assert raw[row["raw_byte_offset"]:row["raw_byte_offset"] + len(line)] == line
    assert raw.splitlines(keepends=True)[row["raw_line_number"] - 1] == line
for phase in ("inner_entry", "inner_after_restrictions"):
    row = observed[phase]
    assert (row["pid"], row["ppid"], row["pgid"], row["sid"], row["pdeath_rc"], row["observed_parent_death_signal"]) == (1, 0, 1, 1, 0, 0)
assert observed["original_killpg_return"]["pgid"] == 780599
assert observed["original_killpg_return"]["result"] == "Ok(())"
case = terminal["cases"][0]
assert case["seconds"] == "5.575" and case["result"] == "FAIL"
xml = ElementTree.fromstring((OUT / "app-disconnect-original-diagnostic.junit.xml").read_bytes())
cases = list(xml.iter("testcase"))
assert len(cases) == 1 and cases[0].attrib["name"] == case["name"] and cases[0].find("failure") is not None
assert restore["restored_exact_original"] and restore["restoration_error"] is None
assert restore["diagnostic_eligibility_error"] is None
assert restore["expected_restored_tree"] == restore["source_variable_at_terminal"] == "f8251e1d14fa8524ab469281296cd4cf708f173c"
assert restore["original_exception"]["type"] == "SystemExit" and restore["original_exception"]["message"] == "1"
states = {}
outer = []
marker = summary["known_fixture_markers"][0]
for event in trace:
    if event["event"] == "owned-process-state":
        proc = event["process"]
        states[(proc["pid"], proc["starttime_ticks"])] = proc
        if proc["pid"] == 780599:
            outer.append(event)
    elif event["event"] == "owned-identity-no-longer-observed":
        states.pop((event["pid"], event["starttime_ticks"]), None)
        if event["pid"] == 780599:
            outer.append(event)
assert sorted(states.values(), key=lambda x: x["pid"]) == sorted(summary["last_observed_owned_processes"], key=lambda x: x["pid"])
assert sorted(p["pid"] for p in states.values()) == [780604, 780606]
assert all(p["state"] == "S" and marker in p["exact_fixture_markers"] for p in states.values())
assert any(e["event"] == "owned-process-state" and e["process"]["pgid"] == 780599 for e in outer)
assert outer[-1]["event"] == "owned-identity-no-longer-observed"
native = bundle["native_status"]
assert native["state"] == "failed" and native["exit_code"] == 1 and not native["timed_out"] and not native["cancelled"]
report = {
    "schema": "hepta.root.app-parent-lifecycle-observation-review.v1",
    "observed_at_utc": datetime.now(timezone.utc).isoformat(),
    "status": "ORIGINAL_CASE_FAILED_PARENT_DEATH_SIGNAL_ABSENT_ORIGINAL_GROUP_KILL_SUCCEEDED_SOURCE_RESTORED",
    "native_job": bundle["native_job"], "native_status": native,
    "bundle": identity(bundle_bytes), "complete_six_files_reopened": [{"name": n, **r} for n, r in files.items()],
    "complete_owned_trace": identity(trace_bytes), "trace_events": len(trace), "trace_samples": summary["samples"],
    "event_counts": dict(collections.Counter(x["event"] for x in trace)),
    "selected_case": case, "original_just_exit": 100, "retries": 0,
    "source_during_execution": terminal["source"], "required_and_actual_restored_tree": restore["source_variable_at_terminal"],
    "one_app_program_and_33_helpers_before_after_exact": True,
    "source_index_and_locks_stable_during_diagnostic": True,
    "all_three_raw_probe_lines_and_byte_offsets_verified": list(observed.values()),
    "same_host_outer_group_correlated_with_process_trace": outer,
    "final_trace_reconstructed_live_identities": sorted(states.values(), key=lambda x: x["pid"]),
    "exact_source_restoration_receipt": restore,
    "findings_zh": [
        "内层namespace PID1在进入时及应用限制后，PR_GET_PDEATHSIG实际均成功返回0；缺失行或读取失败均未被替代为0。",
        "原killpg操作对host PGID780599实际返回Ok，且同身份外bwrap从trace消失；不是原group-kill API失败导致的结论。",
        "内层helper780604和Python780606仍保持同PID/starttime/marker、stateS直到终态，原5秒marker退出合同仍FAIL。",
        "结果证明所观察边界缺少parent-death signal，未证明具体LSM/exec/credential步骤何时、为何改变它。",
        "三份临时观测源码已在完整owned tree/index/locks/untracked guard下恢复f825；目标目录中旧诊断二进制不因此获得恢复后源码资格。",
    ],
    "pending_provenance": "The complete helper compiler/catalog/source-map export is separate and is not yet independently reviewed in this receipt. The six-file bundle and all185 trace events were fully verified here.",
    "next_execution": {"approved_runner": "6a88d730302334977a3275218443f766cd07fd55",
                       "approved_manifest": "7dbc3adb768e10592beba53ef7511f68dd17cf11",
                       "condition": "Start with fresh exact f825/index/locks/untracked guard; no existing diagnostic binary hash is inherited as a new product PASS."},
    "all_original_blockers_closed": False,
}
destination = ROOT / "deliverables/fourth-app-parent-probe-root-review.json"
destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"path": str(destination), **identity(destination.read_bytes()), "source_restored": True,
                  "pdeath_signals": [0, 0], "original_killpg": "Ok(())", "case": case["result"]}))
