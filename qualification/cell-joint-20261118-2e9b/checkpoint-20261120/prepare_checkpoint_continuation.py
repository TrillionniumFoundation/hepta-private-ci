"""Freeze an honest continuation; this does not execute or qualify experiments."""

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import hashlib
import json


ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent
PUB = ROOT / "next-publication"
EVIDENCE = PUB / "qualification/cell-e6-metrics-integration-20261119"


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


now = datetime.now(timezone.utc)
e6 = read(ROOT / "e6_640_checkpoint_fragment.json")
e6["published_evidence_head"] = "02d5b32dd81c4fc820d8468c617908c8f2907a50"
e6["published_evidence_tree"] = "aa42cce8faa9a30455fb0159103910d2818ac721"
e6["published_evidence_pr"] = 6776
e6["publication"] = {
    "source_parent": e6["source_commit"],
    "files": 30,
    "preexisting_files": 15750,
    "preexisting_bytes_unchanged": True,
    "full_original_blob_gate_base": "d83f70f38137a99a86a3afd122199ba9cdae4f79",
    "full_original_blob_gate_changed_paths": 98,
    "full_original_blob_gate_exit": 0,
    "original_blob_tests": 7,
    "original_blob_tests_exit": 0,
    "maximum_blob_bytes": 512000,
    "result_sha256": digest(WORK / "e6_owner_work/publication640_RESULT.json"),
    "new_product_qualification": False,
    "evidence_directory": "../cell-e6-metrics-integration-20261119/e6-640-publication-readback",
}
e6["noupdate6"]["physical_observation"] = {
    "C_source_journal_bytes": 6456,
    "C_source_witness_bytes": 672,
    "C_cell_journal_bytes": 654,
    "C_cell_witness_bytes": 224,
    "C_generation_journal_bytes": 40,
    "C_generation_witness_bytes": 112,
    "lengths_are_not_completion_proof": True,
    "physical_metadata_files": 785,
    "exported_nonkey_physical_files": 52,
    "private_key_bodies_exported": False,
    "original_business_debug_image_bodies_exported": False,
}
parts = read(WORK / "e6_owner_work/c_identity_evidence/archive-parts.json")
e6["noupdate6"]["original_archive"] = {
    "files": 229,
    "raw_bytes": 67362373,
    "compressed_bytes": parts["archive_bytes"],
    "sha256": parts["archive_sha256"],
    "parts": 3,
    "maximum_part_bytes": 480000,
}
e6["current_source_unavailable_diagnosis"] = {
    "historical_exact_root_cause_established": False,
    "actual_error": 'Invalid("Unavailable")',
    "static_path": "ACK loss recovery calls task.require_current before Source publication; shared Root CURRENT try_lock can fence on concurrent use",
    "source_unavailable_display": "Circuit task owner is unavailable or fenced",
    "short_Unavailable_alone_does_not_identify_lane_transport_artifact_finaluse_or_clock": True,
    "next_candidate": "Read the exact Source publication before CURRENT; Missing/Pending waits only inside the original deadline; after Completed preserve original CURRENT/capture/admission checks",
    "failure_only_payload_free_phase_diagnostics_planned": True,
    "generic_exact_replay_serialization_proven": False,
    "full_Root_plus_Feature_ACK_component_positive_constructed": False,
    "mechanism_component_controls_must_not_be_reported_as_full_owner_positive": True,
    "new_candidate_compilation_or_native_at_snapshot": False,
    "original_2s_ACK_500ms_64_read_and_authority_deadlines_changed": False,
}
write(ROOT / "e6_640_checkpoint_fragment.json", e6)

