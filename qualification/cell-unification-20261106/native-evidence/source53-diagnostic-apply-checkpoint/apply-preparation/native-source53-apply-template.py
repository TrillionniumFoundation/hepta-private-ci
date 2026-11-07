#!/usr/bin/env python3
"""INERT source52 -> source53 apply-only executor.

Only the native owner may bind and run this reviewed script. It runs no Rust,
dependency regeneration, formatter, workspace gate, or remote Git operation.
A failure preserves the actual source/index state; there is no automatic reset.
This source adds diagnostic stage records; it does not claim a behavior repair.
"""
from pathlib import Path, PurePosixPath
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
import time

FROZEN = False
EXPECTED_COMMIT = None
EXPECTED_TREE = None
EXPECTED_CHANGED_COUNT = None
INPUT_BYTES = None
INPUT_SHA256 = None
SOURCE53_MANIFEST_PIN = None
DELTA_MANIFEST_PIN = None
CANDIDATE_PINS = None

T = Path("/home/alex/work/hepta-cell-unified-20261106-a")
S = T / "source"
E = T / "evidence"
R = E / "native-source53-apply"
INPUT_NAME = "source53-apply-input.tar.gz"
SOURCE53_MANIFEST_OUTPUT_NAME = 'native-candidate-r30-source.json'
FRAMEWORK_PARENT = "bef6fa7645df9df12b69fda499e97eed25de6c75"
SOURCE52_COMMIT = '1e0910becc37383e6d17ecf861ea844fd07d8862'
SOURCE52_TREE = '211f15baff19095e8c98bcea2b0ed99ca2270ade'
SOURCE52_COUNT = 195
SOURCE52_MANIFEST_NAME = 'native-candidate-r28-source.json'
SOURCE52_MANIFEST_PIN = {'bytes': 55209, 'sha256': '3ff99b41bab572666b424fdbf9a508b33be13e6487d9effa7dd6a0e14b4ec898', 'git_blob': 'f057b526bf2ba492d6bb5810222f69ac0cc3bdd2'}
R29_TERMINAL_NAME = 'native-workspace-r29-terminal-process-status.json'
R29_TERMINAL_PIN = {'bytes': 730, 'sha256': '9577b5c1f87e1f529edffcb262683067d0379dc4a9b16c84a2a43c68388374bf', 'git_blob': '1c6fc37a5f85c915bd1fac9ae7a4fa10db35ae03'}
R29_JOB_ID = '1a1b1f83e4b-fc05-7bcd'
CARGO_LOCK_SHA256 = "4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c"
BAZEL_LOCK_SHA256 = "e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb"
LOCKS = ("codex-rs/Cargo.lock", "MODULE.bazel.lock")
ALLOWED_PATHS = ('codex-rs/app-server/src/request_processors/account_processor/bedrock_setup.rs', 'codex-rs/app-server/tests/suite/v2/bedrock_setup.rs')
FILE_KEYS = ("path", "mode", "bytes", "sha256", "git_blob")
HUNK = re.compile(rb"@@ -([0-9]+)(?:,([0-9]+))? \+([0-9]+)(?:,([0-9]+))? @@[^\r\n]*\n")


EXISTING_BASELINE_LEAF_PINS = {'codex-rs/app-server/src/request_processors/account_processor/bedrock_setup.rs': {'bytes': 5606, 'sha256': 'af9ceab5047c7ee06bba84d47684748b38bfbb32e287db4a6fca84b2b45fa6fa', 'git_blob': '9e7cb31856c2b938c6a8ba73f8affb36bd4b5e3d'}, 'codex-rs/app-server/tests/suite/v2/bedrock_setup.rs': {'bytes': 11612, 'sha256': '25c5036f352b673af21adfd37930f3f1762359b7422084c6e4eaaa9c1f513d55', 'git_blob': '87cfaf3ae45eafbc54dad94a96226f4a807209a5'}}
R29_PREFIX = 'native-workspace-r29'
R29_FAILURE_PINS = {'native-workspace-r29-terminal-process-status.json': {'bytes': 730, 'sha256': '9577b5c1f87e1f529edffcb262683067d0379dc4a9b16c84a2a43c68388374bf', 'git_blob': '1c6fc37a5f85c915bd1fac9ae7a4fa10db35ae03'}, 'native-workspace-r29-tests-raw-process-result.json': {'bytes': 500, 'sha256': 'c840e6ff388a9863aee1dce8b0bc148446ee6541025a7c7ba8b4ec96196d43c8', 'git_blob': '9db48c9908ac31a1e0f4def51657c1e5d6bd1e46'}, 'native-workspace-r29-tests-receipt.json': {'bytes': 2782, 'sha256': '9ca2e64a0ff00b86840d76c2003caf7608965719e481a541235e43d462bd574a', 'git_blob': '635387c0203c9023312dd1c80984803834d20d87'}, 'native-workspace-r29-source-post-test-verification.json': {'bytes': 643, 'sha256': 'e116303f0a7fac5b3d9f79ca3471331c9be7640120b124585ce2a61c70623703', 'git_blob': '8004aaebcc2ef58884dbc24ce17a287cc4e416e8'}}


