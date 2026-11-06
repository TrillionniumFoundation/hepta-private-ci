#!/usr/bin/env python3
"""INERT source50 -> source51 apply-only executor.

Only the native owner may bind and run this reviewed script. It runs no Rust,
dependency regeneration, formatter, workspace gate, or remote Git operation.
A failure preserves the actual source/index state; there is no automatic reset.
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

FROZEN = True
EXPECTED_COMMIT = 'e28b0f385ee882f842911044958b2810f62f6379'
EXPECTED_TREE = '763c8d2b4089f6e9806c3bbb68fa247bc2f6af36'
EXPECTED_CHANGED_COUNT = 194
INPUT_BYTES = 43449
INPUT_SHA256 = 'dc2f53ce98abf1e4d4c7172fd10fbf14815a1e33d26fda817932c60ed85b9357'
SOURCE51_MANIFEST_PIN = {'bytes': 55418, 'sha256': '74b7a35a77019ec90e42ec33dc0e81bbdbaca585541a028d57fffbe77c69a41a', 'git_blob': '09ad6990ac2eeec1eb7d21689eef7733a531f75b'}
DELTA_MANIFEST_PIN = {'bytes': 1583, 'sha256': 'b0a7085b6731978cea2614ff9660c2b47e9c0a0ac5228c5b96694c62ba56a74d', 'git_blob': 'cc51d64769a0d0664f9d1f46ee6e8a1e57307e14'}
CANDIDATE_PINS = {'codex-rs/exec-server/tests/common/fake_bwrap.rs': {'before': {'mode': '100644', 'bytes': 1635, 'sha256': 'ae37954afd591c387652cd8ea036a15f461dbad48946274bbca57be4bd1648de', 'git_blob': 'cc79362f7a8a3a44b0a93949d18494281511ec7b'}, 'after': {'mode': '100644', 'bytes': 1817, 'sha256': '83d3637f2648b967c70e2368c623fe0b84afe1cdf32860284d897923ad0dc1ca', 'git_blob': 'e74489437549cf2c61075fd893945cd78e34247c'}}, 'codex-rs/network-proxy/src/http_proxy.rs': {'before': {'mode': '100644', 'bytes': 69053, 'sha256': '7500b8820d7894da45ed4f444aca28573f1e5f9462f94c97ccb19019a0f6b430', 'git_blob': '50135c6cd4c426c3ec16d65d448c01a1fb776ddd'}, 'after': {'mode': '100644', 'bytes': 69092, 'sha256': 'f8b6cb1adf67ea828efb29f68e10fd97a30e379574c93374c2a88f5364153967', 'git_blob': '17220a242091325aa66bd4cdb3419cd3a30b09ed'}}}

T = Path("/home/alex/work/hepta-cell-unified-20261106-a")
S = T / "source"
E = T / "evidence"
R = E / "native-source51-apply"
INPUT_NAME = "source51-apply-input.tar.gz"
SOURCE51_MANIFEST_OUTPUT_NAME = "native-candidate-r26-source.json"
FRAMEWORK_PARENT = "bef6fa7645df9df12b69fda499e97eed25de6c75"
SOURCE50_COMMIT = "1fdd647b0ecb235530e8b88bbea45b3d3762906f"
SOURCE50_TREE = "ea48acf562499192a25e05ae28926a32632dee62"
SOURCE50_COUNT = 194
SOURCE50_MANIFEST_NAME = "native-candidate-r24-source.json"
SOURCE50_MANIFEST_PIN = {
    "bytes": 53832,
    "sha256": "ba7515c75980451e0b2514bce338b0ada8847daeef5ace5deacf45ca02e940c0",
    "git_blob": "2b6988709adfd80084a846688453ceafd3f4accf",
}
R24_TERMINAL_NAME = "native-source50-project-r24-terminal-process-status.json"
R24_TERMINAL_PIN = {
    "bytes": 730,
    "sha256": "644e58b095e57c8b037cb282aa1da04f50501cb04b7c3f472d18e48272cda14f",
    "git_blob": "bec33f505f774d6ed6056df873bb2dbf4b751c43",
}
R24_JOB_ID = "1a1b17f112c-fc05-792a"
CARGO_LOCK_SHA256 = "4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c"
BAZEL_LOCK_SHA256 = "e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb"
LOCKS = ("codex-rs/Cargo.lock", "MODULE.bazel.lock")
ALLOWED_PATHS = (
    "codex-rs/exec-server/tests/common/fake_bwrap.rs",
    "codex-rs/network-proxy/src/http_proxy.rs",
)
FILE_KEYS = ("path", "mode", "bytes", "sha256", "git_blob")
HUNK = re.compile(rb"@@ -([0-9]+)(?:,([0-9]+))? \+([0-9]+)(?:,([0-9]+))? @@[^\r\n]*\n")


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
    require(digest(EXPECTED_COMMIT, 40) and digest(EXPECTED_TREE, 40), "source51 identity unbound")
    require(EXPECTED_COMMIT != SOURCE50_COMMIT and EXPECTED_TREE != SOURCE50_TREE, "no new source identity")
    require(type(EXPECTED_CHANGED_COUNT) is int and EXPECTED_CHANGED_COUNT > 0, "source51 count unbound")
    require(type(INPUT_BYTES) is int and INPUT_BYTES > 0 and digest(INPUT_SHA256, 64), "input archive unbound")
    for expected in (SOURCE50_MANIFEST_PIN, R24_TERMINAL_PIN, SOURCE51_MANIFEST_PIN, DELTA_MANIFEST_PIN):
        validate_pin(expected)
    require(isinstance(CANDIDATE_PINS, dict) and set(CANDIDATE_PINS) == set(ALLOWED_PATHS), "two reviewed candidate bindings required")
    for path, row in CANDIDATE_PINS.items():
        safe_relative(path)
        require(path.endswith(".rs") and Path(path).name != "build.rs", "dependency/build input prohibited")
        require(set(row) == {"before", "after"}, "candidate binding shape")
        for side in ("before", "after"):
            require(isinstance(row[side], dict) and set(row[side]) == {"mode", "bytes", "sha256", "git_blob"}, "candidate pin shape")
            validate_pin({key: row[side][key] for key in ("bytes", "sha256", "git_blob")})
            require(row[side]["mode"] == "100644", "candidate mode change prohibited")
        require(row["before"] != row["after"], "candidate must be an actual change")
    for name in (INPUT_NAME, SOURCE50_MANIFEST_NAME, SOURCE51_MANIFEST_OUTPUT_NAME, R24_TERMINAL_NAME):
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
            and len(files) == expected_count == len(paths)
            and report["changed_path_set_matches"]
            and not report["unstaged_paths"] and not report["untracked_paths"] and not mismatches
            and report["cargo_lock_sha256"] == CARGO_LOCK_SHA256
            and report["bazel_lock_sha256"] == BAZEL_LOCK_SHA256
        )
    except Exception as error:
        report["error"] = repr(error)
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
    require(set(outputs) == set(ALLOWED_PATHS), "patch does not cover exactly two reviewed Rust paths")
    return outputs


def load_inputs():
    old_raw = (E / SOURCE50_MANIFEST_NAME).read_bytes()
    require(pin(old_raw) == SOURCE50_MANIFEST_PIN, "source50 manifest bytes changed")
    old = json.loads(old_raw)
    require(old["source_tree"] == SOURCE50_TREE and old["source_commit"] == SOURCE50_COMMIT, "source50 identity")
    old_files = normalized_files(old["changed_files"])
    require(len(old_files) == SOURCE50_COUNT and set(ALLOWED_PATHS) <= set(old_files), "source50 path set")
    terminal_raw = (E / R24_TERMINAL_NAME).read_bytes()
    require(pin(terminal_raw) == R24_TERMINAL_PIN, "r24 original terminal bytes changed")
    terminal = json.loads(terminal_raw)
    require(terminal["job_id"] == R24_JOB_ID and terminal["state"] == "failed" and terminal["exit_code"] == 100, "r24 did not close at original test failure")
    for key in ("timed_out", "cancelled", "automatic_retry"):
        require(terminal[key] is False, "r24 terminal flag " + key)
    for key in ("audit_recorded", "output_complete", "output_durable", "terminal_publication_confirmed"):
        require(terminal[key] is True, "r24 closure missing " + key)
    archive_raw = (T / INPUT_NAME).read_bytes()
    require(len(archive_raw) == INPUT_BYTES and pin(archive_raw)["sha256"] == INPUT_SHA256, "source51 archive pin")
    members = {}
    expected_members = {"delta-manifest.json", "source51-manifest.json", "candidate.patch"}
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
    require(set(members) == expected_members and len(members) == 7, "exact seven input members required")
    require(pin(members["source51-manifest.json"]) == SOURCE51_MANIFEST_PIN and pin(members["delta-manifest.json"]) == DELTA_MANIFEST_PIN, "new manifest pins")
    source = json.loads(members["source51-manifest.json"])
    require(source["source_tree"] == EXPECTED_TREE and source["source_commit"] == EXPECTED_COMMIT, "root source51 identity")
    require(source["source_parent_commit"] == SOURCE50_COMMIT, "source51 parent must be source50")
    files = normalized_files(source["changed_files"])
    require(len(files) == EXPECTED_CHANGED_COUNT and set(files) == set(old_files), "two existing-file edits cannot change full path set")
    for obj in (old, source):
        require(obj["cargo_lock_sha256"] == CARGO_LOCK_SHA256 and obj["bazel_lock_sha256"] == BAZEL_LOCK_SHA256, "manifest dual-lock identity")
    delta = json.loads(members["delta-manifest.json"])
    require(delta["schema"] == "hepta.source51-apply-delta.v1", "delta schema")
    for key, value in {"source_before_tree": SOURCE50_TREE, "source_before_commit": SOURCE50_COMMIT, "source_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT}.items():
        require(delta[key] == value, "delta identity " + key)
    require(delta["patch"] == {"path": "candidate.patch", **pin(members["candidate.patch"])}, "patch pin")
    require(isinstance(delta["files"], list) and len(delta["files"]) == 2, "delta must have two files")
    delta_rows = {}
    for row in delta["files"]:
        require(set(row) == {"path", "before", "after"} and row["path"] not in delta_rows, "delta row schema/duplicate")
        delta_rows[row["path"]] = {"before": row["before"], "after": row["after"]}
    require(delta_rows == CANDIDATE_PINS, "delta differs from independently bound candidate pins")
    before = {}
    after = {}
    for path, pair in CANDIDATE_PINS.items():
        for side, destination in (("before", before), ("after", after)):
            raw = members[side + "/" + path]
            raw.decode("utf-8")
            require({"mode": "100644", **pin(raw)} == pair[side], "candidate member pin")
            destination[path] = raw
        require(old_files[path] == {"path": path, **pair["before"]}, "candidate before/full source50 mismatch")
        require(files[path] == {"path": path, **pair["after"]}, "candidate after/full source51 mismatch")
    for path in old_files.keys() - set(ALLOWED_PATHS):
        require(old_files[path] == files[path], "unreviewed full-manifest change: " + path)
    require(replay_patch(members["candidate.patch"], before) == after, "forward patch not exact")
    require(replay_patch(members["candidate.patch"], after, reverse=True) == before, "inverse patch not exact")
    return old_files, files, members, {"input_archive": {"path": INPUT_NAME, **pin(archive_raw)},
                                    "source50_manifest": {"path": SOURCE50_MANIFEST_NAME, **pin(old_raw)},
                                    "r24_terminal": {"path": R24_TERMINAL_NAME, **pin(terminal_raw)},
                                    "patch_forward_inverse_exact": True, "declared_paths": list(ALLOWED_PATHS)}


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
    raw = {"schema": "hepta.source51-original-git-command-result.v1", "command": command, "cwd": str(S),
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
    failure = {"schema": "hepta.source51-apply-failure.v1", "status": "FAILED_NO_AUTOMATIC_RESTORE",
               "error": repr(error), "source_before_tree": SOURCE50_TREE,
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
        "failure-index-from-source50.patch": ("diff", "--no-ext-diff", "--no-textconv", "--binary", "--cached", SOURCE50_TREE),
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
    announce({"phase": "source51-apply", "status": "failed", "failure": str(R / "failure.json")})


def main():
    check_bindings()
    require(S.is_dir() and not S.is_symlink(), "source directory unavailable")
    require(not R.exists(), "create-only apply evidence already exists")
    require(not (E / SOURCE51_MANIFEST_OUTPUT_NAME).exists(), "source51 output manifest already exists")
    old_files, files, members, inputs = load_inputs()
    R.mkdir(parents=True)
    try:
        write_json(R / "input-validation.json", inputs)
        for name, raw in members.items():
            write_new(R / "input" / safe_relative(name), raw)
        require(Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve() == S.resolve(), "wrong Git worktree")
        pre = source_guard(old_files, SOURCE50_TREE, SOURCE50_COMMIT, SOURCE50_COUNT)
        write_json(R / "pre-apply-source-guard.json", pre)
        require(pre["pass"] is True, "source50 complete preguard failed")
        patch_path = R / "input/candidate.patch"
        run_git_phase("apply-check", ["apply", "--check", str(patch_path)])
        recheck = source_guard(old_files, SOURCE50_TREE, SOURCE50_COMMIT, SOURCE50_COUNT)
        write_json(R / "immediately-before-apply-source-guard.json", recheck)
        require(recheck["pass"] is True and recheck["native_head"] == pre["native_head"], "source changed during preflight")
        run_git_phase("apply", ["apply", str(patch_path)])
        prestage = {"schema": "hepta.source51-prestage-guard.v1", "pass": False}
        prestage["index_tree"] = git("write-tree").decode().strip()
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
            prestage["index_tree"] == SOURCE50_TREE and set(prestage["unstaged_paths"]) == set(ALLOWED_PATHS)
            and not prestage["untracked_paths"] and not mismatches
            and prestage["cargo_lock_sha256"] == CARGO_LOCK_SHA256 and prestage["bazel_lock_sha256"] == BAZEL_LOCK_SHA256
        )
        write_json(R / "prestage-source-guard.json", prestage)
        require(prestage["pass"] is True, "post-apply prestage guard failed; source preserved")
        run_git_phase("stage-exact-paths", ["add", "--", *ALLOWED_PATHS])
        post = source_guard(files, EXPECTED_TREE, EXPECTED_COMMIT, EXPECTED_CHANGED_COUNT)
        post["schema"] = "hepta.source51-apply-postguard.v1"
        post["native_head_unchanged"] = post.get("native_head") == pre["native_head"]
        actual_tree = post.get("actual_tree")
        delta_paths = git_paths("diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--name-only", "-z", SOURCE50_TREE, actual_tree) if digest(actual_tree, 40) else []
        post["changed_from_source50_paths"] = delta_paths
        post["dependency_inputs_changed_paths"] = [path for path in delta_paths if path not in ALLOWED_PATHS]
        post["pass"] = post["pass"] and post["native_head_unchanged"] and set(delta_paths) == set(ALLOWED_PATHS) and not post["dependency_inputs_changed_paths"]
        post_raw = (json.dumps(post, sort_keys=True, indent=2) + "\n").encode()
        write_new(R / "post-apply-source-guard.json", post_raw)
        require(post["pass"] is True, "source51 postguard failed; source/index preserved")
        actual_patch = git("diff", "--no-ext-diff", "--no-textconv", "--binary", SOURCE50_TREE, EXPECTED_TREE)
        write_new(R / "actual-source50-to-source51.patch", actual_patch)
        manifest_raw = members["source51-manifest.json"]
        write_new(E / SOURCE51_MANIFEST_OUTPUT_NAME, manifest_raw)
        complete = {
            "schema": "hepta.source51-apply-complete.v1",
            "source_before_tree": SOURCE50_TREE, "source_before_commit": SOURCE50_COMMIT,
            "source_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT,
            "source_manifest": {"path": SOURCE51_MANIFEST_OUTPUT_NAME, **pin(manifest_raw)},
            "delta_manifest": {"path": "native-source51-apply/input/delta-manifest.json", **pin(members["delta-manifest.json"])},
            "source_postguard": {"path": "native-source51-apply/post-apply-source-guard.json", **pin(post_raw)},
            "source_guards_pass": True,
            "cargo_lock_sha256": CARGO_LOCK_SHA256, "bazel_lock_sha256": BAZEL_LOCK_SHA256,
            "actual_changed_file_count": post["actual_changed_file_count"],
            "changed_from_source50_paths": delta_paths,
            "dependency_inputs_changed_paths": [],
            "bazel_lock_update_executed": False, "rust_executed": False, "fix_fmt_executed": False,
            "inherited_lock_boundary": "Source50 lock success is retained only for identical dependency inputs and unchanged raw locks; this is not a new lock invocation or Rust qualification.",
            "native_git_head": post["native_head"],
            "root_commit_mapping_is_tree_identity_not_checkout_claim": True,
        }
        write_json(R / "complete.json", complete)
        announce({"phase": "source51-apply", "status": "complete", "source_tree": EXPECTED_TREE, "complete": str(R / "complete.json")})
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
