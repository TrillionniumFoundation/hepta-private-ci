#!/usr/bin/env python3
"""Create one source51 evidence attachment, or read it back without execution.

This program only reads local files, hashes bytes, parses Python syntax/Git
trees, and writes the NEW attachment. It never imports a retained runner,
starts a subprocess, contacts a host, or executes Rust/formatters/Git commands.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile


GROUP_REL = "hepta-cell/qualification/cell-unification-20261106/native-evidence/source51-repair-apply-checkpoint"
COMMIT = "e28b0f385ee882f842911044958b2810f62f6379"
TREE = "763c8d2b4089f6e9806c3bbb68fa247bc2f6af36"
BASE_COMMIT = "1fdd647b0ecb235530e8b88bbea45b3d3762906f"
BASE_TREE = "ea48acf562499192a25e05ae28926a32632dee62"
NATIVE_HEAD = "bef6fa7645df9df12b69fda499e97eed25de6c75"
CARGO_LOCK = "4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c"
BAZEL_LOCK = "e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb"
R26_FINAL_SHA = "c46f22be2c4b71004dc086870eaf5a69efed0ee32cde47cf33a2ef818f168396"
APPLY_JOB = "1a1b1ae7f60-fc05-7a41"
R26_JOB = "1a1b1b739ee-fc05-7a70"
T = "/home/alex/work/hepta-cell-unified-20261106-a"
S = T + "/source"
CHANGED = [
    "codex-rs/exec-server/tests/common/fake_bwrap.rs",
    "codex-rs/network-proxy/src/http_proxy.rs",
]

# Explicit closed/preparation input roots. In particular no active r26 phase
# logs, r27 inputs, final-scope files, or top-level mutable reports are read.
INPUT_ROOTS = [
    ("native-validation-results/source51-bwrap-comparison-closed", "native-comparison", "closed diagnostic, not a Rust gate"),
    ("native-validation-results/source51-apply-closed", "native-apply", "closed source application only"),
    ("source51-preparation", "registration", "historical preparation plus actual registration and root authorizations"),
    ("exec-server-bwrap-r24-repair", "candidates/exec-helper", "frozen candidate, retained failure and diagnostic provenance"),
    ("source51-network-candidate", "candidates/network", "frozen fixture candidate"),
    ("source51-network-independent-review", "reviews/network", "independent static review"),
    ("source51-apply-preparation", "apply-preparation", "inert historical template and input contract"),
    ("source51-apply-input-independent-review", "reviews/apply-input", "independent static binding review"),
    ("source51-apply-native-independent-review", "reviews/apply-native", "independent static template review"),
    ("source51-native-gates-preparation", "r26-preparation", "inert historical r26 templates"),
    ("native-validation-results/r26-source51-bound-input", "r26-bound", "frozen bound/final runner input, not a result"),
    ("source51-r26-template-independent-review", "reviews/r26-template", "independent static template/binding review"),
    ("r26-bound-independent-review", "reviews/r26-bound", "independent static actual binding review"),
    ("native-validation-results/r26-start-launch", "r26-launch", "immutable initial launch observation only"),
]
EXTRA_FILES = [
    ("r26_bound_independent_review.py", "reviews/r26-bound/verify_actual_bindings.py", "exact independent static audit script, retained only"),
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def pin(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
    }


def check_pin(raw, expected, label):
    actual = pin(raw)
    for key in ("bytes", "sha256", "git_blob"):
        if key in expected:
            require(actual[key] == expected[key], f"{label}: {key} differs")
    return actual


def jbytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def safe_rel(name):
    p = PurePosixPath(name)
    require(not p.is_absolute() and ".." not in p.parts and str(p) == name, f"unsafe relative path: {name}")
    return name


def tree_sha(entries):
    require(len({e["path"] for e in entries}) == len(entries), "duplicate direct tree child")
    ordered = sorted(entries, key=lambda e: (e["path"] + ("/" if e["type"] == "tree" else "")).encode())
    body = b"".join(
        e["mode"].lstrip("0").encode() + b" " + e["path"].encode() + b"\0" + bytes.fromhex(e["sha"])
        for e in ordered
    )
    return hashlib.sha1(b"tree " + str(len(body)).encode() + b"\0" + body).hexdigest()


def patch_sections(raw):
    lines = raw.decode().splitlines(keepends=True)
    sections = []
    i = 0
    while i < len(lines):
        if lines[i].startswith("--- a/"):
            path = lines[i][6:].rstrip("\n")
            require(i + 1 < len(lines) and lines[i + 1] == "+++ b/" + path + "\n", "patch path mismatch")
            i += 2
            hunks = []
            while i < len(lines) and not lines[i].startswith(("diff --git ", "--- a/")):
                m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", lines[i])
                require(m is not None, "unexpected patch hunk line")
                old_start, old_count, new_start, new_count = (
                    int(m[1]), int(m[2] or "1"), int(m[3]), int(m[4] or "1")
                )
                i += 1
                old, new = [], []
                while i < len(lines) and not lines[i].startswith(("@@ ", "diff --git ", "--- a/")):
                    line = lines[i]
                    require(line and line[0] in " +-", "unsupported patch line/no-newline marker")
                    if line[0] in " -":
                        old.append(line[1:])
                    if line[0] in " +":
                        new.append(line[1:])
                    i += 1
                require(len(old) == old_count and len(new) == new_count, "patch hunk count differs")
                hunks.append((old_start, new_start, old, new))
            sections.append((path, hunks))
        else:
            require(lines[i].startswith(("diff --git ", "index ")), "unexpected patch header")
            i += 1
    return sections


def apply_hunks(raw, hunks, reverse=False):
    lines = raw.decode().splitlines(keepends=True)
    out, position = [], 0
    for old_start, new_start, old, new in hunks:
        start, expected, replacement = (new_start, new, old) if reverse else (old_start, old, new)
        start = max(start - 1, 0)
        require(start >= position, "overlapping patch hunks")
        require(lines[start:start + len(expected)] == expected, "patch old context differs")
        out.extend(lines[position:start])
        out.extend(replacement)
        position = start + len(expected)
    out.extend(lines[position:])
    return "".join(out).encode()


def assignment_spans(raw):
    text = raw.decode()
    lines = text.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    result = {}
    for node in ast.parse(text).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            result[node.targets[0].id] = (starts[node.lineno - 1], starts[node.end_lineno], ast.literal_eval(node.value) if isinstance(node.value, (ast.Constant, ast.List, ast.Tuple, ast.Dict)) else None)
    return text, result


def validate(get):
    """Recompute from supplied raw originals; get can resolve the sealed group."""
    def read_json(path):
        return json.loads(get(path))

    preparation = "source51-preparation/"
    manifest_path = preparation + "native-candidate-r26-source.json"
    manifest_raw = get(manifest_path)
    check_pin(manifest_raw, {"bytes": 55418, "sha256": "74b7a35a77019ec90e42ec33dc0e81bbdbaca585541a028d57fffbe77c69a41a"}, manifest_path)
    source = json.loads(manifest_raw)
    base = read_json(preparation + "input/source50-actual-manifest.json")
    require((source["source_commit"], source["source_tree"]) == (COMMIT, TREE), "actual source identity differs")
    require((base["source_commit"], base["source_tree"]) == (BASE_COMMIT, BASE_TREE), "parent identity differs")
    for document in (base, source):
        require(document["cargo_lock_sha256"] == CARGO_LOCK and document["bazel_lock_sha256"] == BAZEL_LOCK, "lock pin differs")
    before_rows = {row["path"]: row for row in base["changed_files"]}
    after_rows = {row["path"]: row for row in source["changed_files"]}
    require(len(before_rows) == len(after_rows) == 194, "manifest row count differs")
    require(before_rows.keys() == after_rows.keys(), "manifest path sets differ")
    changed = sorted(k for k in before_rows if before_rows[k] != after_rows[k])
    require(changed == CHANGED, "manifest change set differs")
    require(sum(k.endswith(".rs") for k in after_rows) == 180, "Rust count differs")
    for row in after_rows.values():
        require(row["mode"] in ("100644", "100755"), "unexpected source mode")
    raw_pairs = {}
    for path in CHANGED:
        before = get(preparation + "original/" + path)
        after = get(preparation + "source/" + path)
        check_pin(before, before_rows[path], "before " + path)
        check_pin(after, after_rows[path], "after " + path)
        raw_pairs[path] = (before, after)
    combined = get(preparation + "combined.patch")
    sections = patch_sections(combined)
    require([p for p, _ in sections] == CHANGED, "combined patch paths differ")
    for path, hunks in sections:
        before, after = raw_pairs[path]
        require(apply_hunks(before, hunks) == after, "forward patch mismatch")
        require(apply_hunks(after, hunks, reverse=True) == before, "inverse patch mismatch")
    candidate_roots = [("exec-server-bwrap-r24-repair", "repair.patch", CHANGED[0]), ("source51-network-candidate", "network-fixture.patch", CHANGED[1])]
    for root, patch, path in candidate_roots:
        require(get(root + "/original/" + path) == raw_pairs[path][0], "candidate before differs")
        require(get(root + "/source/" + path) == raw_pairs[path][1], "candidate after differs")
        one = patch_sections(get(root + "/" + patch))
        require(len(one) == 1 and one[0][0] == path, "candidate patch path differs")
        require(apply_hunks(raw_pairs[path][0], one[0][1]) == raw_pairs[path][1], "candidate patch differs")
    api = read_json(preparation + "CREATED-COMMIT-API-ORIGINAL.json")
    require(api["sha"] == COMMIT and api["tree"]["sha"] == TREE and [x["sha"] for x in api["parents"]] == [BASE_COMMIT], "GitData registration differs")
    check_pin(get(preparation + "CREATED-COMMIT-API-ORIGINAL.json"), source["source_identity_bound_from_actual_git_api"], "commit API binding")

    # Independent seven-direct-tree reconstruction from immutable source50.
    queries = read_json(preparation + "input/GIT-TREE-QUERIES.json")["queries"]
    require(len(queries) == 7, "direct tree count differs")
    original_trees = {}
    for q in queries:
        data = get(preparation + q["file"])
        check_pin(data, q, q["file"])
        obj = json.loads(data)
        require(obj["truncated"] is False, "truncated Git tree")
        require(tree_sha(obj["tree"]) == obj["sha"] == q["git_tree"], "base direct Git tree hash differs")
        original_trees[q["directory"]] = (q["key"], obj)
    require(original_trees[""][1]["sha"] == BASE_TREE, "base root differs")
    derived = {}
    for directory in sorted(original_trees, key=lambda value: (value.count("/"), len(value)), reverse=True):
        key, obj = original_trees[directory]
        entries = []
        for entry in obj["tree"]:
            e = {k: entry[k] for k in ("path", "mode", "type", "sha")}
            full = "/".join(x for x in (directory, entry["path"]) if x)
            if full in original_trees:
                require(entry["sha"] == original_trees[full][1]["sha"], "base parent child link differs")
                e["sha"] = derived[full]
            elif full in raw_pairs:
                require(entry["sha"] == pin(raw_pairs[full][0])["git_blob"], "base leaf differs")
                e["sha"] = pin(raw_pairs[full][1])["git_blob"]
            entries.append(e)
        actual = tree_sha(entries)
        saved = read_json(preparation + "derived-trees/" + key + ".json")
        require(saved["entries"] == entries and saved["expected_git_tree"] == actual, "derived tree payload differs")
        derived[directory] = actual
    require(derived[""] == TREE, "offline reconstructed source51 tree differs")

    freeze = read_json(preparation + "ROOT-APPLY-INPUT-FREEZE.json")
    archive_path = preparation + "source51-apply-input.tar.gz"
    archive_raw = get(archive_path)
    check_pin(archive_raw, freeze["input_archive"], "original apply archive")
    expected_archive = {
        "candidate.patch": combined,
        "delta-manifest.json": get(preparation + "source51-delta-manifest.json"),
        "source51-manifest.json": manifest_raw,
    }
    for path, (before, after) in raw_pairs.items():
        expected_archive["before/" + path] = before
        expected_archive["after/" + path] = after
    archive_members = []
    with tarfile.open(fileobj=io.BytesIO(archive_raw), mode="r:gz") as archive:
        members = archive.getmembers()
        require(len(members) == len({m.name for m in members}) == 7, "apply archive count differs")
        require({m.name for m in members} == expected_archive.keys(), "apply archive member set differs")
        for m in members:
            safe_rel(m.name)
            require(m.isfile(), "apply archive nonregular member")
            data = archive.extractfile(m).read()
            require(data == expected_archive[m.name], "apply archive bytes differ")
            check_pin(data, freeze["member_pins"][m.name], "archive " + m.name)
            archive_members.append({"path": m.name, "tar_mode": oct(m.mode), **pin(data)})

    checked_manifests = []
    for root in ("exec-server-bwrap-r24-repair", "source51-preparation", "source51-native-gates-preparation"):
        handoff = read_json(root + "/HANDOFF-MANIFEST.json")
        rows = handoff["files"]
        require(len(rows) == handoff["file_count"], "frozen handoff count differs")
        for row in rows:
            check_pin(get(root + "/" + safe_rel(row["path"])), row, root + "/" + row["path"])
        checked_manifests.append({"path": root + "/HANDOFF-MANIFEST.json", "listed_files_verified": len(rows), **pin(get(root + "/HANDOFF-MANIFEST.json"))})

    comparison = "native-validation-results/source51-bwrap-comparison-closed/"
    comp_read = read_json(comparison + "LOCAL-READBACK.json")
    for row in comp_read["files"]:
        check_pin(get(comparison + safe_rel(row["path"])), row, "comparison original " + row["path"])
    pre = read_json(comparison + "preconditions.json")
    comp = read_json(comparison + "complete.json")
    require(pre["source_tree"] == comp["source_tree"] == BASE_TREE and pre["source_count"] == comp["source_count"] == 194, "comparison source differs")
    require(pre["source_guard_pass"] and comp["source_guard_pass"], "comparison source guard failed")
    require(pre["locks_before"] == comp["locks_after"] and pre["programs"] == comp["programs"], "comparison program/lock identities changed")
    require(not comp["rust_execution"] and not comp["source_mutation"] and not comp["full_fs_helper_or_test_suite_qualification"], "comparison scope differs")
    probe_results = []
    for label in ("system", "repo"):
        for kind in ("version", "probe"):
            stem = comparison + label + "-" + kind
            intent = read_json(stem + "-intent.json")
            raw = read_json(stem + "-raw-process-result.json")
            receipt = read_json(stem + "-receipt.json")
            require(intent["command"] == raw["command"] == receipt["command"], "probe command differs")
            require(intent["program_before"] == comp["programs"][label], "probe program pin differs")
            require(raw["exit_code"] == receipt["exit_code"] == (1 if (label, kind) == ("repo", "probe") else 0), "probe raw exit differs")
            require(raw["started_unix"] <= raw["ended_unix"] and raw["elapsed_seconds"] >= 0, "probe time order differs")
            for stream in ("stdout", "stderr"):
                data = get(stem + "-" + stream + ".txt")
                check_pin(data, receipt[stream], "probe stream")
                require(data.decode() == receipt[stream + "_text"], "probe text differs")
            if kind == "probe":
                require(raw["command"][1:] == pre["probe_argv"] == ["--unshare-user", "--unshare-net", "--ro-bind", "/", "/", "/bin/true"], "probe argv altered")
            probe_results.append({"label": label, "kind": kind, "command": raw["command"], "exit_code": raw["exit_code"], "receipt": pin(get(stem + "-receipt.json"))})
    require(get(comparison + "repo-probe-stderr.txt") == b"bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted\n", "retained repo failure differs")
    compare_outer = read_json(comparison + "terminal-process-status.json")
    check_natural_zero(compare_outer, "1a1b19909e1-fc05-79c4")

    apply = "native-validation-results/source51-apply-closed/"
    app_read = read_json(apply + "LOCAL-READBACK.json")
    require(len(app_read["files"]) == 23, "original apply readback subset differs")
    for row in app_read["files"]:
        check_pin(get(apply + row["path"]), row, "apply original " + row["path"])
    streams = read_json(apply + "GIT-COMMAND-STREAMS-READBACK.json")
    require(len(streams["original_started_and_stream_files"]) == 9, "apply streams subset differs")
    for row in streams["original_started_and_stream_files"]:
        check_pin(get(apply + "original/" + row["path"]), row, "apply stream " + row["path"])
    app = apply + "original/native-source51-apply/"
    expected_commands = [
        ["git", "apply", "--check", T + "/evidence/native-source51-apply/input/candidate.patch"],
        ["git", "apply", T + "/evidence/native-source51-apply/input/candidate.patch"],
        ["git", "add", "--", *CHANGED],
    ]
    git_results = []
    last_end = 0
    for stem, command in zip(("apply-check", "apply", "stage-exact-paths"), expected_commands):
        started = read_json(app + stem + "-started.json")
        raw = read_json(app + stem + "-raw-process-result.json")
        receipt = read_json(app + stem + "-receipt.json")
        require(raw == {k: v for k, v in receipt.items() if k not in ("stdout", "stderr")}, "Git raw/receipt differs")
        require(raw["command"] == started["command"] == command and raw["cwd"] == started["cwd"] == S, "Git command/cwd differs")
        require(raw["exit_code"] == 0 and raw["wait_exception"] is None, "Git operation failed")
        require(last_end <= started["started_unix"] <= raw["started_unix"] <= raw["ended_unix"], "Git command chronology differs")
        last_end = raw["ended_unix"]
        for stream in ("stdout", "stderr"):
            data = get(app + stem + "-" + stream + ".log")
            check_pin(data, receipt[stream], "Git stream")
            require(data == b"", "original Git stream not empty")
        git_results.append({"name": stem, "command": command, "exit_code": raw["exit_code"], "raw_receipt_fields_exact": True, "streams_empty": True})
    complete = read_json(app + "complete.json")
    post = read_json(app + "post-apply-source-guard.json")
    pre_guard = read_json(app + "pre-apply-source-guard.json")
    require(get(app + "pre-apply-source-guard.json") == get(app + "immediately-before-apply-source-guard.json"), "two preguards differ")
    for guard, expected_tree in ((pre_guard, BASE_TREE), (post, TREE)):
        require(guard["pass"] and guard["actual_tree"] == guard["expected_tree"] == expected_tree and guard["actual_changed_file_count"] == 194, "apply source guard failed")
        require(guard["changed_path_set_matches"] and sorted(guard["changed_paths"]) == sorted(after_rows), "guard path set differs")
        require(guard["file_mismatches"] == guard["unstaged_paths"] == guard["untracked_paths"] == [], "source not clean/exact")
        require(guard["native_head"] == NATIVE_HEAD, "native HEAD changed")
        require(guard["cargo_lock_sha256"] == CARGO_LOCK and guard["bazel_lock_sha256"] == BAZEL_LOCK, "guard lock differs")
    require(post["changed_from_source50_paths"] == CHANGED and post["dependency_inputs_changed_paths"] == [], "apply scope differs")
    require(complete["source_tree"] == TREE and complete["source_commit"] == COMMIT and complete["source_guards_pass"], "apply completion differs")
    require(not complete["rust_executed"] and not complete["bazel_lock_update_executed"] and not complete["fix_fmt_executed"], "apply claimed forbidden scope")
    check_pin(manifest_raw, complete["source_manifest"], "apply source manifest")
    require(get(apply + "original/native-candidate-r26-source.json") == manifest_raw, "native/root source manifest differs")
    check_pin(get(app + "post-apply-source-guard.json"), complete["source_postguard"], "complete/postguard binding")
    require(get(app + "input/delta-manifest.json") == get(preparation + "source51-delta-manifest.json"), "native delta differs")
    apply_outer = read_json(apply + "controller/terminal-process-status.json")
    check_natural_zero(apply_outer, APPLY_JOB)

    # Verify the frozen runnable bytes as data, never import/execute them.
    r26 = "native-validation-results/r26-source51-bound-input/"
    template = get("source51-native-gates-preparation/native-run-r26-template-v2.py")
    bound = get(r26 + "native-run-r26-bound.py")
    final = get(r26 + "native-run-r26.py")
    bindings = read_json(r26 + "ACTUAL-BINDINGS.json")
    require(len(bindings) == 15, "binding count differs")
    original_text, original_assignments = assignment_spans(template)
    bound_text, bound_assignments = assignment_spans(bound)
    replacements = []
    for name, value in bindings.items():
        require(bound_assignments[name][2] == value, "bound literal differs")
        begin, end, _ = bound_assignments[name]
        old_begin, old_end, _ = original_assignments[name]
        replacements.append((begin, end, original_text[old_begin:old_end]))
    inverse = bound_text
    for begin, end, old in sorted(replacements, reverse=True):
        inverse = inverse[:begin] + old + inverse[end:]
    require(inverse.encode() == template, "15-binding inverse differs")
    require(bound.count(b"FROZEN = False") == 1 and bound.replace(b"FROZEN = False", b"FROZEN = True", 1) == final, "final freeze changed other bytes")
    check_pin(final, {"bytes": 46796, "sha256": R26_FINAL_SHA}, "final runner")
    require(final == get(preparation + "ROOT-APPROVED-R26.py"), "root approved r26 differs")
    auth = read_json(preparation + "ROOT-R26-LAUNCH-AUTHORIZATION.json")
    check_pin(final, auth["approved_final"], "root r26 final pin")
    check_pin(get(app + "complete.json"), auth["apply_complete"], "root apply completion pin")
    check_pin(get(apply + "controller/terminal-process-status.json"), auth["apply_terminal"], "root apply terminal pin")
    require(auth["source_tree"] == TREE and auth["apply_job_id"] == APPLY_JOB and auth["authorized"], "r26 authorization differs")
    apply_auth = read_json(preparation + "ROOT-APPLY-LAUNCH-AUTHORIZATION.json")
    check_pin(get(preparation + "ROOT-APPROVED-APPLY.py"), apply_auth["approved_final"], "approved apply runner")
    check_pin(archive_raw, apply_auth["input_archive"], "authorized input archive")

    launch_root = "native-validation-results/r26-start-launch/"
    launch = read_json(launch_root + "original-launch.json")
    launch_review = read_json(launch_root + "LAUNCH-READBACK.json")
    for row in launch_review["originals"]:
        check_pin(get(launch_root + row["path"]), row, "launch original")
    require(launch["job"]["id"] == launch_review["job_id"] == R26_JOB, "launch job differs")
    require(launch["job"]["launch_state"] == "launched" and launch["launch"]["ok"] and not launch["reused"], "original launch differs")
    require(len(launch["job"]["args"]) == 2 and launch["job"]["args"][0] == "-c", "launch argument shape differs")
    require(launch["job"]["args"][1].encode() + b"\n" == get(launch_root + "original-command.txt"), "launch command plus recorded final LF differs")
    runner_info = read_json(launch_root + "runner-file-info.json")
    require(runner_info["size"] == len(final) and runner_info["sha256"] == pin(final)["sha256"], "native runner upload identity differs")
    require(all(launch_review[k] is None for k in ("python_result", "strict_result", "tests_result")), "launch snapshot includes a gate result")
    require(launch_review["control_error_is_gate_result"] is False, "control error was promoted to gate result")

    return {
        "schema": "hepta.source51-repair-apply-attachment-independent-readback.v1",
        "scope": "Local raw-byte and static evidence reconciliation; no command/runner/Git/Rust/formatter execution.",
        "source_registration": {"commit": COMMIT, "tree": TREE, "parent_commit": BASE_COMMIT, "parent_tree": BASE_TREE, "actual_git_api_verified": True, "unsigned_git_commit_preserved": api["verification"]["verified"] is False},
        "source_manifest": {"rows": 194, "rust_paths": 180, "other_paths": 14, "changed_parent_rows": 2, "unchanged_parent_rows": 192, "two_raw_before_after_pairs_verified": True, "other_192_source_payloads_reread_by_this_audit": False, "native_full_source_guard_retained": True, "pin": pin(manifest_raw)},
        "offline_git_rebuild": {"original_direct_trees_rehashed": 7, "parent_child_links_verified": 6, "new_direct_trees_rebuilt": 7, "only_changed_leaf_paths": CHANGED, "computed_tree": derived[""], "remote_git_writes": False},
        "mechanical_patch": {"paths": CHANGED, "forward_and_inverse_exact": True, "combined": pin(combined)},
        "frozen_handoff_subsets": checked_manifests,
        "apply_input_archive": {**pin(archive_raw), "regular_members": 7, "members": archive_members, "raw_archive_unchanged": True},
        "diagnostic": {"job_id": compare_outer["job_id"], "outer_exit": 0, "source_tree": BASE_TREE, "programs": comp["programs"], "original_results": probe_results, "same_restricted_probe_argv": True, "system_probe_exit": 0, "repo_probe_exit": 1, "repo_stderr": pin(get(comparison + "repo-probe-stderr.txt")), "rust_gate_qualification": False, "specific_LSM_or_netlink_errno_cause_proven": False},
        "native_apply": {"job_id": APPLY_JOB, "outer_exit": 0, "natural_durable_terminal": True, "original_git_results": git_results, "native_head": NATIVE_HEAD, "native_index_tree": TREE, "guards_pass": True, "complete": pin(get(app + "complete.json")), "postguard": pin(get(app + "post-apply-source-guard.json")), "cargo_lock_sha256": CARGO_LOCK, "bazel_lock_sha256": BAZEL_LOCK, "dependency_inputs_changed": [], "new_lock_invocation": False, "rust_or_formatter_invocation": False},
        "r26_launch_snapshot": {"job_id": R26_JOB, "state": "LAUNCHED_ONLY", "final_runner": pin(final), "fifteen_literal_bindings_inverse_exact": True, "only_freeze_delta": True, "actual_uploaded_runner_matches": True, "saved_command_file_equals_original_argument_plus_one_final_lf": True, "python_result": None, "strict_result": None, "tests_result": None, "initial_control_errors_are_not_gate_results": True},
        "qualification_boundaries": {"r24": "FAIL: original 1561 PASS / 3 FAIL / 0 TIMEOUT / 3 reported skip, Python32 and strict0 do not promote the gate", "r25": "NOT_EXECUTED_BLOCKED", "source51_rust_gate_result_in_this_attachment": None, "r26_active_logs_read": False, "final_fix_fmt_executed_by_this_audit": False, "science": "HOLD", "authority": "DENY_ALL"},
        "history": "Original provisional false/pending fields, original readback corrections, and initial controller errors are preserved byte-for-byte. Later apply success is recorded separately; no original report is rewritten.",
    }


def check_natural_zero(terminal, job):
    require(terminal["job_id"] == job and terminal["state"] == "succeeded" and terminal["exit_code"] == 0, "outer terminal differs")
    for key in ("cancelled", "timed_out", "automatic_retry"):
        require(terminal[key] is False, "outer nonnatural terminal")
    for key in ("output_complete", "output_durable", "terminal_publication_confirmed"):
        require(terminal[key] is True, "outer output not durable")
    require(all(v is False for v in terminal["log_truncated"].values()), "outer log truncated")
    require(all(v is None for v in terminal["log_errors"].values()), "outer log error")


def put_new(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
    require(path.read_bytes() == raw, "written file readback differs: " + str(path))


def build(workspace):
    destination = workspace / GROUP_REL
    require(not destination.exists(), "create-only destination already exists")
    inventory = []
    for root, target, stage in INPUT_ROOTS:
        source_root = workspace / root
        require(source_root.is_dir() and not source_root.is_symlink(), "missing input directory: " + root)
        for path in sorted(source_root.rglob("*")):
            require(not path.is_symlink(), "input contains symlink")
            if path.is_file():
                relative = str(path.relative_to(workspace))
                inventory.append((relative, target + "/" + str(path.relative_to(source_root)), stage, path.read_bytes()))
    for relative, target, stage in EXTRA_FILES:
        path = workspace / relative
        require(path.is_file() and not path.is_symlink(), "missing extra input: " + relative)
        inventory.append((relative, target, stage, path.read_bytes()))
    require(len({x[0] for x in inventory}) == len(inventory), "duplicate source input")
    original_bytes = {relative: raw for relative, _, _, raw in inventory}
    report = validate(original_bytes.__getitem__)
    destination.mkdir(parents=True, exist_ok=False)
    mapping, canonical_large = [], {}
    for relative, proposed, stage, raw in inventory:
        ident = pin(raw)
        key = (ident["bytes"], ident["sha256"])
        duplicate = len(raw) >= 16384 and key in canonical_large
        target = canonical_large[key] if duplicate else proposed
        safe_rel(target)
        if duplicate:
            require((destination / target).read_bytes() == raw, "deduplicated bytes differ")
        else:
            put_new(destination / target, raw)
            if len(raw) >= 16384:
                canonical_large[key] = target
        mapping.append({"source": relative, "destination": target, "encoding": "identity", "deduplicated_large_copy": duplicate, "stage": stage, **ident})
    # A second local read of every selected source detects mutation while copying.
    for row in mapping:
        check_pin((workspace / row["source"]).read_bytes(), row, "post-copy original " + row["source"])
        check_pin((destination / row["destination"]).read_bytes(), row, "copied " + row["destination"])
    map_doc = {"schema": "hepta.source51-attachment-source-destination-map.v1", "source_workspace_at_assembly": str(workspace), "input_files": len(mapping), "raw_input_bytes_including_duplicates": sum(row["bytes"] for row in mapping), "unique_stored_original_paths": len({row["destination"] for row in mapping}), "large_copy_deduplication_threshold_bytes": 16384, "all_sources_exact_and_unmodified": True, "compression": "none; all originals identity copied, existing input tar retained unchanged", "files": mapping}
    put_new(destination / "SOURCE-DESTINATION-MAPPING.json", jbytes(map_doc))
    put_new(destination / "INDEPENDENT-READBACK.json", jbytes(report))
    closure = {
        "schema": "hepta.source51-repair-apply-checkpoint-closure.v1",
        "state": "SOURCE_REGISTERED_AND_APPLY_PASS_R26_LAUNCH_SNAPSHOT_ONLY",
        "source_commit": COMMIT, "source_tree": TREE, "source_parent_commit": BASE_COMMIT,
        "source_changed_paths": 194, "source_rust_paths": 180,
        "change_from_source50": CHANGED,
        "native_head": NATIVE_HEAD,
        "actual_apply": {"job_id": APPLY_JOB, "exit_code": 0, "original_git_exit_codes": [0, 0, 0], "guards_pass": True},
        "r26": {"job_id": R26_JOB, "observation": "immutable initial launch only", "python_exit": None, "strict_exit": None, "tests_exit": None, "terminal_counts": None},
        "r24_engineering_disposition": "FAIL",
        "r25_executed": False, "final_fix_fmt_executed_in_this_attachment": False,
        "science": "HOLD", "authority": "DENY_ALL",
        "originals_rewritten": False, "active_logs_read": False,
        "independent_readback": {"path": "INDEPENDENT-READBACK.json", **pin(jbytes(report))},
        "mapping": {"path": "SOURCE-DESTINATION-MAPPING.json", **pin(jbytes(map_doc))},
        "missing_required_artifacts": [],
        "scope_limits": ["Comparison is a controlled launcher diagnostic, not a full helper or Rust gate.", "194 manifest rows and the two changed payload pairs are independently checked here; native guards attest all194 files. This group does not duplicate all194 source files.", "Source51 GitData commit maps the staged native tree; native HEAD remains bef6fa.", "Source50 unchanged dependency/lock evidence is inherited; no new lock command is claimed.", "Historical preparation fields remain unchanged even after later registration and apply.", "Future r26/r27 and fix/fmt qualifications require separate closed receipts."],
    }
    put_new(destination / "CLOSURE.json", jbytes(closure))
    readme = """# Source51 修复与实际应用证据\n\n本组封存 source51 注册、两处精确修复、真实 launcher 对照、实际 apply 成功及 r26 的初始启动输入。它不包含 r26 的测试终态。科学结论保持 **HOLD**，authority 保持 **DENY_ALL**。\n\n## 身份与阶段\n\n| 项目 | 封存事实 |\n| --- | --- |\n| GitData commit | e28b0f385ee882f842911044958b2810f62f6379 |\n| Source tree | 763c8d2b4089f6e9806c3bbb68fa247bc2f6af36 |\n| Parent source50 | 1fdd647b0ecb235530e8b88bbea45b3d3762906f / ea48acf562499192a25e05ae28926a32632dee62 |\n| 变更清单 | 194 路径，180 Rust；相对 source50 只改两条既有路径 |\n| Native HEAD | bef6fa7645df9df12b69fda499e97eed25de6c75；本组不把 GitData commit 写成 checkout |\n| Apply | 三条原 Git 命令 exit0，原 outer 自然0，前后源码及双锁 guard 通过 |\n| r26 | 仅原 job 1a1b1b739ee-fc05-7a70 的初始 launched 快照；三阶段结果均 null |\n| 既有失败 | r24 仍为 1561 PASS / 3 FAIL / 0 TIMEOUT / 3 reported skip；r25 未执行 |\n\n## 改动与证据强度\n\nexec-server 的测试 launcher 在安装新的 child PATH shim 之前，使用已有生产函数寻找 system bwrap；只有找不到时使用仓库二进制。选定程序的后续运行错误继续传播，没有失败后换程序。原 shim 的完整参数、FD、环境传递、隔离配置及测试断言保留。\n\n受控对照保留同一组 --unshare-user / --unshare-net / --ro-bind 参数：固定 /usr/bin/bwrap 0.11.1 返回0，固定仓库 bwrap 返回1并留下原61字节 loopback 错误。对照未运行 Rust，不证明所有 bwrap 后端合格，也没有确定该错误的具体 LSM 或 netlink errno 根因。\n\nnetwork-proxy 的改动只为直接 CONNECT policy 测试配置现有 allow_local_binding 选项，保留生产默认值和独立地址 guard 测试。两个 candidate 的原文、补丁和独立审查均保留。\n\n## 读取入口\n\n- [闭合范围](CLOSURE.json) 与 [独立读回](INDEPENDENT-READBACK.json)：重新校验两条补丁正反、7棵原始直接 Git tree、实际 commit、7成员输入包、三条 Git raw/receipt/stream/outer 和 r26 的冻结输入。\n- [原件映射](SOURCE-DESTINATION-MAPPING.json)：每个原路径、原字节 pin、当前存放位置。大于等于16KiB的同字节重复件只存一次；原件自身的相对引用可通过此映射解析。\n- [附件清单](ATTACHMENT-MANIFEST.json) 与 [二进制计划](BINARY-PLAN.json)：逐件原始 SHA256/Git blob；输入 tar 未改写。\n- registration/ 保留早期 pending/false 原字段及后来的实际注册和 root 授权；native-apply/ 保留实际运行原件；r26-launch/ 仅保留初始启动与控制器查询错误。控制器查询错误不视作测试结果。\n- reviews/ 与候选内 independent-review/ 保留各审查者原始范围；新附件读回不冒充先前报告的原字节。\n\n只读复算：运行本组 tools/assemble_attachment.py --verify-only <本组目录>。该入口只解析与哈希本组文件，不导入或运行任何被封存的 runner，不访问 native，不执行 Git、Rust 或 formatter。\n\n本组不重复194源码目录。完整清单保留，变更的两对源码保留；对其余192路径的独立结论限定为与 source50 清单逐项一致，实际 full-source 核验以原 native guard 为证。最终 fix/fmt、完整项目和默认工作区门须等待各自独立闭合记录。\n"""
    put_new(destination / "README.md", readme.encode())
    put_new(destination / "tools/assemble_attachment.py", Path(__file__).read_bytes())
    binary_rows = []
    for path in sorted(destination.rglob("*")):
        if path.is_file():
            raw = path.read_bytes()
            try:
                raw.decode("utf-8")
                utf8 = True
            except UnicodeDecodeError:
                utf8 = False
            if not utf8 or path.suffix in (".gz", ".zip", ".tar"):
                binary_rows.append({"path": str(path.relative_to(destination)), **pin(raw), "encoding": "original archive bytes", "new_compression": False, "git_upload_performed_by_assembler": False, "reuse_known_git_blob_if_already_registered": True})
    put_new(destination / "BINARY-PLAN.json", jbytes({"schema": "hepta.source51-attachment-binary-plan.v1", "files": binary_rows, "file_count": len(binary_rows), "unique_git_blobs": len({r["git_blob"] for r in binary_rows}), "root_handles_git_registration": True, "new_gzip_files": 0}))
    manifest_files = []
    for path in sorted(destination.rglob("*")):
        if path.is_file():
            manifest_files.append({"path": str(path.relative_to(destination)), **pin(path.read_bytes())})
    attachment = {"schema": "hepta.source51-repair-apply-attachment-manifest.v1", "self_excluded": True, "file_count": len(manifest_files), "bytes_excluding_this_manifest": sum(r["bytes"] for r in manifest_files), "all_originals_identity_encoded": True, "files": manifest_files}
    put_new(destination / "ATTACHMENT-MANIFEST.json", jbytes(attachment))
    return verify(destination)


