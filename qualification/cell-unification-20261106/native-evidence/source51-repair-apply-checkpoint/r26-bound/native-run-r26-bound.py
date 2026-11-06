"""INERT source51 r26 gate template. Bind the separately applied source first.

This runner never applies/stages a patch, updates dependencies, formats, or starts
the workspace gate. The source50 lock command remains a historical source50
result; inheritance requires an independently verified two-file Rust-only delta
and unchanged complete dependency inputs/dual locks. The original r24 FAIL is
retained, and every original project phase runs again on the frozen source51.
"""
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

FROZEN = False
EXPECTED_COMMIT = 'e28b0f385ee882f842911044958b2810f62f6379'
EXPECTED_TREE = '763c8d2b4089f6e9806c3bbb68fa247bc2f6af36'
EXPECTED_CHANGED_COUNT = 194
SOURCE_MANIFEST_NAME = 'native-candidate-r26-source.json'
SOURCE_MANIFEST_SHA256 = '74b7a35a77019ec90e42ec33dc0e81bbdbaca585541a028d57fffbe77c69a41a'
CARGO_LOCK_SHA256 = '4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c'
BAZEL_LOCK_SHA256 = 'e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb'
LOCK_INPUT_PINS = {'complete.json': {'bytes': 2292, 'sha256': '141820576f72e474b614a75b7414f1508575e636fca059b5593ab36ec05f8b7c'}, 'postguard.json': {'bytes': 1250, 'sha256': '835e143f4ebc54028640e25df8fef74e7fc3bf1a55caca4027e4e4c2ba7c20fe'}, 'generated-source.json': {'bytes': 52992, 'sha256': '7e5b9d8ba537cc527f94154ae405382ac4197e217d14a44a6c48d4e70099fe97'}, 'lock-update-raw-process-result.json': {'bytes': 384, 'sha256': '625775accc1f9507cb142f9b34a6d81aac05885ca4459b94eaf36b1d7e8839a8'}, 'lock-update-receipt.json': {'bytes': 777, 'sha256': 'dce6237eabf6c713e750dd6f6d5d8ac1336c98ab90a03a63b831a5cf0f503007'}, 'lock-update.log': {'bytes': 2808, 'sha256': '580619bbafa9c83e4d461572f7d138531b14d8cfb078be0933fc9467d8ebfff2'}, 'lock-update.resources.txt': {'bytes': 752, 'sha256': '95bc589bd25490158644c6c5eebae3f3e6a491be76565824b0fc0eb8cf7fc3bb'}}
LOCK_TERMINAL_NAME = 'native-source50-lock-update/terminal-process-status.json'
LOCK_TERMINAL_SHA256 = '9f983f56f14016b31725f9bb75dc8b4c8772a3e69581b7387afa5fdaaddfeda0'
LOCK_TERMINAL_BYTES = 729
LOCK_JOB_ID = '1a1b16cb87c-fc05-7898'
BASELINE_NAME = 'source50-four-package-r23-baseline.json'

T = Path("/home/alex/work/hepta-cell-unified-20261106-a")
S = T / "source"
E = T / "evidence"
LOCK_DIRECTORY = E / "native-source50-lock-update"
FRAMEWORK_PARENT = "bef6fa7645df9df12b69fda499e97eed25de6c75"
PREFIX = "native-source51-project-r26"
PACKAGES = [
    "codex-cli", "codex-exec-server", "codex-network-proxy",
    "codex-external-agent-migration",
]
LOCK_FILES = ("codex-rs/Cargo.lock", "MODULE.bazel.lock")
LOCK_EVIDENCE_FILES = (
    "complete.json", "postguard.json", "generated-source.json",
    "lock-update-raw-process-result.json", "lock-update-receipt.json",
    "lock-update.log", "lock-update.resources.txt",
)
BASELINE_SHA256 = "6feba9a285f77f16fc1d34710d2737eae78a4ba3be74affd40f5703bc8ce405e"
BASELINE_BYTES = 277789
BASELINE_COUNT = 1564
PREVIOUS_SOURCE49_COMMIT = "50dd4bedefcd1b8e2e8cd5cf5023c60a86d38d0a"
PREVIOUS_SOURCE49_TREE = "be34ab1afe622ad3b8f030c8c5018f4f54fbc304"
# All future apply/source51 identities remain explicitly unbound.
APPLY_COMPLETE_NAME = 'native-source51-apply/complete.json'
APPLY_COMPLETE_SHA256 = '9e295dd805964c19f283a8a43c803844ee0470f7105d67fa01dc4b7f2e81f3ff'
APPLY_COMPLETE_BYTES = 1898
APPLY_TERMINAL_NAME = 'native-source51-apply/terminal-process-status.json'
APPLY_TERMINAL_SHA256 = '643fcba8ca0fd15bbff9afe41bbb3c16cd767a4ab70fce27f929d31921c0b1bf'
APPLY_TERMINAL_BYTES = 729
APPLY_JOB_ID = '1a1b1ae7f60-fc05-7a41'
DELTA_MANIFEST_NAME = 'native-source51-apply/input/delta-manifest.json'
DELTA_MANIFEST_SHA256 = 'b0a7085b6731978cea2614ff9660c2b47e9c0a0ac5228c5b96694c62ba56a74d'
DELTA_MANIFEST_BYTES = 1583

