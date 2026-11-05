from __future__ import annotations

import datetime
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
SNAP = ROOT / "snapshot-1"
OUT = ROOT / "minimal-correction"


def identity(b: bytes) -> dict:
    return {"bytes": len(b), "sha256": hashlib.sha256(b).hexdigest(),
            "blob": hashlib.sha1(b"blob " + str(len(b)).encode() + b"\0" + b).hexdigest()}


def main() -> None:
    files = {p.name: p.read_text() for p in (SNAP / "deliverables").iterdir()}
    before = files.copy()
    edits = []

    def replace(name: str, old: str, new: str, reason: str) -> None:
        assert files[name].count(old) == 1, (name, old)
        line = files[name][:files[name].index(old)].count("\n") + 1
        files[name] = files[name].replace(old, new, 1)
        edits.append({"file": name, "line_before_edit": line, "old": old, "new": new, "reason": reason})

    ledger = json.loads(files["current-blockers.json"])
    by_id = {x["id"]: x for x in ledger["items"]}
    field_updates = {
        "B02": "PR#4797保持Draft，已发布cabc。保留第四批f825原25控制25PASS、所属七包5408 JUnit PASS/8FAIL与完整workspace19503 selected=19485 JUnit PASS/17FAIL/1TIMEOUT的原结果。随后Skills9、Migration166、V8及runtime76已在各自固定源通过，App原断连在c6限域通过；新fb9原full19506 selected=19490 JUnit PASS/16FAIL，57ignored、25早退、零retry。完整新旧原件均已独立重建核验；最终fix/fmt和新head原平台CI仍开放，尚未发布第四批源码。",
        "B11": "cabc source/merge各254exec通过，13resume和121rollout分列。strict ACL/token/delete原3失败保留。保持原public query和token旗标的窄ACL幂等V2、DELETE与父DELETE_CHILD四格物理矩阵V2及原Windows成功日志保留均已静态审查并精确应用到fb9组合源，尚未在Windows原生编译或执行。历史助手所述审批限制的原decision/action/reason尚未恢复，不作为新审批事实或永久禁令。",
        "B15": by_id["B15"]["evidence_scope_zh"].replace("完整新原件复核、最终fix/fmt与固定新源原平台CI仍待完成。", "完整新42件原件已独立重建复核；最终fix/fmt与固定新源原平台CI仍待完成。"),
    }
    for bid, value in field_updates.items():
        old = by_id[bid]["evidence_scope_zh"]
        replace("current-blockers.json", json.dumps(old, ensure_ascii=False), json.dumps(value, ensure_ascii=False),
                bid + ": synchronize evidence scope with already completed original receipts, without changing status or exit")
    old = ledger["code_ci_composition_note"]
    new = "21 unpublished source commits reach actualfb9. OriginalPython57 passed; post-Python ordinary-index byte failure is preserved and all9575 entry semantics match originalcabc. Root accepted currentc41 snapshot. The unfiltered full continuation completed without source reapplication or Python rerun:19490 JUnit PASS/16FAIL,57ignored,25bound early returns,0retry. All42 original files were independently reconstructed. Original scoped hygiene is tracked separately; no final code-tree or published-head CI qualification is claimed."
    replace("current-blockers.json", json.dumps(old, ensure_ascii=False), json.dumps(new, ensure_ascii=False),
            "Top-level composition note must not say completed full stages are still running")
    replace("CURRENT_AUDIT_PROGRESS.zh-CN.md",
            "[本轮非通过逐项根审](fourth-full-fb9-nonpass-root-review.json)",
            "[本轮非通过逐项根审](fourth-full-fb9-nonpass-root-review.json) / [新42件完整原件根审](fourth-full-fb9-complete-root-review.json)",
            "Bind the 42-file reconstruction statement directly to its completed full review")
    replace("CURRENT_AUDIT_PROGRESS.zh-CN.md",
            "literal-deny原25已通过；继续原所属7包和完整workspace、原fix/fmt，统一源码/锁/证据发布",
            "保留原25、所属7包与两轮full的已完成原结果；完成原fix/fmt后统一源码/锁/证据发布，16项失败继续开放",
            "Current action should not imply that already completed owning/full scopes have not run")
    replace("CURRENT_AUDIT_PROGRESS.zh-CN.md",
            "若继续研究，执行R0/R1/R2的新冻结协议与独立数据；不继续也可保留明确不采用决策，不追求事后正结果。",
            by_id["B18"]["next_closure_gate_zh"],
            "Keep B18's Markdown next gate consistent with the already updated machine ledger and independent #4823 evidence")
    replace("FOURTH_BATCH_QUALIFICATION.md",
            "| Final fix/fmt | Pending after concrete failure triage | Not yet executed | No final code-tree qualification |",
            "| Final fix/fmt | Original scoped flow after fb9 full | Execution and any automatic source delta are tracked by the current root receipt; no terminal success claimed here | No final code-tree qualification |",
            "Remove stale unexecuted wording without guessing the ongoing hygiene terminal result")
    replace("PROJECT_DIRECTION_AND_PLAN.zh-CN.md",
            "先追查新增线程恢复与代理响应失败，再完成最终fix/fmt并发布现有Draft，以固定新提交运行原Windows/macOS Intel/Linux等CI。",
            "新增线程恢复与代理响应失败的原因保持OPEN并单独继续定位；完成最终fix/fmt后发布现有Draft，以固定新提交运行原Windows/macOS Intel/Linux等CI。",
            "Reflect root's explicit non-blocking Draft publication decision while retaining both new failures")
    after_ledger = json.loads(files["current-blockers.json"])
    unchanged_fields = ["status", "original_exit_condition_zh", "closure_class"]
    for old_item, new_item in zip(ledger["items"], after_ledger["items"], strict=True):
        assert old_item["id"] == new_item["id"]
        for field in unchanged_fields:
            assert old_item[field] == new_item[field]
    assert ledger["counts"] == after_ledger["counts"]
    assert ledger["scoped_closed_ids"] == after_ledger["scoped_closed_ids"]
    assert ledger["open_ids"] == after_ledger["open_ids"]
    assert ledger["scientific_hold_ids"] == after_ledger["scientific_hold_ids"]
    OUT.mkdir(exist_ok=True)
    changed = []
    patches = []
    for name in sorted(files):
        if files[name] == before[name]:
            continue
        relative = "deliverables/" + name
        p = OUT / relative
        p.parent.mkdir(exist_ok=True)
        p.write_text(files[name])
        delta = "diff --git a/" + relative + " b/" + relative + "\n"
        delta += "".join(difflib.unified_diff(before[name].splitlines(keepends=True), files[name].splitlines(keepends=True),
                                              fromfile="a/" + relative, tofile="b/" + relative))
        patches.append(delta)
        changed.append({"path": relative, "preimage": identity(before[name].encode()), "postimage": identity(files[name].encode())})
    patch = "".join(patches)
    (OUT / "report-consistency.patch").write_text(patch)
    with tempfile.TemporaryDirectory(prefix="review-patch-", dir=OUT) as temp:
        checkout = Path(temp)
        for row in changed:
            p = checkout / row["path"]
            p.parent.mkdir(exist_ok=True, parents=True)
            p.write_text(before[p.name])
        subprocess.run(["git", "init", "-q", str(checkout)], check=True)
        subprocess.run(["git", "-C", str(checkout), "apply", "--check", "-"], input=patch.encode(), check=True)
        subprocess.run(["git", "-C", str(checkout), "apply", "-"], input=patch.encode(), check=True)
        for row in changed:
            assert identity((checkout / row["path"]).read_bytes()) == row["postimage"]
    manifest = {
        "schema": "hepta.fourth.final-report-minimal-correction.v1",
        "observed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "base_snapshot": "../snapshot-1/snapshot-receipt.json",
        "scope": "Proposed edits only in this independent directory. Root deliverables, registry, source, native lane and refs are unchanged.",
        "files": changed, "edits": edits,
        "patch": {"path": "report-consistency.patch", **identity(patch.encode())},
        "isolated_git_apply_check_and_postimage_verification": True,
        "all_23_status_exit_closure_class_unchanged": True,
        "all_23_id_sets_and_counts_unchanged": True,
        "no_evidence_index_or_registry_edit": True,
        "ongoing_hygiene_limit": "This patch claims no hygiene terminal success. Root should merge against its latest actual receipt and retain any subsequent source-specific updates.",
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"files": changed, "patch": manifest["patch"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
