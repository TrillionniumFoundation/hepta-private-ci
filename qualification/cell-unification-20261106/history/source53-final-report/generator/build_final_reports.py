#!/usr/bin/env python3
"""Generate one reviewable final candidate from closed evidence and actual Git registration.

Only local files are read/written. No native, Git, formatter, test or network command is run.
FUTURE-BINDINGS.json is intentionally inert until root supplies exact future originals.
"""
import argparse
import copy
import difflib
import hashlib
import json
import re
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "hepta-cell/qualification/cell-unification-20261106"
TESTED_COMMIT = "f74be175de66a4b351cd239d39d98cd34fe9cc1b"
TESTED_TREE = "440d4a8e09af4009e4d9ea067388826308da8803"
HEAD = "bef6fa7645df9df12b69fda499e97eed25de6c75"
HISTORY = "history/source53-final-report"
INPUTS = {}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def safe(value):
    require(isinstance(value, str), "unbound path")
    p = PurePosixPath(value)
    require(value and not p.is_absolute() and ".." not in p.parts and str(p) == value and "\\" not in value,
            "unsafe path: " + value)
    return value


def read(path, expected=None):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "missing/nonregular input: " + str(path))
    raw = path.read_bytes()
    actual = pin(raw)
    if expected:
        require(all(actual[key] == expected[key] for key in ("bytes", "sha256", "git_blob") if key in expected),
                "input pin mismatch: " + str(path))
    INPUTS[str(path.relative_to(ROOT))] = {"path": str(path.relative_to(ROOT)), **actual}
    return raw


def pinned(record):
    require(isinstance(record, dict) and {"path", "bytes", "sha256", "git_blob"} <= set(record), "future input is not fully bound")
    return read(ROOT / safe(record["path"]), record)


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def report_ref(path):
    raw = read(path)
    return {"path": str(Path(path).relative_to(REPORT)), **pin(raw)}, raw


def pointer(value, path):
    if not path:
        return value
    require(path.startswith("/"), "JSON pointer must be explicit")
    for key in path[1:].split("/"):
        key = key.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def differences(before, after, prefix=""):
    result = []
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            path = prefix + "/" + key.replace("~", "~0").replace("/", "~1")
            if key not in before:
                result.append({"pointer": path, "operation": "add", "after": after[key]})
            elif key not in after:
                result.append({"pointer": path, "operation": "remove", "before": before[key]})
            else:
                result.extend(differences(before[key], after[key], path))
    elif before != after:
        result.append({"pointer": prefix, "operation": "replace", "before": before, "after": after})
    return result


def paragraph(text, starts, replacement):
    blocks = text.split("\n\n")
    indexes = [idx for idx, block in enumerate(blocks) if block.startswith(starts)]
    require(len(indexes) == 1, "paragraph anchor not unique: " + starts)
    blocks[indexes[0]] = replacement
    return "\n\n".join(blocks)