LOCK_SOURCE50_COMMIT = "1fdd647b0ecb235530e8b88bbea45b3d3762906f"
LOCK_SOURCE50_TREE = "ea48acf562499192a25e05ae28926a32632dee62"
LOCK_SOURCE50_CHANGED_COUNT = 194
SOURCE50_MANIFEST_NAME = "native-candidate-r24-source.json"
SOURCE50_MANIFEST_BYTES = 53832
SOURCE50_MANIFEST_SHA256 = "ba7515c75980451e0b2514bce338b0ada8847daeef5ace5deacf45ca02e940c0"
ALLOWED_SOURCE51_DELTA = (
    "codex-rs/exec-server/tests/common/fake_bwrap.rs",
    "codex-rs/network-proxy/src/http_proxy.rs",
)
R24_JOB_ID = "1a1b17f112c-fc05-792a"
R24_FAILURE_PINS = {
    "native-source50-project-r24-terminal-process-status.json": {
        "bytes": 730, "sha256": "644e58b095e57c8b037cb282aa1da04f50501cb04b7c3f472d18e48272cda14f",
    },
    "native-source50-project-r24-tests-raw-process-result.json": {
        "bytes": 637, "sha256": "052f63cb18e5fb4ff97004286a336ada1437ac7484826895c059497fb139125c",
    },
    "native-source50-project-r24-tests-receipt.json": {
        "bytes": 2314, "sha256": "cfd55b78649de4920ea9a3307b1fdfd6f9674b757cf39586cfa45bcee927e3af",
    },
    "native-source50-project-r24-tests-source-post-verification.json": {
        "bytes": 633, "sha256": "5188c63a461f0f3f0a11a3c238b2df7aceb97f8f599c48e53dba15514d358728",
    },
}
PYTHON_TEST_COUNT = 32
MIN_FREE_BYTES = 20 * 1024**3
ANSI = re.compile(rb"\x1b\[[0-?]*[ -/]*[@-~]")
FILE_KEYS = ("path", "bytes", "sha256", "git_blob", "mode")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def data_pin(raw):
    return {
        "bytes": len(raw), "sha256": sha(raw),
        "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
    }


def safe_relative(value):
    require(isinstance(value, str) and bool(value), "missing relative path binding")
    path = PurePosixPath(value)
    require(not path.is_absolute() and ".." not in path.parts, "unsafe evidence/source path")
    return path


def hex_digest(value, width):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{" + str(width) + r"}", value) is not None



def check_bindings():
    # Preparation and missing-input barriers are not removable with Python -O.
    require(FROZEN is True, "INERT PREPARATION: no gate may execute")
    require(sys.flags.optimize == 0, "optimized Python is not an approved executor")
    require(os.environ.get("PYTHONOPTIMIZE") in (None, "", "0"), "optimized child Python is not approved")
    require(hex_digest(EXPECTED_COMMIT, 40) and hex_digest(EXPECTED_TREE, 40), "actual source51 identity missing")
    require(EXPECTED_COMMIT != LOCK_SOURCE50_COMMIT and EXPECTED_TREE != LOCK_SOURCE50_TREE, "new source identity was not bound")
    require(type(EXPECTED_CHANGED_COUNT) is int and EXPECTED_CHANGED_COUNT > 0, "actual source51 changed count missing")
    for value in (
        SOURCE_MANIFEST_SHA256, CARGO_LOCK_SHA256, BAZEL_LOCK_SHA256,
        LOCK_TERMINAL_SHA256, APPLY_COMPLETE_SHA256, APPLY_TERMINAL_SHA256,
        DELTA_MANIFEST_SHA256,
    ):
        require(hex_digest(value, 64), "actual source/dual-lock/apply/terminal hash missing")
    for name in (
        SOURCE_MANIFEST_NAME, LOCK_TERMINAL_NAME, BASELINE_NAME,
        APPLY_COMPLETE_NAME, APPLY_TERMINAL_NAME, DELTA_MANIFEST_NAME,
    ):
        safe_relative(name)
        require(not name.startswith(PREFIX + "-"), "input name collides with create-only output prefix")
    for value in (LOCK_TERMINAL_BYTES, APPLY_COMPLETE_BYTES, APPLY_TERMINAL_BYTES, DELTA_MANIFEST_BYTES):
        require(type(value) is int and value > 0, "actual closure byte count missing")
    for value in (LOCK_JOB_ID, APPLY_JOB_ID):
        require(isinstance(value, str) and bool(value), "actual closed job ID missing")
    require(APPLY_JOB_ID not in (LOCK_JOB_ID, R24_JOB_ID), "apply job identity reused")
    require(isinstance(LOCK_INPUT_PINS, dict) and set(LOCK_INPUT_PINS) == set(LOCK_EVIDENCE_FILES), "seven source50 lock input pins required")
    for name, expected in LOCK_INPUT_PINS.items():
        require(type(expected["bytes"]) is int and expected["bytes"] >= 0, "lock input size missing: " + name)
        require(hex_digest(expected["sha256"], 64), "lock input hash missing: " + name)


def write_json(name, value):
    raw = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()
    path = E / safe_relative(name)
    with path.open("xb") as output:
        output.write(raw)
    return {"path": name, **data_pin(raw)}


def announce(value):
    try:
        print(json.dumps(value), flush=True)
    except OSError:
        pass


def git(*args):
    return subprocess.check_output(["git", *args], cwd=S)


def git_paths(*args):
    return [raw.decode() for raw in git(*args).split(b"\0") if raw]


def normalized_files(entries):
    require(isinstance(entries, list), "source files must be a list")
    result = {}
    for entry in entries:
        row = {key: entry[key] for key in FILE_KEYS}
        safe_relative(row["path"])
        require(row["mode"] in ("100644", "100755"), "unsupported source mode")
        require(row["path"] not in result, "duplicate source path")
        result[row["path"]] = row
    return result


def source_file_pin(path):
    relative = safe_relative(path)
    target = S / relative
    require(target.is_file() and not target.is_symlink(), "source is not a regular file: " + path)
    raw = target.read_bytes()
    record = git("ls-tree", "-z", EXPECTED_TREE, "--", path).rstrip(b"\0")
    header, actual_path = record.split(b"\t", 1)
    mode, kind, blob = header.decode().split()
    actual = data_pin(raw)
    actual_mode = "100755" if target.stat().st_mode & 0o111 else "100644"
    require(actual_path.decode() == path and kind == "blob", "tree path/type mismatch")
    require(mode == actual_mode and blob == actual["git_blob"], "worktree/index source identity mismatch")
    return {"path": path, **actual, "mode": mode}


