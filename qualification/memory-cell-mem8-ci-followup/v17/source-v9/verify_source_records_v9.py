#!/usr/bin/env python3
"""Audit original V9 source-only records offline; never runs repository code."""
import ast
import base64
from datetime import datetime
import difflib
import hashlib
import json
import lzma
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
import tomllib

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent
RECORDS = ROOT / "records"
HEAD = '408226fc670bfa8c1736e2b264750b549237b7c4'
TREE = '112fe78dedd76b258b17976cff14693c52897c8d'
BASE_TREE = "12159640adcf073b51f3837e75575e11f5c20233"
HARNESS = '43d28191901d7d08c4543884d2f81c0b44eb8678'
INPUT_SHA = '66bafeebc5d006befa4b333eadb0f555304d6cac72ee520c6dda55e3ed78c90a'
GOLDEN_SHA = "17ac4ede6046ccde7f2a2952d2e3e699ff75258089e195b3783638ac9735fc96"


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def safe_path(path):
    value = PurePosixPath(path)
    assert path and not value.is_absolute() and ".." not in value.parts
    assert value.as_posix() == path and "\\" not in path
    return value


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            assert key not in result, ("duplicate JSON key", key)
            result[key] = value
        return result
    def invalid(value):
        raise ValueError("non-JSON number: " + value)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def read_json(name):
    return strict_json((RECORDS / name).read_bytes())


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode()


def listing(name):
    entries = {}
    for row in (RECORDS / name).read_bytes().split(b"\0"):
        if not row:
            continue
        metadata, raw_path = row.split(b"\t", 1)
        mode, kind, digest = metadata.decode().split()
        path = raw_path.decode()
        safe_path(path)
        assert kind in {"blob", "commit"} and path not in entries
        assert re.fullmatch("[0-9a-f]{40}", digest)
        entries[path] = {"mode": mode, "type": kind, "git_blob": digest}
    return entries


def git_tree(entries):
    node = {}
    for path, value in entries.items():
        current = node
        parts = safe_path(path).parts
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        assert parts[-1] not in current
        current[parts[-1]] = (value["mode"], value["git_blob"])
    def hash_node(current):
        body = b""
        for name, child in sorted(current.items(), key=lambda row: row[0].encode() +
                                  (b"/" if isinstance(row[1], dict) else b"")):
            mode, digest = ("40000", hash_node(child)) if isinstance(child, dict) else child
            body += mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(digest)
        return hashlib.sha1(b"tree " + str(len(body)).encode() + b"\0" + body).hexdigest()
    return hash_node(node)


manifest = read_json("FILE_MANIFEST.json")
listed = set()
for member in manifest["members"]:
    safe_path(member["path"])
    assert member["path"] not in listed
    listed.add(member["path"])
    path = RECORDS / member["path"]
    assert path.is_file() and not path.is_symlink()
    assert identity(path.read_bytes()) == {key: member[key] for key in ("bytes", "sha256", "git_blob")}
actual_paths = {path.relative_to(RECORDS).as_posix() for path in RECORDS.rglob("*") if path.is_file()}
assert actual_paths == listed | {"FILE_MANIFEST.json"}
assert not any(path.is_symlink() for path in RECORDS.rglob("*"))
archive_info = strict_json((ROOT / "ARCHIVE_INFO.json").read_bytes())
archive_path = ROOT / archive_info["path"]
assert identity(archive_path.read_bytes()) == {key: archive_info[key] for key in ("bytes", "sha256", "git_blob")}
with tarfile.open(archive_path, "r:xz") as archive:
    names = set()
    for member in archive:
        safe_path(member.name)
        assert member.isfile() and member.name not in names
        names.add(member.name)
        assert archive.extractfile(member).read() == (RECORDS / member.name).read_bytes()
    assert names == actual_paths and len(names) == archive_info["members"]

