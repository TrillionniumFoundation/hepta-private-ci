#!/usr/bin/env python3
"""Offline provenance and exact-delta proof, not a Rust or native test result."""
import argparse
import difflib
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import xml.etree.ElementTree as ET

from static_helpers import identity, merkle


BASE = "3982ba56dc5a3f1da0c1de7ea57992f88125c359"
SOURCE = "67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed"
FILE = "codex-rs/hepta-intelligence-eval/src/fenced_holdout_file.rs"
TESTS = "codex-rs/hepta-intelligence-eval/src/fenced_holdout_file_tests.rs"
OWNER = "codex-rs/hepta-intelligence-eval/src/fenced_holdout.rs"
NEW_TESTS = [
    "dropping_store_unlocks_while_a_duplicate_file_remains_open",
    "failed_create_unlocks_while_a_duplicate_file_remains_open",
    "failed_recover_unlocks_while_a_duplicate_file_remains_open",
]
GUARD = """struct FileLock(File);

impl Drop for FileLock {
    fn drop(&mut self) {
        // Closing this file alone may leave its lock held by a duplicated or
        // inherited descriptor. Release it when the owning store leaves scope.
        let _ = self.0.unlock();
    }
}

"""


def read_json(path):
    return json.loads(path.read_bytes())


def response_body(value):
    structured = value.get("structuredContent")
    if structured is None:
        structured = json.loads(next(x["text"] for x in value["content"] if x["type"] == "text"))
    assert not value.get("isError")
    return structured["content"]


def check_source_archive(path, search):
    observed = []
    scanned = 0
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            if not member.isfile() or not member.name.startswith("source/") or not member.name.endswith(".rs"):
                continue
            scanned += 1
            text = archive.extractfile(member).read().decode("utf-8")
            for number, line in enumerate(text.splitlines(), 1):
                hits = [needle for needle in search["needles"] if needle in line]
                if hits:
                    observed.append({"path": member.name[7:], "line": number, "needles": hits, "text": line})
    assert scanned == search["scanned_rust_files"] == 4832
    assert observed == search["match_lines"]