def guard(files):
    result = {
        "expected_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT,
        "changed_file_count": len(files), "pass": False,
    }
    try:
        result["actual_tree"] = git("write-tree").decode().strip()
        result["native_head"] = git("rev-parse", "HEAD").decode().strip()
        result["unstaged_paths"] = git_paths("diff", "--name-only", "-z")
        result["untracked_paths"] = git_paths("ls-files", "--others", "--exclude-standard", "-z")
        actual_paths = git_paths("diff", "--no-renames", "--name-only", "-z", FRAMEWORK_PARENT, EXPECTED_TREE)
        result["changed_path_set_matches"] = set(actual_paths) == set(files) and len(actual_paths) == len(files)
        mismatches = []
        for path, expected in files.items():
            try:
                if source_file_pin(path) != expected:
                    mismatches.append({"path": path, "error": "raw/Git/mode mismatch"})
            except Exception as error:
                mismatches.append({"path": path, "error": repr(error)})
        result["file_mismatches"] = mismatches
        result["cargo_lock_sha256"] = sha((S / LOCK_FILES[0]).read_bytes())
        result["bazel_lock_sha256"] = sha((S / LOCK_FILES[1]).read_bytes())
        result["pass"] = (
            result["actual_tree"] == EXPECTED_TREE
            and not result["unstaged_paths"] and not result["untracked_paths"]
            and not mismatches and result["changed_path_set_matches"]
            and result["cargo_lock_sha256"] == CARGO_LOCK_SHA256
            and result["bazel_lock_sha256"] == BAZEL_LOCK_SHA256
        )
    except Exception as error:
        result["guard_error"] = repr(error)
    return result


def lock_prerequisite():
    originals = {}
    pins = []
    for name in LOCK_EVIDENCE_FILES:
        raw = (LOCK_DIRECTORY / name).read_bytes()
        expected = LOCK_INPUT_PINS[name]
        require(len(raw) == expected["bytes"] and sha(raw) == expected["sha256"], "lock original pin mismatch: " + name)
        originals[name] = raw
        pins.append({"path": "native-source50-lock-update/" + name, **data_pin(raw)})
    raw_result = json.loads(originals["lock-update-raw-process-result.json"])
    receipt = json.loads(originals["lock-update-receipt.json"])
    post = json.loads(originals["postguard.json"])
    complete = json.loads(originals["complete.json"])
    generated = json.loads(originals["generated-source.json"])
    require(raw_result["schema"] == "hepta.original-command-raw-result.v1", "lock raw schema mismatch")
    for value in (raw_result, receipt):
        require(value["exit_code"] == 0, "original lock command did not pass")
        require(value["command"] == ["just", "bazel-lock-update"] and value["cwd"] == str(S), "wrong original lock command")
    for key in ("command", "cwd", "source_tree_before_command", "exit_code", "started_unix", "ended_unix", "elapsed_seconds"):
        require(raw_result[key] == receipt[key], "lock raw/receipt mismatch: " + key)
    require(receipt["ended_unix"] >= receipt["started_unix"], "invalid lock time order")
    require(abs(receipt["elapsed_seconds"] - (receipt["ended_unix"] - receipt["started_unix"])) < 1e-6, "lock elapsed mismatch")
    require(receipt["log"] == data_pin(originals["lock-update.log"]), "lock log receipt mismatch")
    require(receipt["resources"] == data_pin(originals["lock-update.resources.txt"]), "lock resource receipt mismatch")
    require(re.findall(rb"^\s*Exit status: ([0-9]+)\s*$", originals["lock-update.resources.txt"], re.M) == [b"0"], "lock resource exit mismatch")
    require(complete["status"] == "LOCK_UPDATE_PASSED_SOURCE_FREEZE_PENDING", "unexpected closed lock status")
    require(complete["receipt"] == receipt and complete["postguard"] == post, "closed lock embedded originals differ")
    require(post["schema"] == "hepta.source50-lock-postguard.v1" and post["guard_pass"] is True, "lock postguard failed")
    require(post["generated_source_tree"] == LOCK_SOURCE50_TREE, "historical source50 generated tree mismatch")
    require(post["actual_changed_file_count"] == LOCK_SOURCE50_CHANGED_COUNT, "actual generated count mismatch")
    require(set(post["working_tree_changed_paths"]) <= set(LOCK_FILES), "unexpected generated lock path")
    require(generated["schema"] == "hepta.source50-generated-lock-source.v1", "generated source schema mismatch")
    require(generated["source_tree"] == LOCK_SOURCE50_TREE and generated["source_commit"] is None, "generated original identity mismatch")
    require(generated["root_source_identity_freeze_pending"] is True, "original generated snapshot was rewritten")
    require(generated["provisional_before_lock_tree"] == raw_result["source_tree_before_command"], "lock before tree mismatch")
    require(post["source_tree_index_before_lock_stage"] == generated["provisional_before_lock_tree"], "lock index provenance mismatch")
    require(generated["cargo_lock_sha256"] == CARGO_LOCK_SHA256 and generated["bazel_lock_sha256"] == BAZEL_LOCK_SHA256, "generated dual-lock mismatch")
    for path, expected_sha in zip(LOCK_FILES, (CARGO_LOCK_SHA256, BAZEL_LOCK_SHA256)):
        require(post["locks"][path]["after"] == data_pin((S / path).read_bytes()), "lock postguard bytes mismatch")
        require(post["locks"][path]["after"]["sha256"] == expected_sha, "bound lock mismatch")
    for value in (post, complete):
        require(value["rust_tests_started"] is False and value["fix_fmt_executed"] is False, "lock snapshot phase confusion")
    terminal_raw = (E / safe_relative(LOCK_TERMINAL_NAME)).read_bytes()
    require(len(terminal_raw) == LOCK_TERMINAL_BYTES and sha(terminal_raw) == LOCK_TERMINAL_SHA256, "lock outer terminal pin mismatch")
    terminal = json.loads(terminal_raw)
    require(terminal["job_id"] == LOCK_JOB_ID and terminal["state"] == "succeeded" and terminal["exit_code"] == 0, "lock outer did not naturally succeed")
    for key in ("timed_out", "cancelled", "automatic_retry"):
        require(terminal[key] is False, "lock outer state invalid: " + key)
    for key in ("output_complete", "output_durable", "terminal_publication_confirmed"):
        require(terminal[key] is True, "lock terminal output incomplete: " + key)
    require(terminal["at_unix_ms"] / 1000 >= receipt["ended_unix"], "lock terminal precedes command end")
    pins.append({"path": LOCK_TERMINAL_NAME, **data_pin(terminal_raw)})
    return generated, pins



