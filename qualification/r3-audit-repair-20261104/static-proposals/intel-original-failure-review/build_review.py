from pathlib import Path
import datetime
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parent
REPO = "TrillionniumFoundation/hepta-private-ci"
BASE = "cabcb40d36e116beaa65750e1f674c52035da785"
MERGE = "28af7f705fa1024b9a6d2ef751fec116002260eb"
BASE_TREE = "b2d7f038d6d88156bc6a4cb29c8703f69b808f29"
CURRENT = "bd7631e98f295fefad7654865cea497ceacf7d06"
CURRENT_TREE = "7d703610ae4f778ad305ebc139860d276f416e8c"


def identity(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest(),
    }


sources = json.loads((ROOT / "source-manifest.json").read_text())["sources"]
source_by_key = {entry["key"]: entry for entry in sources}
for entry in sources:
    raw = (ROOT / entry["local_file"]).read_bytes()
    assert identity(raw)["git_blob"] == entry["blob"]
    assert identity(raw)["sha256"] == entry["sha256"]

unchanged = []
for old, new in [
    ("pty", "current_pty"),
    ("unix_io", "current_unix_io"),
    ("process", "current_process"),
    ("forward_prod", "current_forward_prod"),
    ("forward_stream", "current_forward_stream"),
    ("message_framing", "current_message_framing"),
    ("core_client", "current_client"),
]:
    a, b = source_by_key[old], source_by_key[new]
    assert a["blob"] == b["blob"]
    assert (ROOT / a["local_file"]).read_bytes() == (ROOT / b["local_file"]).read_bytes()
    unchanged.append({"path": a["path"], "old_blob": a["blob"], "candidate_blob": b["blob"], "byteequal": True})

