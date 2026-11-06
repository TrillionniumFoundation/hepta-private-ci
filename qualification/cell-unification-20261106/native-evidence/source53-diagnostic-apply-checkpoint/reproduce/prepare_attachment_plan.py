"""Local evidence planning only; no native calls, Git operations or source writes."""
from pathlib import Path, PurePosixPath
import ast
import hashlib
import json

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent
SOURCE52 = "1e0910becc37383e6d17ecf861ea844fd07d8862"
TREE52 = "211f15baff19095e8c98bcea2b0ed99ca2270ade"
SOURCE53 = "f74be175de66a4b351cd239d39d98cd34fe9cc1b"
TREE53 = "440d4a8e09af4009e4d9ea067388826308da8803"
HEAD = "bef6fa7645df9df12b69fda499e97eed25de6c75"
CARGO = "4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c"
BAZEL = "e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb"
ATTEMPT = ROOT / "native-validation-results/source53-apply-attempt1-closed"


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def safe(name):
    p = PurePosixPath(name)
    assert name and not p.is_absolute() and ".." not in p.parts and "." not in p.parts
    assert p.as_posix() == name and "\\" not in name
    return name


def read(path, expected=None):
    path = Path(path)
    assert path.is_file() and not path.is_symlink()
    for parent in path.parents:
        assert not parent.is_symlink()
    raw = path.read_bytes()
    if expected:
        actual = pin(raw)
        for key in ("bytes", "sha256", "git_blob"):
            if key in expected:
                assert actual[key] == expected[key], (str(path), key)
    return raw


def obj(path, expected=None):
    return json.loads(read(path, expected))


