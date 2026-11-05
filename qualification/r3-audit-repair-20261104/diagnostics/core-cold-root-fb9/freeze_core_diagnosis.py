from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent.parent
NAME = "suite::multi_agent_resume::cold_root_resume_restores_agent_identity_and_role_on_followup"
ERROR = "thread 01a1a9fe-9432-7365-982c-7a0f11490eee not found"


def identity(data: bytes) -> dict:
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def anchor(path: str, start: int, end: int) -> dict:
    data = (ROOT / "source" / path).read_bytes()
    lines = data.decode().splitlines(keepends=True)
    return {"path": path, **identity(data), "start_line_1_based": start, "end_line_inclusive": end,
            "text": "".join(lines[start - 1:end])}


def xml_member(path: Path) -> dict:
    data = path.read_bytes()
    needle = ('name="' + NAME + '"').encode()
    position = data.index(needle)
    assert data.count(needle) == 1
    start = data.rfind(b"<testcase", 0, position)
    end = data.index(b"</testcase>", position) + len(b"</testcase>")
    member = data[start:end]
    return {"source_path": str(path.relative_to(WORKSPACE)), "source_identity": identity(data),
            "byte_start_inclusive": start, "byte_end_exclusive": end,
            "line_start_1_based": data[:start].count(b"\n") + 1,
            "line_end_1_based": data[:end].count(b"\n") + 1,
            "member_identity": identity(member), "text": member.decode()}