def load_source(generated):
    old_raw = (E / SOURCE50_MANIFEST_NAME).read_bytes()
    require(len(old_raw) == SOURCE50_MANIFEST_BYTES and sha(old_raw) == SOURCE50_MANIFEST_SHA256, "historical source50 root manifest mismatch")
    old = json.loads(old_raw)
    require(old["source_tree"] == LOCK_SOURCE50_TREE and old["source_commit"] == LOCK_SOURCE50_COMMIT, "historical source50 root identity mismatch")
    require(old["cargo_lock_sha256"] == CARGO_LOCK_SHA256 and old["bazel_lock_sha256"] == BAZEL_LOCK_SHA256, "source50 dual-lock mismatch")
    old_files = normalized_files(old["changed_files"])
    require(len(old_files) == LOCK_SOURCE50_CHANGED_COUNT, "historical source50 count mismatch")
    require(old_files == normalized_files(generated["changed_files"]), "source50 root manifest differs from original lock-generated source")

    raw = (E / safe_relative(SOURCE_MANIFEST_NAME)).read_bytes()
    require(sha(raw) == SOURCE_MANIFEST_SHA256, "actual source51 manifest hash mismatch")
    source = json.loads(raw)
    require(source["source_tree"] == EXPECTED_TREE and source["source_commit"] == EXPECTED_COMMIT, "root-frozen source51 identity mismatch")
    require(source["source_parent_commit"] == LOCK_SOURCE50_COMMIT, "source51 root manifest parent mismatch")
    require(source["cargo_lock_sha256"] == CARGO_LOCK_SHA256 and source["bazel_lock_sha256"] == BAZEL_LOCK_SHA256, "source51 dual-lock mismatch")
    files = normalized_files(source["changed_files"])
    require(len(files) == EXPECTED_CHANGED_COUNT, "actual source51 file count mismatch")
    require(set(files) == set(old_files), "two existing source paths must not add or remove manifest paths")
    return files, {"path": SOURCE_MANIFEST_NAME, **data_pin(raw)}, old_files, {"path": SOURCE50_MANIFEST_NAME, **data_pin(old_raw)}



def read_fixed(name, byte_count, digest):
    raw = (E / safe_relative(name)).read_bytes()
    require(len(raw) == byte_count and sha(raw) == digest, "fixed original mismatch: " + name)
    return raw, {"path": name, **data_pin(raw)}


def read_pinned(pin):
    require(isinstance(pin, dict) and set(pin) == {"path", "bytes", "sha256", "git_blob"}, "incomplete evidence pin")
    require(type(pin["bytes"]) is int and pin["bytes"] >= 0, "invalid evidence length")
    require(hex_digest(pin["sha256"], 64) and hex_digest(pin["git_blob"], 40), "invalid evidence digest")
    raw, actual = read_fixed(pin["path"], pin["bytes"], pin["sha256"])
    require(actual == pin, "evidence Git blob mismatch")
    return raw


def closed_terminal(raw, job_id, state, exit_code):
    terminal = json.loads(raw)
    require(terminal["job_id"] == job_id and terminal["state"] == state and terminal["exit_code"] == exit_code, "wrong natural outer terminal")
    for key in ("timed_out", "cancelled", "automatic_retry"):
        require(terminal[key] is False, "outer state invalid: " + key)
    for key in ("output_complete", "output_durable", "terminal_publication_confirmed"):
        require(terminal[key] is True, "outer evidence incomplete: " + key)
    require(all(value is False for value in terminal["log_truncated"].values()), "outer log truncated")
    require(all(value is None for value in terminal["log_errors"].values()), "outer log error")
    return terminal


def r24_failed_prerequisite():
    originals = {}
    pins = []
    for name, expected in R24_FAILURE_PINS.items():
        raw, pin = read_fixed(name, expected["bytes"], expected["sha256"])
        originals[name] = raw
        pins.append(pin)
    terminal = closed_terminal(
        originals["native-source50-project-r24-terminal-process-status.json"], R24_JOB_ID, "failed", 100,
    )
    raw_result = json.loads(originals["native-source50-project-r24-tests-raw-process-result.json"])
    receipt = json.loads(originals["native-source50-project-r24-tests-receipt.json"])
    post = json.loads(originals["native-source50-project-r24-tests-source-post-verification.json"])
    args = [value for package in PACKAGES for value in ("-p", package)]
    for value in (raw_result, receipt):
        require(value["phase"] == "tests" and value["exit_code"] == 100, "original r24 test failure changed")
        require(value["source_tree"] == LOCK_SOURCE50_TREE and value["source_commit"] == LOCK_SOURCE50_COMMIT, "r24 failure source mismatch")
        require(value["command"] == ["just", "test", "--locked", *args, "--retries", "0"], "r24 original command mismatch")
        require(value["cwd"] == str(S / "codex-rs"), "r24 cwd mismatch")
    for key in ("command", "cwd", "source_tree", "source_commit", "phase", "exit_code", "start_unix", "end_unix"):
        require(raw_result[key] == receipt[key], "r24 raw/receipt mismatch: " + key)
    require(receipt["effective_exit_code"] == 100 and receipt["phase_pass"] is False, "r24 failure qualification changed")
    require(receipt["raw_process_result"] == {"path": "native-source50-project-r24-tests-raw-process-result.json", **data_pin(originals["native-source50-project-r24-tests-raw-process-result.json"])}, "r24 raw receipt binding mismatch")
    require(receipt["source_postguard"] == {"path": "native-source50-project-r24-tests-source-post-verification.json", **data_pin(originals["native-source50-project-r24-tests-source-post-verification.json"])}, "r24 postguard binding mismatch")
    require(receipt["source_guards_pass"] is True and post["pass"] is True, "r24 source guard failed")
    require(post["actual_tree"] == post["expected_tree"] == LOCK_SOURCE50_TREE and post["source_commit"] == LOCK_SOURCE50_COMMIT, "r24 postguard source mismatch")
    require(post["changed_file_count"] == LOCK_SOURCE50_CHANGED_COUNT and post["gate_exit_code"] == 100, "r24 postguard count/exit mismatch")
    require(post["cargo_lock_sha256"] == CARGO_LOCK_SHA256 and post["bazel_lock_sha256"] == BAZEL_LOCK_SHA256, "r24 dual-lock mismatch")
    require(terminal["at_unix_ms"] / 1000 >= receipt["end_unix"], "r24 outer terminal precedes test end")
    return pins


