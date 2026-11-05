"""Independent read-only publication checks for the V9 audit documents."""
import argparse
import collections
import hashlib
import json
import posixpath
import re
from pathlib import Path

WORK = Path(__file__).resolve().parents[2]
DOCS = WORK / "hepta-audit-fifth/v9/documents"
PREFIX = "qualification/r3-audit-repair-20261104/continuation-20261105/"
NAMES = ["CONTINUATION_PROGRESS_V8.zh-CN.md", "PROJECT_DIRECTION_AND_EXECUTION_PLAN_V6.zh-CN.md", "continuation-blocker-progress-v7.json", "LATEST.md"]
EXPECTED_FROZEN_BLOBS = {
    "CONTINUATION_PROGRESS_V8.zh-CN.md": "aaa0602beacdf422e4d2525dc8a8f22b51486cae",
    "PROJECT_DIRECTION_AND_EXECUTION_PLAN_V6.zh-CN.md": "4b5f581302cab6d347eb4c0d6c7ace25eb3ece71",
    "continuation-blocker-progress-v7.json": "081fbfb2fe2c1a2eee35b43258512fd721be6d29",
    "LATEST.md": "6e7c3793c9b2de434f723f7b6d3c1f927c0bced4",
}


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    originals = {name: (DOCS / name).read_bytes() for name in NAMES}
    assert {name: identity(raw)["git_blob"] for name, raw in originals.items()} == EXPECTED_FROZEN_BLOBS
    current = json.loads(originals["continuation-blocker-progress-v7.json"])
    prior_path = WORK / "hepta-audit-fifth/recovery-2113/ledger-v6.json"
    prior_bytes = prior_path.read_bytes()
    prior = json.loads(prior_bytes)
    evidence_path = WORK / "hepta-audit-fifth/v9/registered-evidence-plan.json"
    evidence_bytes = evidence_path.read_bytes()
    evidence = json.loads(evidence_bytes)
    base_path = WORK / "hepta-audit-fifth/recovery-2113/trees/auditV8-leaves.json"
    base_bytes = base_path.read_bytes()
    base = json.loads(base_bytes)
    items, old_items = current["items"], prior["items"]
    assert len(items) == len(old_items) == len({row["id"] for row in items}) == 23
    assert [row["id"] for row in items] == [row["id"] for row in old_items]
    assert all(a["original_exit_condition_zh"] == b["original_exit_condition_zh"] for a, b in zip(items, old_items))
    counts = dict(collections.Counter(row["closure_class"] for row in items))
    assert counts == current["counts"] == current["current_v9"]["counts"] == {"CLOSED_SCOPED": 15, "OPEN": 7, "SCIENTIFIC_HOLD": 1}
    transitions = [{"id": a["id"], "from": b["closure_class"], "to": a["closure_class"]} for a, b in zip(items, old_items) if a["closure_class"] != b["closure_class"]]
    assert transitions == [{"id": key, "from": "OPEN", "to": "CLOSED_SCOPED"} for key in ["B07", "B09", "B10", "B20"]]
    assert not current["all_blockers_closed"] and not current["whole_candidate_qualified"]
    assert current["original_23_status_exit_and_closure_class_unchanged"] is False
    assert current["original_23_ids_and_exit_conditions_unchanged"] is True
    product = current["product"]
    assert product == current["current_v9"]["product"]
    assert product["head"] == "67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed"
    assert product["tree"] == product["merge_tree"] == "3982ba56dc5a3f1da0c1de7ea57992f88125c359"
    assert product["base"] == "63652be658ebed8d3052eb789b951793384fd5e4"
    assert product["merge"] == "b7a57dbb61b00e51c05da9cf5c4bc95b365d85ae"
    assert product["exact_changed_paths_from_parent"] == 3 and product["cumulative_changed_paths_from_5b"] == 15
    diagnostic = current["current_v9"]["B11"]
    assert diagnostic["head"] == "021a59ff05ccd963bc087918db823aa86af31bb8"
    assert diagnostic["tree"] == diagnostic["actual_merge_tree"] == "36ca349de7f4c7c5a2914cf1960a81d8621350fa"
    assert diagnostic["parents"] == ["855733b0f88c82c68135b1879682358a818daa84", product["head"]]
    assert diagnostic["actual_merge_parents"] == [product["head"], diagnostic["head"]]
    assert diagnostic["product_B11"] == "OPEN"
    assert diagnostic["all11_source_pins_bound_to_actual_HEAD_and_merge"] is True
    actual_root_records = {row["path"]: row for row in evidence["items"]}
    for transition in current["closure_transitions_v9"]:
        path = PREFIX + transition["root_receipt"]
        row = actual_root_records[path]
        raw = Path(row["local_file"]).read_bytes()
        assert identity(raw)["git_blob"] == row["git_blob"] == transition["actual_git_blob"]
        closure = json.loads(raw)
        assert closure["decision"] == "CLOSED_SCOPED"
        original_exit = next(item["original_exit_condition_zh"] for item in items if item["id"] == transition["id"])
        assert closure["original_exit_condition_zh"] == original_exit
    native10_documented = diagnostic["native10"]["root_original_verification"]
    native10_row = actual_root_records[PREFIX + native10_documented["receipt"]]
    native10_raw = Path(native10_row["local_file"]).read_bytes()
    assert identity(native10_raw)["git_blob"] == native10_row["git_blob"] == native10_documented["actual_git_blob"] == "a113b64b48ed88f1392a4498f3bd18e5caba9c5f"
    native10 = json.loads(native10_raw)
    assert native10["head"] == diagnostic["head"] and native10["actual_checkout"] == diagnostic["actual_merge"] and native10["actual_tree"] == diagnostic["tree"]
    assert {k: native10["whole"][k] for k in ("passed", "failed", "ignored")} == native10_documented["whole"] == {"passed": 147, "failed": 7, "ignored": 2}
    assert len(native10["positives"]) == native10_documented["exact_positive"] == 4
    assert all(p["terminal"]["exit_code"] == 0 for p in native10["positives"])
    assert native10["negative_assertion"] == native10_documented["negative_assertion"] == "acl_tests.rs:597:9"
    assert native10["negative_XML_exit"] == native10_documented["negative_XML_exit"] == 101
    assert native10["counterfactual_terminal"]["restored_exact_original_bytes"] is native10_documented["exact_original_source_restore"] is True
    assert native10["physical_negative_marker"] == "deny_repair_identity: directory=false returned_ok=true replacement_changed=true original_changed=false"
    assert native10["helper_terminal"]["results"]["actual_named_pass_count"] == native10_documented["helper_actual_cases"] == 21
    assert native10["helper_terminal"]["results"]["libtest_summaries"][0][1:6] == ["21", "0", "0", "0", "0"]
    assert native10["all84_original_members_CRC_full_bytes_verified"] is native10_documented["all84_members_full_CRC"] is True
    compacts = native10["complete7_compact_logs"]
    assert len(compacts) == 7
    actions = [a for c in compacts for a in c["actions"]]
    actual_tests = [a for a in actions if a["role"] == "actual_test"]
    assert len(actual_tests) == native10_documented["actual_local_noncache_test_actions"] == 7
    assert len([a for a in actions if a["role"] == "XML_wrapper"]) == native10_documented["separate_XML_actions"] == 7
    assert all(a["runner"] == "local" and a["cache_hit"] is False and a["timeout_millis"] == native10_documented["original_target_timeout_millis"] == 300000 for a in actual_tests)
    assert native10["B11"] == native10_documented["B11"] == "OPEN" and native10["whole_candidate_qualified"] is False
    assert native10["full_index_and_lock_bytes_not_archived_here"] is True
    assert native10["hard_cancellation_restoration_not_guaranteed"] is True
    plan = originals["PROJECT_DIRECTION_AND_EXECUTION_PLAN_V6.zh-CN.md"].decode()
    table_rows = re.findall(r"^\| (B\d\d) \| ([^\n]+) \|$", plan, re.M)
    assert len(table_rows) == 23
    for item, (key, text) in zip(items, table_rows):
        assert key == item["id"]
        assert text.endswith(item["original_exit_condition_zh"])
        assert text.startswith(item["closure_class"] + " / ")
    # Current maintenance instructions must follow the published current head;
    # historical source facts and prior_* fields deliberately keep old SHA names.
    stale_current_gates = [row["id"] for row in items if "eed" in row.get("next_closure_gate_zh", "")]
    assert not stale_current_gates, stale_current_gates
    b02_latest = next(row["latest_continuation_zh"] for row in items if row["id"] == "B02")
    assert "67cc" in b02_latest and "3476" not in b02_latest
    known = {row["path"] for row in base["leaves"]} | set(actual_root_records)
    known |= {PREFIX + name for name in NAMES}
    known.add(PREFIX + "evidence-index-v9-registered.json")
    links = []
    for name in NAMES:
        if not name.endswith(".md"):
            continue
        for match in re.finditer(r"\[[^\]]*\]\(([^)]+)\)", originals[name].decode()):
            link = match.group(1)
            if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", link) or link.startswith("#"):
                continue
            target = posixpath.normpath(PREFIX + link.split("#")[0])
            assert target in known, (name, link, target)
            links.append({"from": name, "link": link, "resolved_repo_path": target})
    assert all((DOCS / name).read_bytes() == raw for name, raw in originals.items()), "documents changed during verification"
    report = {"schema": "v9-documents-independent-publication-review-v1", "review_scope": "Current four documents, original 23-item exits, exact product/diagnostic pins, actual root closure bytes, and relative repository links; not new product testing.", "document_recorded_utc": current["recorded_utc"], "result": "STATIC_PUBLICATION_ACCEPT", "documents": [{"name": name, "repo_path": PREFIX + name, **identity(raw)} for name, raw in originals.items()], "prior_ledger": identity(prior_bytes), "registered_evidence_plan": {**identity(evidence_bytes), "entries_observed": evidence["entry_count"]}, "audit_V8_leaf_catalog": identity(base_bytes), "all23_ids_and_exit_conditions_byte_equal": True, "counts": counts, "only_closure_transitions": transitions, "whole_candidate_qualified": False, "all_blockers_closed": False, "product": product, "diagnostic_source": {k: diagnostic[k] for k in ["head", "tree", "parents", "actual_merge", "actual_merge_tree", "actual_merge_parents", "product_B11"]}, "native10_observation_as_documented": diagnostic["native10"], "relative_links": links, "relative_link_count": len(links), "broken_links": [], "single_allowed_forthcoming_index": PREFIX + "evidence-index-v9-registered.json", "scope_review_zh": ["四项新增闭合均绑定原退出句和实际root回执；历史整轮失败、ignore、early return、attempt以及原48平台待验没有改写。", "B10旧3请求修正为4的已审oracle差异明确写出，未宣称旧全部请求数字节不变。", "B20负源404后的精确重建、旧GNU/current lib信号差异、真实stdio关闭与独立Windows动作均明确保留。", "B11依旧OPEN；API步骤success与物理负控、精确恢复、helper及whole资格分开。", "Linux原64GB/32GiB/jobs4、full→scoped fix→fmt顺序、旧driver UNKNOWN及禁止无新容量依据启动均保留。", "研究D−B采用门、Root/Current/FinalUse正常入口及外部实际接受均保持独立。"], "first_review_finding": "Current B02 latest text and five maintenance gates referenced the prior eed head; final review requires these current instructions follow 67cc while preserving historical source facts.", "new_native_execution": False, "source_ref_modified": False, "blocker_ledger_modified_by_reviewer": False}
    report["expected_frozen_document_blobs_verified"] = EXPECTED_FROZEN_BLOBS
    report["native10_root_receipt_identity"] = identity(native10_raw)
    report["native10_asserted_scope_matches_root_receipt"] = True
    report["resolved_review_findings"] = ["Current B02 text and five maintenance gates now name 67cc; historical source facts remain unchanged.", "Previously unregistered native10 terminal API link is now bound to an actual create-and-full-GET byte-equal registration included in the evidence plan."]
    report["native10_limits_retained"] = ["The physical negative reached file replacement only, not the directory negative.", "Original whole 147/7/2 remains a failure and B11 remains OPEN.", "Source/index/lock consistency is based on original recorded metadata; full index and lock bytes are not archived in the native10 receipt.", "Hard cancellation does not guarantee finally restoration; helper INFINITE wait and Command.status gained no deadline.", "PATH Python 3.12.10 is not measurement of the actual interpreter executable or sys.version."]
    raw = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.exists():
            assert args.output.read_bytes() == raw, "frozen publication review changed"
        else:
            args.output.write_bytes(raw)
    print(json.dumps({"result": report["result"], "counts": counts, "relative_links": len(links), "documents": report["documents"], "report_identity": identity(raw)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