def main() -> None:
    comparison_path = WORKSPACE / "ci-audit/recovered-20261105/full-f825-to-fb9-exact-case-comparison-v1.json"
    comparison = json.loads(comparison_path.read_text())
    compared = next(x for x in comparison["two_new_failures"] if x["name"] == NAME)
    old = xml_member(WORKSPACE / "ci-audit/recovered-20261105/full-owning-compressed-archive/full-junit.original")
    new = xml_member(WORKSPACE / "ci-audit/recovered-20261105/full-fb9-complete-archive/decoded-verified-v1/full-workspace.junit.xml")
    assert 'time="8.780"' in old["text"] and "<failure" not in old["text"]
    assert 'time="8.209"' in new["text"] and ERROR in new["text"]
    assert 'type="test failure with exit code 101"' in new["text"]
    raw_path = WORKSPACE / "ci-audit/recovered-20261105/full-fb9-complete-archive/decoded-verified-v1/full-workspace.log"
    data = raw_path.read_bytes()
    lines = data.splitlines(keepends=True)
    selection = b"".join(lines[73016:73031])
    assert NAME.encode() in selection and ERROR.encode() in selection
    assert data.count(ERROR.encode()) == 1
    raw = {"source_path": str(raw_path.relative_to(WORKSPACE)), "source_identity": identity(data),
           "line_start_1_based": 73017, "line_end_1_based": 73031,
           "byte_start_inclusive": sum(map(len, lines[:73016])),
           "byte_end_exclusive": sum(map(len, lines[:73031])),
           "excerpt_identity": identity(selection), "text": selection.decode(),
           "exact_error_occurrences_in_complete_raw": 1}
    (ROOT / "core-cold-root-fb9-original-block.log").write_bytes(selection)
    source_records = []
    for receipt in sorted(ROOT.glob("source-read-*-verification.json")):
        for row in json.loads(receipt.read_text()):
            rel = Path(row["path"]).relative_to(Path("research-audit/fb9-new-failures-20261105/source"))
            if str(rel).startswith("codex-rs/exec-server/"):
                continue
            body = (ROOT / "source" / rel).read_bytes()
            actual = identity(body)
            assert all(actual[key] == row[key] for key in actual)
            source_records.append({"path": str(rel), **actual,
                                   "native_version": row.get("native_version", row.get("version")),
                                   "verification_receipt": receipt.name})
    keys = [row["path"] for row in source_records]
    assert len(keys) == len(set(keys))
    paths = {
        "test": "codex-rs/core/tests/suite/multi_agent_resume.rs",
        "codex": "codex-rs/core/src/codex_thread.rs",
        "session": "codex-rs/core/src/session/mod.rs",
        "live": "codex-rs/thread-store/src/live_thread.rs",
        "writer": "codex-rs/thread-store/src/local/live_writer.rs",
        "manager": "codex-rs/core/src/thread_manager.rs",
        "protocol": "codex-rs/protocol/src/error.rs",
        "store_error": "codex-rs/thread-store/src/error.rs",
        "init": "codex-rs/core/src/session_rollout_init_error.rs",
        "spawn": "codex-rs/core/src/agent/control/spawn.rs",
        "mock": "codex-rs/core/tests/common/responses.rs",
        "residency": "codex-rs/core/src/agent/control/residency.rs",
        "fixture": "codex-rs/core/tests/common/test_codex.rs",
    }
    evidence = {
        "original_flushes_before_shutdown": anchor(paths["test"], 349, 371),
        "codex_flush_delegates": anchor(paths["codex"], 330, 339),
        "session_preserves_store_error_as_io_other": anchor(paths["session"], 1355, 1367),
        "live_flush_two_operations": anchor(paths["live"], 268, 282),
        "metadata_after_flush": anchor(paths["live"], 388, 416),
        "missing_live_recorder_and_flush_path": anchor(paths["writer"], 298, 351),
        "shutdown_removes_recorder": anchor(paths["writer"], 155, 199),
        "bare_store_error_display": anchor(paths["store_error"], 18, 26),
        "different_manager_error_display": anchor(paths["protocol"], 91, 102),
        "manager_get_maps_missing_thread": anchor(paths["manager"], 1859, 1866),
        "session_init_adds_prefix": anchor(paths["init"], 8, 36),
        "resume_read_maps_missing_thread": anchor(paths["manager"], 2803, 2810),
        "fixture_restart_calls_shutdown_then_resume": anchor(paths["fixture"], 589, 603),
        "shutdown_wait_does_not_propagate_store_shutdown_error": anchor(paths["session"], 930, 939),
        "thread_registry_insertion": anchor(paths["manager"], 2708, 2735),
        "startup_delivery_ack_before_return": anchor(paths["manager"], 2409, 2414),
        "spawn_commit_before_initial_input": anchor(paths["spawn"], 730, 742),
        "initial_input_after_registration": anchor(paths["spawn"], 790, 810),
        "recorder_before_custom_matcher": anchor(paths["mock"], 877, 887),
        "matcher_composition_order": anchor(paths["mock"], 1252, 1287),
        "worker_id_selection_is_only_parent_id": anchor(paths["test"], 266, 288),
        "residency_unload_path": anchor(paths["residency"], 117, 178),
        "residency_excludes_root_and_protects_active_work": anchor(paths["residency"], 246, 280),
        "later_reload_lookup_has_explicit_expect": anchor(paths["test"], 474, 481),
    }
    proposal = json.loads((ROOT / "core-diagnostic-proposal/repair-manifest.json").read_text())
    result = {
        "schema": "hepta.core-cold-root-resume.readonly-diagnosis.v1",
        "frozen_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": "CAUSE_OPEN_SOURCE_SUPPORTED_DIAGNOSTIC_PROPOSAL_ONLY",
        "source_tree": "fb9e131272f7e7a138d6c0d1af2b048b9a6ab7ff",
        "native_full_job": "1a1a9f68261-fc05-3a71",
        "case": {"classname": "codex-core::all", "name": NAME},
        "comparison": {"path": str(comparison_path.relative_to(WORKSPACE)),
                       "identity": identity(comparison_path.read_bytes()),
                       "git_blob_published": "12ba495fa1c545f5e56f9444f420f23dba61b59e",
                       "data": compared},
        "original_evidence": {"old_case": old, "current_case": new, "current_full_raw_block": raw},
        "source_acquisition": {
            "mechanism": "Typed read_multiple_files / immutable-version binary_read or fixed Git blob cross-checked with actual file_info SHA; read-only, no native process job launched.",
            "snapshot_limit": "Each file is independently versioned. These reads are not an atomic whole-tree snapshot; the source tree/job binding comes from CI's unchanged-source receipts.",
            "files": source_records,
        },
        "confirmed": [
            "The old f825 exact case passed in 8.780 s; current fb9 failed in 8.209 s with ordinary Rust exit 101. This is not a nextest timeout. Different source/program identities are retained.",
            "The complete current raw block and XML contain only the bare thread-store-style error; no phase, traceback, selected child identity or shutdown/eviction event is present.",
            "ThreadManager::get_thread produces CodexErr::ThreadNotFound whose display is `no thread with id: ...`, unlike the current error. The two direct get_thread ? sites are therefore not supported as the source of this exact text.",
            "Session-init maps ThreadStoreError::ThreadNotFound to `Failed to initialize session: ...`; the inspected rollout-resume read mapper instead uses the different CodexErr::ThreadNotFound wording.",
            "The original sibling/worker/root flushes at lines 365-367 preserve a ThreadStoreError via io::Error::other without adding a prefix. LiveThread::flush first flushes the store, then applies pending metadata. This is a concrete compatible propagation path, not proof of the failed phase or specific cause.",
            "A missing live recorder produces the same ThreadStoreError. Shutdown/discard remove that recorder; this is intended fail-closed behavior for late writes and must not be converted to success merely to green this test.",
            "The ordinary initial input is dispatched after exact runtime insertion, delivery acknowledgement and spawn reservation commit. Therefore simple actual INITIAL_TASK-before-registration is not supported by this inspected order.",
            "ResponseMock records before a later custom matcher, while this test chooses a child only by parent ID. Unmatched-request selection is a real fixture observation risk, but the original run has no request bodies to prove it happened or caused this error.",
        ],
        "open_hypotheses": [
            "Which of the three explicit flushes, or an uninspected wrapper path, produced the bare error.",
            "Whether the failing thread's live recorder had been shut down/retired, or post-flush metadata could not resolve the stored thread.",
            "Whether the fixture selected the intended worker/grandchild/sibling from recorded-but-unmatched requests.",
            "Whether any residency unload occurred. Capacity is three and only SubAgent sessions are residents; no eviction event is in the original output.",
        ],
        "rejected_shortcuts": [
            "No cold-reload failure is inferred from the test name.",
            "No old passing program or other platform scope is borrowed as current qualification.",
            "No retries, longer waits, ignored error, persistence bypass, capacity increase or matcher change is proposed as a proven fix.",
        ],
        "evidence_anchors": evidence,
        "diagnostic_proposal": proposal,
        "next_gate": {
            "package": "codex-core", "binary": "all", "exact_case": NAME,
            "source_before_after_required": True, "same_original_budgets_and_zero_retries": True,
            "raw_stderr_and_junit_required": True,
            "success_does_not_prove_historical_cause": True,
            "approval_and_execution": "Await root review and a future sole-CI exact-source scope. No native execution has been requested or performed by this audit.",
        },
        "ledger": "The new full failure stays OPEN. This receipt does not change any original 23 blocker ID, exit condition or scoped-closure count and does not delay the current A Draft publication.",
    }
    (ROOT / "core-cold-root-static-diagnosis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    md = f'''# Core cold-root 新失败：只读诊断与最小观测提案

结论仍为 **原因未明（OPEN）**。固定源 `fb9e131272f7e7a138d6c0d1af2b048b9a6ab7ff` 的原全量中，此例实际 8.209 秒普通 Rust 测试失败（退出码 101）；旧 f825 同名例为 8.780 秒 PASS。新旧程序 SHA 不同，旧通过不转借为当前资格。

原完整日志第 73017–73031 行和完整 JUnit 都只有 `Error: {ERROR}`，没有阶段或回溯。不能从名称推断“冷恢复失败”。精确原件、字节区间和哈希均在同名 JSON 中。

## 已收窄的错误链

`ThreadManager::get_thread` 缺线程会显示 `no thread with id: …`；会话初始化映射会带 `Failed to initialize session:`。这两条直接传播的文字与实际裸错误不同。

原测试第 365–367 行依次 flush sibling、worker、root。`CodexThread::flush_rollout → Session::flush_rollout → LiveThread::flush` 使用 `io::Error::other` 保留底层 `ThreadStoreError` 的裸显示，因而是已确认兼容的传播链。该链先刷 live writer，再同步待提交 metadata；缺 recorder 与 metadata 错误尚未区分。原源码明确 shutdown/discard 会移除 recorder，晚写应失败，不能把这类错误吞掉。

实际初始任务发送在 manager 插入 runtime、交付 ACK 和 spawn reservation commit 之后，不能仅凭观测到子请求就归因“注册晚于实际初始任务”。另一方面，共用 ResponseMock 的 recorder 位于自定义 matcher 之前，而本测试只按 parent ID 选择 worker；这是可审的观测风险，但原失败没有请求正文，尚不能证明本次命中了它。原 residency 容量三及实际卸载路径均已读；没有卸载事件证据，未建议增加容量或重启掩盖失败。

## 可审的独立诊断补丁

仅在原两次 manager lookup、三个 flush、一次 root restart 的原 Result 上增加 `inspect_err`，出错时打印固定阶段、该测试线程 ID 与原错误 Debug。返回的 Err、原 `?`、所有原请求、断言、sleep、timeout、shutdown 顺序均保持。成功路径无新增读/写/请求/等待；不读取共享 home 或日志正文。

源码后像 `{proposal['postimage']['git_blob']}`；补丁 `{proposal['patch']['git_blob']}`。六处逆替换精确还原原文件；隔离 Git 的 apply/check 与反向恢复均逐字验证。**未 rustfmt、未编译、未执行、未应用到 native 或任何 ref。** 此提案只增加错误定位，不是根因修复。

后续只需在 root 批准的未来同源原 CI scope 选中此原 case、沿用原预算和零重试，保留 stderr/JUnit 与实际程序/源身份。如果仍没有新增阶段标记，说明错误来自其余传播路径，应继续定位；如果仅 PASS，也不能追认本次历史原因。当前 A Draft 发布不应等待这项诊断；23 项原退出条件及状态计数不变。
'''
    (ROOT / "CORE_COLD_ROOT_DIAGNOSIS.zh-CN.md").write_text(md)
    print(json.dumps({name: identity((ROOT / name).read_bytes()) for name in
                      ["core-cold-root-static-diagnosis.json", "CORE_COLD_ROOT_DIAGNOSIS.zh-CN.md"]}, indent=2))


if __name__ == "__main__":
    main()
