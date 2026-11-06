"""Create an inert r26 artifact from the exact closed r24 runner; never run it."""
from pathlib import Path
import ast
import difflib
import hashlib
import json


ROOT = Path('/workspace/scratch/08f5efd48967')
OUT = ROOT / 'source51-native-gates-preparation'
BASE = ROOT / 'native-validation-results/r24-source50-bound-input/native-run-r24.py'
BASE_SHA = 'a5831d0af0f0eaec8905a2cd2a62cafc6b545885b8705dc509b87f4981aad0bf'
original_raw = BASE.read_bytes()
assert len(original_raw) == 31087 and hashlib.sha256(original_raw).hexdigest() == BASE_SHA
original = original_raw.decode()
text = original


def replace_once(old, new):
    global text
    assert text.count(old) == 1, old[:160]
    text = text.replace(old, new, 1)


def replace_function(name, new):
    global text
    tree = ast.parse(text)
    node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    lines = text.splitlines(keepends=True)
    old = ''.join(lines[node.lineno - 1:node.end_lineno])
    assert old.endswith('\n')
    replace_once(old, new.rstrip() + '\n')


replace_once('"""INERT source50 gate template. Review and bind actual post-lock identities first.\n\nThis runner NEVER applies a patch, stages files, updates dependencies, formats,\nor starts the workspace gate. The prior source49 FAIL remains a separate record.\n"""', '''"""INERT source51 r26 gate template. Bind the separately applied source first.

This runner never applies/stages a patch, updates dependencies, formats, or starts
the workspace gate. The source50 lock command remains a historical source50
result; inheritance requires an independently verified two-file Rust-only delta
and unchanged complete dependency inputs/dual locks. The original r24 FAIL is
retained, and every original project phase runs again on the frozen source51.
"""''')
replace_once('FROZEN = True', 'FROZEN = False')
for name, value in (
    ('EXPECTED_COMMIT', "'1fdd647b0ecb235530e8b88bbea45b3d3762906f'"),
    ('EXPECTED_TREE', "'ea48acf562499192a25e05ae28926a32632dee62'"),
    ('EXPECTED_CHANGED_COUNT', '194'),
    ('SOURCE_MANIFEST_NAME', "'native-candidate-r24-source.json'"),
    ('SOURCE_MANIFEST_SHA256', "'ba7515c75980451e0b2514bce338b0ada8847daeef5ace5deacf45ca02e940c0'"),
):
    replace_once(name + ' = ' + value, name + ' = None')
replace_once('PREFIX = "native-source50-project-r24"', 'PREFIX = "native-source51-project-r26"')
replace_once('PYTHON_TEST_COUNT = 32', '''# All future apply/source51 identities remain explicitly unbound.
APPLY_COMPLETE_NAME = None
APPLY_COMPLETE_SHA256 = None
APPLY_COMPLETE_BYTES = None
APPLY_TERMINAL_NAME = None
APPLY_TERMINAL_SHA256 = None
APPLY_TERMINAL_BYTES = None
APPLY_JOB_ID = None
DELTA_MANIFEST_NAME = None
DELTA_MANIFEST_SHA256 = None
DELTA_MANIFEST_BYTES = None

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
PYTHON_TEST_COUNT = 32''')

replace_function('check_bindings', r'''
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
''')

lock_node = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == 'lock_prerequisite')
lock_lines = text.splitlines(keepends=True)
lock_old = ''.join(lock_lines[lock_node.lineno - 1:lock_node.end_lineno])
lock_new = lock_old.replace('EXPECTED_TREE', 'LOCK_SOURCE50_TREE').replace('EXPECTED_CHANGED_COUNT', 'LOCK_SOURCE50_CHANGED_COUNT')
lock_new = lock_new.replace('actual generated tree differs from reviewed root source', 'historical source50 generated tree mismatch')
replace_once(lock_old, lock_new)

replace_function('load_source', r'''
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
    require(source["cargo_lock_sha256"] == CARGO_LOCK_SHA256 and source["bazel_lock_sha256"] == BAZEL_LOCK_SHA256, "source51 dual-lock mismatch")
    files = normalized_files(source["changed_files"])
    require(len(files) == EXPECTED_CHANGED_COUNT, "actual source51 file count mismatch")
    require(set(files) == set(old_files), "two existing source paths must not add or remove manifest paths")
    return files, {"path": SOURCE_MANIFEST_NAME, **data_pin(raw)}, old_files, {"path": SOURCE50_MANIFEST_NAME, **data_pin(old_raw)}
''')

additional = r'''
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
    actual_paths = git_paths("diff", "--no-renames", "--name-only", "-z", LOCK_SOURCE50_TREE, EXPECTED_TREE)
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
    patch_raw = read_pinned(delta["patch"])
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
        "reviewed_delta_patch": delta["patch"],
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


'''
replace_once('def load_baseline():', additional + 'def load_baseline():')

