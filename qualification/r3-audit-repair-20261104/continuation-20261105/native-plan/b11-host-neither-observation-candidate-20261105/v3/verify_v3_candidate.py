#!/usr/bin/env python3
"""Cloud-only byte/provenance checks; never compile or run product code."""

import collections
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parent
REPO_PATH = "codex-rs/windows-sandbox-rs/src/token_neither_privilege_observation.rs"
BEFORE = "b40b49ce772c402c51ddb16bb98ff73dc78cdb41"
AFTER = "8c16416c185f17871c25139bc16c6fd112b5fd41"
PUBLISHED_TREE = "9cb7302777ce018dd022086041c2225d1dd5c8dd"


def git_hash(kind, body):
    return hashlib.sha1(kind.encode() + b" " + str(len(body)).encode() + b"\0" + body).hexdigest()


def identity(path):
    body = path.read_bytes()
    return {
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "git_blob": git_hash("blob", body),
    }


def rebuild_tree(leaves):
    children = collections.defaultdict(dict)
    for path, entry in leaves.items():
        parts = path.split("/")
        for index in range(len(parts) - 1):
            children["/".join(parts[:index])][parts[index]] = ("40000", None)
        children["/".join(parts[:-1])][parts[-1]] = (entry["mode"].lstrip("0"), entry["sha"])
    hashes = {}

    def visit(directory):
        encoded = []
        for name, (mode, sha) in children[directory].items():
            if mode == "40000":
                sha = visit(f"{directory}/{name}".lstrip("/"))
            key = name.encode() + (b"/" if mode == "40000" else b"")
            encoded.append((key, mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(sha)))
        body = b"".join(item for _, item in sorted(encoded))
        hashes[directory] = git_hash("tree", body)
        return hashes[directory]

    return visit(""), hashes