cold = read(ROOT / "cold_checkpoint_fragment.json")
cold["status"] = "OBSERVED_NOT_FINAL; formal gates paused until ordinary C succeeds on a new frozen source"
cold["ordinary_latest_confirmed_freeze"] = e6["source_commit"]
cold["ordinary_latest_confirmed_tree"] = e6["source_tree"]
cold["ordinary_noupdate6_status"] = "Original parent failed Invalid(Unavailable); zero completed C; does not qualify cold composition"
cold["remote_gates_still_waiting_owner_release"] = False
cold["remote_gates_waiting_specific_C_fix"] = True
cold["next_ordinary_frozen_source_is_not_yet_cold_qualified"] = True
cold["pending_source_snapshot_640_inputs_sha256"] = "66079377d71b92229cd06723f07ac4fcd771afaeb803899d784766b7a7854bc3"
cold["independent_design_peer_review"] = {
    "evidence": "../cell-e6-metrics-integration-20261119/checkpoint-next-gate-preparation/E6_DESIGN_REVIEW.md",
    "original_design_bytes_preserved": True,
    "late_original_controller_authorization_still_needed": True,
    "revocation_policy_freshness_after_writer_retirement_still_needed": True,
    "same_selector_and_head_key_correctly_rejected": True,
    "planned_controls": 34,
    "executed_controls": 0,
}
cold["isolated_primitive_draft"] = {
    "evidence": "../cell-e6-metrics-integration-20261119/adopt-head-use-primitive-draft",
    "source_files": 3,
    "unformatted_source_lines": 649,
    "wire_fields": 68,
    "decode_limit_bytes": 16384,
    "default_disabled": True,
    "private_relative_fact_denies_all_product_authority": True,
    "production_enrollment_or_custody_implemented": False,
    "module_wired": False,
    "compiled": False,
    "native_controls_executed": 0,
    "signatures_issued": 0,
    "original_first_draft_revision_preserved": True,
    "static_readback_sha256": "3dcc8e9f1a51eba22dddc3e8cc0ae7529498a4318c82c55a98124fd1b356a32c",
    "publication_plan_sha256": "045282aff007bc699115fc4ac9d504c79d5b13bfb7ba221eec021e73fc909908",
}
write(ROOT / "cold_checkpoint_fragment.json", cold)

ci = read(ROOT / "ci_238_checkpoint_fragment.json")
mac = ci["mac_fixture_candidate"]
mac["status"] = "FIXTURE_PATCH_FORMATTED; NATIVE4_AND_NATIVE5_DEPENDENCY_FAILURES; ZERO_NATIVE_CASES"
mac["independent_dependency_preparation"]["status"] = "Exact shallow preparation and 54-member archive independently checked by root"
mac["independent_dependency_preparation"]["evidence_directory"] = "../cell-e6-metrics-integration-20261119/mac-crossterm-shallow"
mac["native5_agent_report"] = {
    "owner": "dpty-5787097273cf95e18b5e691a3ebabaf0c509a6acd97972dd72aa6cfa2a72dd77",
    "idempotency_key": "mac-fixture-native5-offline-20261120-e9e051",
    "controller_sha256": "7c6d9541d88719544437be4e9723980243660c2e6d3a5b5a911630fe368b52d2",
    "result_sha256": "4eb76583bf64b106a94432cbab91a756fae253eb91194b623d3bacc35ca5976f",
    "terminal": True,
    "project_command_exit": 101,
    "project_command_seconds": 0.289810,
    "owner_seconds": 1.081012,
    "native_cases": 0,
    "source_inventory_unchanged": True,
    "Cargo_lock_and_product_guards_unchanged": True,
    "new_missing_dependency": "https://github.com/openai-oss-forks/tokio-tungstenite",
    "new_missing_revision": "0e5b2d73aa18dd9f0a50ee9ff199d5aef7594186",
    "immediate_additional_Cargo_retry": False,
    "root_has_read_original_receipt_at_this_snapshot": False,
    "next_work": "Read exact locked Git dependency/cache inventory before bounded exact-commit material preparation",
}
mac["crossterm_cache_seed_agent_report"] = {
    "first_attempt_retained": "Overbroad any-Git precheck refused an unrelated Git process before fetch/cache writes",
    "second_attempt_owner": "dpty-19c98d769829873767f45bccf0ffe55fba7d83b095147fb9b8d9fcf886737b71",
    "second_result_sha256": "6fc8ef470a73caac73479c7e7eb8f7d40c2968f0aff50ad345ac468bd43ffc70",
    "local_fetches": 1,
    "network_fetches": 0,
    "owner_seconds": 0.276758,
    "target_commit": "45fecb9508105988f42fe6ff0441783ed3717f92",
    "target_tree": "f43069917d73c60e5286f56fef318cb13febf204",
    "old_partial_pack_hashes_unchanged": True,
    "configuration_changed": False,
    "source_or_lockfile_changed": False,
    "root_has_read_original_receipt_at_this_snapshot": False,
}
native5_result_path = WORK / "mac_dependency_work/native5/remote/RESULT.json"
seed_result_path = WORK / "mac_dependency_work/crossterm-cache-seed-2/remote/RESULT.json"
seed_first_path = WORK / "mac_dependency_work/crossterm-cache-seed-1/remote/RESULT.json"
native5_stderr_path = WORK / "mac_dependency_work/native5/remote/native-project.stderr"
assert digest(native5_result_path) == mac["native5_agent_report"]["result_sha256"]
assert digest(seed_result_path) == mac["crossterm_cache_seed_agent_report"]["second_result_sha256"]
assert digest(seed_first_path) == "7683cec5f435efafac561bb3685fbdcae086fd9c49fc8d6847ee5a817684d144"
assert digest(native5_stderr_path) == "9a99fc15d540041793f501c2f79accc7af8fda0a23b59a103b5439272dc80053"
native5_result = read(native5_result_path)
seed_result = read(seed_result_path)
assert native5_result["exit_code"] == 1
assert native5_result["stages"][0]["exit_code"] == 101
assert seed_result["status"] == "EXACT_LOCAL_CACHE_REF_READY"
mac["native5_agent_report"]["root_has_read_original_receipt_at_this_snapshot"] = True
mac["native5_agent_report"]["original_result"] = native5_result
mac["native5_agent_report"]["project_command_seconds"] = native5_result["stages"][0]["wall_seconds"]
mac["native5_agent_report"]["owner_seconds"] = native5_result["owner_wall_seconds"]
mac["native5_agent_report"]["evidence_directory"] = "../cell-e6-metrics-integration-20261119/mac-native5-readback"
mac["crossterm_cache_seed_agent_report"]["root_has_read_original_receipt_at_this_snapshot"] = True
mac["crossterm_cache_seed_agent_report"]["owner_seconds"] = seed_result["owner_wall_seconds"]
mac["crossterm_cache_seed_agent_report"]["original_seed1_result_sha256"] = digest(seed_first_path)
write(ROOT / "ci_238_checkpoint_fragment.json", ci)