result, start = read_json("RESULT.json"), read_json("START.json")
assert result["initial_commit"] == HEAD and result["initial_tree"] == TREE
assert result["base_tree"] == BASE_TREE
assert result["status"] == "passed_source_gates_only_review_remaining" and result["failure"] is None
assert result["native_tests_executed"] == result["model_requests_executed"] == 0
assert not result["source_refs_modified"] and not result["source_candidate_committed"] and not result["donor_used"]
assert result["source_before"] == {"head": HEAD, "tree": TREE, "status": ""}
assert all(result["source_after"][key] == result["source_before"][key] for key in ("head", "tree"))
begin, end, deadline = [datetime.fromisoformat(result[key]) for key in ("started_at", "finished_at", "deadline_utc")]
assert begin <= end <= deadline and (deadline - begin).total_seconds() == 600
assert (start["workflow_commit"], start["workflow_run"], start["workflow_attempt"]) == (HARNESS, '43054829731', '1')
assert start["started_at"] == result["started_at"] and start["deadline_utc"] == result["deadline_utc"]
encoded = (RECORDS / "INPUT.json.xz").read_bytes()
assert len(encoded) == 388060 and identity(encoded)["sha256"] == INPUT_SHA
assert lzma.decompress(encoded) == (RECORDS / "INPUT.json").read_bytes()
assert identity((RECORDS / "DRIVER.py").read_bytes())["git_blob"] == '210febab5369cbd99bd38c1b39cf8523b8f9399e'
assert identity((RECORDS / "AGENTS.md").read_bytes())["git_blob"] == "faa57cc0db48123e1011f1eb47692cd3bbbcfc3a"
source, capsule = read_json("INPUT.json"), read_json("FORMATTED_CAPSULE.json")
assert source["source_gate_run_version"] == 9
assert len(source["files"]) == len(capsule["files"]) == 117
input_rows = {row["path"]: row for row in source["files"]}
post_rows = {row["path"]: row for row in capsule["files"]}
assert len(input_rows) == len(post_rows) == 117 and set(input_rows) == set(post_rows)
retained_paths = set(input_rows) - {row["path"] for row in source["new_reviewed_edits_vs_parent"]}
assert len(retained_paths) == 116
assert all(post_rows[path]["postimage_git_blob"] == input_rows[path]["input_git_blob"] for path in retained_paths)
base, initial, final = [listing(name) for name in ("BASE_TREE.ls-tree", "INITIAL_TREE.ls-tree", "CANDIDATE_TREE.ls-tree")]
assert git_tree(base) == BASE_TREE and git_tree(initial) == TREE
assert git_tree(final) == result["candidate_tree"]
assert len(initial) == len(final) == 14053
expected_initial, expected_final = dict(base), dict(base)
changed, format_patch = [], ""
for path, row in input_rows.items():
    before = (RECORDS / "pre-format" / path).read_bytes()
    after = (RECORDS / "post-format" / path).read_bytes()
    assert identity(before) == {"bytes": row["bytes"], "sha256": row["sha256"], "git_blob": row["input_git_blob"]}
    assert before == row["content"].encode()
    assert (base.get(path) or {}).get("git_blob") == row["preimage_git_blob"]
    if row["preimage_git_blob"]:
        assert identity((RECORDS / "base" / path).read_bytes())["git_blob"] == row["preimage_git_blob"]
    post = post_rows[path]
    assert identity(after) == {"bytes": post["postimage_bytes"], "sha256": post["postimage_sha256"], "git_blob": post["postimage_git_blob"]}
    assert after == base64.b64decode(post["content_base64"], validate=True)
    assert row["mode"] == post["mode"]
    expected_initial[path] = {"mode": row["mode"], "type": "blob", "git_blob": row["input_git_blob"]}
    expected_final[path] = {"mode": post["mode"], "type": "blob", "git_blob": post["postimage_git_blob"]}
    if before != after:
        changed.append(path)
        format_patch += "".join(difflib.unified_diff(before.decode().splitlines(keepends=True), after.decode().splitlines(keepends=True), fromfile="pre-format/" + path, tofile="post-format/" + path))
assert initial == expected_initial and final == expected_final
assert set(changed) == set(read_json("FORMAT_RESULT.json")["formatter_changed_paths"])
assert result["source_after"]["status"] == "".join("M  " + path + "\n" for path in sorted(changed))
for lock in start["locks"]:
    assert base[lock["path"]] == initial[lock["path"]] == final[lock["path"]]
    assert final[lock["path"]]["git_blob"] == lock["git_blob"]