def write(name, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    path = OUT / safe(name)
    with path.open("xb") as output:
        output.write(raw)
    return {"path": str(path.relative_to(ROOT)), **pin(raw)}


def terminal(value, job, state, code):
    assert value["job_id"] == job and value["state"] == state and value["exit_code"] == code
    assert value["output_complete"] and value["output_durable"] and value["terminal_publication_confirmed"]
    assert all(value[key] is False for key in ("timed_out", "cancelled", "automatic_retry"))


def verify_attempt1():
    receipt = obj(ATTEMPT / "LOCAL-READBACK.json", {"bytes": 21723, "sha256": "7b60502442fc1b658fdf52a77706bde6f9f0434dd7cf3f69c193c5fd8940ccfa"})
    assert len(receipt["files"]) == 26
    names = set()
    for entry in receipt["files"]:
        name = safe(entry["path"])
        assert name not in names
        names.add(name)
        read(ATTEMPT / name, entry)
    actual = {p.relative_to(ATTEMPT).as_posix() for p in ATTEMPT.rglob("*") if p.is_file()}
    assert actual == names | {"LOCAL-READBACK.json"}
    failed = obj(ATTEMPT / "source53ApplyStatusRaw.json")
    checked = obj(ATTEMPT / "source53ApplyGuardStatusRaw.json")
    terminal(failed, "1a1b24b6516-fc05-7d5f", "failed", 1)
    terminal(checked, "1a1b24e91df-fc05-7d75", "succeeded", 0)
    stderr, stdout = read(ATTEMPT / "stderr.log"), read(ATTEMPT / "stdout.log")
    assert len(stderr) == 1025 and not stdout
    assert b"FileNotFoundError" in stderr
    assert b"/home/alex/work/hepta-cell-unified-20261106-a/source53-apply-input.tar.gz" in stderr
    assert failed["log_bytes"]["stderr"]["stored"] == len(stderr)
    assert failed["log_bytes"]["stdout"]["stored"] == len(stdout)
    guard = obj(ATTEMPT / "native-source53-attempt1-unchanged52.json")
    assert guard["pass"] and guard["actual_tree"] == guard["expected_tree"] == TREE52
    assert guard["source_commit"] == SOURCE52 and guard["native_head"] == HEAD
    assert guard["actual_changed_file_count"] == guard["expected_count"] == 195
    assert guard["changed_path_set_matches"] and not guard["file_mismatches"]
    assert not guard["unstaged_paths"] and not guard["untracked_paths"]
    assert guard["cargo_lock_sha256"] == CARGO and guard["bazel_lock_sha256"] == BAZEL
    assert guard["apply_evidence_directory_exists"] is False
    assert guard["source53_output_manifest_exists"] is False
    assert guard["source_mutation_executed"] is False and guard["rust_executed"] is False
    source52 = obj(ROOT / "source53-apply-preparation/references/source52-actual-manifest.json")
    files = source52.get("changed_files", source52.get("files"))
    assert len(files) == 195
    assert set(guard["changed_paths"]) == {entry["path"] for entry in files}
    delta = obj(ROOT / "source53-apply-preparation/derived/delta-manifest.json")
    leaves = guard["existing_repo_leaves_outside_prior_changed_manifest"]
    assert leaves["before_existing_repo_leaves_not_in_prior_changed_manifest"] is True
    assert len(leaves["leaves"]) == 2
    expected_before = {entry["path"]: entry["before"] for entry in delta["files"]}
    for leaf in leaves["leaves"]:
        assert leaf["path"] in expected_before
        for key in ("bytes", "sha256", "git_blob"):
            assert leaf[key] == expected_before[leaf["path"]][key]
        assert leaf["actual_working_bytes_equal_existing_Git_leaf"] is True
        assert leaf["source_tree"] == TREE52 and leaf["mode"] == "100644"
    original_script = read(ROOT / "source53-apply-binding/native-source53-apply.py", {
        "bytes": 39810, "sha256": "5265e05a75c1aa4ba4eb36257a704306c17dc66ef78c2f7386a5beeb990b9168"}).decode()
    fn = {n.name: ast.get_source_segment(original_script, n) for n in ast.parse(original_script).body if isinstance(n, ast.FunctionDef)}
    assert fn["main"].index("load_inputs()") < fn["main"].index("R.mkdir(")
    assert "(T / INPUT_NAME).read_bytes()" in fn["load_inputs"]
    correct, wrong = receipt["corrected_input_file_info"], receipt["original_wrong_location_file_info"]
    expected_input = pin(read(ROOT / "source53-apply-preparation/derived/source53-apply-input.tar.gz"))
    for info in (correct, wrong):
        assert info["size"] == expected_input["bytes"] and info["sha256"] == expected_input["sha256"]
    assert correct["path"] == "/home/alex/work/hepta-cell-unified-20261106-a/source53-apply-input.tar.gz"
    assert wrong["path"] == "/home/alex/work/hepta-cell-unified-20261106-a/evidence/source53-apply-input.tar.gz"
    authorization = obj(ROOT / "source53-root-preparation/ROOT-APPLY-AUTHORIZATION-v2.json", {
        "bytes": 4079, "sha256": "700aaeb19a1f7e57c2a2aa64a72e5ba0571d0571d83d2f24525487b2bd36a6bc"})
    assert authorization["script_bytes_unchanged"] and authorization["correction_changes_only_input_placement"]
    assert authorization["unique_launch_key"] == "cell-source53-apply-only-20261106-v2"
    assert authorization["automatic_retry_or_restore_authorized"] is False
    return {
        "schema": "hepta.source53-attempt1-independent-closure.v1",
        "status": "PREPARATION_PATH_FAILURE_PRESERVED_SOURCE52_UNCHANGED",
        "all27_original_files_rehashed": True,
        "original_apply_job": failed["job_id"], "original_exit": 1,
        "original_stderr": {"path": "attempt1/stderr.log", **pin(stderr)},
        "original_stdout": {"path": "attempt1/stdout.log", **pin(stdout)},
        "failure_before_git_or_evidence_creation_confirmed_by_script_and_separate_guard": True,
        "read_only_guard_job": checked["job_id"], "read_only_guard_exit": 0,
        "source_commit": SOURCE52, "source_tree": TREE52, "changed_files": 195,
        "native_HEAD": HEAD, "dual_locks_unchanged": True,
        "all195_path_set_and_two_existing_before_leaf_pins_independently_checked": True,
        "wrong_E_copy_retained": True, "correct_T_input_exact_bytes_create_only_record_preserved": True,
        "corrected_attempt_authorized_but_no_result_in_this_initial_plan": True,
        "rust_gate_failed_by_this_event": False, "source_mutation_by_first_attempt": False,
        "diagnostic_only": True, "behavior_repair_claimed": False,
        "local_analysis_only": True, "native_or_rust_executed_by_this_reviewer": False,
    }


def main():
    attempt = verify_attempt1()
    attempt_pin = write("ATTEMPT1-INDEPENDENT-READBACK.json", attempt)
    group_dirs = [
        ("app-server-bedrock-r29-investigation", "causal-review"),
        ("app-server-bedrock-dispatch-r29-independent", "dispatch-review"),
        ("app-server-bedrock-r29-diagnostic-preparation", "diagnostic-candidate"),
        ("source53-native-diagnostic-review", "native-candidate-review"),
        ("source53-apply-preparation", "apply-preparation"),
        ("source53-apply-template-native-review", "apply-template-native-review"),
        ("source53-apply-binding", "apply-binding"),
        ("source53-apply-binding-independent-review", "apply-binding-independent-review"),
        ("source53-root-preparation", "root-registration-and-authorization"),
        ("native-validation-results/source53-apply-attempt1-closed", "attempt1"),
        ("source53-r30-independent-static-review", "r30-static-review"),
    ]
    entries = []
    for source_dir, destination_dir in group_dirs:
        directory = ROOT / source_dir
        for path in sorted(directory.rglob("*")):
            if "__pycache__" in path.parts:
                continue
            assert not path.is_symlink()
            if not path.is_file():
                continue
            relative = path.relative_to(directory).as_posix()
            raw = read(path)
            entries.append({"source": path.relative_to(ROOT).as_posix(),
                            "destination": safe(destination_dir + "/" + relative), **pin(raw)})
    entries.append({"source": attempt_pin["path"], "destination": "ATTEMPT1-INDEPENDENT-READBACK.json",
                    **{key: attempt_pin[key] for key in ("bytes", "sha256", "git_blob")}})
    assert len({x["destination"] for x in entries}) == len(entries)
    manifest = obj(ROOT / "source53-apply-preparation/derived/native-candidate-r30-source.json")
    assert manifest["source_commit"] == SOURCE53 and manifest["source_tree"] == TREE53
    assert len(manifest["changed_files"]) == manifest["changed_file_count"] == 197
    assert manifest["rust_file_count"] == 183 and manifest["other_file_count"] == 14
    write("PREPARATION-PLAN.json", {
        "schema": "hepta.source53-diagnostic-formal-preparation-plan.v1",
        "state": "FROZEN_INITIAL_INPUT_PLAN_AWAITING_ACTUAL_CORRECTED_APPLY_CLOSURE",
        "output_group": "native-evidence/source53-diagnostic-apply-checkpoint",
        "source53_registered_commit": SOURCE53, "source53_registered_tree": TREE53,
        "source53_parent_commit": SOURCE52, "source53_parent_tree": TREE52,
        "source53_scope": {"files": 197, "rust_files": 183, "other_files": 14, "owners": 26, "ci_selectors": 27},
        "diagnostic_only": True, "behavior_repair_claimed": False,
        "entries": entries, "entry_count": len(entries), "total_input_bytes": sum(x["bytes"] for x in entries),
        "v1_attempt_closed": attempt,
        "additional_inputs_required_before_apply_formal_seal": [
            "Corrected-v2 actual outer terminal/command/stdout/stderr and exact launch identity",
            "Actual three Git raw results/receipts/logs/resources plus pre/stage/post guards",
            "Actual source53 complete and complete197 manifest, both tied to root identity",
        ],
        "optional_later_R30_snapshot_policy": "Only separately closed original launch/phase files explicitly selected by root. Never read an active log or infer a terminal result. A full R30 gate belongs to its own closure.",
        "formal_group_created": False, "canonical_reports_INDEX_ledger_or_source_written": False,
        "science": "HOLD", "authority": "DENY_ALL", "rust_or_native_executed": False,
    })
    print(json.dumps({"entries": len(entries), "bytes": sum(x["bytes"] for x in entries), "attempt1_readback": attempt_pin}))


if __name__ == "__main__":
    main()