config = {
    "observed_utc": now.isoformat().replace("+00:00", "Z"),
    "observed_local": now.astimezone(ZoneInfo("America/New_York")).isoformat(),
    "e6_latest": e6,
    "e5_codec": read(ROOT / "e5_codec_checkpoint_fragment.json"),
    "cold_D_review": cold,
    "ci_238": ci,
    "interpretation": "The exact #6709 accounting fix and its original controls remain integrated. Original student evaluation remains ResearchNoUpdate (both A students 1/4; future P and both students 0/4); all used call budgets and historical negatives remain. Sixteen public project materials are complete, but source-only bounded codec/token measurements admit no original fixed-prefix training: 15/16 inputs exceed the original limit; growth curves remain null and authenticated users remain zero. E3 bounded material recovery is terminal incomplete. Independent E6 source 640bac3c passes 11+16+5 native components, original source/caller checks and project lint; its original NoUpdate6 parent still fails Invalid(Unavailable) before completed C. Evidence is published at 02d5b32d; precise historical cause remains unknown, with ACK/CURRENT overlap under source-level investigation. Cold composition and default-disabled Adopt primitive remain unqualified. Joint CI at 238 retains real failures and the PR-metadata/base-ref mismatch; two Mac fixture changes are formatted but native attempts remain blocked on exact dependency material. Chain's original liveness and full-system-cost failures remain. All ten joint qualification flags stay false; independent branch evidence is not a joint execution.",
    "checkpoint_readbacks": {
        "E6_published_negative": "../cell-e6-metrics-integration-20261119/e6-640-publication-readback",
        "E5_final_exact_head_gate": "../cell-e6-metrics-integration-20261119/e5-codec-final-readback",
        "CI_base_identity": "../cell-e6-metrics-integration-20261119/ci-base-reconciliation",
        "Mac_original_attempts": "../cell-e6-metrics-integration-20261119/mac-fixtures-20261120",
        "Mac_exact_dependency_material": "../cell-e6-metrics-integration-20261119/mac-crossterm-shallow",
        "next_checkpoint_original_blob_gate_preparation": "../cell-e6-metrics-integration-20261119/checkpoint-next-gate-preparation",
    },
}
write(ROOT / "next_checkpoint_config.json", config)