def require(value, message):
    if not value:
        raise RuntimeError(message)


def pin(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
    }


def safe_relative(value):
    require(isinstance(value, str) and bool(value), "relative path missing")
    p = PurePosixPath(value)
    require(not p.is_absolute() and str(p) == value, "noncanonical relative path")
    require(all(part not in ("", ".", "..") for part in p.parts), "unsafe relative path")
    require("\0" not in value and "\\" not in value, "unsafe path characters")
    return p


def digest(value, width):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{" + str(width) + r"}", value) is not None


def validate_pin(value):
    require(isinstance(value, dict) and set(value) == {"bytes", "sha256", "git_blob"}, "missing complete pin")
    require(type(value["bytes"]) is int and value["bytes"] >= 0, "invalid byte size")
    require(digest(value["sha256"], 64) and digest(value["git_blob"], 40), "invalid digest")


def check_bindings():
    require(FROZEN is True, "INERT PREPARATION: apply is not authorized")
    require(sys.flags.optimize == 0 and os.environ.get("PYTHONOPTIMIZE") in (None, "", "0"), "optimized Python is not an approved executor")
    require(digest(EXPECTED_COMMIT, 40) and digest(EXPECTED_TREE, 40), "source53 identity unbound")
    require(EXPECTED_COMMIT != SOURCE52_COMMIT and EXPECTED_TREE != SOURCE52_TREE, "no new source identity")
    require(type(EXPECTED_CHANGED_COUNT) is int and EXPECTED_CHANGED_COUNT == SOURCE52_COUNT + len(ALLOWED_PATHS), "source53 count must be prior195 plus exactly two existing repository leaves")
    require(type(INPUT_BYTES) is int and INPUT_BYTES > 0 and digest(INPUT_SHA256, 64), "input archive unbound")
    for expected in (SOURCE52_MANIFEST_PIN, R29_TERMINAL_PIN, SOURCE53_MANIFEST_PIN, DELTA_MANIFEST_PIN):
        validate_pin(expected)
    require(set(EXISTING_BASELINE_LEAF_PINS) == set(ALLOWED_PATHS) and len(ALLOWED_PATHS) == 2, "two independently reviewed existing leaves required")
    for expected in EXISTING_BASELINE_LEAF_PINS.values():
        validate_pin(expected)
    require(isinstance(CANDIDATE_PINS, dict) and set(CANDIDATE_PINS) == set(ALLOWED_PATHS), "two reviewed existing repository leaf bindings required")
    for path, row in CANDIDATE_PINS.items():
        safe_relative(path)
        require(path.endswith(".rs") and Path(path).name != "build.rs", "dependency/build input prohibited")
        require(set(row) == {"before", "after"}, "candidate binding shape")
        for side in ("before", "after"):
            require(isinstance(row[side], dict) and set(row[side]) == {"mode", "bytes", "sha256", "git_blob"}, "candidate pin shape")
            validate_pin({key: row[side][key] for key in ("bytes", "sha256", "git_blob")})
            require(row[side]["mode"] == "100644", "candidate mode change prohibited")
        require(row["before"] != row["after"], "candidate must be an actual change")
    for expected in R29_FAILURE_PINS.values():
        validate_pin(expected)
    require(set(R29_FAILURE_PINS) == {
        R29_TERMINAL_NAME, R29_PREFIX + "-tests-raw-process-result.json",
        R29_PREFIX + "-tests-receipt.json", R29_PREFIX + "-source-post-test-verification.json",
    }, "four actual failed r29 originals are required")
    for name in (INPUT_NAME, SOURCE52_MANIFEST_NAME, SOURCE53_MANIFEST_OUTPUT_NAME, *R29_FAILURE_PINS):
        safe_relative(name)


