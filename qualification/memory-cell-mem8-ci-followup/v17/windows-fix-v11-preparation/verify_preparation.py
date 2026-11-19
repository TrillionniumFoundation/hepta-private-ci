#!/usr/bin/env python3
"""Verify the final V11 lint preparation; execute neither harness nor repository code."""
import ast
import hashlib
import json
from pathlib import Path
import sys


HEAD = "ceadcb3b11dbd94a9d07afb7e6301555e4ff3f80"
TREE = "27651abb15e269c427c75f28f92a3bd1cd9d191f"
OLD_HEAD = "d0f6507e08f7f5c5855f5164d07c049a34d1a6d9"
OLD_TREE = "658fa040046285116b1fd81b94ff8c96444072ad"
CHANGED = "codex-rs/windows-sandbox-rs/src/setup_process.rs"
PLAN = ".github/fixtures/mem-windows-sandbox-fix-plan.json"
DRIVER = ".github/scripts/mem_windows_sandbox_fix.py"
SUPPORT = ".github/scripts/mem_windows_sandbox_fix_support.py"
WORKFLOW = ".github/workflows/hepta-mem-windows-sandbox-fix.yml"


def ident(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def rows(raw):
    result = {}
    for part in raw.split(b"\0"):
        if part:
            left, name = part.split(b"\t", 1)
            mode, kind, sha = left.decode().split()
            name = name.decode()
            assert kind == "blob" and name not in result
            result[name] = mode, sha
    return result


def merkle(entries):
    root = {}
    for name, value in entries.items():
        current = root
        parts = name.split("/")
        assert all(p not in ("", ".", "..") for p in parts)
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        assert parts[-1] not in current
        current[parts[-1]] = value
    def visit(node):
        raw = bytearray()
        for name, value in sorted(node.items(), key=lambda pair: (pair[0] + ("/" if isinstance(pair[1], dict) else "")).encode()):
            mode, sha = ("40000", visit(value)) if isinstance(value, dict) else value
            raw.extend(mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(sha))
        return hashlib.sha1(b"tree " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    return visit(root)


def main(root):
    manifest = json.loads((root / "FILE_MANIFEST.json").read_bytes())
    for row in manifest["files"]:
        path = Path(row["path"])
        assert not path.is_absolute() and ".." not in path.parts
        assert ident((root / path).read_bytes()) == {k: row[k] for k in ("bytes", "sha256", "git_blob")}
    final = json.loads((root / "STATIC_PREPARATION.json").read_bytes())
    assert final["status"] == "FROZEN_PREPARED_NOT_ADMITTED"
    assert (final["source_head"], final["source_tree"]) == (HEAD, TREE)
    generated = root / "rendered"
    for row in final["four_objects"]:
        assert ident((generated / row["path"]).read_bytes()) == {k: row[k] for k in ("bytes", "sha256", "git_blob")}
    plan = json.loads((generated / PLAN).read_bytes())
    prior = json.loads((root / "reference/prior-rendered" / PLAN).read_bytes())
    assert (plan["source_head"], plan["source_tree"]) == (HEAD, TREE)
    assert (prior["source_head"], prior["source_tree"]) == (OLD_HEAD, OLD_TREE)
    before = rows((root / "reference/PRIOR_TREE.ls-tree").read_bytes())
    after_raw = (root / "reference/CANDIDATE_TREE.ls-tree").read_bytes()
    after = rows(after_raw)
    assert len(before) == len(after) == 14053 and set(before) == set(after)
    assert merkle(before) == OLD_TREE and merkle(after) == TREE
    assert [p for p in after if before[p] != after[p]] == [CHANGED]
    assert ident(after_raw) == plan["complete_tree_inventory"]
    assert len(plan["files"]) == len(prior["files"]) == 20
    assert set(plan["files"]) == set(prior["files"])
    assert [p for p in plan["files"] if plan["files"][p] != prior["files"][p]] == [CHANGED]
    for name, pin in plan["files"].items():
        assert after[name] == (pin["mode"], pin["git_blob"])
        assert ident((root / "source-inputs" / name).read_bytes()) == {k: pin[k] for k in ("bytes", "sha256", "git_blob")}
    assert {p for p in plan["files"] if p.endswith(".lock")} == {"MODULE.bazel.lock", "codex-rs/Cargo.lock"}
    assert all(plan["files"][p] == prior["files"][p] for p in plan["files"] if p.endswith(".lock"))
    for name, git_blob in ((DRIVER, "a6e1f9d76de87cb7f86bfe7b7db76b2675034cc4"), (SUPPORT, "85b6407d0b8a8fa6bd6859f86ccbbdbae3635595")):
        raw = (generated / name).read_bytes()
        assert raw == (root / "reference/prior-rendered" / name).read_bytes()
        assert ident(raw)["git_blob"] == git_blob
        ast.parse(raw)
    workflow = (generated / WORKFLOW).read_text()
    inverse = workflow
    for current, old, count in (
        ("codex/mem8-windows-sandbox-fix-v11-20261111-ed353817", "codex/mem8-windows-sandbox-fix-v10-20261111-ed353817", 2),
        (HEAD, OLD_HEAD, 3), (TREE, OLD_TREE, 1),
    ):
        assert inverse.count(current) == count
        inverse = inverse.replace(current, old)
    assert inverse.encode() == (root / "reference/prior-rendered" / WORKFLOW).read_bytes()
    assert ident(workflow.encode())["git_blob"] == "cfd269de944d445e4772cd943bc95695c595d3d9"
    assert plan["job_timeout_minutes"] == 65 and plan["native_test_commands"] == []
    assert plan["scoped_fix_command"] == ["just", "fix", "--locked", "-p", "codex-windows-sandbox"]
    assert plan["native_or_elevated_PASS_admission_dependency"] is False
    audit_raw = (root / "reference/V11_ROOT_SOURCE_GATE_AUDIT.json").read_bytes()
    audit = json.loads(audit_raw)
    assert audit["status"] == "PASS_FULL_ORIGINAL_ZIP_CANONICAL_TAR_AND_UNCHANGED_VERIFIER"
    assert (audit["source"], audit["tree"]) == (HEAD, TREE)
    assert audit["formatter_changed_paths"] == [] and audit["source_after_clean"] is True
    assert (audit["python_pass"], audit["old_name_hits"], audit["rust_inventory"]) == (18, 0, 6204)
    assert audit["full_golden_equal_except_derived_count"] and audit["both_lock_bytes_unchanged"]
    assert audit["native_tests_executed"] == audit["real_model_requests"] == 0
    qualification = plan["source_only_qualification"]
    assert qualification["status"] == "QUALIFIED_SOURCE_ONLY_NOT_NATIVE"
    assert (qualification["original_run"], qualification["original_job"], qualification["attempt"]) == (audit["run"], audit["job"], audit["attempt"])
    assert qualification["root_full_audit"] == ident(audit_raw)
    commit_raw = (root / "reference/V11_CANDIDATE_COMMIT_READBACK.json").read_bytes()
    assert ident(commit_raw) == plan["commit_readback"]
    commit = json.loads(commit_raw)
    assert commit["sha"] == HEAD and commit["tree"]["sha"] == TREE
    assert [p["sha"] for p in commit["parents"]] == [OLD_HEAD]
    history = root / "history/provisional-before-source-gate-binding"
    historical_manifest = json.loads((history / "HISTORY_MANIFEST.json").read_bytes())
    for row in historical_manifest["files"]:
        assert ident((history / row["path"]).read_bytes()) == {k: row[k] for k in ("bytes", "sha256", "git_blob")}
    historical_plan = json.loads((history / "rendered" / PLAN).read_bytes())
    assert historical_plan["source_only_qualification"]["status"] == "PENDING_ORIGINAL_V11_SOURCE_GATE"
    assert all(historical_plan[k] == plan[k] for k in plan if k != "source_only_qualification")
    return {"status": "PASS_FINAL_V11_LINT_PREPARATION_BYTES_ONLY",
            "source": HEAD, "tree": TREE, "tree_entries": len(after), "full_dependency_texts": 20,
            "sole_dependency_change": CHANGED, "driver_and_support_byte_identical_to_original_V10": True,
            "workflow_only_six_identity_substitutions": True, "provisional_history_preserved": True,
            "source_gate_run": audit["run"], "source_gate_job": audit["job"],
            "native_execution": 0, "model_requests": 0, "workflow_admission": False,
            "original_V10_lint_result": "FAIL_DIRTY_SOURCE",
            "scope": "This preparation authorizes no execution and transfers no earlier native or lint PASS."}


if __name__ == "__main__":
    print(json.dumps(main(Path(sys.argv[1]).resolve()), indent=2, sort_keys=True))