def inherited_dependency_check(old_files, files, delta):
    require(delta["schema"] == "hepta.source51-apply-delta.v1", "unexpected source51 delta schema")
    require(delta["source_before_tree"] == LOCK_SOURCE50_TREE and delta["source_before_commit"] == LOCK_SOURCE50_COMMIT, "delta source50 parent mismatch")
    require(delta["source_tree"] == EXPECTED_TREE and delta["source_commit"] == EXPECTED_COMMIT, "delta source51 identity mismatch")
    actual_paths = git_paths("diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--name-only", "-z", LOCK_SOURCE50_TREE, EXPECTED_TREE)
    require(len(actual_paths) == len(ALLOWED_SOURCE51_DELTA) and set(actual_paths) == set(ALLOWED_SOURCE51_DELTA), "source51 Git tree delta is not the two reviewed Rust paths")
    delta_rows = delta["files"]
    require(isinstance(delta_rows, list) and len(delta_rows) == len(ALLOWED_SOURCE51_DELTA), "wrong delta row count")
    rows = {row["path"]: row for row in delta_rows}
    require(set(rows) == set(ALLOWED_SOURCE51_DELTA), "wrong or duplicate delta path")
    for path in ALLOWED_SOURCE51_DELTA:
        require(PurePosixPath(path).suffix == ".rs" and PurePosixPath(path).name != "build.rs", "dependency/build input cannot inherit a lock result")
        before = {"path": path, **rows[path]["before"]}
        after = {"path": path, **rows[path]["after"]}
        require(before == old_files[path] and after == files[path], "delta does not match complete source manifests")
        require(before["mode"] == after["mode"] and before["git_blob"] != after["git_blob"], "unexpected mode change or unchanged delta")
        for tree, expected in ((LOCK_SOURCE50_TREE, before), (EXPECTED_TREE, after)):
            record = git("ls-tree", "-z", tree, "--", path).rstrip(b"\0")
            header, actual_path = record.split(b"\t", 1)
            mode, kind, blob = header.decode().split()
            require(actual_path.decode() == path and kind == "blob" and mode == expected["mode"] and blob == expected["git_blob"], "delta Git tree entry mismatch")
            raw = git("cat-file", "blob", blob)
            require(data_pin(raw) == {key: expected[key] for key in ("bytes", "sha256", "git_blob")}, "delta Git raw bytes mismatch")
    for path in set(files) - set(ALLOWED_SOURCE51_DELTA):
        require(files[path] == old_files[path], "unreviewed manifest path changed: " + path)
    for path, digest in zip(LOCK_FILES, (CARGO_LOCK_SHA256, BAZEL_LOCK_SHA256)):
        before = git("show", LOCK_SOURCE50_TREE + ":" + path)
        after = git("show", EXPECTED_TREE + ":" + path)
        require(before == after and sha(before) == digest, "historical and new Git lock bytes differ")
    # The delta patch path is relative to its archived input directory.
    # Preserve the original delta bytes; derive an evidence-relative read pin.
    require(delta["patch"]["path"] == "candidate.patch", "unexpected delta patch member")
    resolved_patch_pin = {
        **delta["patch"],
        "path": str(safe_relative(DELTA_MANIFEST_NAME).parent / "candidate.patch"),
    }
    patch_raw = read_pinned(resolved_patch_pin)
    require(bool(patch_raw), "reviewed patch is empty")
    return {
        "schema": "hepta.source51-source50-lock-inheritance.v1",
        "lock_executed_for_source_commit": LOCK_SOURCE50_COMMIT,
        "lock_executed_for_source_tree": LOCK_SOURCE50_TREE,
        "current_source_commit": EXPECTED_COMMIT, "current_source_tree": EXPECTED_TREE,
        "actual_git_tree_changed_paths": actual_paths,
        "all_other_git_tree_entries_unchanged": True,
        "dependency_inputs_changed_paths": [], "git_modes_unchanged": True,
        "cargo_lock_sha256": CARGO_LOCK_SHA256, "bazel_lock_sha256": BAZEL_LOCK_SHA256,
        "source51_bazel_lock_update_executed": False,
        "inheritance_basis": "Exact two existing non-build Rust paths; all other Git tree entries and both raw locks are unchanged.",
        "reviewed_delta_patch": delta["patch"], "resolved_patch_evidence": resolved_patch_pin,
    }


def apply_prerequisite(files, source_pin, old_files):
    complete_raw, complete_pin = read_fixed(APPLY_COMPLETE_NAME, APPLY_COMPLETE_BYTES, APPLY_COMPLETE_SHA256)
    terminal_raw, terminal_pin = read_fixed(APPLY_TERMINAL_NAME, APPLY_TERMINAL_BYTES, APPLY_TERMINAL_SHA256)
    delta_raw, delta_pin = read_fixed(DELTA_MANIFEST_NAME, DELTA_MANIFEST_BYTES, DELTA_MANIFEST_SHA256)
    complete = json.loads(complete_raw)
    require(complete["schema"] == "hepta.source51-apply-complete.v1", "source51 apply complete schema mismatch")
    require(complete["source_before_tree"] == LOCK_SOURCE50_TREE and complete["source_before_commit"] == LOCK_SOURCE50_COMMIT, "apply parent mismatch")
    require(complete["source_tree"] == EXPECTED_TREE and complete["source_commit"] == EXPECTED_COMMIT, "apply new identity mismatch")
    require(complete["source_manifest"] == source_pin and complete["delta_manifest"] == delta_pin, "apply manifests not bound to current originals")
    require(complete["source_guards_pass"] is True and complete["actual_changed_file_count"] == len(files), "apply source/count guard failed")
    require(complete["cargo_lock_sha256"] == CARGO_LOCK_SHA256 and complete["bazel_lock_sha256"] == BAZEL_LOCK_SHA256, "apply dual-lock mismatch")
    require(len(complete["changed_from_source50_paths"]) == len(ALLOWED_SOURCE51_DELTA) and set(complete["changed_from_source50_paths"]) == set(ALLOWED_SOURCE51_DELTA), "apply changed path mismatch")
    require(complete["dependency_inputs_changed_paths"] == [], "apply changed dependency inputs")
    for key in ("bazel_lock_update_executed", "rust_executed", "fix_fmt_executed"):
        require(complete[key] is False, "apply-only phase scope changed: " + key)
    post_raw = read_pinned(complete["source_postguard"])
    post = json.loads(post_raw)
    require(post["schema"] == "hepta.source51-apply-postguard.v1" and post["pass"] is True, "apply postguard failed")
    require(post["actual_tree"] == EXPECTED_TREE and post["source_commit"] == EXPECTED_COMMIT, "apply postguard identity mismatch")
    require(post["actual_changed_file_count"] == len(files) and post["changed_path_set_matches"] is True, "apply postguard count/path mismatch")
    require(post["cargo_lock_sha256"] == CARGO_LOCK_SHA256 and post["bazel_lock_sha256"] == BAZEL_LOCK_SHA256, "apply postguard lock mismatch")
    for key in ("unstaged_paths", "untracked_paths", "file_mismatches"):
        require(post[key] == [], "apply postguard contains a mismatch: " + key)
    terminal = closed_terminal(terminal_raw, APPLY_JOB_ID, "succeeded", 0)
    if "ended_unix" in complete:
        require(terminal["at_unix_ms"] / 1000 >= complete["ended_unix"], "apply terminal precedes completion")
    inheritance = inherited_dependency_check(old_files, files, json.loads(delta_raw))
    return {
        "complete": complete_pin, "terminal": terminal_pin,
        "source_postguard": complete["source_postguard"], "delta_manifest": delta_pin,
        "source50_lock_inheritance": inheritance,
    }