def write_new(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def write_json(path, value):
    write_new(path, (json.dumps(value, sort_keys=True, indent=2) + "\n").encode())


def announce(value):
    try:
        print(json.dumps(value, sort_keys=True), flush=True)
    except (BrokenPipeError, OSError):
        pass


def git(*args):
    result = subprocess.run(["git", *args], cwd=S, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    require(result.returncode == 0, "git read failed: " + repr(args) + ": " + result.stderr.decode(errors="replace"))
    return result.stdout


def git_paths(*args):
    raw = git(*args)
    require(not raw or raw.endswith(b"\0"), "unterminated Git path list")
    paths = [part.decode("utf-8") for part in raw.split(b"\0") if part]
    for path in paths:
        safe_relative(path)
    require(len(paths) == len(set(paths)), "duplicate Git path")
    return paths


def normalized_files(entries):
    require(isinstance(entries, list), "source list missing")
    result = {}
    for entry in entries:
        row = {key: entry[key] for key in FILE_KEYS}
        safe_relative(row["path"])
        require(row["mode"] in ("100644", "100755"), "source mode unsupported")
        validate_pin({key: row[key] for key in ("bytes", "sha256", "git_blob")})
        require(row["path"] not in result, "duplicate manifest source")
        result[row["path"]] = row
    return result


def source_raw(path):
    p = S.joinpath(*safe_relative(path).parts)
    current = p
    while current != S:
        require(not current.is_symlink(), "symlink in source path: " + path)
        current = current.parent
    mode = p.stat().st_mode
    require(stat.S_ISREG(mode), "not a regular source: " + path)
    return p.read_bytes(), "100755" if mode & 0o111 else "100644"


def source_guard(files, expected_tree, expected_commit, expected_count):
    report = {"expected_tree": expected_tree, "source_commit": expected_commit, "expected_count": expected_count, "pass": False}
    try:
        report["actual_tree"] = git("write-tree").decode().strip()
        report["native_head"] = git("rev-parse", "HEAD").decode().strip()
        report["unstaged_paths"] = git_paths("diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z")
        report["untracked_paths"] = git_paths("ls-files", "--others", "--exclude-standard", "-z")
        paths = git_paths("diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--name-only", "-z", FRAMEWORK_PARENT, report["actual_tree"])
        report["changed_paths"] = paths
        report["actual_changed_file_count"] = len(paths)
        report["changed_path_set_matches"] = set(paths) == set(files) and len(paths) == len(files)
        mismatches = []
        for path, expected in files.items():
            try:
                raw, actual_mode = source_raw(path)
                actual = {"path": path, "mode": actual_mode, **pin(raw)}
                record = git("ls-tree", "-z", report["actual_tree"], "--", path)
                require(record.endswith(b"\0") and record.count(b"\0") == 1, "tree path missing/ambiguous")
                header, name = record[:-1].split(b"\t", 1)
                mode, kind, blob = header.decode().split()
                require(name.decode() == path and kind == "blob", "tree path/type mismatch")
                require(actual == expected and mode == actual_mode and blob == actual["git_blob"], "raw/Git/mode mismatch")
            except Exception as error:
                mismatches.append({"path": path, "error": repr(error)})
        report["file_mismatches"] = mismatches
        report["cargo_lock_sha256"] = pin((S / LOCKS[0]).read_bytes())["sha256"]
        report["bazel_lock_sha256"] = pin((S / LOCKS[1]).read_bytes())["sha256"]
        report["pass"] = (
            report["actual_tree"] == expected_tree
            and report["native_head"] == FRAMEWORK_PARENT
            and len(files) == expected_count == len(paths)
            and report["changed_path_set_matches"]
            and not report["unstaged_paths"] and not report["untracked_paths"] and not mismatches
            and report["cargo_lock_sha256"] == CARGO_LOCK_SHA256
            and report["bazel_lock_sha256"] == BAZEL_LOCK_SHA256
        )
        if expected_tree == SOURCE52_TREE:
            report["existing_repo_leaves_outside_prior_changed_manifest"] = existing_baseline_leaves_guard()
    except Exception as error:
        report["error"] = repr(error)
        report["pass"] = False
    return report


def replay_patch(patch, originals, reverse=False):
    """Validate the bounded text-only patch before any source mutation."""
    require(patch.endswith(b"\n"), "unterminated patch")
    lines = patch.splitlines(keepends=True)
    index = 0
    outputs = {}
    while index < len(lines):
        diff_header = None
        if lines[index].startswith(b"diff --git "):
            diff_header = lines[index]
            index += 1
            if index < len(lines) and lines[index].startswith(b"index "):
                require(re.fullmatch(rb"index [0-9a-f]{7,40}\.\.[0-9a-f]{7,40}(?: 100644)?\n", lines[index]) is not None, "unsupported index header")
                index += 1
        require(index + 1 < len(lines) and lines[index].startswith(b"--- a/") and lines[index + 1].startswith(b"+++ b/"), "only existing regular text modifications supported")
        path = lines[index][6:-1].decode("utf-8")
        require(lines[index + 1] == ("+++ b/" + path + "\n").encode(), "rename/path mismatch")
        require(path in originals and path in ALLOWED_PATHS and path not in outputs, "undeclared/duplicate patch path")
        if diff_header is not None:
            require(diff_header == ("diff --git a/" + path + " b/" + path + "\n").encode(), "diff header mismatch")
        index += 2
        source = originals[path].splitlines(keepends=True)
        require(originals[path].endswith(b"\n"), "reviewed Rust input must end in LF")
        result = []
        cursor = 0
        hunks = 0
        while index < len(lines) and lines[index].startswith(b"@@ "):
            match = HUNK.fullmatch(lines[index])
            require(match is not None, "invalid hunk header")
            old_start, old_count, new_start, new_count = (int(match[1]), int(match[2] or b"1"), int(match[3]), int(match[4] or b"1"))
            if reverse:
                old_start, new_start, old_count, new_count = new_start, old_start, new_count, old_count
            start = old_start - 1 if old_start else 0
            target_start = new_start - 1 if new_start else 0
            require(cursor <= start <= len(source), "overlapping/out-of-range hunk")
            result.extend(source[cursor:start])
            cursor = start
            require(len(result) == target_start, "new hunk coordinate mismatch")
            index += 1
            old_seen = 0
            new_seen = 0
            while old_seen < old_count or new_seen < new_count:
                require(index < len(lines), "truncated hunk")
                line = lines[index]
                tag, body = line[:1], line[1:]
                require(tag in (b" ", b"+", b"-"), "binary/mode/no-newline record prohibited")
                if reverse and tag != b" ":
                    tag = b"-" if tag == b"+" else b"+"
                if tag in (b" ", b"-"):
                    require(cursor < len(source) and source[cursor] == body, "patch original byte mismatch")
                    cursor += 1
                    old_seen += 1
                if tag in (b" ", b"+"):
                    result.append(body)
                    new_seen += 1
                require(old_seen <= old_count and new_seen <= new_count, "hunk count exceeded")
                index += 1
            require(old_seen == old_count and new_seen == new_count, "hunk counts")
            hunks += 1
        require(hunks > 0, "empty file patch")
        result.extend(source[cursor:])
        outputs[path] = b"".join(result)
    require(set(outputs) == set(ALLOWED_PATHS), "patch does not cover exactly the two reviewed existing Rust leaves")
    return outputs


def existing_baseline_leaves_guard():
    leaves = []
    for path in ALLOWED_PATHS:
        expected = EXISTING_BASELINE_LEAF_PINS[path]
        record = git("ls-tree", "-z", SOURCE52_TREE, "--", path)
        require(record.endswith(b"\0") and record.count(b"\0") == 1, "existing baseline Git leaf absent or ambiguous")
        header, name = record[:-1].split(b"\t", 1)
        mode, kind, blob = header.decode().split()
        require(name.decode() == path and kind == "blob" and mode == "100644"
                and blob == expected["git_blob"], "existing source52 leaf Git identity differs")
        committed = git("cat-file", "blob", blob)
        require(pin(committed) == expected, "existing baseline Git blob bytes differ")
        raw, actual_mode = source_raw(path)
        require(actual_mode == mode and pin(raw) == expected, "existing baseline leaf working bytes/mode differ")
        require(CANDIDATE_PINS[path]["before"] == {"mode": mode, **expected},
                "candidate before pin is not the independently reviewed existing leaf")
        leaves.append({"path": path, "mode": mode, **pin(raw), "source_tree": SOURCE52_TREE,
                       "actual_working_bytes_equal_existing_Git_leaf": True})
    return {"before_existing_repo_leaves_not_in_prior_changed_manifest": True, "leaves": leaves}


def r29_failed_prerequisite():
    originals = {}
    pins = []
    for name, expected in R29_FAILURE_PINS.items():
        raw = (E / safe_relative(name)).read_bytes()
        require(pin(raw) == expected, "original failed r29 pin differs: " + name)
        originals[name] = raw
        pins.append({"path": name, **pin(raw)})
    terminal = json.loads(originals[R29_TERMINAL_NAME])
    require(terminal["job_id"] == R29_JOB_ID and terminal["state"] == "failed"
            and terminal["exit_code"] == 100, "r29 did not naturally close at its original workspace failure")
    for field in ("timed_out", "cancelled", "automatic_retry"):
        require(terminal[field] is False, "invalid r29 termination flag: " + field)
    for field in ("audit_recorded", "output_complete", "output_durable", "terminal_publication_confirmed"):
        require(terminal[field] is True, "r29 durable closure missing: " + field)
    raw_name = R29_PREFIX + "-tests-raw-process-result.json"
    receipt_name = R29_PREFIX + "-tests-receipt.json"
    post_name = R29_PREFIX + "-source-post-test-verification.json"
    result, receipt, post = (json.loads(originals[name]) for name in (raw_name, receipt_name, post_name))
    require(result["schema"] == "hepta.native-raw-process-result.v1"
            and receipt["schema"] == "hepta.native-workspace-gate-receipt.v2", "r29 original schemas differ")
    for value in (result, receipt):
        require(value["phase"] == "workspace-tests" and value["source_tree"] == SOURCE52_TREE
                and value["source_commit"] == SOURCE52_COMMIT and value["exit_code"] == 100
                and value["command"] == ["just", "test", "--locked", "--retries", "0"]
                and value["cwd"] == str(S / "codex-rs"), "r29 original failed gate identity differs")
    for key in ("phase", "source_tree", "source_commit", "command", "cwd", "start_unix", "end_unix", "exit_code"):
        require(result[key] == receipt[key], "r29 raw/receipt mismatch: " + key)
    require(receipt["end_unix"] >= receipt["start_unix"]
            and abs(receipt["elapsed_seconds"] - (receipt["end_unix"] - receipt["start_unix"])) < 1e-6,
            "r29 original time accounting mismatch")
    require(receipt["effective_exit_code"] == 100 and receipt["phase_pass"] is False
            and receipt["test_scope"] == "original_default_workspace" and receipt["packages_argument"] is None
            and receipt["workspace_member_count"] == receipt["workspace_default_member_count"] == 193
            and receipt["retries"] == 0 and receipt["filters"] == "no_additions"
            and receipt["features"] == "unchanged_defaults" and receipt["fix_fmt_executed"] is False,
            "r29 failure or original no-p193 selection was relabeled")
    require(receipt["source_manifest"] == SOURCE52_MANIFEST_NAME
            and receipt["source_manifest_sha256"] == SOURCE52_MANIFEST_PIN["sha256"],
            "r29 receipt does not bind original source52 manifest")
    require(receipt["raw_process_result"] == {"path": raw_name, **pin(originals[raw_name])}
            and receipt["source_postguard"] == {"path": post_name, **pin(originals[post_name])},
            "r29 original receipt pointers differ")
    require(receipt["source_guards_pass"] is True and post["pass"] is True
            and post["actual_tree"] == post["expected_tree"] == SOURCE52_TREE
            and post["source_commit"] == SOURCE52_COMMIT
            and post["changed_file_count"] == SOURCE52_COUNT and post["gate_exit_code"] == 100
            and post["phase"] == "workspace-tests" and post["native_head"] == FRAMEWORK_PARENT,
            "r29 failed gate did not preserve the exact baseline source")
    require(post["changed_path_set_matches"] is True
            and post["unstaged_paths"] == post["untracked_paths"] == post["file_mismatches"] == []
            and post["cargo_lock_sha256"] == CARGO_LOCK_SHA256
            and post["bazel_lock_sha256"] == BAZEL_LOCK_SHA256, "r29 baseline guard or dual-lock mismatch")
    require(terminal["at_unix_ms"] / 1000 >= receipt["end_unix"], "r29 terminal precedes test end")
    return pins


def manifest_row_slices(raw):
    text = raw.decode("utf-8")
    matches = list(re.finditer(r'"changed_files"\s*:\s*\[', text))
    require(len(matches) == 1, "one changed_files array required")
    position = matches[0].end()
    decoder = json.JSONDecoder()
    rows = {}
    while True:
        while position < len(text) and text[position].isspace():
            position += 1
        require(position < len(text), "truncated changed_files array")
        if text[position] == "]":
            return rows
        value, end = decoder.raw_decode(text, position)
        require(isinstance(value, dict) and value["path"] not in rows, "invalid or duplicate raw source row")
        rows[value["path"]] = text[position:end].encode("utf-8")
        position = end
        while position < len(text) and text[position].isspace():
            position += 1
        require(position < len(text) and text[position] in ",]", "invalid source array separator")
        if text[position] == ",":
            position += 1


def load_inputs():
    old_raw = (E / SOURCE52_MANIFEST_NAME).read_bytes()
    require(pin(old_raw) == SOURCE52_MANIFEST_PIN, "source52 manifest bytes changed")
    old = json.loads(old_raw)
    require(old["source_tree"] == SOURCE52_TREE and old["source_commit"] == SOURCE52_COMMIT, "source52 identity")
    old_files = normalized_files(old["changed_files"])
    require(len(old_files) == SOURCE52_COUNT and set(ALLOWED_PATHS).isdisjoint(old_files),
            "both new changed leaves must be outside the prior195 changed manifest")
    r29_pins = r29_failed_prerequisite()
    archive_raw = (T / INPUT_NAME).read_bytes()
    require(len(archive_raw) == INPUT_BYTES and pin(archive_raw)["sha256"] == INPUT_SHA256, "source53 archive pin")
    members = {}
    expected_members = {"delta-manifest.json", "source53-manifest.json", "candidate.patch"}
    expected_members |= {side + "/" + path for side in ("before", "after") for path in ALLOWED_PATHS}
    with tarfile.open(fileobj=io.BytesIO(archive_raw), mode="r:gz") as archive:
        for member in archive.getmembers():
            safe_relative(member.name)
            require(member.isfile() and not member.issym() and not member.islnk(), "archive links/nonregular member")
            require(member.name in expected_members and member.name not in members, "unexpected/duplicate archive member")
            stream = archive.extractfile(member)
            require(stream is not None, "archive read missing")
            data = stream.read()
            require(len(data) == member.size, "archive member truncated")
            members[member.name] = data
    require(set(members) == expected_members and len(members) == 7, "exact seven two-leaf input members required")
    require(pin(members["source53-manifest.json"]) == SOURCE53_MANIFEST_PIN
            and pin(members["delta-manifest.json"]) == DELTA_MANIFEST_PIN, "new manifest pins")
    source = json.loads(members["source53-manifest.json"])
    require(source["source_tree"] == EXPECTED_TREE and source["source_commit"] == EXPECTED_COMMIT,
            "root source53 identity")
    require(source["source_parent_commit"] == SOURCE52_COMMIT, "source53 parent must be source52")
    require(source["diagnostic_only"] is True and source["behavior_repair_claimed"] is False,
            "diagnostic source must not be relabeled as a behavior repair")
    files = normalized_files(source["changed_files"])
    require(len(files) == EXPECTED_CHANGED_COUNT == SOURCE52_COUNT + len(ALLOWED_PATHS)
            and set(files) == set(old_files) | set(ALLOWED_PATHS),
            "full source53 manifest must be exactly unchanged195 plus the two existing Bedrock leaves")
    for obj in (old, source):
        require(obj["cargo_lock_sha256"] == CARGO_LOCK_SHA256
                and obj["bazel_lock_sha256"] == BAZEL_LOCK_SHA256, "manifest dual-lock identity")
    delta = json.loads(members["delta-manifest.json"])
    require(delta["schema"] == "hepta.source53-apply-delta.v1", "delta schema")
    require(delta["diagnostic_only"] is True and delta["behavior_repair_claimed"] is False,
            "diagnostic delta must not be relabeled as a behavior repair")
    for key, value in {
        "source_before_tree": SOURCE52_TREE, "source_before_commit": SOURCE52_COMMIT,
        "source_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT,
    }.items():
        require(delta[key] == value, "delta identity " + key)
    require(delta["patch"] == {"path": "candidate.patch", **pin(members["candidate.patch"])}, "patch pin")
    require(isinstance(delta["files"], list) and len(delta["files"]) == len(ALLOWED_PATHS), "delta must have exactly two files")
    delta_rows = {}
    for row in delta["files"]:
        require(set(row) == {"path", "before", "after"} and row["path"] not in delta_rows, "delta row schema/duplicate")
        delta_rows[row["path"]] = {"before": row["before"], "after": row["after"]}
    require(delta_rows == CANDIDATE_PINS, "delta differs from independently bound two-leaf pins")
    before, after = {}, {}
    for path, pair in CANDIDATE_PINS.items():
        for side, destination in (("before", before), ("after", after)):
            raw = members[side + "/" + path]
            raw.decode("utf-8")
            require({"mode": "100644", **pin(raw)} == pair[side], "candidate member pin")
            destination[path] = raw
        require(pair["before"] == {"mode": "100644", **EXISTING_BASELINE_LEAF_PINS[path]},
                "candidate before is not the independently pinned existing source52 leaf")
        require(files[path] == {"path": path, **pair["after"]}, "candidate after/full source53 mismatch")
    old_rows = {row["path"]: row for row in old["changed_files"]}
    new_rows = {row["path"]: row for row in source["changed_files"]}
    old_slices = manifest_row_slices(old_raw)
    new_slices = manifest_row_slices(members["source53-manifest.json"])
    for path in old_files:
        require(old_files[path] == files[path] and old_rows[path] == new_rows[path]
                and old_slices[path] == new_slices[path], "any prior195 manifest row bytes or values changed: " + path)
    require(replay_patch(members["candidate.patch"], before) == after, "forward patch not exact")
    require(replay_patch(members["candidate.patch"], after, reverse=True) == before, "inverse patch not exact")
    leaves = existing_baseline_leaves_guard()
    return old_files, files, members, {
        "input_archive": {"path": INPUT_NAME, **pin(archive_raw)},
        "source52_manifest": {"path": SOURCE52_MANIFEST_NAME, **pin(old_raw)},
        "r29_original_failed_100_closure": r29_pins,
        "patch_forward_inverse_exact": True, "declared_paths": list(ALLOWED_PATHS),
        "prior_changed_file_count": SOURCE52_COUNT, "actual_changed_file_count": len(files),
        "before_existing_repo_leaves_not_in_prior_changed_manifest": True,
        "source52_original_changed_manifest_rows_unchanged": True,
        "source52_original_manifest_row_json_slices_byte_identical": True,
        "existing_baseline_leaves": leaves,
        "diagnostic_only": True, "behavior_repair_claimed": False,
    }


def run_git_phase(name, args):
    command = ["git", *args]
    write_json(R / (name + "-started.json"), {"command": command, "cwd": str(S), "started_unix": time.time()})
    start = time.time()
    monotonic_start = time.monotonic()
    wait_issue = None
    with (R / (name + "-stdout.log")).open("xb") as out, (R / (name + "-stderr.log")).open("xb") as err:
        child = subprocess.Popen(command, cwd=S, stdin=subprocess.DEVNULL, stdout=out, stderr=err)
        try:
            return_code = child.wait()
        except BaseException as error:
            wait_issue = repr(error)
            return_code = child.wait()
    ended = time.time()
    raw = {"schema": "hepta.source53-original-git-command-result.v1", "command": command, "cwd": str(S),
           "exit_code": return_code, "started_unix": start, "ended_unix": ended,
           "elapsed_seconds": time.monotonic() - monotonic_start, "wait_exception": wait_issue}
    # Store the true process result before reading/hashing logs or any postguard.
    write_json(R / (name + "-raw-process-result.json"), raw)
    require(wait_issue is None, "git phase wait exception retained")
    require(return_code == 0, name + " exited " + str(return_code))
    receipt = {**raw, "stdout": pin((R / (name + "-stdout.log")).read_bytes()), "stderr": pin((R / (name + "-stderr.log")).read_bytes())}
    write_json(R / (name + "-receipt.json"), receipt)
    return raw


def record_failure(error):
    failure = {"schema": "hepta.source53-apply-failure.v1", "status": "FAILED_NO_AUTOMATIC_RESTORE",
               "error": repr(error), "source_before_tree": SOURCE52_TREE,
               "expected_source_tree": EXPECTED_TREE, "complete_written": (R / "complete.json").exists(),
               "bazel_lock_update_executed": False, "rust_executed": False, "fix_fmt_executed": False,
               "inspection_errors": []}
    queries = {
        "actual_index_tree": ("write-tree",),
        "native_head": ("rev-parse", "HEAD"),
        "unstaged_paths": ("diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z"),
        "untracked_paths": ("ls-files", "--others", "--exclude-standard", "-z"),
    }
    for key, args in queries.items():
        try:
            data = git(*args)
            failure[key] = [part.decode() for part in data.split(b"\0") if part] if key.endswith("_paths") else data.decode().strip()
        except Exception as issue:
            failure["inspection_errors"].append({"item": key, "error": repr(issue)})
    for name, args in {
        "failure-worktree.patch": ("diff", "--no-ext-diff", "--no-textconv", "--binary"),
        "failure-index-from-source52.patch": ("diff", "--no-ext-diff", "--no-textconv", "--binary", "--cached", SOURCE52_TREE),
    }.items():
        try:
            raw = git(*args)
            write_new(R / name, raw)
            failure[name] = pin(raw)
        except Exception as issue:
            failure["inspection_errors"].append({"item": name, "error": repr(issue)})
    for path in LOCKS:
        try:
            failure[path] = pin((S / path).read_bytes())
        except Exception as issue:
            failure["inspection_errors"].append({"item": path, "error": repr(issue)})
    write_json(R / "failure.json", failure)
    announce({"phase": "source53-apply", "status": "failed", "failure": str(R / "failure.json")})


def main():
    check_bindings()
    require(S.is_dir() and not S.is_symlink(), "source directory unavailable")
    require(not R.exists(), "create-only apply evidence already exists")
    require(not (E / SOURCE53_MANIFEST_OUTPUT_NAME).exists(), "source53 output manifest already exists")
    old_files, files, members, inputs = load_inputs()
    R.mkdir(parents=True)
    try:
        write_json(R / "input-validation.json", inputs)
        for name, raw in members.items():
            write_new(R / "input" / safe_relative(name), raw)
        require(Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve() == S.resolve(), "wrong Git worktree")
        pre = source_guard(old_files, SOURCE52_TREE, SOURCE52_COMMIT, SOURCE52_COUNT)
        write_json(R / "pre-apply-source-guard.json", pre)
        require(pre["pass"] is True, "source52 complete preguard failed")
        patch_path = R / "input/candidate.patch"
        run_git_phase("apply-check", ["apply", "--check", str(patch_path)])
        recheck = source_guard(old_files, SOURCE52_TREE, SOURCE52_COMMIT, SOURCE52_COUNT)
        write_json(R / "immediately-before-apply-source-guard.json", recheck)
        require(recheck["pass"] is True and recheck["native_head"] == pre["native_head"], "source changed during preflight")
        run_git_phase("apply", ["apply", str(patch_path)])
        prestage = {"schema": "hepta.source53-prestage-guard.v1", "pass": False}
        prestage["index_tree"] = git("write-tree").decode().strip()
        prestage["native_head"] = git("rev-parse", "HEAD").decode().strip()
        prestage["unstaged_paths"] = git_paths("diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z")
        prestage["untracked_paths"] = git_paths("ls-files", "--others", "--exclude-standard", "-z")
        mismatches = []
        for path, expected in files.items():
            try:
                raw, mode = source_raw(path)
                require({"path": path, "mode": mode, **pin(raw)} == expected, "post-apply full raw mismatch")
            except Exception as error:
                mismatches.append({"path": path, "error": repr(error)})
        prestage["mismatches"] = mismatches
        prestage["cargo_lock_sha256"] = pin((S / LOCKS[0]).read_bytes())["sha256"]
        prestage["bazel_lock_sha256"] = pin((S / LOCKS[1]).read_bytes())["sha256"]
        prestage["pass"] = (
            prestage["index_tree"] == SOURCE52_TREE and prestage["native_head"] == FRAMEWORK_PARENT
            and set(prestage["unstaged_paths"]) == set(ALLOWED_PATHS)
            and not prestage["untracked_paths"] and not mismatches
            and prestage["cargo_lock_sha256"] == CARGO_LOCK_SHA256 and prestage["bazel_lock_sha256"] == BAZEL_LOCK_SHA256
        )
        write_json(R / "prestage-source-guard.json", prestage)
        require(prestage["pass"] is True, "post-apply prestage guard failed; source preserved")
        run_git_phase("stage-exact-paths", ["add", "--", *ALLOWED_PATHS])
        post = source_guard(files, EXPECTED_TREE, EXPECTED_COMMIT, EXPECTED_CHANGED_COUNT)
        post["schema"] = "hepta.source53-apply-postguard.v1"
        post["native_head_unchanged"] = post.get("native_head") == pre["native_head"]
        actual_tree = post.get("actual_tree")
        delta_paths = git_paths("diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--name-only", "-z", SOURCE52_TREE, actual_tree) if digest(actual_tree, 40) else []
        post["changed_from_source52_paths"] = delta_paths
        post["prior_changed_file_count"] = SOURCE52_COUNT
        post["before_existing_repo_leaves_not_in_prior_changed_manifest"] = True
        post["source52_original_changed_manifest_rows_unchanged"] = True
        post["diagnostic_only"] = True
        post["behavior_repair_claimed"] = False
        post["dependency_inputs_changed_paths"] = [path for path in delta_paths if path not in ALLOWED_PATHS]
        post["pass"] = post["pass"] and post["native_head_unchanged"] and set(delta_paths) == set(ALLOWED_PATHS) and not post["dependency_inputs_changed_paths"]
        post_raw = (json.dumps(post, sort_keys=True, indent=2) + "\n").encode()
        write_new(R / "post-apply-source-guard.json", post_raw)
        require(post["pass"] is True, "source53 postguard failed; source/index preserved")
        actual_patch = git("diff", "--no-ext-diff", "--no-textconv", "--binary", SOURCE52_TREE, EXPECTED_TREE)
        write_new(R / "actual-source52-to-source53.patch", actual_patch)
        manifest_raw = members["source53-manifest.json"]
        write_new(E / SOURCE53_MANIFEST_OUTPUT_NAME, manifest_raw)
        complete = {
            "schema": "hepta.source53-apply-complete.v1",
            "source_before_tree": SOURCE52_TREE, "source_before_commit": SOURCE52_COMMIT,
            "source_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT,
            "source_manifest": {"path": SOURCE53_MANIFEST_OUTPUT_NAME, **pin(manifest_raw)},
            "delta_manifest": {"path": "native-source53-apply/input/delta-manifest.json", **pin(members["delta-manifest.json"])},
            "source_postguard": {"path": "native-source53-apply/post-apply-source-guard.json", **pin(post_raw)},
            "source_guards_pass": True,
            "cargo_lock_sha256": CARGO_LOCK_SHA256, "bazel_lock_sha256": BAZEL_LOCK_SHA256,
            "prior_changed_file_count": SOURCE52_COUNT,
            "before_existing_repo_leaves_not_in_prior_changed_manifest": True,
            "source52_original_changed_manifest_rows_unchanged": True,
            "diagnostic_only": True, "behavior_repair_claimed": False,
            "actual_changed_file_count": post["actual_changed_file_count"],
            "changed_from_source52_paths": delta_paths,
            "dependency_inputs_changed_paths": [],
            "bazel_lock_update_executed": False, "rust_executed": False, "fix_fmt_executed": False,
            "inherited_lock_boundary": "The original source50 lock success is retained only for identical dependency inputs and unchanged raw locks through source51, source52 and source53; this is not a new lock invocation or Rust qualification.",
            "native_git_head": post["native_head"],
            "root_commit_mapping_is_tree_identity_not_checkout_claim": True,
        }
        write_json(R / "complete.json", complete)
        announce({"phase": "source53-apply", "status": "complete", "source_tree": EXPECTED_TREE, "complete": str(R / "complete.json")})
    except BaseException as error:
        try:
            record_failure(error)
        except BaseException as recording_error:
            try:
                write_json(R / "failure-recording-error.json", {"original_error": repr(error), "recording_error": repr(recording_error), "no_restore_attempted": True})
            except BaseException:
                pass
        raise


if __name__ == "__main__":
    main()