def verify(destination):
    manifest = json.loads((destination / "ATTACHMENT-MANIFEST.json").read_bytes())
    listed = manifest["files"]
    actual = sorted(str(p.relative_to(destination)) for p in destination.rglob("*") if p.is_file())
    require(actual == sorted([r["path"] for r in listed] + ["ATTACHMENT-MANIFEST.json"]), "attachment file set differs")
    require(len(listed) == manifest["file_count"], "attachment count differs")
    require(sum(row["bytes"] for row in listed) == manifest["bytes_excluding_this_manifest"], "attachment byte total differs")
    for row in listed:
        check_pin((destination / safe_rel(row["path"])).read_bytes(), row, "attachment " + row["path"])
    map_doc = json.loads((destination / "SOURCE-DESTINATION-MAPPING.json").read_bytes())
    mapping = map_doc["files"]
    require(len(mapping) == len({r["source"] for r in mapping}) == map_doc["input_files"], "source mapping count differs")
    resolved = {}
    for row in mapping:
        raw = (destination / safe_rel(row["destination"])).read_bytes()
        check_pin(raw, row, "mapped " + row["source"])
        require(row["encoding"] == "identity", "unexpected encoding")
        resolved[row["source"]] = raw
    actual_report = validate(resolved.__getitem__)
    require(jbytes(actual_report) == (destination / "INDEPENDENT-READBACK.json").read_bytes(), "recomputed semantic report differs")
    binaries = json.loads((destination / "BINARY-PLAN.json").read_bytes())
    for row in binaries["files"]:
        check_pin((destination / row["path"]).read_bytes(), row, "binary")
    return {
        "status": "EXACT_ATTACHMENT_AND_CLOSED_APPLY_READBACK_PASS_R26_RESULT_NOT_CLAIMED",
        "directory": str(destination), "file_count_including_manifest": len(actual),
        "total_stored_bytes": sum((destination / p).stat().st_size for p in actual),
        "source_mapping_count": len(mapping),
        "unique_stored_original_paths": len({r["destination"] for r in mapping}),
        "deduplicated_large_source_entries": sum(r["deduplicated_large_copy"] for r in mapping),
        "attachment_manifest": pin((destination / "ATTACHMENT-MANIFEST.json").read_bytes()),
        "closure": pin((destination / "CLOSURE.json").read_bytes()),
        "readback": pin((destination / "INDEPENDENT-READBACK.json").read_bytes()),
        "binary_files": binaries["files"],
        "missing_required_artifacts": [],
        "read_only_verification": True, "native_execution": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--verify-only", type=Path)
    args = parser.parse_args()
    require(bool(args.workspace) != bool(args.verify_only), "supply exactly one mode")
    result = verify(args.verify_only.resolve()) if args.verify_only else build(args.workspace.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