def load_baseline():
    raw = (E / safe_relative(BASELINE_NAME)).read_bytes()
    require(len(raw) == BASELINE_BYTES and sha(raw) == BASELINE_SHA256, "1564-ID baseline pin mismatch")
    baseline = json.loads(raw)
    require(baseline["schema"] == "hepta.closed-four-package-executed-baseline.v1", "baseline schema mismatch")
    require(baseline["source_commit"] == PREVIOUS_SOURCE49_COMMIT and baseline["source_tree"] == PREVIOUS_SOURCE49_TREE, "baseline is not original source49")
    require(set(baseline["packages"]) == set(PACKAGES) and baseline["identity_key"] == ["binary", "name"], "baseline owner/key mismatch")
    ids = {(row["binary"], row["name"]) for row in baseline["test_ids"]}
    require(len(ids) == len(baseline["test_ids"]) == baseline["count"] == BASELINE_COUNT, "baseline duplicate/count mismatch")
    require(all(row["package"] in PACKAGES and row["binary"].split("::", 1)[0] == row["package"] for row in baseline["test_ids"]), "baseline package mismatch")
    return ids, {"path": BASELINE_NAME, **data_pin(raw)}


def execution_environment():
    env = os.environ.copy()
    env.update({
        "PATH": str(T / "bin") + ":/home/alex/.cargo/bin:" + env.get("PATH", ""),
        "RUSTUP_TOOLCHAIN": "1.96.0", "CARGO_BUILD_JOBS": "2",
        "CARGO_TARGET_DIR": str(T / "target"), "CARGO_NET_GIT_FETCH_WITH_CLI": "true",
        "NEXTEST_TEST_THREADS": "2", "PYTHONDONTWRITEBYTECODE": "1",
        "CARGO_PROFILE_TEST_DEBUG": "0", "CARGO_PROFILE_DEV_DEBUG": "0",
    })
    for key in ("CARGO_INCREMENTAL", "CARGO_BUILD_TARGET", "RUSTFLAGS"):
        env.pop(key, None)
    prerequisite_raw = (E / "agentd-prerequisite-env.json").read_bytes()
    for key, value in json.loads(prerequisite_raw).items():
        if key in ("RUSTY_V8_ARCHIVE", "RUSTY_V8_SRC_BINDING_PATH", "PROTOC", "PROTOC_INCLUDE", "DOTSLASH_CACHE"):
            env[key] = value
    keys = (
        "RUSTUP_TOOLCHAIN", "CARGO_BUILD_JOBS", "CARGO_TARGET_DIR", "CARGO_NET_GIT_FETCH_WITH_CLI",
        "NEXTEST_TEST_THREADS", "NEXTEST_PROFILE", "HEPTA_NEXTTEST_FULL_METADATA",
        "CARGO_PROFILE_TEST_DEBUG", "CARGO_PROFILE_DEV_DEBUG", "CARGO_INCREMENTAL",
        "CARGO_BUILD_TARGET", "RUSTFLAGS", "DOTSLASH_CACHE", "PYTHONOPTIMIZE",
    )
    return env, {key: env.get(key) for key in keys}, data_pin(prerequisite_raw)


def clean_lines(raw):
    offset = 0
    for number, line in enumerate(raw.splitlines(keepends=True), 1):
        yield number, offset, ANSI.sub(b"", line).decode("utf-8", "replace").rstrip("\r\n")
        offset += len(line)


def review_python(raw):
    lines = list(clean_lines(raw))
    summaries = [(n, o, text, re.fullmatch(r"\s*Ran ([0-9]+) tests? in ([0-9.]+)s\s*", text)) for n, o, text in lines]
    summaries = [(n, o, text, match) for n, o, text, match in summaries if match]
    ok = [(n, o, text) for n, o, text in lines if text.strip() == "OK"]
    skipped = [(n, o, text) for n, o, text in lines if re.search(r"\.\.\. skipped\b|^OK \(.*skipped=", text)]
    passed = len(summaries) == 1 and int(summaries[0][3][1]) == PYTHON_TEST_COUNT and len(ok) == 1 and not skipped
    return {
        "schema": "hepta.source51-python-runner-readback.v1",
        "log": data_pin(raw), "expected_test_count": PYTHON_TEST_COUNT,
        "reported_test_count": int(summaries[0][3][1]) if len(summaries) == 1 else None,
        "summary_lines": [{"line": n, "byte_offset": o, "text": text} for n, o, text, _ in summaries],
        "ok_lines": [{"line": n, "byte_offset": o, "text": text} for n, o, text in ok],
        "skip_lines": [{"line": n, "byte_offset": o, "text": text} for n, o, text in skipped],
        "reported_skipped": 0 if passed else None, "pass": passed,
    }