raw_evidence = {}
for key, name, expected in [
    ("pty", "original-pty-test.log", "7cd3de653d7acecc41a960c406ee931b972413f70d79389f2c2a816f641df47e"),
    ("pty_xml", "original-pty-test.xml", "98b329a05810064e9e9a5ef6e7d8f5b7e82b743e90e11499330c6d24c27fba66"),
    ("forward", "original-forward-test.log", "228e852e65905d64c1f0861f704b467b2da62247507a9eefbb2265a5702cda68"),
    ("core_shard10_final", "original-core-shard10-test.log", "1cfd18fd46a30e38e0f1022e9c8108e385a8edc44aa06e75501a3328b2c0c053"),
]:
    raw = (ROOT / name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == expected
    raw_evidence[key] = {"file": name, **identity(raw), "complete_bytes_read": True}

pty_lines = (ROOT / "original-pty-test.log").read_text().splitlines()
pty_roster = []
for number, line in enumerate(pty_lines, 1):
    match = re.fullmatch(r"test (\S+) \.\.\. (ok|FAILED|ignored)", line)
    if match:
        pty_roster.append({"case": match[1], "result": match[2], "line": number})
assert len(pty_roster) == 30
assert sum(entry["result"] == "ok" for entry in pty_roster) == 28
assert sum(entry["result"] == "FAILED" for entry in pty_roster) == 2

core_lines = (ROOT / "original-core-shard10-test.log").read_text().splitlines()
core_projection = {
    "successful_server_handshake_lines": [i + 1 for i, line in enumerate(core_lines) if "Server handshake done." in line],
    "successful_client_handshake_lines": [i + 1 for i, line in enumerate(core_lines) if "Client handshake done." in line],
    "fixture_requests": [{"line": i + 1, "text": line} for i, line in enumerate(core_lines) if "[ws test server" in line],
    "initial_readonly_config_lines": [i + 1 for i, line in enumerate(core_lines) if "sandbox_policy=read-only" in line],
    "submitted_disabled_profile_lines": [i + 1 for i, line in enumerate(core_lines) if "sandbox_policy: Some(DangerFullAccess)" in line and "permission_profile: Some(Disabled)" in line],
    "assertion_line": next(i + 1 for i, line in enumerate(core_lines) if "panicked at core/tests/suite/turn_state.rs:136:5" in line),
    "assertion": "actual request count 1; expected 4",
    "final_shard_summary": next(line for line in reversed(core_lines) if line.startswith("test result:")),
}
assert len(core_projection["successful_server_handshake_lines"]) == 1
assert len(core_projection["successful_client_handshake_lines"]) == 1
assert len(core_projection["fixture_requests"]) == 2


def source_ref(key, lines):
    entry = source_by_key[key]
    actual_lines = len((ROOT / entry["local_file"]).read_text().splitlines())
    assert 1 <= lines[0] <= actual_lines
    return {"path": entry["path"], "ref": entry["ref"], "blob": entry["blob"], "lines": [lines[0], min(lines[1], actual_lines)]}


cases = [
    {
        "case": "suite::turn_state::websocket_turn_state_persists_within_turn_and_resets_after",
        "target": "//codex-rs/core:core-all-test",
        "original_result": "FAIL",
        "classification": "FIXTURE_CONTRACT_MISMATCH_SOURCE_PROVEN; CURRENT_A_FIXTURE_REPAIR; FRESH_INTEL_GATE_PENDING",
        "original_observation": "Read-only startup prewarm completed; the submitted turn explicitly changes to Disabled/DangerFullAccess. One server/client handshake and only connection 0 request 0 were recorded. Final assertion is 1 versus 4. The complete collector also records two earlier failed attempts of this exact case; those are retries of this job, not independent platforms.",
        "causal_source_chain": [
            "Old test expects a single physical connection while its asserted sandbox vector changes read-only to danger-full-access.",
            "TestCodex::submit_turn sends a Disabled permission profile. WebsocketConnectionIdentity keeps sandbox and sandbox_mode in the serialized compatibility projection.",
            "On changed identity, websocket_connection awaits a new connection before replacing the retained old one.",
            "The old fixture handles each accepted connection's full script serially, waiting for request 1 on the retained old connection. It cannot accept the policy-driven second handshake during that wait.",
        ],
        "candidate_effect": "The same-permission case now configures Disabled before startup and submits default overrides, preserving 1 handshake/4 requests and state/reset/turn-ID assertions. A separate concurrent-server control preserves the original read-only to Disabled vector and requires 2 handshakes, physical request counts [1,3], actual tool output and unchanged state/reset assertions. No production permission-isolation guard is weakened.",
        "limits": ["This review proves the fixture/source contract conflict and its consistency with the original full trace, not a new Intel pass.", "The added reconnect control must execute its assertions; a no-network early return is not qualification.", "The two other failed attempts are recorded by original collector verification, not re-read as full bytes in this narrow review."],
        "sources": [source_ref("base_turn_state", [95, 195]), source_ref("test_codex", [926, 980]), source_ref("core_client", [377, 431]), source_ref("core_client", [1797, 1857]), source_ref("responses_metadata", [357, 383]), source_ref("responses", [1488, 1664]), source_ref("current_turn_state", [98, 244]), source_ref("current_turn_state", [338, 444]), source_ref("current_concurrent", [48, 174])],
        "fresh_intel_observations": ["Exact original case passes with 1 actual handshake, 4 requests and the original null/null/ts-1/null turn-state vector.", "The already-added permission-change control passes with the actual read-only prewarm, 2 handshakes and [1,3] requests; it must not be rescued by server-forced Close/EOF.", "Retain the existing stable-within-turn companion and its actual tool output checks; use exact case results, not a target-only pass."],
    },
    {
        "case": "forwarder_runs_commands_and_transfers_files",
        "target": "//codex-rs/exec-server:exec-server-forward-test",
        "original_result": "FAIL",
        "classification": "OPEN_WRITE_PHASE_TIMEOUT; CURRENT_A_DIAGNOSTIC_ONLY",
        "original_observation": {"phase": "13 MiB fs_write_file RPC", "payload_bytes": 13631488, "elapsed_seconds": "30.603316921", "original_budget_seconds": 30, "whole_case_seconds": "35.07"},
        "causal_source_chain": ["The complete 632-byte log explicitly identifies forward large-file write phase timed out.", "Read-back byte equality, encryption assertion, connection.close and forwarder shutdown follow this write and were not reached after its timeout.", "Current A only adds fixture relay received-frame/byte/task-state totals and owned destination metadata in this timeout context. The actual forwarding/framing implementation is byteequal to cabc."],
        "candidate_effect": "Diagnostic only. No identified production root cause is repaired by the added counters.",
        "limits": ["Do not call this a forward-close failure.", "Received opaque encrypted bytes are counted before the relay forwarding send and in both directions. They do not prove delivery, reassembly, decryption, disk completion or an RPC ACK.", "Destination metadata equal to the payload size would still not prove RPC completion; missing or partial data only narrows the stage.", "No causal production bug was proven by this static review; host throughput, scheduling and transport progress remain unresolved."],
        "sources": [source_ref("base_forward", [121, 174]), source_ref("current_forward", [121, 176]), source_ref("current_relay", [155, 174]), source_ref("forward_prod", [1, 236]), source_ref("forward_stream", [1, 240]), source_ref("message_framing", [1, 200])],
        "fresh_intel_observations": ["On the original exact case, distinguish successful write/read-back/encryption/close completion from another write timeout.", "If it times out, preserve the before/after received totals, relay task finished flag and destination metadata from the current A error context.", "Keep 30 s and the full 13 MiB byte equality. A pass on another host or an ARM job does not close the Intel gate."],
    },
    {
        "case": "tests::pty_dropped_output_receiver_keeps_draining_child",
        "target": "//codex-rs/utils/pty:pty-unit-tests",
        "original_result": "FAIL",
        "classification": "OPEN_PORTABLE_PTY_DRAIN; CURRENT_A_HAS_NO_REPAIR_TO_THIS_CASE_OR_PRODUCTION",
        "original_observation": {"backend": "portable", "spawn_elapsed_seconds": "0.013942087", "wait_elapsed_seconds": "2.028399059", "outcome": "deadline_elapsed", "has_exited": False, "exit_code": None, "child_phase": "python_started", "missing_phase": "output_write_returned", "original_budget_seconds": 2},
        "causal_source_chain": ["The Python side channel proves the child started. At the deadline the 4 MiB stdout write had not produced its after-write marker and the session had not observed exit.", "The test loops portable first and preserved-FD second. The first result?? exits on this timeout, so the preserved-FD branch was not executed in this failed attempt.", "The production Unix reader ignores closed output-channel send errors and continues reading, so the simple claim that dropping the output receiver stops the read loop contradicts the source.", "Current A leaves this entire test body and the PTY production files unchanged; its output collector changes are not used by this test's direct exit_rx timeout."],
        "candidate_effect": "Existing phase diagnostics remain available. No new production repair or causal closure for this Intel drain failure.",
        "limits": ["The trace does not measure actual kernel read progress or the reader's terminal I/O result.", "A blocked writer, scheduler pressure, an I/O error and other native lifecycle causes cannot be separated from these two phase markers alone.", "The 10 s child alarm is cleanup protection and is not permission to increase the 2 s acceptance bound."],
        "sources": [source_ref("current_tests", [1152, 1234]), source_ref("pty", [153, 288]), source_ref("unix_io", [46, 142])],
        "fresh_intel_observations": ["Require the exact original case to pass its original 2 s window for both portable and preserved-FD backends.", "On any failure retain backend, spawn/wait elapsed, outcome, has_exited, stored exit_code and the side-channel phase; do not infer the second backend ran if the first returned Err.", "A repeated python_started-only failure remains open. If another source change is then needed, the next narrow evidence would be the owned reader's real byte/error result and real waiter error; that is not present in current A and is not claimed here."],
    },
    {
        "case": "tests::pty_close_stdin_preserves_large_input_and_delivers_eof",
        "target": "//codex-rs/utils/pty:pty-unit-tests",
        "original_result": "FAIL",
        "classification": "OPEN_EXIT_RESULT_CAUSE; CURRENT_A_FIXES_CLOSED_OUTPUT_POLLING_AND_SEPARATES_DIAGNOSTICS",
        "original_observation": {"actual": [-1, "__complete__"], "expected": [0, "__complete__"], "original_collector_budget_seconds": 5, "original_ready_budget_seconds": 2},
        "causal_source_chain": ["The completion marker is printed after Python receives EOF and checks the entire input byte sequence. It does not itself prove successful process reaping or delivery of exit code zero.", "The old collector returns -1 both on its deadline and on a closed exit channel; it also forwards an actual -1 exit message. The old failure cannot distinguish these paths.", "A permanently closed broadcast receiver was left enabled in the old select loop. Current A disables that ready output branch while still waiting for the real exit signal and the original deadline.", "The portable PTY waiter still maps a child.wait error to -1. That production code is unchanged and its concrete error cause is not recorded in current A."],
        "candidate_effect": "A valid test-helper behavior correction plus outcome-specific diagnostics. The added closed-output/delayed-real-exit control checks that EOF does not fabricate an exit result, but is not a physical Intel PTY causal counterfactual.",
        "limits": ["Do not infer the old -1 was an OS process exit code.", "Do not infer the old -1 was caused by the always-ready closed-output branch; the old log is insufficient and select scheduling is not a causal proof.", "Even actual exit_code_received=-1 would identify the waiter result branch but not expose the underlying child.wait error.", "The strict (0, __complete__) assertion, input bytes, 2 s ready and 5 s exit budgets are unchanged."],
        "sources": [source_ref("base_tests", [102, 143]), source_ref("current_tests", [102, 193]), source_ref("current_tests", [1239, 1288]), source_ref("pty", [240, 254]), source_ref("process", [208, 217])],
        "fresh_intel_observations": ["Preserve the collector outcome: exit_code_received, exit_channel_closed or deadline_elapsed, plus code, elapsed, output-branch-disabled flag and output bytes.", "Preserve the case's collected_code, has_exited and session_exit_code observation, and require the original strict result.", "Run the already-added closed-output control within the ordinary target; its passing result is helper coverage, not a substitute for this physical PTY case."],
    },
]

record = {
    "schema": "intel_original_failures_static_causal_review_v1",
    "reviewed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "verdict": "ONE_SOURCE_PROVEN_FIXTURE_CONTRACT_REPAIR; THREE_ORIGINAL_FAILURE_CAUSES_REMAIN_OPEN; NO_NEW_PRODUCTION_PATCH_PROPOSED",
    "review_scope": "Four original cabc Intel failures only. Read-only fixed-source review, exact saved artifact member reads and isolated artifact generation; no native test/build, host modification, ref mutation or changes to CI budgets/assertions.",
    "original": {"head": BASE, "actual_merge_commit": MERGE, "tree": BASE_TREE, "artifact_id": 13361109041, "collector_review_blob": "493bceae8e704b162d85e8169d6c99f3763fa7f4"},
    "candidate": {"head": CURRENT, "tree": CURRENT_TREE, "scope": "Current A before the separately pending App parent-liveness candidate. Later unrelated A changes do not constitute new evidence for these Intel cases."},
    "raw_evidence": raw_evidence,
    "core_final_trace_projection": core_projection,
    "pty_exact_roster": pty_roster,
    "already_passed_at_original_intel_head": [entry for entry in pty_roster if entry["case"] in {"tests::pty_preserving_inherited_fds_keeps_python_repl_running", "tests::pty_python_repl_readiness_waits_for_execution_after_input_echo"}],
    "pty_xml_scope": "The original XML contains one Bazel target error wrapper; the complete libtest stdout supplies 30 cases, 28 PASS and 2 FAIL. Do not count the XML wrapper as one unit test.",
    "unchanged_production": unchanged,
    "cases": cases,
    "fresh_hosted_acceptance": {"platform": "original macOS Intel x86_64-apple-darwin lane", "requirements": ["Bind actual tested merge/tree and the reviewed source blobs.", "Use complete exact-case original stdout/XML at the same source; record cached target status and retries separately.", "Do not convert a network/Python/helper early return, target-only PASS or omitted success line into exact-case qualification.", "Preserve all original budgets, input sizes, byte comparisons and assertions; no new broad test group is requested.", "A rerun PASS is evidence for that exact source/platform attempt. It does not retroactively establish the cause of an earlier timeout."]},
    "original_platform_gate_closed_by_this_review": 0,
    "counts_do_not_update": "The original 48-name ledger and whole-project blocker totals are not modified by this review.",
    "source_manifest": "source-manifest.json",
    "source_rows_verified": len(sources),
    "archive_extraction_receipt": "core-raw-extraction-receipt.json",
    "read_failure_preserved": "Initial exact path read on rog returned FileNotFoundError. CI identified the original owner as desktop. Subsequent authorized reads used desktop and pinned the original file version; no archive was moved or downloaded.",
}
(ROOT / "causal-review.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")

summary = """# macOS Intel 原失败因果复核

## 结论

**本次没有发现可凭现有证据直接修复的 PTY 或 forward 生产缺陷。** `turn_state` 的测试夹具与真实 WebSocket 权限隔离规则存在已核实冲突，A 中的夹具修正针对这一冲突；其余三个旧失败的根因仍开放。此次只读审计不增加任何 Intel 平台闭合项。

| 原精确用例 | 原 Intel 事实 | 当前 A 的实际作用 | 结论 |
|---|---|---|---|
| `websocket_turn_state_persists_within_turn_and_resets_after` | 只读预热成功后提交 Disabled；仅一次成功握手、一个预热请求，最终 1 对 4 | 同权限原例固定启动权限；独立真实权限变化例要求 2 次握手和 `[1,3]` 请求 | 夹具冲突有源码及完整原日志支持；新 Intel 资格待原 CI |
| `forwarder_runs_commands_and_transfers_files` | 13 MiB **写入阶段** 30.603316921 秒超时 | 仅补 relay 接收进度与目的文件大小诊断 | 不是 close 阶段失败；生产根因未知 |
| `pty_dropped_output_receiver_keeps_draining_child` | portable 启动 13.942 ms；2.028 s 时仍未观察到退出，只有 `python_started` | 此用例及 PTY 生产源码完全未变 | drain 根因未知；preserved-FD 分支当次尚未执行 |
| `pty_close_stdin_preserves_large_input_and_delivers_eof` | 实际 `(-1, "__complete__")`，预期 `(0, "__complete__")` | 停止轮询已关闭的输出分支；区分三种退出结果并记录会话状态 | 合理的夹具修正，但不能证明旧 Intel 的 -1 来自该分支 |

## 固定来源与原文

原候选 `cabcb40d36e116beaa65750e1f674c52035da785`，实际测试 merge `28af7f705fa1024b9a6d2ef751fec116002260eb`，tree `b2d7f038d6d88156bc6a4cb29c8703f69b808f29`。本次 A 源码固定于 `bd7631e98f295fefad7654865cea497ceacf7d06` / tree `7d703610ae4f778ad305ebc139860d276f416e8c`。

已读取完整 PTY 原日志 3,403 B（SHA256 `7cd3de65…`）及原 XML 3,870 B；从原 desktop 已保存 ZIP 精确读取并核验 forward 全文 632 B（`228e852e…`）、Core shard10 final 全文 2,914,739 B（`1cfd18fd…`）。读取绑定同一文件 version，逐 chunk SHA256、解压 CRC 与原成员 SHA256 全部一致；未重新下载或运行 native job。完整哈希和 27 份固定源文件身份见机器报告及 `source-manifest.json`。

PTY 原日志实际有 **30 个用例，28 PASS / 2 FAIL**。`pty_preserving_inherited_fds_keeps_python_repl_running` 和 `pty_python_repl_readiness_waits_for_execution_after_input_echo` 都有明确 `ok` 行，应保留这两项成功事实。Bazel XML 的一个 error 是目标包装结果，不是一条单元用例。

## 能解释的部分

原 `turn_state` 测试要求“只读预热 → 完全访问 turn”仍只有一条物理连接。但生产 `WebsocketConnectionIdentity` 明确保留 sandbox 与 sandbox_mode，权限变化就要重新握手；它在新握手完成前保留旧连接。旧服务器按一条连接的完整脚本串行处理，正在等旧连接的第二个请求，因而不能并行完成新握手。完整失败原文恰好只有预热的 request 0 和 `warm-1` completion，随后最终断言 1 对 4。

A 没有删除权限隔离。原同权限用例仍要求一次握手、四次请求以及原 turn-state 清理关系；新增并发服务器用例保留原权限变化序列，要求两次真实握手、`[1,3]` 物理请求、真实工具结果和相同的状态清理关系。该源码修正能解释原夹具冲突，不能代替新 Intel 结果。

## 仍不能解释的部分

forward 原错误发生在 `fs_write_file`，后续 read-back、加密断言、`connection.close()` 和 forwarder shutdown 尚未到达。当前新增计数在 relay **转发前**累计双向 opaque bytes，不能据此证明目的端收到、写盘完成或 ACK 已回。完整生产转发/分帧源码与 cabc 字节一致，因此当前 A 不构成这项超时的生产修复。

PTY drain 用例直接等待 `exit_rx` 的原 2 秒窗口，不使用修改后的输出收集器。源码中的 Unix reader 在输出接收者关闭后仍继续读取，不能把“drop receiver 就停止 drain”当已证根因。原日志只证明写入后的 side-channel marker 未出现，尚无真实 reader 字节/错误结果。

PTY close 的旧收集器把 deadline、exit channel 关闭及真正收到的 -1 都折成 -1。`__complete__` 证明 Python 已收到 EOF 并通过输入字节检查，不能证明 wait/reap 已成功。A 的三路诊断和关闭分支停用能消除歧义；新增关闭输出后再发送真实退出码的控制只验证夹具合同，不是旧 Intel 故障的物理反事实。实际 waiter 仍可能把 `child.wait()` 错误映射为 -1，具体错误目前未打印。

## 下一次原 Intel CI 的最小判定项

1. 保留精确 source/tree、完整目标日志与实际 case roster；缓存目标、重试及 helper/network/Python 提前返回要单独记，不能外推为精确用例通过。
2. `turn_state` 观察原例的一握手四请求，以及已有权限变化控制的两握手 `[1,3]`；保原状态、turn ID 和实际工具结果断言。
3. forward 若再超时，读取现有 A 的 before/after 接收量、relay task finished 与目的文件 metadata；仍须原 13 MiB 写入及完整读回通过才能通过该用例。
4. PTY drain 分别保 portable / preserved-FD 的阶段、2 秒结果与实际会话状态。第一分支失败不能算第二分支已运行。
5. PTY close 区分 `exit_code_received`、`exit_channel_closed`、`deadline_elapsed`，结合 `has_exited` 与 `session_exit_code`，继续要求原 `(0, "__complete__")`，不改 2/5 秒预算。

当前无需另开广泛测试或增加预算。若同样的 drain / write 超时再次出现，现有观测仍不足的部分继续开放，再针对真实读写或 wait 错误补最小诊断。其它主机的一次成功不能替代 Intel 资格，也不能反推旧超时的根因。
"""
(ROOT / "CAUSAL_REVIEW_ZH.md").write_text(summary)

output = {name: identity((ROOT / name).read_bytes()) for name in ["causal-review.json", "CAUSAL_REVIEW_ZH.md", "source-manifest.json", "core-raw-extraction-receipt.json", "original-forward-test.log"]}
(ROOT / "delivery-identities.json").write_text(json.dumps(output, indent=2) + "\n")
print(json.dumps(output, indent=2))