def main():
    before_path = ROOT / "source" / REPO_PATH
    after_path = ROOT / "candidate" / REPO_PATH
    before = before_path.read_text()
    after = after_path.read_text()
    assert identity(before_path)["git_blob"] == BEFORE
    assert identity(after_path)["git_blob"] == AFTER
    assert [p.relative_to(ROOT / "candidate").as_posix() for p in (ROOT / "candidate").rglob("*") if p.is_file()] == [REPO_PATH]
    source_map = json.loads((ROOT / "source-map.json").read_text())
    tree = json.loads((ROOT / "evidence/published-intended-full-tree.json").read_text())
    assert not tree["truncated"] and tree["sha"] == PUBLISHED_TREE
    leaves = {row["path"]: row for row in tree["tree"] if row["type"] != "tree"}
    assert len(leaves) == 10589 and leaves[REPO_PATH]["sha"] == BEFORE
    rebuilt, directories = rebuild_tree(leaves)
    assert rebuilt == PUBLISHED_TREE
    for row in tree["tree"]:
        if row["type"] == "tree":
            assert directories[row["path"]] == row["sha"]
    for row in source_map["original_sources"]:
        local = ROOT / "source" / row["repository_path"]
        actual = identity(local)
        assert all(actual[k] == row[k] for k in actual)
        assert actual["git_blob"] == leaves[row["repository_path"]]["sha"]
    assert len(source_map["original_sources"]) == 14
    assert source_map["changes"] == [{"path": REPO_PATH, "before": identity(before_path), "after": identity(after_path)}]
    assert not source_map["native_execution_performed"] and not source_map["compilation_performed"]
    assert not source_map["formatting_tool_performed"] and not source_map["ref_mutation_performed"]

    # The full orchestration, all three Rust paths, both cmd subjects and final
    # physical oracles are an exact unchanged suffix, not rewritten assertions.
    run_marker = "pub(super) fn run() -> Result<()> {"
    assert before.split(run_marker, 1)[1] == after.split(run_marker, 1)[1]
    token_marker = "// A bounded, aligned native result."
    owned_marker = "struct OwnedChild {"
    assert before.split(token_marker, 1)[1].split(owned_marker, 1)[0] == after.split(token_marker, 1)[1].split(owned_marker, 1)[0]
    old_cmd = before.split("fn cmd_observation(", 1)[1].split(run_marker, 1)[0]
    new_cmd = after.split("fn cmd_observation(", 1)[1].split(run_marker, 1)[0]
    old_start = old_cmd.index("    // The existing backend assigns its real Job")
    old_end = old_cmd.index("    drop(input);", old_start)
    new_start = new_cmd.index("    // Both subjects use this identical test-only path.")
    new_end = new_cmd.index("    drop(input);", new_start)
    restored_cmd = new_cmd[:new_start] + old_cmd[old_start:old_end] + new_cmd[new_end:]
    restored_cmd = restored_cmd.replace("child.job", "child.created.job")
    assert restored_cmd == old_cmd
    assert before.count("/*dwmilliseconds*/ 5_000") == after.count("/*dwmilliseconds*/ 5_000") == 3
    assert "#[test]" not in after and "#[ignore" not in after
    probe = ROOT / "source/codex-rs/windows-sandbox-rs/src/token_integrity_probe_tests.rs"
    assert identity(probe)["git_blob"] == "fc9faa6d47ac5fdefa216affceb51a586f8e6b81"
    production = {row["repository_path"]: row["git_blob"] for row in source_map["original_sources"] if row["repository_path"] != REPO_PATH}
    assert "sandbox token has no restricting SIDs" in (ROOT / "source/codex-rs/windows-sandbox-rs/src/desktop.rs").read_text()
    assert "#[cfg(test)]\n#[path = \"token_integrity_probe_tests.rs\"]\nmod integrity_probe;" in (ROOT / "source/codex-rs/windows-sandbox-rs/src/token.rs").read_text()

    # Validate the complete submitted patch in an unrelated empty local git
    # directory. No repository ref, product code or native tool is executed.
    patch = (ROOT / "v2-to-v3.patch").read_bytes()
    assert patch == (ROOT / "full.patch").read_bytes()
    assert patch.count(b"--- a/") == 1 and patch.count(b"\n@@ ") == 5
    commands = []
    with tempfile.TemporaryDirectory(prefix="b11-v3-byte-check-") as temp:
        directory = Path(temp)
        local = directory / REPO_PATH
        local.parent.mkdir(parents=True)
        local.write_bytes(before_path.read_bytes())
        for args in [["git", "init", "-q"], ["git", "apply", "--check", str(ROOT / "full.patch")], ["git", "apply", str(ROOT / "full.patch")], ["git", "apply", "--reverse", "--check", str(ROOT / "full.patch")], ["git", "apply", "--reverse", str(ROOT / "full.patch")]]:
            result = subprocess.run(args, cwd=directory, capture_output=True, text=True, check=False)
            commands.append({"argv": args, "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
            assert result.returncode == 0
            if args == ["git", "apply", str(ROOT / "full.patch")]:
                assert local.read_bytes() == after_path.read_bytes()
        assert local.read_bytes() == before_path.read_bytes()

    # These checks prove symbol availability only; they do not type-check Rust.
    primary = {}
    for namespace, filename in [("security", "Security"), ("threading", "System-Threading"), ("jobs", "System-JobObjects"), ("fswin", "Storage-FileSystem")]:
        source = (ROOT / f"primary/windows-sys-0.52.0-{filename}.rs.source.txt").read_text()
        names = sorted(set(re.findall(r"\b" + namespace + r"::([A-Za-z_][A-Za-z0-9_]*)", after)))
        assert all(re.search(r"\b" + re.escape(name) + r"\b", source) for name in names)
        primary[namespace] = names

    # Preserve the initial failing run as an original, with no invented needed
    # length and no conversion of three Rust observations into five matrices.
    log_path = ROOT / "evidence/native11-full-job.original.log"
    assert identity(log_path)["sha256"] == "29c7b0343a5f8865bd2bf8088e3108e2c3db3b3f89f93c0aaa72b89834d685bc"
    lines = log_path.read_text().splitlines()
    records = collections.defaultdict(list)
    for index, line in enumerate(lines, 1):
        marker = "PROBE_OBSERVATION_ONLY neither_privileges "
        if marker in line:
            kind, _, body = line.split(marker, 1)[1].partition(" ")
            records[kind].append((index, json.loads(body)))
    assert {k: len(v) for k, v in records.items()} == {"filesystem": 1, "subjects": 1, "rust_before": 3, "rust_physical": 3}
    subjects = records["subjects"][0][1]
    assert subjects["ordinary"]["identity"] == subjects["disable_max_privilege"]["identity"]
    assert subjects["ordinary"]["identity"]["restricted_sids"] == []
    assert records["filesystem"][0][1]["filesystem"] == "NTFS"
    errors = [{"line": i, "text": line} for i, line in enumerate(lines, 1) if "GetTokenInformation(TokenRestrictedSids) size query failed: 122" in line]
    assert len(errors) == 2
    summaries = [{"line": i, "text": line} for i, line in enumerate(lines, 1) if "test result:" in line]
    assert len(summaries) == 3
    assert "92 passed; 0 failed; 0 ignored" in summaries[0]["text"]
    assert all("54 passed; 8 failed; 2 ignored" in row["text"] for row in summaries[1:])

    updated = dict(leaves)
    updated[REPO_PATH] = dict(updated[REPO_PATH], sha=AFTER)
    new_tree, new_directories = rebuild_tree(updated)
    changed = sorted(path for path in set(leaves) | set(updated) if leaves.get(path) != updated.get(path))
    assert changed == [REPO_PATH] and len(new_directories) == len(directories)
    result = {
        "decision": "STATIC_BYTE_REVIEW_ONLY_NO_NATIVE_QUALIFICATION",
        "before": identity(before_path),
        "after": identity(after_path),
        "source_map": identity(ROOT / "source-map.json"),
        "patch": identity(ROOT / "full.patch"),
        "published_tree": rebuilt,
        "expected_candidate_tree": new_tree,
        "directory_nodes_including_root": len(directories),
        "unchanged_leaf_count": len(leaves) - 1,
        "changed_paths": changed,
        "source_dependencies_verified_against_actual_tree": len(source_map["original_sources"]),
        "unchanged_production_and_probe_sources": production,
        "same_full_run_function_bytes": True,
        "same_full_token_record_and_effective_token_bytes": True,
        "same_cmd_gate_work_cleanup_oracle_bytes_except_launcher_and_job_field": True,
        "original_probe_and_eight_rows_byte_unchanged": True,
        "new_test_or_ignore_attributes": 0,
        "prior_roster_static_preservation_expectation": {"whole": 156, "exact_filter": 155},
        "all_three_existing_wait_values_ms": [5000, 5000, 5000],
        "patch_roundtrip": commands,
        "primary_binding_name_availability_only": primary,
        "initial_failure_original": identity(log_path),
        "initial_failure_errors": errors,
        "initial_failure_summary_lines": summaries,
        "initial_failure_whole_result": {"passed": 146, "failed": 8, "ignored": 2, "reprinted_failure_subset_counted_once": True},
        "initial_failure_observation_record_counts": {k: len(v) for k, v in records.items()},
        "initial_failure_cmd_children_observed": 0,
        "initial_failure_needed_buffer_bytes": None,
        "native_execution_performed": False,
        "compilation_performed": False,
        "formatting_tool_performed": False,
        "ref_mutation_performed": False,
        "B11": "OPEN",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