replacements = {
    "OBSERVED_LOCAL": now.astimezone(ZoneInfo("America/New_York")).isoformat(),
    "E6_TABLE": "实际源码 `640bac3c` 的 native11、retirement16、delivery5 全过；原完整 NoUpdate6 仍在 C 回读时报 `Invalid(Unavailable)`，新证据已发布到 `02d5b32d`",
    "CI_CURRENT": """238 的工程与 v8 检查通过，但不能称为全 CI 通过。architecture 的精确 head 检查通过，base 与 required job 失败；blocking 中原 contract、cargo-deny 及部分 Windows／Mac 检查失败。cargo-deny 日志读取三次出现 Transport closed，原因仍未知。contract 指出的四项历史外仓 workflow 引用继续保留，没有改检查器或豁免它们。

对 base 身份作了额外原 API 对照：PR 元数据报告 `2742bc37`，实际同名 base branch ref 为其直接后继 `06133474`，prospective merge 的两个 parent 是 `06133474` 与 `238fc484`。因此实际构建基于已经推进一步的分支；PR 元数据为何未同步仍未知。没有换 base branch、改分支或声称平台缓存故障。[完整 API 原件与对照](../cell-e6-metrics-integration-20261119/ci-base-reconciliation/)。""",
    "MAC_FIXTURE_DETAIL": """Mac 的两个具体 fixture 修改使用真实 canonical 临时目录，并让 reopen 的 fleet 路径与原 create_run 一致；产品拒绝检查和原断言不改。原 formatter 已通过，项目 native 尚未通过。前两次设置／缺依赖失败、第三次人工中断及其观测限制都保留。

第四次实际项目命令最终因 crossterm 依赖下载失败退出 101，命令 3,085.996 秒、外层 owner 3,087.346 秒，0 个 Rust 测试；它曾被工具标为 lost/target_reboot，但独立 OS 观察证实原 owner 当时仍活着，之后才真实终止。期间没有启动第二 Cargo，也没有按 PID 杀进程。不能把这段记录写成已经证明机器重启、死锁或零网络进展。

随后用独立目录取得锁定的 crossterm `45fecb95` 单提交浅对象，严格 fsck 通过，实际 22.897 秒；完整 54 成员归档已独立逐字回读。目标 cache 的本机 seed 成功，未改锁文件、配置或旧 partial pack。独立第五次原 `just test --locked --offline` 在 0.290 秒后因另一未缓存的精确 tokio-tungstenite revision 退出 101，仍是 0 个 native case。seed／第五次的数字在本次冻结时来自执行 agent 的终态回报，完整原件正在归档；不会据此声称 fixture 已通过。下一步先检查全部锁定 Git 依赖的材料缺口。[原始尝试与 fixture 说明](../cell-e6-metrics-integration-20261119/mac-fixtures-20261120/) · [精确依赖原件](../cell-e6-metrics-integration-20261119/mac-crossterm-shallow/)。""",
    "E5_CODEC_DETAIL": """后续五个可独立审阅的 Draft 为 [#6786](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6786)、[#6787](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6787)、[#6788](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6788)、[#6789](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6789)、[#6790](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6790)。最终证据 head 为 `148e37c26586677e83f0e57e100def8805c1a020`。11 个 Python 模块实现有界的 source 输入、动作表达、回放边界及 token 测量；输入先于 target 冻结，16 项 after-poison 控制未改变输入选择。

实际结果：16/16 完整结构往返，17 个 runtime 文件逐字一致；11/16 的动作在受限解释器中可执行，只有 2/16 通过有限静态闭包检查。原 Qwen tokenizer 的 CPU-only 测量显示 15/16 输入超过 4096 token，15/16 完整序列超过 3584，5/16 target 超过 384，6/16 prompt 字节超过 65,536。只有原第 12 个 attrs 材料同时落入这些界限；它不在通过的固定 prefix 内，也还没有 optimizer 单位、完整预算和未来验收绑定。

因此原 1／4／16 prefix 均不获训练准入，没有调换来源、截断后再声称完整输入，或用 after 内容选择训练输入。原材料中的测试及 fixture 可能本来来自修复后的测试，故不声称所有上游材料都没有 after 字节。该控制验证的是这版输入选择的边界。

本轮模型权重加载、forward、生成、训练及新增 native replay 都为 0。token 测量 owner 为 8.432 秒，其 child 7.460 秒和 CPU 11.568 秒是不同且重叠的口径。最终 `63f49455→148e37c2` 的 58 个变化路径实际通过原 blob gate，512,000 字节及 allowlist 不变；该门不是训练收益验证。[最终原 gate 回读](../cell-e6-metrics-integration-20261119/e5-codec-final-readback/)。""",
    "E6_READ65_DETAIL": """新的 [已发布证据 `02d5b32d`](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/02d5b32dd81c4fc820d8468c617908c8f2907a50/evidence/e6-c-identity-noupdate6-20261120) 同时保留 `2b8125e3` 与 `640bac3c` 两次原尝试。前者真实完成 415 项 source／47 模块、907 protected、320 targeted、1,159 full caller 检查，并通过 native11、retirement16 和 delivery5；原 NoUpdate5 随后在“signed ordinary request differs from the published Feature task”处失败，实际读到 request55，没有完成 C。此前 request65 的失败记录仍保留，64 上限没有提高；request65 是本地拒绝，不是第 65 次成功读取。

`640bac3c` 只修正 C fixture 的真实身份来源：runtime 来自解码 configuration，model tuple 来自其 semantic digest，artifact set 来自 bundle digest。原 issuer、签名、产品 guard、完整父流程及所有期限均不变。该精确源码重新通过完整 415／907／320／1,159 source 门、原 `just fix --locked --offline -p codex-hepta-agentd` 与 native11＋16＋5；源码前后字节一致。

完整原 NoUpdate6 的真实首错变为 `Invalid(\"Unavailable\")`，仍是 1 case／1 fail。case 75.141 秒、项目命令 75.947 秒、owner 127.650 秒，不能叠加。C source journal／witness 已有 6,456／672 字节，Cell journal／witness 已有 654／224 字节，generation 仍为 40／112；这些写入不等于 C 完成。原件 229 文件、67,362,373 字节归档为 1,025,424 字节，密钥及可能包含密钥的 debug business image 正文未导出。

静态调用链显示，两秒 ACK 丢失后的 observer 在查看 Source publication 前会检查 CURRENT；该私有 Root 通道对并发 try_lock 失败会永久 fence。这是一条具体可修复的失效路径，但现有旧日志不能证明本次历史失败一定由它造成，也尚不能排除 transport、Artifact、FinalUse 或时钟路径。下一候选只前置同一 Source publication 观察：Missing／Pending 在原 deadline 内等待，Completed 后继续原 CURRENT、capture 和 expected admission 检查；没有把 Unavailable 改为继续等待。

真实 Root lane 机制控制、Feature ACK 组件控制和完整原父流程将分别报告，不冒称已经构造同一个完整 Root＋Feature ACK 正控。实际 Root observe_after 故障注入尚未完成。新发布 head 的原 7 项 blob 单测及原全 98 路径字节门通过，全部 15,750 个既有文件未变；这些仍不授予原父流程资格。[联合回读绑定](../cell-e6-metrics-integration-20261119/e6-640-publication-readback/)。""",
    "COLD_D_DETAIL": """冷恢复分支当前完成的是观察性源码组合，保留全部原 cold 新增文件、原拒绝条件和独立 target；1,214 个边界、927 条 protected 记录还未在最终组合执行正式门。原 NoUpdate6 未完成 C，故暂停冷正式编译／父流程，等待具体修复后的新冻结源；不能继承独立普通分支的通过结果。三文件 D 身份修正也是源码草案，实际新 D、FinalUse 均为 0。

Adopt 的 240 秒 head 与 300 秒真实退休等待之间的缺口已有 [独立设计](../cell-e6-metrics-integration-20261119/adopt-head-use-design/)：专用历史内容读取、新目的 Selector、真实 C 完成与新 D 的绑定，以及相应 Root／恢复／live 检查。34 个拒绝控制只是计划，0 个已执行。独立复核指出，最后还需要依赖已确定 selection／intent 的原 controller authorization，以及旧 writer 退休后的真实 policy／撤销新鲜度来源；不变的 frontier 不能代替当前有效性。

另有 [三个 Rust 文件的默认关闭原语草案](../cell-e6-metrics-integration-20261119/adopt-head-use-primitive-draft/)，共 649 行、68 个固定字段、16 KiB 严格解码上限。私有相对验证结果拒绝所有产品授权；没有 module 接线、实际编译、签名、native 或生产 enrollment。首次 subject／policy 构造依赖问题已在源码自审修正，原草案 revision 仍保存。它提供可审阅的后续实现边界，不是已实现 Adopt 冷启动。""",
}
template = (ROOT / "CURRENT_PROGRESS.next_template.md").read_text()
template = template.replace("的最新已发布证据为 `ab5e792d", "的此前已发布证据为 `ab5e792d")
for key, value in replacements.items():
    assert "{{" + key + "}}" in template
    template = template.replace("{{" + key + "}}", value)
assert "{{" not in template
template = template.replace(
    "seed／第五次的数字在本次冻结时来自执行 agent 的终态回报，完整原件正在归档；不会据此声称 fixture 已通过。",
    "两次 seed 的真实 RESULT、第五次的完整 RESULT 和原错误日志均已独立读取并核对 SHA；它们继续表明 fixture 未通过 native 验证。[新增终态原件](../cell-e6-metrics-integration-20261119/mac-native5-readback/)。",
)
output = PUB / "qualification/cell-joint-20261118-2e9b/CURRENT_PROGRESS.md"
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(template)
print(json.dumps({"observed_utc": config["observed_utc"], "markdown_bytes": output.stat().st_size, "markdown_sha256": digest(output)}, ensure_ascii=False))