phases = []
for path in sorted(RECORDS.glob("*.json")):
    receipt = strict_json(path.read_bytes())
    if not isinstance(receipt, dict) or not {"raw_file", "exit_code", "timed_out"} <= receipt.keys():
        continue
    safe_path(receipt["raw_file"])
    data = (RECORDS / receipt["raw_file"]).read_bytes()
    assert identity(data) == {key: receipt[key] for key in ("bytes", "sha256", "git_blob")}
    assert not receipt["timed_out"] and receipt["cleanup"] is None
    assert receipt["exit_code"] == (1 if path.stem == "full-tree-old-case-name-scan" else 0)
    assert begin <= datetime.fromisoformat(receipt["started_at"]) <= datetime.fromisoformat(receipt["finished_at"]) <= end
    phases.append({"phase": path.stem, **receipt})
phase_map = {row["phase"]: row for row in phases}
assert {"format", "diff-check", "full-tree-old-case-name-scan", "caller-self-test", "caller-verify", "stage-formatted-candidate",
        "python-test_hepta_typed_callers", "python-test_hepta_caller_cache"} <= phase_map.keys()
assert read_json("caller-self-test.raw.log") == {"status": "PASS_HEPTA_CALLER_PROOF_SELF_TEST"}
assert read_json("CALLER_SELF_TEST_CHECK.json")["status"] == "PASS"
rename = read_json("FULL_TREE_RENAME_SCAN.json")
assert len(rename["renames"]) == 13 and rename["matches"] == [] and rename["review_required"] is False
assert rename["renames"] == source["case_renames"]
assert (RECORDS / phase_map["full-tree-old-case-name-scan"]["raw_file"]).read_bytes() == b""

regressions = []
for script, expected_count in (("scripts/test_hepta_typed_callers.py", 16), ("scripts/test_hepta_caller_cache.py", 2)):
    tree = ast.parse((RECORDS / "post-format" / script).read_text())
    expected_ids = sorted("__main__." + node.name + "." + method.name for node in tree.body if isinstance(node, ast.ClassDef)
                          for method in node.body if isinstance(method, ast.FunctionDef) and method.name.startswith("test_"))
    assert len(expected_ids) == expected_count
    label = "python-" + Path(script).stem
    raw = (RECORDS / phase_map[label]["raw_file"]).read_bytes()
    text = raw.decode()
    cases = re.findall(r"^(test_[A-Za-z0-9_]+) \(([^()\r\n]+)\) \.\.\. (.+)$", text, re.MULTILINE)
    observed_ids = [case[1] for case in cases]
    assert sorted(observed_ids) == expected_ids and len(set(observed_ids)) == expected_count
    assert all(outcome == "ok" and identifier.endswith("." + method) for method, identifier, outcome in cases)
    assert re.findall(r"^Ran (\d+) tests? in [0-9.]+s$", text, re.MULTILINE) == [str(expected_count)]
    assert text.rstrip().endswith("\nOK")
    count_record = read_json(label + "-COUNTS.json")
    assert count_record["status"] == "PASS" and count_record["actual_named_pass"] == expected_count
    assert count_record["actual_named_fail"] == count_record["actual_named_skip"] == 0
    assert sorted(count_record["expected_case_ids"]) == expected_ids
    assert count_record == result["source_python_regressions"][label]
    regressions.append({"script": script, "actual_case_ids": observed_ids, "pass": expected_count, "fail": 0, "skip": 0, "raw": identity(raw)})

golden_raw = (RECORDS / "GOLDEN_CALLER_RECEIPT.json").read_bytes()
assert len(golden_raw) == 75046 and identity(golden_raw)["sha256"] == GOLDEN_SHA
golden, actual_caller = strict_json(golden_raw), read_json("caller-verify.raw.log")
assert golden["rustFilesScanned"] == 6200
callers_data = (RECORDS / "CALLERS.toml").read_bytes()
assert identity(callers_data)["git_blob"] == "c1a1b945171cdb20723e398cabe6a7888fa0abdb"
roots = tomllib.loads(callers_data.decode())["source_roots"]
roster = sorted(path for source_root in roots for path, row in initial.items()
                if path.startswith(source_root.rstrip("/") + "/") and path.endswith(".rs"))