def review_tests(raw, baseline):
    lines = list(clean_lines(raw))
    starts = [(n, o, text, re.match(r"^\s*Starting ([0-9]+) tests?\b", text)) for n, o, text in lines]
    starts = [(n, o, text, m) for n, o, text, m in starts if m]
    summaries = [(n, o, text, re.match(r"^\s*Summary\s+\[\s*([0-9.]+)s\]\s+([0-9]+) tests? run:\s*(.*)$", text)) for n, o, text in lines]
    summaries = [(n, o, text, m) for n, o, text, m in summaries if m]
    require(len(starts) == len(summaries) == 1, "complete nextest Starting/Summary required")
    start, summary = starts[0], summaries[0]
    require(start[0] < summary[0], "invalid nextest event order")
    row_pattern = re.compile(r"^\s*(PASS|FAIL|TIMEOUT)\s+\[\s*([0-9.]+)s\]\s+(\S+)\s+(.+)$")
    rows = []
    footer_rows = []
    for number, offset, text in lines:
        match = row_pattern.match(text)
        if not match:
            continue
        row = {"status": match[1], "seconds": float(match[2]), "binary": match[3], "name": match[4].strip(),
               "line": number, "byte_offset": offset}
        if start[0] < number < summary[0]:
            rows.append(row)
        elif number > summary[0]:
            footer_rows.append(row)
    current = {(row["binary"], row["name"]): row for row in rows}
    counts = {status: sum(row["status"] == status for row in rows) for status in ("PASS", "FAIL", "TIMEOUT")}
    tail = summary[3][3]
    def summary_count(label):
        match = re.search(r"\b([0-9]+) " + label + r"\b", tail)
        return int(match[1]) if match else 0
    expected_counts = {"PASS": summary_count("passed"), "FAIL": summary_count("failed"), "TIMEOUT": summary_count("timed out")}
    reported_skipped = summary_count("skipped")
    missing = sorted(baseline - set(current))
    unsuccessful = sorted(identity for identity in baseline & set(current) if current[identity]["status"] != "PASS")
    unexpected_packages = sorted({row["binary"].split("::", 1)[0] for row in rows} - set(PACKAGES))
    passed = (
        len(rows) == len(current) == int(start[3][1]) == int(summary[3][2])
        and bool(rows) and counts == expected_counts
        and counts["FAIL"] == counts["TIMEOUT"] == 0
        and not missing and not unsuccessful and not unexpected_packages
    )
    review = {
        "schema": "hepta.source51-four-package-closed-readback.v1",
        "log": data_pin(raw), "starting": {"line": start[0], "byte_offset": start[1], "text": start[2]},
        "summary": {"line": summary[0], "byte_offset": summary[1], "text": summary[2], "seconds": float(summary[3][1])},
        "unique_test_count": len(current), "execution_rows": len(rows), "counts": counts,
        "summary_counts": expected_counts, "reported_skipped": reported_skipped,
        "skip_identities_inferred": False, "duplicate_execution_ids": len(rows) != len(current),
        "footer_rows_excluded": footer_rows, "baseline_count": len(baseline),
        "baseline_is_source49_previous_failure_population_not_previous_pass": True,
        "baseline_missing": [{"binary": b, "name": n} for b, n in missing],
        "baseline_not_pass": [{"binary": b, "name": n} for b, n in unsuccessful],
        "additional_test_ids": [{"binary": b, "name": n} for b, n in sorted(set(current) - baseline)],
        "unexpected_packages": unexpected_packages,
        "per_package": {package: {status: sum(row["binary"].split("::", 1)[0] == package and row["status"] == status for row in rows)
                                 for status in ("PASS", "FAIL", "TIMEOUT")} for package in PACKAGES},
        "baseline_used_as_filter": False, "pass": passed,
    }
    return rows, review


def run_phase(phase, command, cwd, env, files, baseline):
    stem = PREFIX + "-" + phase
    before = guard(files)
    write_json(stem + "-source-pre-verification.json", before)
    require(before["pass"], "source preguard failed before " + phase)
    require(shutil.disk_usage(T).free > MIN_FREE_BYTES, "insufficient free space before " + phase)
    log = E / (stem + ".log")
    resources = E / (stem + "-resources.txt")
    started = time.time()
    announce({"phase": phase + "-start", "source_tree": EXPECTED_TREE, "command": command, "cwd": str(cwd)})
    with log.open("xb") as output:
        process = subprocess.Popen(
            ["/usr/bin/time", "-v", "-o", str(resources), *command],
            cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT,
        )
        try:
            rc = process.wait()
        finally:
            # Never mutate/clean/retry while a Rust subprocess may still be alive.
            # No terminate/kill or added deadline is used by this runner.
            if process.poll() is None:
                rc = process.wait()
            else:
                rc = process.returncode
            ended = time.time()
            raw_result = {
                "schema": "hepta.native-raw-process-result.v1", "phase": phase,
                "source_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT,
                "command": command, "cwd": str(cwd), "start_unix": started, "end_unix": ended,
                "exit_code": rc, "log_and_resource_hashing_pending": True,
            }
            raw_pin = write_json(stem + "-raw-process-result.json", raw_result)
            announce({**raw_result, "event": phase + "-raw-process-return"})
    # The original return has already been durably recorded. Derived failure
    # never overwrites it, even if hashing, postguard or acceptance fails.
    issues = []
    log_raw = None
    resource_raw = None
    try:
        log_raw = log.read_bytes()
        resource_raw = resources.read_bytes()
        statuses = re.findall(rb"^\s*Exit status: ([0-9]+)\s*$", resource_raw, re.M)
        require(statuses == [str(rc).encode()], "resource/original process exit mismatch")
    except Exception as error:
        issues.append({"stage": "original_output_readback", "error": repr(error)})
    post = guard(files)
    post.update(phase=phase, gate_exit_code=rc)
    post_pin = write_json(stem + "-source-post-verification.json", post)
    if not post["pass"]:
        issues.append({"stage": "source_postguard", "error": "source/dual-lock guard failed; source retained"})
    acceptance = None
    if log_raw is not None and phase in ("python-runner", "tests"):
        try:
            if phase == "python-runner":
                review = review_python(log_raw)
            else:
                rows, review = review_tests(log_raw, baseline)
                write_json(stem + "-test-results.json", rows)
            acceptance = write_json(stem + "-result-review.json", review)
            if not review["pass"]:
                issues.append({"stage": "closed_log_acceptance", "error": "required original execution coverage/result not met"})
        except Exception as error:
            issues.append({"stage": "closed_log_parse", "error": repr(error)})
    effective = rc if rc else (1 if issues else 0)
    receipt = {
        "schema": "hepta.native-gate-receipt.v2", "phase": phase,
        "source_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT,
        "source_manifest": SOURCE_MANIFEST_NAME, "source_manifest_sha256": SOURCE_MANIFEST_SHA256,
        "environment_manifest": PREFIX + "-environment.json", "command": command, "cwd": str(cwd),
        "start_unix": started, "end_unix": ended, "elapsed_seconds": ended - started,
        "exit_code": rc, "effective_exit_code": effective, "raw_process_result": raw_pin,
        "log_sha256": sha(log_raw) if log_raw is not None else None,
        "resources_sha256": sha(resource_raw) if resource_raw is not None else None,
        "source_postguard": post_pin, "source_guards_pass": post["pass"],
        "packages": PACKAGES if phase != "python-runner" else [],
        "retries": 0 if phase == "tests" else None,
        "filters": "no_additions", "features": "unchanged_defaults",
        "acceptance_readback": acceptance, "issues": issues, "phase_pass": effective == 0,
        "fix_fmt_executed": False, "baseline_used_as_filter": False,
    }
    receipt_pin = write_json(stem + "-receipt.json", receipt)
    announce(receipt)
    return effective, receipt_pin