def main(root, source_archive):
    authority = read_json(root / "authority/main67-full-tree.json")
    assert authority["sha"] == BASE and not authority["truncated"]
    leaves = {x["path"]: x for x in authority["tree"] if x["type"] != "tree"}
    assert len(leaves) == 10582
    actual_root, nodes = merkle(leaves)
    assert actual_root == BASE
    for entry in authority["tree"]:
        if entry["type"] == "tree":
            assert nodes[entry["path"]] == entry["sha"]
    sources = read_json(root / "authority/source-manifest.json")["files"]
    for entry in sources:
        data = (root / "source" / entry["path"]).read_bytes()
        assert identity(data) == {k: entry[k] for k in ["bytes", "git_blob", "sha256"]}
        assert leaves[entry["path"]]["sha"] == entry["git_blob"]
    primary = read_json(root / "authority/primary-manifest.json")
    primary_gets = 0
    for entry in primary:
        path = root / entry["path"]
        assert identity(path.read_bytes()) == {k: entry[k] for k in ["bytes", "git_blob", "sha256"]}
        original = Path(str(path) + ".GET.original.json")
        if original.is_file():
            assert response_body(read_json(original)).encode("utf-8") == path.read_bytes()
            primary_gets += 1

    source_gets = read_json(root / "authority/source-and-candidate.actual.json")
    for entry in source_gets:
        data = (root / entry["kind"] / entry["path"]).read_bytes()
        assert identity(data) == {k: entry[k] for k in ["bytes", "git_blob", "sha256"]}
        raw = read_json(root / f"authority/full-GET-{entry['git_blob']}.original.json")
        assert response_body(raw).encode("utf-8") == data

    old = (root / "source" / FILE).read_text()
    new = (root / "candidate" / FILE).read_text()
    assert new.count(GUARD) == 1
    reverted = new.replace(GUARD, "", 1)
    reverted = reverted.replace("    file: FileLock,", "    file: File,", 1)
    reverted = reverted.replace("pub fn create(file: File, binding: Digest32)", "pub fn create(mut file: File, binding: Digest32)", 1)
    reverted = reverted.replace("        file: File,\n", "        mut file: File,\n", 1)
    assert reverted.count("        let mut file = acquire(file, binding)?;") == 2
    reverted = reverted.replace("        let mut file = acquire(file, binding)?;", "        acquire(&file, binding)?;")
    reverted = reverted.replace("            .file\n            .0\n", "            .file\n")
    reverted = reverted.replace("file.0", "file")
    reverted = reverted.replace("fn acquire(file: File, binding: Digest32) -> Result<FileLock, LockedFileCasErrorV1> {", "fn acquire(file: &File, binding: Digest32) -> Result<(), LockedFileCasErrorV1> {", 1)
    reverted = reverted.replace("    })?;\n    Ok(FileLock(file))\n}", "    })\n}", 1)
    assert reverted == old, "only the private lock ownership projection may differ"
    assert "try_clone" not in new and "unsafe" not in new
    assert "impl Drop for LockedFileFinalHoldoutCasStoreV1" not in new
    owner = (root / "source" / OWNER).read_text()
    assert "pub fn into_store(self) -> S {\n        self.store\n    }" in owner
    assert "impl<S" in owner and "impl Drop" not in owner
    old_tests = (root / "source" / TESTS).read_bytes()
    new_tests = (root / "candidate" / TESTS).read_bytes()
    assert new_tests.startswith(old_tests)
    addition = new_tests[len(old_tests):].decode("utf-8")
    assert re.findall(r"#\[test\]\nfn (\w+)", addition) == NEW_TESTS
    assert "sleep" not in addition and "Command" not in addition
    assert len(re.findall(r"#\[test\]", old_tests.decode())) == 3

    expected_patch = ""
    changed = []
    candidate = {path: dict(entry) for path, entry in leaves.items()}
    assert sorted(str(p.relative_to(root / "candidate")) for p in (root / "candidate").rglob("*") if p.is_file()) == sorted([FILE, TESTS])
    for path in [FILE, TESTS]:
        before = (root / "source" / path).read_bytes()
        after = (root / "candidate" / path).read_bytes()
        expected_patch += "".join(difflib.unified_diff(before.decode().splitlines(keepends=True), after.decode().splitlines(keepends=True), fromfile="a/" + path, tofile="b/" + path))
        changed.append({"path": path, "preimage": identity(before), "postimage": identity(after)})
        candidate[path]["sha"] = identity(after)["git_blob"]
    assert (root / "full.patch").read_text() == expected_patch
    with tempfile.TemporaryDirectory(prefix="holdout-lock-patch-proof-") as temporary:
        temporary = Path(temporary)
        for path in [FILE, TESTS]:
            target = temporary / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((root / "source" / path).read_bytes())
        for flags, expected in [([], "candidate"), (["--reverse"], "source")]:
            result = subprocess.run(["git", "apply", *flags, str(root / "full.patch")], cwd=temporary, capture_output=True, check=False)
            assert result.returncode == 0 and not result.stderr, result.stderr
            for path in [FILE, TESTS]:
                assert (temporary / path).read_bytes() == (root / expected / path).read_bytes()
    candidate_root, _ = merkle(candidate)
    created = read_json(root / "authority/candidate-full-tree.create.original.json")
    assert not created.get("isError") and created["structuredContent"]["sha"] == candidate_root
    actual_tree = json.loads(response_body(read_json(root / "authority/candidate-full-tree.GET.original.json")))
    assert actual_tree["sha"] == candidate_root and not actual_tree["truncated"]
    root_children = {}
    for entry in actual_tree["tree"]:
        assert "/" not in entry["path"]
        root_children[entry["path"]] = {
            "mode": "40000" if entry["type"] == "tree" else entry["mode"],
            "sha": entry["sha"],
        }
    import hashlib
    ordered = sorted(actual_tree["tree"], key=lambda x: (x["path"] + ("/" if x["type"] == "tree" else "")).encode())
    raw_tree = b"".join(root_children[e["path"]]["mode"].encode() + b" " + e["path"].encode() + b"\0" + bytes.fromhex(e["sha"]) for e in ordered)
    assert hashlib.sha1(b"tree " + str(len(raw_tree)).encode() + b"\0" + raw_tree).hexdigest() == candidate_root
    assert all(candidate[p] == leaves[p] for p in leaves if p not in [FILE, TESTS])

    search = read_json(root / "authority/callsite-search.json")
    for hit in search["match_lines"]:
        lines = (root / "source" / hit["path"]).read_text().splitlines()
        assert lines[hit["line"] - 1] == hit["text"]
    if source_archive is not None:
        check_source_archive(source_archive, search)

    evidence = root / "evidence/original"
    manifest_root = evidence / "artifacts/artifact-13474454125/failed-test-logs/invocation-fw7e1rzb"
    manifest = read_json(manifest_root / "manifest.json")
    assert manifest["source"] == {"commit": "b7a57dbb61b00e51c05da9cf5c4bc95b365d85ae", "tree": BASE, "tracked_worktree_dirty": False}
    for entry in manifest["files"]:
        if not entry["archive_relative_path"].startswith("targets/0000/"):
            continue
        data = (manifest_root / entry["archive_relative_path"]).read_bytes()
        assert len(data) == entry["bytes"] and identity(data)["sha256"] == entry["sha256"]
    test_log = (manifest_root / "targets/0000/test.log").read_text()
    assert "left: Some(Busy)" in test_log and "right: Some(Rollback)" in test_log
    assert "114 passed; 1 failed; 0 ignored" in test_log
    xml = (manifest_root / "targets/0000/test.xml").read_bytes()
    ET.fromstring(xml)
    actions = read_json(root / "evidence/holdout-compact-actions.selected.json")
    assert len(actions) == 2
    test_action, xml_action = actions
    assert test_action["exit_code"] == 101 and test_action["runner"] == "darwin-sandbox" and test_action["cache_hit"] is False
    assert test_action["timeout_millis"] == 300000
    assert xml_action["exit_code"] == 0 and xml_action["cache_hit"] is False
    assert xml_action["outputs"][0]["digest"]["hash"] == identity(xml)["sha256"]
    job = evidence / "original/job-127679861749.decoded.original.log"
    assert identity(job.read_bytes())["sha256"] == "b5f1fd02ed8a83328f500126cced6f23c196f3f69d48b0df5749ab039ddca884"

    mechanism = read_json(root / "mechanism/probe.stdout.json")
    execution = read_json(root / "mechanism/execution.json")
    assert execution["exit_code"] == 0 and execution["stderr_bytes"] == 0
    assert identity((root / "mechanism/probe.stdout.json").read_bytes())["sha256"] == execution["stdout_sha256"]
    assert mechanism["case_count"] == 4
    assert mechanism["original_mac_failure_cause_proven"] is False
    assert [x.get("while_duplicate_open", x.get("while_child_before_exec")) for x in mechanism["cases"]] == ["WouldBlock", "Acquired", "WouldBlock", "Acquired"]
    return {
        "decision": "STATIC_CANDIDATE_READY_FOR_INDEPENDENT_REVIEW",
        "source": {"head": SOURCE, "tree": BASE, "leaves": len(leaves), "source_files_verified": len(sources)},
        "candidate": {"computed_tree": candidate_root, "changed_paths": changed, "unchanged_leaves": 10580, "actual_postimage_full_GETs": 2, "full_tree_actual_create_and_root_GET": True},
        "primary_full_GETs": primary_gets,
        "source_full_GETs": 3,
        "original_three_file_tests_byte_preserved": True,
        "added_regressions_not_executed": NEW_TESTS,
        "all_original_storage_logic_reconstructed_byte_exactly_after_removing_ownership_delta": True,
        "public_owner_and_into_store_unchanged": True,
        "all_rust_call_search": {"scanned": search["scanned_rust_files"], "matched_lines": len(search["match_lines"]), "matched_paths": len(set(x["path"] for x in search["match_lines"]))},
        "original_mac_failure": {"job": 127679861749, "artifact": 13474454125, "passed": 114, "failed": 1, "actual": "Busy", "expected": "Rollback", "runner": "darwin-sandbox", "cached": False, "test_exit": 101, "original_timeout_ms": 300000},
        "local_os_mechanism": {"cases": 4, "platform": mechanism["platform"], "scope": mechanism["scope"]},
        "original_mac_cause_proven": False,
        "project_compile_tests_and_fmt_executed": False,
        "native_or_ref_mutation": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--source-archive", type=Path)
    args = parser.parse_args()
    print(json.dumps(main(args.root.resolve(), args.source_archive), indent=2, sort_keys=True))