replace_once('    files, source_pin = load_source(generated)', '''    files, source_pin, source50_files, source50_pin = load_source(generated)
    r24_failed_pins = r24_failed_prerequisite()
    apply_proof = apply_prerequisite(files, source_pin, source50_files)''')
replace_once('        "lock_originals_and_outer_terminal": lock_pins, "initial_source_guard": initial_pin,', '''        "source50_lock_originals_and_outer_terminal": lock_pins,
        "source50_root_manifest": source50_pin, "source51_apply": apply_proof,
        "original_r24_failed_100_provenance": r24_failed_pins,
        "source50_lock_inherited_only_for_unchanged_dependency_inputs": True,
        "source51_bazel_lock_update_executed": False,
        "initial_source_guard": initial_pin,''')
replace_once('        "previous_source49_workspace_result": "FAILED_100_20220_PASS_7_FAIL_1_TIMEOUT_130_REPORTED_SKIP",', '''        "previous_source49_workspace_result": "FAILED_100_20220_PASS_7_FAIL_1_TIMEOUT_130_REPORTED_SKIP",
        "previous_source50_project_result": "FAILED_100_1561_PASS_3_FAIL_0_TIMEOUT_3_REPORTED_SKIP",''')
text = text.replace('"hepta.source50-python-runner-readback.v1"', '"hepta.source51-python-runner-readback.v1"')
text = text.replace('"hepta.source50-four-package-closed-readback.v1"', '"hepta.source51-four-package-closed-readback.v1"')
text = text.replace('"hepta.source50-project-environment.v1"', '"hepta.source51-project-environment.v1"')
text = text.replace('"hepta.source50-project-preconditions.v1"', '"hepta.source51-project-preconditions.v1"')
text = text.replace('"hepta.source50-project-gates-complete.v1"', '"hepta.source51-project-gates-complete.v1"')
text = text.replace('"hepta.source50-project-orchestration-error.v1"', '"hepta.source51-project-orchestration-error.v1"')
replace_once('        "phase_receipts": receipts, "source_guards_pass": True,', '''        "phase_receipts": receipts, "source_guards_pass": True,
        "source50_lock_inherited_for_unchanged_dependency_inputs": True,
        "source51_bazel_lock_update_executed": False,
        "source51_apply_complete": apply_proof["complete"],''')

tree = ast.parse(text)
assert next(n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'FROZEN' for t in n.targets)).value.value is False
unknown = [n.targets[0].id for n in tree.body if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.Constant) and n.value.value is None]
assert len(unknown) == 15, unknown
original_functions = {n.name: ast.get_source_segment(original, n) for n in ast.parse(original).body if isinstance(n, ast.FunctionDef)}
new_functions = {n.name: ast.get_source_segment(text, n) for n in tree.body if isinstance(n, ast.FunctionDef)}
unchanged = sorted(name for name, body in original_functions.items() if new_functions.get(name) == body)
for name in ('run_phase', 'execution_environment', 'load_baseline', 'guard', 'source_file_pin', 'clean_lines'):
    assert name in unchanged, name
for name in ('review_python', 'review_tests'):
    assert new_functions[name].replace('hepta.source51-', 'hepta.source50-') == original_functions[name], name
raw = text.encode()
patch = ''.join(difflib.unified_diff(original.splitlines(keepends=True), text.splitlines(keepends=True), fromfile='closed-r24/native-run-r24.py', tofile='preparation/native-run-r26-template.py')).encode()
OUT.mkdir(parents=True, exist_ok=True)
for name, data in (
    ('reference-native-run-r24.py', original_raw),
    ('native-run-r26-template.py', raw),
    ('r24-r26-preparation.patch', patch),
):
    with (OUT / name).open('xb') as stream:
        stream.write(data)
report = {
    'schema': 'hepta.source51-r26-inert-preparation-readback.v1',
    'state': 'INERT_PENDING_SOURCE51_FREEZE_AND_APPLY_CLOSURE',
    'reference': {'bytes': len(original_raw), 'sha256': BASE_SHA},
    'template': {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()},
    'diff': {'bytes': len(patch), 'sha256': hashlib.sha256(patch).hexdigest()},
    'ast_parse_pass': True, 'frozen': False, 'unknown_bindings': unknown,
    'unchanged_whole_functions': unchanged,
    'schema_only_changes_in_functions': ['review_python', 'review_tests'],
    'phase_commands_and_run_phase_body_unchanged': True,
    'native_or_rust_executed': False,
    'source_apply_performed': False,
    'source50_lock_result_relabelled_as_source51': False,
}
with (OUT / 'PREPARATION-READBACK.json').open('x') as stream:
    json.dump(report, stream, indent=2); stream.write('\n')
print(json.dumps(report, indent=2))