def run_frozen():
    # All outputs are create-only, including failed prerequisites.
    require(not list(E.glob(PREFIX + "-*")), "this run prefix already has evidence; no automatic retry")
    require(shutil.disk_usage(T).free > MIN_FREE_BYTES, "insufficient free space")
    generated, lock_pins = lock_prerequisite()
    files, source_pin, source50_files, source50_pin = load_source(generated)
    r24_failed_pins = r24_failed_prerequisite()
    apply_proof = apply_prerequisite(files, source_pin, source50_files)
    baseline, baseline_pin = load_baseline()
    initial = guard(files)
    initial_pin = write_json(PREFIX + "-source-pre-verification.json", initial)
    require(initial["pass"], "actual frozen source is not clean/byte-identical")
    env, selection, prerequisite_env_pin = execution_environment()
    write_json(PREFIX + "-environment.json", {
        "schema": "hepta.source51-project-environment.v1",
        "source_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT,
        "source_manifest": SOURCE_MANIFEST_NAME, "source_manifest_sha256": SOURCE_MANIFEST_SHA256,
        "selection": selection, "approved_prerequisite_env_pin": prerequisite_env_pin,
        "free_bytes_before": shutil.disk_usage(T).free,
        "source_environment_immutable_during_gates": True,
        "test_deadlines_features_filters_retries_unchanged": True,
        "sandbox_or_network_protection_environment_overridden": False,
    })
    write_json(PREFIX + "-preconditions.json", {
        "schema": "hepta.source51-project-preconditions.v1",
        "source_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT,
        "actual_changed_file_count": len(files), "source_manifest": source_pin,
        "cargo_lock_sha256": CARGO_LOCK_SHA256, "bazel_lock_sha256": BAZEL_LOCK_SHA256,
        "source50_lock_originals_and_outer_terminal": lock_pins,
        "source50_root_manifest": source50_pin, "source51_apply": apply_proof,
        "original_r24_failed_100_provenance": r24_failed_pins,
        "source50_lock_inherited_only_for_unchanged_dependency_inputs": True,
        "source51_bazel_lock_update_executed": False,
        "initial_source_guard": initial_pin,
        "baseline": baseline_pin, "baseline_use": "acceptance only after the full unfiltered gate",
        "previous_source49_workspace_result": "FAILED_100_20220_PASS_7_FAIL_1_TIMEOUT_130_REPORTED_SKIP",
        "previous_source50_project_result": "FAILED_100_1561_PASS_3_FAIL_0_TIMEOUT_3_REPORTED_SKIP",
        "patch_application_performed_by_this_runner": False,
        "lock_update_performed_by_this_runner": False,
        "expected_python_tests": PYTHON_TEST_COUNT,
    })
    args = [value for package in PACKAGES for value in ("-p", package)]
    phases = [
        ("python-runner", ["python3", "-m", "unittest", "discover", "-s", "scripts", "-p", "test_run_nextest*.py", "-v"], S),
        ("strict", ["just", "clippy", "--locked", *args, "--", "-D", "warnings"], S / "codex-rs"),
        ("tests", ["just", "test", "--locked", *args, "--retries", "0"], S / "codex-rs"),
    ]
    receipts = []
    for phase, command, cwd in phases:
        code, receipt_pin = run_phase(phase, command, cwd, env, files, baseline)
        receipts.append(receipt_pin)
        if code:
            write_json(PREFIX + "-incomplete.json", {
                "source_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT,
                "failed_phase": phase, "effective_exit_code": code, "completed_phase_receipts": receipts,
                "subsequent_phases_started": False, "source_retained": True,
                "workspace_started": False, "fix_fmt_executed": False,
            })
            return code
    final_guard = guard(files)
    write_json(PREFIX + "-source-final-verification.json", final_guard)
    require(final_guard["pass"], "final same-source guard failed")
    write_json(PREFIX + "-complete.json", {
        "schema": "hepta.source51-project-gates-complete.v1",
        "source_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT,
        "source_manifest": SOURCE_MANIFEST_NAME, "source_manifest_sha256": SOURCE_MANIFEST_SHA256,
        "cargo_lock_sha256": CARGO_LOCK_SHA256, "bazel_lock_sha256": BAZEL_LOCK_SHA256,
        "python_exit": 0, "python_tests": PYTHON_TEST_COUNT, "python_skipped": 0,
        "strict_exit": 0, "tests_exit": 0, "packages": PACKAGES,
        "required_old_ids": BASELINE_COUNT, "all_old_ids_observed_pass": True,
        "phase_receipts": receipts, "source_guards_pass": True,
        "source50_lock_inherited_for_unchanged_dependency_inputs": True,
        "source51_bazel_lock_update_executed": False,
        "source51_apply_complete": apply_proof["complete"],
        "workspace_not_started_by_this_runner": True, "fix_fmt_executed": False,
        "free_bytes_after": shutil.disk_usage(T).free,
        "whole_workspace_qualification": "PENDING_SEPARATE_ORIGINAL_GATE",
    })
    return 0


def main():
    check_bindings()  # False/None rejects before evidence writes or subprocesses.
    try:
        return run_frozen()
    except BaseException as error:
        path = E / (PREFIX + "-orchestration-error.json")
        if E.is_dir() and not path.exists():
            write_json(path.name, {
                "schema": "hepta.source51-project-orchestration-error.v1",
                "source_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT,
                "error_type": type(error).__name__, "error": str(error),
                "no_automatic_retry": True, "source_retained": True,
                "workspace_started": False, "fix_fmt_executed": False,
            })
        raise


if __name__ == "__main__":
    sys.exit(main())
