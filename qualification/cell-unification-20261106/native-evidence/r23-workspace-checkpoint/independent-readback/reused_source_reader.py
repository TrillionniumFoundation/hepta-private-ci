#!/usr/bin/env python3
"""Read restored, closed r20/r21/r22 artifacts; perform no builds or Git writes.

This is a NEW audit after scratch loss. It does not reproduce missing old audit
bytes. The original framework map is complete cached Git data, reserialized as
an explicitly new input. Full trees are rebuilt from its leaves and each raw
archive's changed-source files, never from a target-tree result supplied by root.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import tarfile

BASE_COMMIT = "bef6fa7645df9df12b69fda499e97eed25de6c75"
BASE_TREE = "ce997fd958b8073d99b1e5bc302b7a0188fb4c3b"
LOCK_SHA = "4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c"
ROOT = Path(__file__).resolve().parent
SPECS = {
    "r20": {
        "archive_sha": "926c742219a6fae6bd96c0997d72bf730930e120a5f7bbf528383ec96466bfe7",
        "archive_bytes": 1271446, "members": 210, "sources": 187,
        "source_manifest": "native-candidate-r20-source.json",
        "source_manifest_sha": "1109bc5d38e702cb4e30de40af8877fe024a2b92933285546ab9b6c02b05bcb8",
        "stage": 48, "commit": "07699df6fb5bfb46562ecb0c2eccd0d232d18eac",
        "tree": "e65356fc570296b74644967054eaded15b8ed440",
        "parent": "0c78b43424ced27d37892a7744de065c1497d5e8",
        "prefix": "native-app-server-r20", "phases": ["strict", "tests"],
        "packages": ["codex-app-server", "codex-linux-sandbox"],
        "exit": 0, "outer_job": "1a1b0b35661-fc05-723f",
    },
    "r21": {
        "archive_sha": "1d9c0dc71fdda73158d1011d828046aa3c6f02219ed311a10d6e864795519652",
        "archive_bytes": 1190333, "members": 206, "sources": 187,
        "source_manifest": "native-candidate-r20-source.json",
        "source_manifest_sha": "1109bc5d38e702cb4e30de40af8877fe024a2b92933285546ab9b6c02b05bcb8",
        "stage": 48, "commit": "07699df6fb5bfb46562ecb0c2eccd0d232d18eac",
        "tree": "e65356fc570296b74644967054eaded15b8ed440",
        "parent": "0c78b43424ced27d37892a7744de065c1497d5e8",
        "prefix": "native-workspace-r21", "phases": ["tests"],
        "packages": None, "exit": 101, "outer_job": "1a1b0c142d4-fc05-729f",
    },
    "r22": {
        "archive_sha": "c7a770bfa2d17e23c05009862c688ab70fed4b30744df7642fe5d2db75b95e95",
        "archive_bytes": 1145892, "members": 215, "sources": 188,
        "source_manifest": "native-candidate-r22-source.json",
        "source_manifest_sha": "8cd1ec59c95d6c777d887f3302b257dc5230a7bfa5570fe9df0f0b2ef361aba5",
        "stage": 49, "commit": "50dd4bedefcd1b8e2e8cd5cf5023c60a86d38d0a",
        "tree": "be34ab1afe622ad3b8f030c8c5018f4f54fbc304",
        "parent": "07699df6fb5bfb46562ecb0c2eccd0d232d18eac",
        "prefix": "native-app-server-client-r22", "phases": ["strict", "tests"],
        "packages": ["codex-app-server-client"],
        "exit": 0, "outer_job": "1a1b0e81574-fc05-73de",
    },
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def pin(data: bytes) -> dict:
    return {"bytes": len(data), "sha256": sha(data)}


def safe(path: str) -> str:
    p = PurePosixPath(path)
    assert path and str(p) == path and not p.is_absolute(), path
    assert all(x not in ("", ".", "..") for x in p.parts), path
    assert "\\" not in path and "\0" not in path, path
    return path


def write_json(path: Path, value) -> dict:
    data = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert not path.is_symlink() and path.read_bytes() == data, str(path)
    else:
        with path.open("xb") as f:
            f.write(data)
    return {"path": str(path.relative_to(ROOT)), **pin(data)}


def tree_hash(children: list[dict]) -> str:
    payload = bytearray()
    def order(e):
        return (e["name"] + ("/" if e["type"] == "tree" else "")).encode()
    for e in sorted(children, key=order):
        assert re.fullmatch(r"[0-9a-f]{40}", e["sha"])
        payload += e["mode"].lstrip("0").encode() + b" " + e["name"].encode() + b"\0"
        payload += bytes.fromhex(e["sha"])
    return hashlib.sha1(b"tree " + str(len(payload)).encode() + b"\0" + payload).hexdigest()


def rebuild(rows: list[dict], validate_original: bool = False) -> dict:
    entries = {}
    dirs = {""}
    for e in rows:
        path = safe(e["path"])
        assert path not in entries, path
        assert (e["type"], e["mode"]) in {
            ("tree", "040000"), ("tree", "40000"),
            ("blob", "100644"), ("blob", "100755"), ("blob", "120000"),
            ("commit", "160000"),
        }, e
        entries[path] = e
        if e["type"] == "tree":
            dirs.add(path)
    children = collections.defaultdict(list)
    for path, e in entries.items():
        pp = PurePosixPath(path)
        parent = str(pp.parent)
        parent = "" if parent == "." else parent
        assert parent in dirs, ("incomplete original map", path, parent)
        children[parent].append(e)
    computed = {}
    proof = []
    for directory in sorted(dirs, key=lambda d: (len(PurePosixPath(d).parts), d), reverse=True):
        bound = []
        for e in children[directory]:
            value = computed[e["path"]] if e["type"] == "tree" else e["sha"]
            bound.append({"name": PurePosixPath(e["path"]).name,
                          "mode": e["mode"], "type": e["type"], "sha": value})
        value = tree_hash(bound)
        if validate_original and directory:
            assert value == entries[directory]["sha"], (directory, value, entries[directory]["sha"])
        computed[directory] = value
        proof.append({"path": directory, "tree": value, "children": len(bound)})
    return {"tree": computed[""], "computed": computed, "proof": proof,
            "entries": entries, "root_children": children[""]}


def load_original() -> dict:
    origin = json.loads((ROOT / "INPUT-ORIGIN.json").read_bytes())
    for row in origin["files"]:
        p = ROOT / row["path"]
        data = p.read_bytes()
        assert len(data) == row["bytes"] and sha(data) == row["sha256"], str(p)
    source = ROOT / "input/original-framework-recursive-reserialized.json"
    if source.exists():
        raw = source.read_bytes()
    else:
        raw = gzip.decompress((ROOT / "input/original-framework-recursive-reserialized.json.gz").read_bytes())
    data = json.loads(raw)
    assert data["truncated"] is False and len(data["tree"]) == 12259
    assert data["sha"] == BASE_COMMIT, "Original API header names commit, not root tree"
    original = rebuild(data["tree"], validate_original=True)
    assert original["tree"] == BASE_TREE
    assert len(original["computed"]) == 1367
    proof_pin = write_json(ROOT / "BASE-TREE-VALIDATION.json", {
        "schema": "hepta.recovered-independent-original-tree.v1",
        "audit_is_new_after_scratch_loss": True,
        "input_kind": "complete original cached Git listing reserialized; not a newly fetched target tree",
        "original_commit": BASE_COMMIT, "computed_original_root_tree": original["tree"],
        "input_entries": len(data["tree"]), "directories_rehashed": len(original["computed"]),
        "all_1366_original_directory_entries_matched": True,
        "full_directory_proof": original["proof"],
        "source_input": {"uncompressed_bytes": len(raw), "uncompressed_sha256": sha(raw)},
    })
    original["report_pin"] = proof_pin
    return original


def archive_read(run: str, native: Path) -> tuple[dict[str, bytes], dict]:
    spec = SPECS[run]
    archive = native / f"checkpoint-{run}-closed.tar.gz"
    raw = archive.read_bytes()
    assert len(raw) == spec["archive_bytes"] and sha(raw) == spec["archive_sha"], run
    items = {}
    modes = {}
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        assert len(members) == spec["members"], (run, len(members))
        for m in members:
            safe(m.name)
            assert m.isfile() and m.type in (tarfile.REGTYPE, tarfile.AREGTYPE), m.name
            assert not m.linkname and m.name not in items and m.mode == 0o644, m.name
            data = tar.extractfile(m).read()
            assert len(data) == m.size, m.name
            items[m.name] = data
            modes[m.name] = f"{m.mode:04o}"
    index = json.loads(items["INDEX.json"])
    assert isinstance(index, list) and len(index) == spec["members"] - 1
    indexed = {}
    for row in index:
        assert set(row) == {"path", "bytes", "sha256", "mode"}, row
        path = safe(row["path"])
        assert path not in indexed and path != "INDEX.json"
        data = items[path]
        assert row == {"path": path, **pin(data), "mode": modes[path]}, path
        indexed[path] = row
    assert set(indexed) == set(items) - {"INDEX.json"}
    extracted = native / f"checkpoint-{run}"
    disk_files = set()
    for p in extracted.rglob("*"):
        assert not p.is_symlink(), str(p)
        if p.is_file():
            name = str(p.relative_to(extracted))
            assert name in items and p.read_bytes() == items[name], name
            assert (p.stat().st_mode & 0o777) == 0o644, name
            disk_files.add(name)
        else:
            assert p.is_dir(), str(p)
    assert disk_files == set(items)
    groups = collections.Counter(path.split("/", 1)[0] for path in items)
    assert groups["source"] == spec["sources"]
    manifest = [{"path": name, **pin(data), "mode": modes[name]} for name, data in sorted(items.items())]
    manifest_pin = write_json(ROOT / run / "ARCHIVE-MEMBERS.json", manifest)
    return items, {
        "archive": {"path": str(archive), **pin(raw), "git_blob": blob(raw)},
        "members": len(items), "indexed_members": len(indexed), "groups": dict(groups),
        "all_member_paths_regular_safe_unique": True, "all_archive_modes_0644": True,
        "all_index_sizes_sha256_modes_matched": True,
        "all_extracted_bytes_and_member_set_matched": True,
        "index": pin(items["INDEX.json"]), "member_readback": manifest_pin,
    }


def source_read(run: str, items: dict[str, bytes], original: dict) -> dict:
    spec = SPECS[run]
    manifest_raw = items["evidence/" + spec["source_manifest"]]
    assert sha(manifest_raw) == spec["source_manifest_sha"]
    manifest = json.loads(manifest_raw)
    assert manifest["source_tree"] == spec["tree"] and manifest["source_commit"] == spec["commit"]
    assert manifest["lock_sha256"] == LOCK_SHA and manifest["applied_stage"] == spec["stage"]
    rows = manifest["changed_files"]
    assert len(rows) == spec["sources"] and len({r["path"] for r in rows}) == len(rows)
    assert {"source/" + r["path"] for r in rows} == {p for p in items if p.startswith("source/")}
    overlay = {path: dict(e) for path, e in original["entries"].items()}
    proofs = []
    for row in rows:
        path = safe(row["path"])
        data = items["source/" + path]
        assert row["mode"] in ("100644", "100755")
        assert len(data) == row["bytes"] and sha(data) == row["sha256"] and blob(data) == row["git_blob"], path
        assert path not in overlay or overlay[path]["type"] == "blob", path
        overlay[path] = {"path": path, "type": "blob", "mode": row["mode"], "sha": blob(data)}
        for pp in PurePosixPath(path).parents:
            name = str(pp)
            if name == ".":
                break
            if name in overlay:
                assert overlay[name]["type"] == "tree", name
            else:
                overlay[name] = {"path": name, "type": "tree", "mode": "040000", "sha": "0" * 40}
        proofs.append({**row, "raw_bytes_verified": True, "git_blob_recomputed": blob(data)})
    lock = items["input/Cargo.lock"]
    assert sha(lock) == LOCK_SHA
    assert blob(lock) == original["entries"]["codex-rs/Cargo.lock"]["sha"]
    computed = rebuild(list(overlay.values()))
    assert computed["tree"] == spec["tree"], (run, computed["tree"])
    commit_path = ROOT / f"input/source{spec['stage']}-commit-original-response.json"
    commit = json.loads(commit_path.read_bytes())
    assert commit["sha"] == spec["commit"] and commit["tree"]["sha"] == computed["tree"]
    assert [p["sha"] for p in commit["parents"]] == [spec["parent"]]
    target_path = ROOT / f"input/source{spec['stage']}-direct-root-original-response.json"
    target = json.loads(target_path.read_bytes())
    assert target["truncated"] is False and target["sha"] == computed["tree"]
    target_children = [{"name": x["path"], "mode": x["mode"], "type": x["type"], "sha": x["sha"]} for x in target["tree"]]
    assert tree_hash(target_children) == computed["tree"]
    computed_children = [{"name": PurePosixPath(x["path"]).name, "mode": x["mode"], "type": x["type"],
                          "sha": computed["computed"][x["path"]] if x["type"] == "tree" else x["sha"]}
                         for x in computed["root_children"]]
    assert sorted(computed_children, key=lambda e: e["name"]) == sorted(target_children, key=lambda e: e["name"])
    changed = [{"path": p, "original_tree": original["computed"].get(p), "computed_tree": s}
               for p, s in sorted(computed["computed"].items()) if original["computed"].get(p) != s]
    source_pin = write_json(ROOT / run / "SOURCE-FILES.json", proofs)
    tree_pin = write_json(ROOT / run / "TREE-REBUILD.json", {
        "schema": "hepta.recovered-independent-overlay-tree.v1",
        "audit_is_new_after_scratch_loss": True,
        "original_framework_commit": BASE_COMMIT, "independently_rebuilt_original_tree": BASE_TREE,
        "base_entries": len(original["entries"]), "overlay_source_files": len(rows),
        "final_entries": len(overlay), "all_final_directories_rehashed": len(computed["computed"]),
        "computed_tree": computed["tree"], "expected_immutable_commit": spec["commit"],
        "expected_immutable_commit_parent": spec["parent"],
        "direct_root_response_independently_matched": True,
        "changed_directories": changed,
        "raw_git_response_inputs": [
            {"path": str(commit_path.relative_to(ROOT)), **pin(commit_path.read_bytes())},
            {"path": str(target_path.relative_to(ROOT)), **pin(target_path.read_bytes())},
        ],
        "root_result_or_target_proof_used_as_rebuild_input": False,
    })
    return {"source_manifest": {"path": "evidence/" + spec["source_manifest"], **pin(manifest_raw)},
            "source_count": len(rows), "computed_tree": computed["tree"], "source_commit": spec["commit"],
            "all_raw_sha_git_blob_declared_modes_matched": True,
            "archive_mode_vs_git_mode": "Archive transport mode is 0644; Git modes are separately bound to the source manifest and tree hash.",
            "raw_lock": {**pin(lock), "git_blob": blob(lock), "matches_original_framework": True},
            "source_readback": source_pin, "tree_readback": tree_pin}


def phase_read(run: str, items: dict[str, bytes]) -> dict:
    spec = SPECS[run]
    phase_results = []
    for phase in spec["phases"]:
        prefix = "evidence/" + spec["prefix"] + "-" + phase
        names = {"receipt": prefix + "-receipt.json", "raw": prefix + "-raw-process-result.json",
                 "log": prefix + ".log", "resources": prefix + "-resources.txt"}
        receipt = json.loads(items[names["receipt"]])
        raw = json.loads(items[names["raw"]])
        resource = items[names["resources"]].decode()
        command = ["just", "clippy" if phase == "strict" else "test", "--locked"]
        for package in spec["packages"] or []:
            command += ["-p", package]
        command += ["--", "-D", "warnings"] if phase == "strict" else ["--retries", "0"]
        expected_exit = spec["exit"] if phase == "tests" else 0
        for obj in (receipt, raw):
            assert obj["command"] == command and obj["exit_code"] == expected_exit
            assert obj["source_tree"] == spec["tree"] and obj["source_commit"] == spec["commit"]
            assert obj["cwd"] == "/home/alex/work/hepta-cell-unified-20261106-a/source/codex-rs"
        for field in ("start_unix", "end_unix"):
            assert receipt[field] == raw[field]
        assert receipt["end_unix"] > receipt["start_unix"]
        assert math.isclose(receipt["elapsed_seconds"], receipt["end_unix"] - receipt["start_unix"], abs_tol=0.000001)
        assert receipt["log_sha256"] == sha(items[names["log"]])
        assert receipt["resources_sha256"] == sha(items[names["resources"]])
        assert receipt["source_manifest"] == spec["source_manifest"]
        assert re.findall(r"(?m)^\s*Exit status: (\d+)\s*$", resource) == [str(expected_exit)]
        assert re.findall(r'^\s*Command being timed: "(.*)"\s*$', resource, re.M) == [" ".join(command)]
        assert receipt["retries"] == (0 if phase == "tests" else None)
        if run == "r21":
            guard_name = "evidence/native-workspace-r21-source-post-test-verification.json"
        else:
            guard_name = prefix + "-source-post-verification.json"
        guard = json.loads(items[guard_name])
        assert guard["pass"] is True and guard["expected_tree"] == guard["actual_tree"] == spec["tree"]
        assert guard["lock_sha256"] == LOCK_SHA and guard["changed_file_count"] == spec["sources"]
        assert guard["gate_exit_code"] == expected_exit
        for field in ("unstaged_paths", "untracked_paths", "file_mismatches"):
            assert guard[field] == []
        phase_results.append({"phase": phase, "command": command, "exit_code": expected_exit,
            "elapsed_seconds": receipt["elapsed_seconds"], "start_unix": receipt["start_unix"], "end_unix": receipt["end_unix"],
            "inputs": {k: {"path": name, **pin(items[name])} for k, name in names.items()},
            "post_guard": {"path": guard_name, **pin(items[guard_name]), "pass": True},
            "raw_rc_receipt_resource_exit_bound": True})
    terminal_name = "evidence/" + spec["prefix"] + "-terminal-process-status.json"
    terminal = json.loads(items[terminal_name])
    assert terminal["job_id"] == spec["outer_job"] and terminal["exit_code"] == spec["exit"]
    assert terminal["state"] == ("succeeded" if spec["exit"] == 0 else "failed")
    for key in ("automatic_retry", "cancelled", "timed_out"):
        assert terminal[key] is False
    for key in ("output_complete", "output_durable", "terminal_publication_confirmed"):
        assert terminal[key] is True
    assert terminal["at_unix_ms"] / 1000 >= phase_results[-1]["end_unix"]
    return {"phase_results": phase_results,
            "outer": {"path": terminal_name, **pin(items[terminal_name]), "job_id": terminal["job_id"],
                      "exit_code": terminal["exit_code"], "state": terminal["state"],
                      "natural_terminal_no_timeout_cancel_retry": True,
                      "complete_and_durable_terminal_publication": True}}


def workspace_read(items: dict[str, bytes]) -> dict:
    metadata_name = "evidence/native-workspace-r21-metadata.json"
    scope_name = "evidence/native-workspace-r21-scope.json"
    metadata = json.loads(items[metadata_name])
    scope = json.loads(items[scope_name])
    members, defaults = metadata["workspace_members"], metadata["workspace_default_members"]
    assert len(members) == len(defaults) == len(set(members)) == len(set(defaults)) == 193
    assert set(members) == set(defaults)
    assert scope["metadata_sha256"] == sha(items[metadata_name])
    assert scope["metadata_command"] == ["cargo", "metadata", "--locked", "--no-deps", "--format-version", "1"]
    package_names = {p["id"]: p["name"] for p in metadata["packages"]}
    for field, ids in (("workspace_members", members), ("workspace_default_members", defaults)):
        expected = [{"id": package_id, "name": package_names[package_id]} for package_id in ids]
        assert scope[field] == expected
    log_name = "evidence/native-workspace-r21-tests.log"
    log = items[log_name].decode()
    assert not re.search(r"(?m)^\s*Starting (?:\[|\d+ tests? across)", log)
    assert not re.search(r"(?m)^\s*(?:PASS|FAIL|TIMEOUT)\s+\[", log)
    errors = re.findall(r"(?m)^error\[E0063\]:.*$", log)
    assert len(errors) == 2 and all("trace" in e and "JSONRPCRequest" in e for e in errors)
    return {"metadata": {"path": metadata_name, **pin(items[metadata_name])},
            "scope": {"path": scope_name, **pin(items[scope_name])},
            "member_count": 193, "default_member_count": 193, "member_sets_equal": True,
            "test_execution_started": False, "test_counts": None,
            "raw_compile_errors": errors, "original_compile_exit": 101,
            "readback_boundary": "Exact error spans and all project test ID parsing are in the independent recovered-checkpoint log review by differentiation_study."}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--native-results", type=Path, required=True)
    args = parser.parse_args()
    original = load_original()
    results = {}
    for run in SPECS:
        items, archive = archive_read(run, args.native_results)
        source = source_read(run, items, original)
        phases = phase_read(run, items)
        result = {"schema": "hepta.recovery-independent-readback.v1",
            "audit_is_new_after_scratch_loss": True,
            "run": run, "archive_and_source_verification": "VERIFIED",
            "archive": archive, "source": source,
            "original_framework_validation": original["report_pin"],
            "original_phases_and_terminal": phases,
            "executed_any_native_commands": False, "executed_rust_or_tests": False,
            "read_active_logs": False, "modified_source": False,
            "old_lost_audit_bytes_reconstructed": False,
            "scientific_or_authority_disposition_changed": False,
            "full_test_id_semantic_readback": "Separately owned by differentiation_study in the new recovered-checkpoint group; this report binds the complete raw logs and original phase results to independently rebuilt source trees."}
        if run == "r21":
            result["workspace"] = workspace_read(items)
        result_pin = write_json(ROOT / run / "INDEPENDENT-READBACK.json", result)
        results[run] = {"report": result_pin, "source_tree": source["computed_tree"],
                       "source_files": source["source_count"], "outer_exit": phases["outer"]["exit_code"]}
    write_json(ROOT / "RECOVERY-SUMMARY.json", {
        "schema": "hepta.recovery-independent-summary.v1", "audit_is_new_after_scratch_loss": True,
        "results": results, "original_framework_input_entries": 12259,
        "original_framework_directories_independently_rehashed": 1367,
        "root_target_proof_used_as_rebuild_input": False,
        "no_builds_tests_or_source_mutations": True,
        "r23_not_read_or_qualified_by_this_audit": True,
    })
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