assert len(roster) == 6204 and len(set(roster)) == 6204
inventory = read_json("CALLER_SOURCE_INVENTORY.json")
assert roster == inventory["paths"] and inventory["rust_files"] == 6204
assert inventory["ignored_path_fragments_applied"] is False
expected_caller = dict(golden)
expected_caller["rustFilesScanned"] = len(roster)
assert canonical(actual_caller) == canonical(expected_caller)
assert canonical(read_json("EXPECTED_CALLER_RECEIPT.json")) == canonical(expected_caller)
assert actual_caller["status"] == "PASS_HEPTA_CALLER_CLOSED_SET" and actual_caller["authorityGranted"] is False
comparison = read_json("CALLER_GOLDEN_COMPARISON.json")
assert comparison == result["caller_golden_comparison"]
assert comparison["status"] == "PASS" and comparison["ignored_receipt_fields"] == []
assert comparison["only_derived_field"] == "rustFilesScanned" and comparison["explicit_count_delta"] == 4
assert comparison["actual_canonical_sha256"] == comparison["expected_canonical_sha256"] == identity(canonical(expected_caller))["sha256"]
tools = read_json("CI_TOOL_IDENTITIES.json")
dotslash = [row for row in tools if row["name"] == "dotslash"]
assert len(dotslash) == 1 and dotslash[0]["bytes"] == 1642752
assert dotslash[0]["sha256"] == "54a03b42f0337eba584bc33563237d45aeca11a34de2e7159f76d7695fe5b936"
assert (RECORDS / "just-version.raw.log").read_bytes().strip() == b"just 1.51.0"
assert (RECORDS / "rustfmt-version.raw.log").read_bytes().strip() == b"rustfmt 1.9.0-stable (ac68faa20c 2026-05-25)"

(ROOT / "FORMAT_ONLY.patch").write_text(format_patch)
summary = {"schema": "hepta.mem8.source-ci.v9.offline-verification.v1", "status": "PASS_OFFLINE_ORIGINAL_SOURCE_RECORDS",
           "original_run": 43054829731, "original_job": 130641359569, "workflow_head": HARNESS,
           "source_head_unchanged": HEAD, "initial_tree": TREE, "formatted_tree": result["candidate_tree"],
           "source_before_clean": True, "source_after_status": result["source_after"]["status"],
           "source_after_note": "Formatter changes, if any, are staged; original HEAD/tree remain unchanged. Staged edits are not clean-tree proof.",
           "base_entries": len(base), "initial_entries": len(initial), "final_entries": len(final), "all_three_merkle_trees_recomputed": True,
           "overlay_paths": 117, "formatter_changed_paths": changed, "format_only_patch": identity(format_patch.encode()),
           "renamed_case_old_name_hits": 0, "rename_inventory": 13, "rust_files_scanned": 6204, "authority_granted": False,
           "original_golden": identity(golden_raw), "full_golden_equal_except_derived_rust_count": True,
           "source_python_regressions": regressions, "source_python_actual_pass": 18, "source_python_actual_fail": 0, "source_python_actual_skip": 0,
           "manifest_members_verified": len(listed), "tar_members_verified": len(actual_paths), "original_archive": archive_info,
           "phase_receipts": phases, "started_at": result["started_at"], "finished_at": result["finished_at"],
           "deadline_utc": result["deadline_utc"], "elapsed_seconds": (end - begin).total_seconds(),
           "native_project_tests": 0, "model_calls": 0, "locks_unchanged": start["locks"], "tool_identities": tools,
           "limit": "Source-only formatter, Python regression, caller and tree proof; no native compile, new Bazel graph solution or provider qualification."}
(ROOT / "OFFLINE_VERIFICATION.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps({key: value for key, value in summary.items() if key not in {"phase_receipts", "source_python_regressions", "tool_identities"}}, indent=2))