def section(text, start, end):
    require(text.count(start) == 1 and text.count(end) == 1, "section anchors changed")
    return text.split(start, 1)[1].split(end, 1)[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bindings", required=True)
    args = parser.parse_args()
    cfg_path = ROOT / safe(args.bindings)
    cfg = json.loads(read(cfg_path))
    require(cfg["schema"] == "hepta.source53-final-report-bindings.v1" and cfg["frozen"] is True,
            "preparation only: actual finalizer and root code registration are not yet bound")
    require(cfg["publication_state"] == "READY_FOR_STACKED_DRAFT_PR"
            and cfg["branch_created"] is False and cfg["pull_request_created"] is False
            and cfg["final_sha_ci"] == "PENDING", "this generator only prepares the pre-publication snapshot")
    base = ROOT / safe(cfg["base_directory"])
    plan = json.loads(read(Path(__file__).with_name("PLAN.json")))
    for row in plan["base_files"]:
        read(ROOT / row["path"], row)
    old = {name: read(base / "candidates" / name) for name in ("README.md", "STATUS.json", "SOURCE_IDENTITY.json")}
    old_pr = {name: read(base / "pr-guide-candidates" / name) for name in
              ("PR-PARAGRAPHS.zh-CN.md", "REVIEW-GUIDE.zh-CN.md", "PATH-GROUPS.json", "DYNAMIC-STATUS.json")}
    canonical = {name: read(REPORT / name) for name in old}
    for name, raw in canonical.items():
        require(raw == read(base / "base/checkpoint6-canonical" / name), "canonical changed since checkpoint6; require explicit rebase")
    status, identity = json.loads(old["STATUS.json"]), json.loads(old["SOURCE_IDENTITY.json"])
    old_status, old_identity = copy.deepcopy(status), copy.deepcopy(identity)

    r31_ref, r31_raw = report_ref(REPORT / "native-evidence/r31-workspace-checkpoint/CLOSURE.json")
    require(r31_ref["sha256"] == "7bbcaceb129f254c49dab140a204a509482cea30bcc805df49393fc3e6c4257c", "closed R31 snapshot changed")
    r31 = json.loads(r31_raw)
    require(r31["source_commit"] == TESTED_COMMIT and r31["source_tree"] == TESTED_TREE
            and r31["raw_exit"] == r31["effective_exit"] == r31["outer_exit"] == 0
            and r31["counts"] == {"PASS": 20228, "FAIL": 0, "TIMEOUT": 0}
            and r31["reported_skipped"] == 130 and r31["diagnostic_only"] is True
            and r31["behavior_repair_claimed"] is False, "actual R31 completion mismatch")
    r31_ind_ref, _ = report_ref(REPORT / "native-evidence/r31-workspace-checkpoint/INDEPENDENT-READBACK.json")
    final_raw = pinned(cfg["finalization_formal_closure"])
    final = json.loads(final_raw)
    final_dir = (ROOT / cfg["finalization_formal_closure"]["path"]).parent
    final_ref = {"path": str(final_dir.relative_to(REPORT)) + "/CLOSURE.json", **pin(final_raw)}
    require(final["schema"] == "hepta.source53-finalization-formal-closure.v1" and final["success"] is True
            and final["state"] == "ACTUAL_FIX_FORMAT_CLOSED_SUCCESS" and final["original_outer_exit_code"] == 0,
            "complete actual fix/format success is required before READY report")
    require(final["tested_source_commit"] == TESTED_COMMIT and final["tested_source_tree"] == TESTED_TREE
            and final["post_fix_or_format_tests_executed"] is False
            and final["qualification_transferred_to_mutated_tree"] is False, "tested/final boundary changed")
    complete_raw = read(final_dir / final["complete"]["path"], final["complete"])
    complete = json.loads(complete_raw)
    require(complete["final_formatted_commit"] is None, "original complete commit must not be backfilled")
    final_tree = complete["final_formatted_tree"]
    require(final_tree == final["final_formatted_tree"] and re.fullmatch(r"[0-9a-f]{40}", final_tree), "final tree missing")

    def native_output(record):
        require(record["path"].startswith("native-source53-finalization/"), "unexpected original pointer")
        suffix = safe(record["path"].split("/", 1)[1])
        path = final_dir / "original/finalization" / suffix
        data = read(path, record)
        return {"path": str(path.relative_to(REPORT)), **pin(data)}, data

    final_manifest_ref, final_manifest_raw = native_output(complete["after_format"]["manifest"])
    tested_manifest_ref, tested_manifest_raw = native_output(complete["tested"]["manifest"])
    final_manifest, tested_manifest = json.loads(final_manifest_raw), json.loads(tested_manifest_raw)
    final_rows = {row["path"]: row for row in final_manifest["changed_files"]}
    tested_rows = {row["path"]: row for row in tested_manifest["changed_files"]}
    require(final_manifest["source_tree"] == final_tree and tested_manifest["source_tree"] == TESTED_TREE
            and set(final_rows) == set(tested_rows) and len(final_rows) == 197
            and sum(name.endswith(".rs") for name in final_rows) == 183, "final source scope changed")
    for phase in ("fix", "format"):
        require(final[phase]["exit_code"] == final[phase]["effective_exit_code"] == 0, "final phase not passed")
    registered = cfg["registered_source"]
    require(isinstance(registered["stage"], int) and registered["stage"] >= 53, "actual registered source stage missing")
    require(re.fullmatch(r"[0-9a-f]{40}", registered["commit"] or "")
            and registered["tree"] == final_tree, "actual registered post-format identity missing")
    commit = registered["commit"]
    api_raw = pinned(registered["commit_api"])
    api = pointer(json.loads(api_raw), registered["commit_api_json_pointer"])
    if isinstance(api, str):
        api = json.loads(api)
    require(isinstance(api, dict), "actual commit API payload is not an object")
    require(api["sha"] == commit and api["tree"]["sha"] == final_tree, "actual Git commit API mismatch")
    if commit != TESTED_COMMIT:
        require([entry["sha"] for entry in api["parents"]] == [TESTED_COMMIT], "post-format code must be independently bound to tested parent")
    else:
        require(final_tree == TESTED_TREE, "cannot reuse tested commit for a different tree")
    root_readback_raw = pinned(registered["root_readback"])
    ledger_raw = pinned(registered["ledger_snapshot"])
    ledger = json.loads(ledger_raw)
    require(ledger["current_source_commit"] == commit and ledger["current_source_tree"] == final_tree,
            "root registration ledger does not bind final code")
    require(ledger["branch_created"] is False and ledger["pull_request_created"] is False,
            "publication already occurred; use a later snapshot workflow instead")
    previous_records = identity["created_source_commits"]
    require(ledger["commits"][:len(previous_records)] == previous_records, "historical source creation records changed")
    require(ledger["commits"][-1]["sha"] == commit and ledger["commits"][-1]["tree"] == final_tree, "last registered code mismatch")

    out = ROOT / safe(cfg["output_directory"])
    require(not out.exists(), "final candidate destination exists; no overwrite/repeated commit loop")
    pending_outputs = {}
    def put(relative, data):
        safe(relative)
        require(relative not in pending_outputs, "duplicate candidate output: " + relative)
        pending_outputs[relative] = data
        return {"path": relative, **pin(data)}
    for path in sorted((base / "new-files").rglob("*")):
        if path.is_file():
            put("new-files/" + str(path.relative_to(base / "new-files")), read(path))
    for name, raw in old.items():
        put("base/r30-closed-candidate-v2/" + name, raw)
        put("new-files/" + HISTORY + "/prior-candidate/" + name, raw)
    for name, raw in old_pr.items():
        put("base/r30-closed-pr-guide/" + name, raw)
        put("new-files/" + HISTORY + "/prior-pr-guide/" + name, raw)
    for name, raw in canonical.items():
        put("base/checkpoint6-canonical/" + name, raw)
    put("new-files/" + HISTORY + "/prior-candidate/HANDOFF-MANIFEST.json", read(base / "HANDOFF-MANIFEST.json"))
    registration_refs = {}
    for name, data in (("CREATED-COMMIT-API-ORIGINAL.json", api_raw), ("ROOT-CODE-READBACK.json", root_readback_raw),
                       ("PUBLICATION-LEDGER-SNAPSHOT.json", ledger_raw)):
        relative = HISTORY + "/final-code-registration/" + name
        put("new-files/" + relative, data)
        registration_refs[name] = {"path": relative, **pin(data)}
    registered_identity = {"stage": registered["stage"], "commit": commit, "tree": final_tree,
                           "parents": [row["sha"] for row in api["parents"]], "actual_GitData_registered": True,
                           "native_checkout_of_created_commit_claimed": False, "root_readback": registration_refs["ROOT-CODE-READBACK.json"],
                           "actual_commit_api": registration_refs["CREATED-COMMIT-API-ORIGINAL.json"],
                           "manifest": final_manifest_ref, "tests_executed_on_this_mutated_tree": False,
                           "qualification_transferred_from_tested_tree": False, "final_SHA_CI": "PENDING"}
    source_transition = {"tested_source": {"stage": 53, "commit": TESTED_COMMIT, "tree": TESTED_TREE, "manifest": tested_manifest_ref},
                         "registered_final_code": registered_identity,
                         "fix_before_tree": final["fix"]["before_tree"], "fix_after_tree": final["fix"]["after_tree"],
                         "formatted_tree": final_tree, "phase_changed_paths": {phase: final[phase]["changed_paths"] for phase in ("fix", "format")},
                         "combined_changed_paths": final["combined_delta_paths"], "finalization": final_ref,
                         "original_complete_final_commit_null_preserved": True, "post_fix_or_format_tests_executed": False,
                         "qualified_source_not_automatically_transferred": True}

    r31_gate = copy.deepcopy(status["validation"]["gates"]["r31"])
    r31_gate.update(state="COMPLETE_ORIGINAL_DEFAULT_WORKSPACE_PASS_ON_TESTED_SOURCE53", last_observed_job_state="succeeded",
                    test_execution_started=True, tests_raw_exit_code=0, tests_effective_exit_code=0, original_outer_exit_code=0,
                    counts={"unique_test_results": 20228, "passed": 20228, "failed": 0, "timed_out": 0, "reported_skipped": 130},
                    tests_elapsed_seconds=r31["tests_wall_seconds_including_build"], nextest_execution_seconds=r31["nextest_execution_seconds"],
                    source_and_dual_lock_postguards_pass=True, natural_outer_durable_complete=True,
                    exact_old_test_ID_set_observed_pass=True, closed_originals=r31_ref, independent_closed_gate_readback=r31_ind_ref,
                    announced_binaries=r31["announced_binaries"], binary_groups_with_executed_rows=r31["binary_groups_with_executed_rows"],
                    result_boundary="Actual full original workspace result is bound to tested source53 f74/440. Final formatted code is a separate identity with final-SHA CI pending.",
                    final_formatted_code_qualification_transferred=False)
    status["validation"]["gates"]["r31"] = r31_gate
    status["validation"]["default_gate_scope"] = "Actual source53 R31 original no-p command; fresh193/default193; exactly20228 original binary+name IDs PASS,130 reportedskip. The result is not rerun or transferred after fix/format."
    boundary = ("Tested source53 f74/440 completed R30 strict/full1345 and R31 original no-p193/full20228 with natural outer0. "
                "Original scoped just fix then default just fmt completed with separate actual receipts/source snapshots. "
                "The registered final code identity is separate, has no post-format local test claim, and awaits final-SHA CI and branch/DraftPR creation. "
                "Earlier failed gates, diagnostic-only limits, science HOLD and authority DENY_ALL remain intact.")
    status["record_state"] = "READY_FOR_STACKED_DRAFT_PR"
    status["snapshot_boundary"] = boundary
    status["tested_source_before_finalization"] = copy.deepcopy(status["current_source"])
    current = copy.deepcopy(status["current_source"])
    current.update(stage=registered["stage"], commit=commit, tree=final_tree,
                   parent_commit=api["parents"][0]["sha"] if api["parents"] else None,
                   state="REGISTERED_FINAL_FORMATTED_CODE_READY_FOR_DRAFT_REVIEW_CI_PENDING",
                   source_identity=registered_identity, finalization=final_ref)
    current["tested_source_native_apply"] = current.pop("native_apply")
    current["scope"] = {key: copy.deepcopy(current["scope"][key]) for key in
        ("owner_package_count", "owner_packages", "ci_package_selector_count", "ci_package_selectors",
         "retained_ci_owner_without_changed_rust_path", "counts_exclude_evidence_attachments", "workflow",
         "changed_source_paths", "rust_paths", "other_paths", "source_counts_are_regular_files",
         "default_HEAD_expected_rust_paths", "default_HEAD_expected_python_paths")}
    current["scope"].update(actual_source_manifest=final_manifest_ref, final_fix_fmt_executed=True,
                            tested_source_scope_and_metadata=status["tested_source_before_finalization"]["scope"],
                            metadata_not_reexecuted_after_finalization=True,
                            derivation="Exact197 final snapshot paths preserve183Rust+14other and unchanged owner/CI/formatter/dependency inputs; original fresh193 metadata remains bound to tested source53.")
    status["current_source"] = current
    status["source_identity_transition"] = source_transition
    status["publication"].update(state="READY_FOR_STACKED_DRAFT_PR", final_release_commit=commit, final_release_tree=final_tree,
                                 final_github_ci="PENDING_EXACT_FINAL_SOURCE_SHA", branch_created=False, pull_request_created=False,
                                 pull_request_url=None, main_merged=False,
                                 draft_pr_preparation="Ready review text only; no branch/PR/CI execution claimed.")
    status["overall"].update(default_workspace_gate_pass=True, default_workspace_gate_pass_source={"commit": TESTED_COMMIT, "tree": TESTED_TREE},
                             all_engineering_blockers_closed=False, final_SHA_CI_pending=True, final_formatted_code_locally_retested=False)
    status["current_failures"].update(current_workspace_gate="SOURCE53_R31_COMPLETE_20228_PASS_130_REPORTED_SKIP",
                                    current_tested_workspace_failure_IDs=[], historical_failure_not_relabelled=True,
                                    same_test_current_r31_observation=r31["original_source52_R29_failure"]["old_failed_to_current_observations"][0]["source53_R31_observation"])
    status["final_fix_fmt"].update(state="ACTUAL_FIX_FORMAT_CLOSED_SUCCESS_FINAL_CODE_REGISTERED", fix_executed=True, fmt_executed=True,
                                 fresh_source53_tool_inventory_bound=True, same_source_workspace_pass_bound=True,
                                 prerequisites=["Actual source53 R30 and R31 natural complete PASS, fresh193 metadata, exact197 source/HEAD/dual locks and actual tool inventory were bound by the unchanged finalizer."],
                                 actual_finalization=final_ref, phases={phase: final[phase] for phase in ("fix", "format")},
                                 source_identity_transition=source_transition, post_fix_or_format_tests_executed=False,
                                 qualification_transferred_to_mutated_tree=False)
    for blocker in status["adoption_blockers"]:
        if blocker["id"] == "workspace-failure":
            blocker.update(state="CLOSED_FOR_TESTED_SOURCE53", historical_requirement=blocker["requirement"],
                           requirement="R31 complete original workspace passed on tested f74/440. Prior source52 failure and unresolved root-cause interpretation remain recorded; final formatted code awaits exact-SHA CI.", evidence=r31_ref)
        elif blocker["id"] == "final-source-release":
            blocker.update(state="OPEN_FOR_BRANCH_PR_AND_FINAL_SHA_CI", historical_requirement=blocker["requirement"],
                           requirement="Actual scoped fix/default fmt and final source registration are complete. Branch/DraftPR creation and exact final-SHA CI remain pending.", evidence=final_ref)
    status["next_source_preparation"].update(state="COMPLETED_TESTED_SOURCE53_PREREQUISITE_FOR_FINALIZATION", r31=copy.deepcopy(r31_gate),
                                            registered_final_code=registered_identity,
                                            source_fields_are_pre_format_tested_source=True)

    identity["historical_tested_source53_identity"] = {key: copy.deepcopy(old_identity[key]) for key in
        ("current_source_stage", "current_source_commit", "current_source_tree", "current_source_parent_commit", "source_scope", "current_source_native_apply")}
    identity.update(state="FINAL_FORMATTED_CODE_REGISTERED_READY_FOR_STACKED_DRAFT_PR_CI_PENDING",
                    current_source_stage=registered["stage"], current_source_commit=commit, current_source_tree=final_tree,
                    current_source_parent_commit=current["parent_commit"], current_source_validation_status="R30_AND_R31_PASS_ON_TESTED_F74_FIX_FMT_COMPLETE_FINAL_CODE_CI_PENDING",
                    tested_source_commit=TESTED_COMMIT, tested_source_tree=TESTED_TREE,
                    final_release_commit=commit, final_release_tree=final_tree,
                    final_fix_executed=True, final_fmt_executed=True, final_fix_fmt_and_publication_pending=True,
                    final_fix_fmt_pending=False, publication_pending=True, final_SHA_CI="PENDING", branch_created=False, pull_request_created=False,
                    source_scope=current["scope"], final_source_registration=registered_identity,
                    source_identity_transition=source_transition,
                    last_closed_rust_gate_tree=TESTED_TREE, last_closed_native_tree=TESTED_TREE,
                    last_closed_default_workspace_tree=TESTED_TREE, last_closed_rust_gate_scope="source53_original_default_workspace20228PASS130reportedskip_before_fix_format",
                    closed_tested_source_native_gates={"r30": copy.deepcopy(status["validation"]["gates"]["r30"]), "r31": copy.deepcopy(r31_gate)},
                    closed_current_native_gates={} if final_tree != TESTED_TREE else {"r30": copy.deepcopy(status["validation"]["gates"]["r30"]), "r31": copy.deepcopy(r31_gate)},
                    pending_native_gates={}, post_fix_or_format_tests_executed=False,
                    qualification_transferred_to_mutated_tree=False)
    identity["tested_source_native_apply"] = identity.pop("current_source_native_apply")
    identity["creation_records_before_finalization"] = copy.deepcopy(identity["creation_records_exact_from_publication_ledger"])
    identity["created_source_commits"] = ledger["commits"]
    identity["created_source_commit_count"] = len(ledger["commits"])
    identity["creation_records_exact_from_publication_ledger"] = registration_refs["PUBLICATION-LEDGER-SNAPSHOT.json"]
    identity["post_format_source_registration_ledger_snapshot"] = {"source_objects": len(ledger["commits"]), "binary_paths": len(ledger["created_blobs"]),
        "artifact_checkpoints": len(ledger["artifact_checkpoints"]), "fixed_snapshot_not_live_counter": True,
        "original_source53_r30_publication_snapshot_preserved": True, "ledger": registration_refs["PUBLICATION-LEDGER-SNAPSHOT.json"]}
    identity["checkpoint_bindings"].append({"gate": "r31", "stage": 53, "commit": TESTED_COMMIT, "tree": TESTED_TREE,
                                            "state": "COMPLETE_ORIGINAL_WORKSPACE_PASS", "original_exit": 0, "evidence": r31_ref,
                                            "independent_readback": r31_ind_ref, "formatted_tree_qualification_transferred": False})
    identity["scope_preparation"].update(state="ACTUAL_FRESH_SCOPE_BOUND_AND_FIX_FORMAT_EXECUTED",
                                         final_fix_fmt_executed=True, workspace_terminal_result=r31_ref, tool_inventory_bound=True,
                                         finalization=final_ref)
    facts = {"schema": "hepta.final-report-closed-facts.v1", "status": "READY_FOR_STACKED_DRAFT_PR",
             "r30": status["validation"]["gates"]["r30"], "r31": r31_gate, "finalization": final_ref,
             "identity_transition": source_transition, "branch_created": False, "pull_request_created": False,
             "final_SHA_CI": "PENDING", "scientific_disposition": "HOLD", "authority": "DENY_ALL",
             "root_cause_proven": False, "behavior_repair_claimed": False}
    fact_data = encode(facts)
    put("new-files/" + HISTORY + "/CLOSED-FACTS.json", fact_data)
    fact_ref = {"path": HISTORY + "/CLOSED-FACTS.json", **pin(fact_data)}
    status["candidate_fact_binding"] = identity["candidate_fact_binding"] = fact_ref

    readme = old["README.md"].decode()
    readme = paragraph(readme, "**当前状态：", f"**当前状态：READY_FOR_STACKED_DRAFT_PR；科学结论 HOLD；权限 DENY_ALL。** 已测试源码为 source53 commit `{TESTED_COMMIT}`、tree `{TESTED_TREE}`；实际 scoped fix 与默认 fmt 完成后的代码已由 root 登记为 commit `{commit}`、tree `{final_tree}`。原生 HEAD 仍为 framework 基线。两份身份分别保存，格式化后没有本地重跑测试；最终 SHA CI、分支与 Draft PR 尚未发生。[当前状态][status]／[源码身份][identity]／[最终化原件][finalization]")
    readme = paragraph(readme, "**source53 只增加诊断日志", "**source53 只增加诊断日志，尚未证明修复 Bedrock 根因。** 已测试的 f74/440 上，R30 app-server strict、完整项目 tests 与 outer 均自然 **0**，**1,345 PASS／0 FAIL／0 TIMEOUT，另报2 skipped**。同源 R31 原 no-p 默认工作区的 **20,228 个唯一测试全部 PASS、0 FAIL、0 TIMEOUT，另报130 skipped**；raw、effective、outer均为0，fresh metadata确认 **193 members＝193 defaults**，原精确ID集合、197源码／HEAD／双锁守卫通过。两门计数不相加，资格不转授给格式化后源码。[R30][r30]／[R31完整原件][r31]")
    readme = paragraph(readme, "最近完整工作区 **R29", "历史工作区 **R29绑定source52，原自然失败100保持不变**：20,228个唯一结果＝**20,227 PASS、1 FAIL、0 TIMEOUT**，另报130 skipped。唯一Bedrock setup原例在10.643秒等待原deadline后FAIL；source53/R30同例0.352秒PASS、R31同例0.354秒PASS分别绑定各自原日志。后续通过没有定位原等待阶段，也没有把旧失败重标为通过。[R29原失败][r29]／[R31独立读回][r31-readback]")
    readme = paragraph(readme, "source52 的 R28 原四包门", "source52 的 R28 原四包门仍保持 **Python32/32、0 skip；strict0；1,564 PASS、0 FAIL、0 TIMEOUT、3 reported skipped；tests／outer0**。source51/R26、source50/R24与更早失败均按各自源码独立保留，旧R25、R27没有执行。source53/R30与R31的实际通过、最终fix/fmt、最终SHA CI和科学采用分别记账，禁止跨阶段累计或转授。[R28][r28]／[R26][r26]／[最终化][finalization]")
    readme = readme.replace("当前 source53 清单有 **197 个变更路径：", "已测试的 source53 清单有 **197 个变更路径：", 1)
    readme = paragraph(readme, "当前 source53/R31 已实际执行原 metadata", "source53/R31原 metadata 实际返回 **0**，193默认成员与全部成员相等。它绑定tested197路径，独立scope核对 **183 Rust＋2 Python、26个owner、27个CI selector**。实际工具inventory及源码／HEAD／双锁核对后，执行了原26-owner `just fix --locked` 与原默认 `just fmt`；没有改HEAD、扩大为 `--all` 或追加格式化后测试。三份源快照及两个独立阶段patch保留原始字节。[范围原件][fresh-scope53]／[最终化原件][finalization]")
    lines = readme.splitlines()
    for idx, line in enumerate(lines):
        if line.startswith("| r31："):
            lines[idx] = "| r31：默认工作区 | tested source53 / `440d4a8` | 原no-p193默认成员；**20,228 PASS、0 FAIL、0 TIMEOUT，130 reported skipped**；raw／effective／outer自然0，源码／HEAD／双锁守卫通过。[完整原件][r31] |"
    readme = "\n".join(lines) + "\n"
    readme = paragraph(readme, "现有源码链尚不能证明原延迟", "现有源码链尚不能证明原延迟来自网络、配置、认证、队列或具体系统调用。source53/R30同例 **0.352秒PASS**、R31同例 **0.354秒PASS**，与source52/R29的 **10.643秒FAIL** 分别保留。R30 strict耗时189.013484955秒、tests命令972.519997597秒、nextest404.442秒；R31 tests命令1854.427961588秒、nextest1643.187秒。这些口径不相加。当前两门通过不证明偶发根因已修复，不给真实模型效能或科学采用资格。[R30读回][r30-readback]／[R31读回][r31-readback]")
    before5 = section(readme, "## 5. 剩余采用与发布门槛", "## 6. 历史快照、恢复与证据阅读")
    after5 = ("\n\n1. R30完整项目门与R31原默认工作区已在tested source53 f74/440上闭合通过。原R29及更早失败继续保留；诊断新增不构成根因修复声明。\n"
              f"2. 实际26-owner fix和默认183Rust＋2Python fmt已完成；fix改动{final['fix']['changed_path_count']}条路径，format改动{final['format']['changed_path_count']}条路径，最终代码commit `{commit}`／tree `{final_tree}`独立登记。没有格式化后本地测试，待最终SHA CI验证。[原件][finalization]\n"
              "3. 把真实后端、真实Encoder receipt与产品owner接到共同合约；补齐完整状态、unknown恢复、当前来源／scope／撤销和最终消费校验。\n"
              "4. 按具体任务完成独立保留、校准、强检索／精确KV／固定策略对照与完整生命周期成本验收。历史训练、fixture回归和测试数量均不能代替这些结果。\n"
              "5. 当前为可分层审阅的Draft PR准备态；分支未创建、PR未发送，最终CI与生产采用尚未获资格。PR创建后的真实链接与CI状态由root另行记录，不从准备文本推断。\n\n")
    readme = readme.replace("## 5. 剩余采用与发布门槛" + before5 + "## 6. 历史快照、恢复与证据阅读",
                            "## 5. 剩余采用与发布门槛" + after5 + "## 6. 历史快照、恢复与证据阅读")
    readme = paragraph(readme, "本候选版本登记 source53", "本版最终候选从此前R30闭合／R31启动的v2快照派生，旧候选、checkpoint6 source52三报告与native INDEX原字节保留。新增事实只引用R31完整闭合和实际finalization；原始complete的finalcommit null没有被回填，root最终代码登记另列。[旧v2原文][prior-final-v2]／[最终化][finalization]")
    readme = paragraph(readme, "source53 正式组分别保存首次准备路径失败", "source53正式组保留首次准备路径失败与明确授权后的应用成功；R29失败、R30项目PASS、R31工作区PASS、工具盘点、实际fix/fmt与root最终代码登记各有独立原件。活动快照保持其历史口径，没有倒写。源码、证据上传和静态审查均不代替最终SHA CI或科学采用。[source53][apply53]／[R29][r29]／[R30][r30]／[R31][r31]／[最终化][finalization]")
    readme = paragraph(readme, "本版登记列表取自固定", "R30附件上传时点的固定ledger保留 **53个源码对象、235个二进制路径、6个artifact checkpoint**；更早208路径快照同样原样保留，不随后续注册回填。最终代码登记使用另一份实际root commit API及固定ledger快照，不能把上传回执计为新测试、分支或PR。[R30时点快照][ledger53-current]／[最终代码登记][final-code-registration]／[早期source53快照][ledger53]")
    warnings = final["fix"]["warnings"]
    warning_count, diagnostic_count = warnings["warning_header_occurrences"], warnings["diagnostic_warning_count"]
    locations = [location for item in warnings["diagnostic_warnings"] for location in item["source_locations"]]
    warning_note = (f"原scoped `just fix` 返回0，原日志包含 {diagnostic_count} 个诊断warning及 {warnings['package_summary_count']} 个package／重复摘要，合计 {warning_count} 个warning header。"
                    + ("诊断位置：" + "、".join("`" + value + "`" for value in locations) + "。" if locations else "")
                    + ("其中包含原 `clippy::large_enum_variant`；" if warnings["large_enum_variant_mentioned"] else "")
                    + "完整原文与byte offsets保留。fix成功不等于追加的 `-D warnings` 严格门通过，未为消除警告增加allow或重跑测试。[完整日志与读回][finalization]")
    readme = readme.replace("## 5. 剩余采用与发布门槛", "## 5. 剩余采用与发布门槛\n\n" + warning_note, 1)
    readme += ("[r31]: native-evidence/r31-workspace-checkpoint/CLOSURE.json\n[r31-readback]: native-evidence/r31-workspace-checkpoint/INDEPENDENT-READBACK.json\n"
               "[finalization]: " + final_ref["path"] + "\n[prior-final-v2]: " + HISTORY + "/prior-candidate/HANDOFF-MANIFEST.json\n"
               "[final-code-registration]: " + HISTORY + "/final-code-registration/CREATED-COMMIT-API-ORIGINAL.json\n")
    for first, last in [("## 1. 重新判断七类职责与历史资产", "## 2. 当前代码具体接通了什么"),
                        ("## 2. 当前代码具体接通了什么", "## 3. 实际门状态：分别绑定源码，禁止相加"),
                        ("## 4. 冻结分化研究：执行完成，两个场景均 HOLD", "## 5. 剩余采用与发布门槛")]:
        require(section(readme, first, last) == section(old["README.md"].decode(), first, last), "immutable science/implementation prose changed")
    for key in ("taxonomy", "source_inputs", "implementation", "science", "historical_assets", "upstream_ci_history", "source_compatibility"):
        require(status[key] == old_status[key], "immutable status evidence changed: " + key)
    for gate, record in old_status["validation"]["gates"].items():
        if gate != "r31":
            require(status["validation"]["gates"][gate] == record, "historical gate changed")
    require(status["current_failures"]["ids"] == old_status["current_failures"]["ids"], "old failure IDs changed")
    require(identity["scientific_disposition"] == "HOLD" and identity["authority"] == "DENY_ALL", "science boundary changed")

    groups = json.loads(old_pr["PATH-GROUPS.json"])
    original_group_values = copy.deepcopy(groups["groups"])
    require(len(groups["paths"]) == len(final_rows) == 197, "review path count changed")
    changed = []
    for row in groups["paths"]:
        name = row["path"]
        require(all(row[key] == tested_rows[name][key] for key in ("mode", "bytes", "sha256", "git_blob")), "tested path pin mismatch")
        row["tested_source_pin"] = {key: row[key] for key in ("mode", "bytes", "sha256", "git_blob")}
        row["changed_during_finalization"] = final_rows[name] != tested_rows[name]
        if row["changed_during_finalization"]:
            changed.append(name)
        row.update(final_rows[name])
        for flag in ("retained_from_source51", "retained_from_source52"):
            if flag in row:
                row["tested_source_" + flag] = row[flag]
                row[flag] = row[flag] and not row["changed_during_finalization"]
        row["source_url"] = "https://github.com/TrillionniumFoundation/hepta-private-ci/blob/" + commit + "/" + name
    require(sorted(changed) == final["combined_delta_paths"], "path table delta mismatch")
    require(groups["groups"] == original_group_values and {k: v["path_count"] for k, v in groups["groups"].items()} == {"A": 25, "B": 123, "C": 38, "D": 9, "E": 2}, "review groups changed")
    groups.update(schema="hepta.final-code-pr-review-groups.v1", source_commit=commit, source_tree=final_tree,
                  source_manifest=final_manifest_ref, tested_source_commit=TESTED_COMMIT, tested_source_tree=TESTED_TREE,
                  tested_source_manifest=tested_manifest_ref, finalization=final_ref, tests_on_formatted_tree_executed=False)
    guide = old_pr["REVIEW-GUIDE.zh-CN.md"].decode()
    guide = paragraph(guide, "# Draft PR 审阅分组候选", "# Draft PR 审阅分组：最终代码候选")
    guide = paragraph(guide, "本稿只提供审阅顺序", f"本稿准备以 `codex/cell-framework-20261105` 为base的stacked Draft PR，没有创建或发送PR。最终代码固定为 **{commit}**，tree **{final_tree}**；tested source53是 **{TESTED_COMMIT}** / **{TESTED_TREE}**。完整197路径＝183Rust＋14其他，26owner／27CI；A25、B123、C38、D9、E2分组保持，PATH-GROUPS逐项保留tested和final两份原pin。")
    guide = paragraph(guide, "source53 已实际应用到原生 staged tree", "tested source53上，R30原app-server strict／完整1345项目门及R31原no-p193工作区均自然退出0；R31为20228PASS／0FAIL／0TIMEOUT，130 reportedskip。实际26owner fix与默认fmt随后完成并导出独立差异，没有格式化后本地测试。最终代码等待exact-SHA CI，分支与PR尚未创建。原R29失败、source53诊断限定与科学HOLD／DENY_ALL保留，详见DYNAMIC-STATUS.json。")
    guide = paragraph(guide, "原 R29 Bedrock 为", "原R29 Bedrock为10.643秒FAIL，source53/R30同例0.352秒PASS、R31同例0.354秒PASS，各原记录独立保留。两完整门的本次通过不证明原根因已定位或修复；E组仍是两条诊断增量。格式化后没有重跑本地测试，最终SHA CI待实际结果。")
    guide = guide.replace("科学 HOLD、DENY_ALL、最终工程门与 CI 待验收保持独立。", "科学HOLD、DENY_ALL、已测试源码的完整工程结果与最终代码CI待验收保持独立。")
    guide = re.sub(r"(https://github\.com/TrillionniumFoundation/hepta-private-ci/blob/)[0-9a-f]{40}(/)",
                   lambda match: match.group(1) + commit + match.group(2), guide)
    first_paragraphs = old_pr["PR-PARAGRAPHS.zh-CN.md"].decode().split("\n\n")
    require(len(first_paragraphs) >= 5, "PR paragraphs changed")
    body_prefix = "\n\n".join(first_paragraphs[1:4])
    last = (f"已测试源码固定为 `{TESTED_COMMIT}`，197路径／26owner。source53两条Bedrock叶仅加固定阶段诊断，原await、预算及22个断言保持；不主张根因修复。原R30 strict／完整1345项目门和R31原no-p193工作区均自然0；R31为20228PASS／0FAIL／0TIMEOUT，130 reportedskip。实际scoped fix→default fmt后，最终代码登记为 `{commit}`；没有格式化后本地测试。最终SHA CI、分支和Draft PR仍待实际发布步骤。科学HOLD、DENY_ALL及所有历史失败不变，分组、双身份与原始回执见REVIEW-GUIDE.zh-CN.md和PATH-GROUPS.json。")
    pr_text = "# 可用于 stacked Draft PR 的短正文\n\n" + body_prefix + "\n\n" + last + "\n"
    dynamic = json.loads(old_pr["DYNAMIC-STATUS.json"])
    dynamic.update(kind="ready_review_preparation_not_publication", source_commit=commit, source_tree=final_tree,
                   tested_source_commit=TESTED_COMMIT, tested_source_tree=TESTED_TREE,
                   r31_default_workspace=copy.deepcopy(r31_gate), final_fix_fmt=copy.deepcopy(status["final_fix_fmt"]),
                   final_registered_code=registered_identity, final_published_source_sha=None,
                   final_ci="PENDING_EXACT_FINAL_CODE_SHA", same_source_workspace_pass_bound=True,
                   fresh_tool_inventory_bound=True, final_candidate_frozen=True, snapshot_boundary=boundary,
                   post_fix_or_format_tests_executed=False, qualification_transferred_to_mutated_tree=False)
    outputs = {"README.md": readme.encode(), "STATUS.json": encode(status), "SOURCE_IDENTITY.json": encode(identity)}
    pr_outputs = {"PR-PARAGRAPHS.zh-CN.md": pr_text.encode(), "PR-BODY.md": (body_prefix + "\n\n" + last + "\n").encode(),
                  "REVIEW-GUIDE.zh-CN.md": guide.encode(), "PATH-GROUPS.json": encode(groups), "DYNAMIC-STATUS.json": encode(dynamic)}
    for name, data in outputs.items():
        put("candidates/" + name, data)
    for name, data in pr_outputs.items():
        put("pr-guide-candidates/" + name, data)
    for label, originals in (("r30-closed-v2", old), ("checkpoint6-canonical", canonical)):
        patch = "".join("".join(difflib.unified_diff(originals[name].decode().splitlines(keepends=True), data.decode().splitlines(keepends=True),
                        fromfile=label + "/" + name, tofile="final-candidate/" + name)) for name, data in outputs.items())
        put("diffs/" + label + "-to-final.patch", patch.encode())
    put("JSON-POINTER-CHANGES.json", encode({"STATUS.json": differences(old_status, status), "SOURCE_IDENTITY.json": differences(old_identity, identity)}))
    put("INPUT-PINS.json", encode({"files": list(INPUTS.values()), "native_commands_executed": False}))
    put("GENERATION-READBACK.json", encode({"schema": "hepta.final-report-candidate-readback.v1", "state": "READY_FOR_ROOT_REVIEW",
        "candidate_state": "READY_FOR_STACKED_DRAFT_PR", "canonical_adopted": False, "native_executed": False,
        "tested_source": {"commit": TESTED_COMMIT, "tree": TESTED_TREE}, "final_code": registered_identity,
        "science_taxonomy_Q24_original_sections_exact": True, "historical_gate_records_exact": True,
        "path_groups": {"A": 25, "B": 123, "C": 38, "D": 9, "E": 2}, "branch_created": False, "pull_request_created": False,
        "CI_result": "PENDING", "INDEX_or_ledger_modified": False, "post_fix_or_format_tests_executed": False}))
    for name, data in canonical.items():
        require((REPORT / name).read_bytes() == data, "canonical was modified")
    for name, data in old.items():
        require((base / "candidates" / name).read_bytes() == data, "previous candidate modified")
    files = [{"path": name, **pin(data)} for name, data in sorted(pending_outputs.items())]
    put("HANDOFF-MANIFEST.json", encode({"schema": "hepta.final-report-candidate-handoff.v1", "files": files,
        "file_count_excluding_manifest": len(files), "candidate_only": True, "canonical_written": False,
        "science": "HOLD", "authority": "DENY_ALL"}))
    out.mkdir(parents=True)
    for name, data in pending_outputs.items():
        path = out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)
    print(json.dumps({"candidate_directory": str(out.relative_to(ROOT)), "file_count": len(files) + 1,
                      "handoff": pin((out / "HANDOFF-MANIFEST.json").read_bytes()), "canonical_adopted": False}, indent=2))


if __name__ == "__main__":
    main()
